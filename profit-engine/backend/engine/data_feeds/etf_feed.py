import logging
from typing import Optional
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_TF_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "60m", "4h": "1h", "1d": "1d",
}
_PERIOD_MAP = {
    "1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d",
    "60m": "60d", "1h": "60d", "1d": "2y",
}


class ETFFeed:
    def __init__(self, cfg):
        self.cfg = cfg

    def fetch_ohlcv(self, symbol: str) -> Optional[pd.DataFrame]:
        try:
            tf = _TF_MAP.get(self.cfg.strategy.timeframe, "60m")
            period = _PERIOD_MAP.get(tf, "60d")
            df = yf.Ticker(symbol).history(period=period, interval=tf)
            if df.empty:
                return None
            df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            df.columns = ["open", "high", "low", "close", "volume"]
            df.index.name = "timestamp"
            return df.tail(self.cfg.strategy.lookback)
        except Exception as exc:
            logger.error("ETFFeed %s: %s", symbol, exc)
            return None
