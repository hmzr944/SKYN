"""
SignalFilter — multi-factor confirmation gate for trade signals.

Checks:
  1. Multi-timeframe (MTF) alignment: 4h trend vs signal direction
  2. CVD divergence: is volume confirming the move?
  3. Funding rate (crypto): crowded positioning warning
  4. Long/Short ratio: additional sentiment filter

Usage:
    filt = await signal_filter.evaluate(signal, df_1h, df_4h, deriv_data)
    if filt.passes:
        # proceed with opening the trade
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from ..analysis.indicators import compute_all
from ..analysis.volume_analysis import cvd_trend
from ..data_feeds.derivatives_feed import DerivativesData
from ..analysis.signals import Signal

logger = logging.getLogger(__name__)


# Minimum net score below which a trade is blocked even if the signal passes
_MIN_NET_SCORE = -15.0


@dataclass
class FilterResult:
    passes: bool            # should we open this trade?
    score_boost: float      # additive adjustment to signal.score (-20 to +20)
    reasons: List[str]      # human-readable explanations
    mtf_aligned: bool       # 4h and 1h in agreement
    cvd_ok: bool            # no CVD divergence against the trade
    funding_ok: bool        # funding rate not dangerously against the trade


class SignalFilter:
    """
    Async filter that evaluates a signal against derivative data, CVD, and
    higher-timeframe confirmation before a position is opened.
    """

    async def evaluate(
        self,
        signal: Signal,
        df_1h: pd.DataFrame,
        df_4h: Optional[pd.DataFrame],
        deriv_data: Optional[DerivativesData],
    ) -> FilterResult:
        """
        Evaluate *signal* against the given data sources.

        Parameters
        ----------
        signal     : the Signal produced by MultiFactorStrategy
        df_1h      : 1h OHLCV DataFrame (already has indicators or raw)
        df_4h      : 4h OHLCV DataFrame; may be None if unavailable
        deriv_data : DerivativesData from DerivativesFeed; may be None
        """
        # HOLD signals should never open a position — block immediately
        if signal.action == "HOLD":
            return FilterResult(
                passes=False,
                score_boost=0.0,
                reasons=["HOLD signal — no entry"],
                mtf_aligned=False,
                cvd_ok=True,
                funding_ok=True,
            )

        boost = 0.0
        reasons: List[str] = []
        mtf_aligned = False
        cvd_ok = True
        funding_ok = True

        # ------------------------------------------------------------------
        # 1. Multi-timeframe confirmation
        # ------------------------------------------------------------------
        boost_mtf, mtf_aligned, mtf_reasons = self._check_mtf(signal, df_4h)
        boost += boost_mtf
        reasons.extend(mtf_reasons)

        # ------------------------------------------------------------------
        # 2. CVD divergence
        # ------------------------------------------------------------------
        boost_cvd, cvd_ok, cvd_reasons = self._check_cvd(signal, df_1h)
        boost += boost_cvd
        reasons.extend(cvd_reasons)

        # ------------------------------------------------------------------
        # 3. Funding rate (crypto)
        # ------------------------------------------------------------------
        boost_funding, funding_ok, funding_reasons = self._check_funding(signal, deriv_data)
        boost += boost_funding
        reasons.extend(funding_reasons)

        # ------------------------------------------------------------------
        # 4. Long/Short ratio
        # ------------------------------------------------------------------
        boost_lsr, lsr_reasons = self._check_lsr(signal, deriv_data)
        boost += boost_lsr
        reasons.extend(lsr_reasons)

        # ------------------------------------------------------------------
        # passes logic
        # ------------------------------------------------------------------
        # Block if MTF strongly contradicts AND total boost is deeply negative
        strongly_against_mtf = boost_mtf <= -20
        passes = not (strongly_against_mtf and boost < _MIN_NET_SCORE)

        return FilterResult(
            passes=passes,
            score_boost=round(boost, 2),
            reasons=reasons,
            mtf_aligned=mtf_aligned,
            cvd_ok=cvd_ok,
            funding_ok=funding_ok,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_mtf(
        self,
        signal: Signal,
        df_4h: Optional[pd.DataFrame],
    ):
        """Returns (boost, aligned, reasons)."""
        if df_4h is None or len(df_4h) < 50:
            return 0.0, False, ["MTF: no 4h data available"]

        try:
            # Compute indicators inline with a minimal dummy config
            df = _compute_4h_indicators(df_4h)
            last = df.iloc[-1]

            e9   = _safe(last, "ema9")
            e21  = _safe(last, "ema21")
            e50  = _safe(last, "ema50")
            e200 = _safe(last, "ema200")
            price = float(last["close"])

            bullish_4h = (
                e50 is not None and e200 is not None and e9 is not None and e21 is not None
                and price > e50 > e200
                and e9 > e21
            )
            bearish_4h = (
                e50 is not None and e200 is not None and e9 is not None and e21 is not None
                and price < e50 < e200
                and e9 < e21
            )

            if bullish_4h and signal.action == "BUY":
                return 15.0, True, ["MTF: 4h bullish — confirms BUY (+15)"]
            if bearish_4h and signal.action == "SELL":
                return 15.0, True, ["MTF: 4h bearish — confirms SELL (+15)"]
            if bullish_4h and signal.action == "SELL":
                return -20.0, False, ["MTF: 4h bullish contradicts SELL (-20)"]
            if bearish_4h and signal.action == "BUY":
                return -20.0, False, ["MTF: 4h bearish contradicts BUY (-20)"]

            # Neither strongly bullish nor bearish on 4h — neutral
            return 0.0, False, ["MTF: 4h trend unclear — neutral"]

        except Exception as exc:
            logger.debug("SignalFilter MTF error: %s", exc)
            return 0.0, False, [f"MTF: error computing 4h indicators ({exc})"]

    def _check_cvd(self, signal: Signal, df_1h: pd.DataFrame):
        """Returns (boost, cvd_ok, reasons)."""
        try:
            trend = cvd_trend(df_1h)
            if trend == "bearish_divergence" and signal.action == "BUY":
                return -10.0, False, ["CVD: bearish divergence against BUY (-10)"]
            if trend == "bullish_divergence" and signal.action == "SELL":
                return -10.0, False, ["CVD: bullish divergence against SELL (-10)"]
            if trend == "confirmed":
                return 5.0, True, ["CVD: confirmed move (+5)"]
            # neutral or divergence in our favour
            return 0.0, True, [f"CVD: {trend}"]
        except Exception as exc:
            logger.debug("SignalFilter CVD error: %s", exc)
            return 0.0, True, ["CVD: error — skipped"]

    def _check_funding(self, signal: Signal, deriv: Optional[DerivativesData]):
        """Returns (boost, funding_ok, reasons)."""
        if deriv is None:
            return 0.0, True, []

        fr = deriv.funding_rate
        action = signal.action

        if fr > 0.0003:   # crowded long (>0.03% / 8h)
            if action == "BUY":
                return -15.0, False, [f"Funding: crowded long ({fr:.4%}) against BUY (-15)"]
            if action == "SELL":
                return 10.0, True, [f"Funding: crowded long ({fr:.4%}) — contrarian SELL edge (+10)"]
        elif fr < -0.0001:  # crowded short
            if action == "SELL":
                return -10.0, False, [f"Funding: crowded short ({fr:.4%}) against SELL (-10)"]
            if action == "BUY":
                return 10.0, True, [f"Funding: crowded short ({fr:.4%}) — contrarian BUY edge (+10)"]

        return 0.0, True, [f"Funding: neutral ({fr:.4%})"]

    def _check_lsr(self, signal: Signal, deriv: Optional[DerivativesData]):
        """Returns (boost, reasons)."""
        if deriv is None:
            return 0.0, []

        llong = deriv.ls_long_pct
        action = signal.action

        if llong > 0.65 and action == "BUY":
            return -10.0, [f"LSR: {llong:.1%} longs — too crowded for BUY (-10)"]
        if llong < 0.35 and action == "SELL":
            return -10.0, [f"LSR: {llong:.1%} longs (shorts crowded) against SELL (-10)"]
        return 0.0, []

    # ------------------------------------------------------------------
    # Data-fetch helper (used by core.py to populate df_4h)
    # ------------------------------------------------------------------

    async def fetch_4h(self, symbol: str, exchange) -> Optional[pd.DataFrame]:
        """
        Fetch 100 bars of 4h OHLCV data using a ccxt exchange instance.
        Returns None on failure.
        """
        try:
            raw = await exchange.fetch_ohlcv(symbol, timeframe="4h", limit=100)
            if not raw:
                return None
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as exc:
            logger.warning("SignalFilter fetch_4h %s: %s", symbol, exc)
            return None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe(row, col: str):
    """Return float value or None if missing/NaN."""
    import math
    val = row.get(col)
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _compute_4h_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply a minimal set of EMA indicators to a raw 4h DataFrame.
    Mirrors the subset of compute_all() needed for MTF checks.
    """
    from ..analysis.indicators import _ema
    df = df.copy()
    c = df["close"]
    df["ema9"]   = _ema(c, 9)
    df["ema21"]  = _ema(c, 21)
    df["ema50"]  = _ema(c, 50)
    df["ema200"] = _ema(c, 200)
    return df
