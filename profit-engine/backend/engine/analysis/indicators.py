import numpy as np
import pandas as pd


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(window=n).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def macd(close: pd.Series, fast: int, slow: int, signal: int):
    line = _ema(close, fast) - _ema(close, slow)
    sig = _ema(line, signal)
    return line, sig, line - sig


def bollinger(close: pd.Series, period: int, std: float):
    mid = _sma(close, period)
    dev = close.rolling(period).std()
    return mid + std * dev, mid, mid - std * dev


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev).abs(),
        (low - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    return (np.sign(close.diff()).fillna(0) * volume).cumsum()


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k: int = 14, d: int = 3):
    lo = low.rolling(k).min()
    hi = high.rolling(k).max()
    pct_k = 100.0 * (close - lo) / (hi - lo).replace(0, np.nan)
    return pct_k, _sma(pct_k, d)


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    tp = (high + low + close) / 3.0
    return (tp * volume).cumsum() / volume.cumsum()


def compute_all(df: pd.DataFrame, s) -> pd.DataFrame:
    """Compute all indicators on df using StrategyConfig s."""
    df = df.copy()
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    df["ema9"] = _ema(c, s.ema_short)
    df["ema21"] = _ema(c, s.ema_medium)
    df["ema50"] = _ema(c, s.ema_long)
    df["ema200"] = _ema(c, s.ema_trend)
    df["rsi"] = rsi(c, s.rsi_period)
    df["macd"], df["macd_sig"], df["macd_hist"] = macd(c, s.macd_fast, s.macd_slow, s.macd_signal_period)
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bollinger(c, s.bb_period, s.bb_std)
    df["bb_pct"] = (c - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)
    df["atr"] = atr(h, l, c, s.atr_period)
    df["obv"] = obv(c, v)
    df["stoch_k"], df["stoch_d"] = stochastic(h, l, c)
    df["vwap"] = vwap(h, l, c, v)
    df["vol_ratio"] = v / v.rolling(20).mean()
    return df
