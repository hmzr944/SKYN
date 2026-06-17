"""
DerivativesFeed — fetches Binance public futures data without authentication.

Endpoints used (all public, no auth):
  - /fapi/v1/premiumIndex   → funding rate
  - /fapi/v1/openInterest   → open interest
  - /futures/data/globalLongShortAccountRatio → long/short ratio

Results are cached for 5 minutes to avoid hammering the API.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

_CACHE_TTL = 300  # 5 minutes in seconds

_BASE_FAPI = "https://fapi.binance.com"
_FUNDING_URL = _BASE_FAPI + "/fapi/v1/premiumIndex"
_OI_URL = _BASE_FAPI + "/fapi/v1/openInterest"
_LSR_URL = _BASE_FAPI + "/futures/data/globalLongShortAccountRatio"


@dataclass
class DerivativesData:
    symbol: str
    funding_rate: float          # e.g. 0.0001 = 0.01%
    open_interest: float         # in base currency units
    long_short_ratio: float      # longAccount / shortAccount ratio
    ls_long_pct: float           # fraction of longs, e.g. 0.592
    ls_short_pct: float          # fraction of shorts, e.g. 0.408
    timestamp: float = field(default_factory=time.time)


# Neutral defaults returned on any error
def _neutral(symbol: str) -> DerivativesData:
    return DerivativesData(
        symbol=symbol,
        funding_rate=0.0,
        open_interest=0.0,
        long_short_ratio=1.0,
        ls_long_pct=0.5,
        ls_short_pct=0.5,
        timestamp=time.time(),
    )


def _to_binance_symbol(symbol: str) -> str:
    """Convert 'BTC/USDT' → 'BTCUSDT'."""
    return symbol.replace("/", "").upper()


class DerivativesFeed:
    """
    Async feed for Binance perpetual futures derivative metrics.

    Creates a fresh aiohttp session per call (lightweight; avoids session
    lifecycle management across the async event loop).

    Cache is keyed by normalised symbol and expires after _CACHE_TTL seconds.
    """

    def __init__(self) -> None:
        # _cache: symbol → (DerivativesData, expire_time)
        self._cache: Dict[str, Tuple[DerivativesData, float]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def fetch(self, symbol: str) -> DerivativesData:
        """Return DerivativesData for *symbol*.  Falls back to neutral on any error."""
        bin_sym = _to_binance_symbol(symbol)

        # Cache hit — return immediately without acquiring lock
        cached, exp = self._cache.get(bin_sym, (None, 0.0))
        if cached is not None and time.time() < exp:
            return cached

        # Fetch under lock so concurrent callers for the same symbol share one request
        async with self._lock:
            # Double-check after acquiring lock
            cached, exp = self._cache.get(bin_sym, (None, 0.0))
            if cached is not None and time.time() < exp:
                return cached

            data = await self._fetch_all(bin_sym)
            self._cache[bin_sym] = (data, time.time() + _CACHE_TTL)
            return data

    async def _fetch_all(self, bin_sym: str) -> DerivativesData:
        """Fetch all three endpoints concurrently."""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                funding_task = self._get_funding(session, bin_sym)
                oi_task = self._get_open_interest(session, bin_sym)
                lsr_task = self._get_long_short_ratio(session, bin_sym)

                funding_rate, oi, (lsr, ls_long, ls_short) = await asyncio.gather(
                    funding_task, oi_task, lsr_task,
                    return_exceptions=False,
                )

            return DerivativesData(
                symbol=bin_sym,
                funding_rate=funding_rate,
                open_interest=oi,
                long_short_ratio=lsr,
                ls_long_pct=ls_long,
                ls_short_pct=ls_short,
                timestamp=time.time(),
            )
        except Exception as exc:
            logger.warning("DerivativesFeed %s: fetch failed (%s) — returning neutral", bin_sym, exc)
            return _neutral(bin_sym)

    async def _get_funding(self, session: aiohttp.ClientSession, bin_sym: str) -> float:
        try:
            async with session.get(_FUNDING_URL, params={"symbol": bin_sym}) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return float(data.get("lastFundingRate", 0.0))
        except Exception as exc:
            logger.debug("DerivativesFeed funding %s: %s", bin_sym, exc)
            return 0.0

    async def _get_open_interest(self, session: aiohttp.ClientSession, bin_sym: str) -> float:
        try:
            async with session.get(_OI_URL, params={"symbol": bin_sym}) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return float(data.get("openInterest", 0.0))
        except Exception as exc:
            logger.debug("DerivativesFeed OI %s: %s", bin_sym, exc)
            return 0.0

    async def _get_long_short_ratio(
        self, session: aiohttp.ClientSession, bin_sym: str
    ) -> Tuple[float, float, float]:
        """Returns (ratio, long_pct, short_pct)."""
        try:
            params = {"symbol": bin_sym, "period": "1h", "limit": 1}
            async with session.get(_LSR_URL, params=params) as resp:
                resp.raise_for_status()
                rows = await resp.json()
                if not rows:
                    return 1.0, 0.5, 0.5
                row = rows[0]
                lsr   = float(row.get("longShortRatio", 1.0))
                llong = float(row.get("longAccount",    0.5))
                lshort = float(row.get("shortAccount",  0.5))
                return lsr, llong, lshort
        except Exception as exc:
            logger.debug("DerivativesFeed LSR %s: %s", bin_sym, exc)
            return 1.0, 0.5, 0.5
