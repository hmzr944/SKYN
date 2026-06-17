import logging
from typing import Optional
import ccxt.async_support as ccxt
import pandas as pd

logger = logging.getLogger(__name__)


class CryptoFeed:
    def __init__(self, cfg):
        self.cfg = cfg
        exchange_class = getattr(ccxt, cfg.exchange.name)
        kwargs = {"enableRateLimit": True}
        if cfg.exchange.api_key:
            kwargs["apiKey"] = cfg.exchange.api_key
            kwargs["secret"] = cfg.exchange.api_secret
        self.exchange = exchange_class(kwargs)

    async def fetch_ohlcv(self, symbol: str) -> Optional[pd.DataFrame]:
        try:
            raw = await self.exchange.fetch_ohlcv(
                symbol,
                timeframe=self.cfg.strategy.timeframe,
                limit=self.cfg.strategy.lookback,
            )
            if not raw:
                return None
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as exc:
            logger.error("CryptoFeed %s: %s", symbol, exc)
            return None

    async def close(self):
        await self.exchange.close()
