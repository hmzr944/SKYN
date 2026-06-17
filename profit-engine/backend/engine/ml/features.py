"""
Feature engineering — 80+ features from OHLCV data.
Designed for XGBoost signal prediction.
"""
import numpy as np
import pandas as pd


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"]  - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build 80+ features from OHLCV.
    Returns DataFrame aligned with df index, NaN rows trimmed.
    """
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]

    feat: dict = {}

    # ── Returns ────────────────────────────────────────────────────
    for p in [1, 2, 3, 5, 8, 13, 21]:
        feat[f"ret_{p}"] = c.pct_change(p)

    # Log returns
    lc = np.log(c)
    for p in [1, 3, 6, 12, 24]:
        feat[f"logret_{p}"] = lc.diff(p)

    # ── Price position ─────────────────────────────────────────────
    for n in [10, 20, 50, 100]:
        rolling_h = h.rolling(n).max()
        rolling_l = l.rolling(n).min()
        denom = (rolling_h - rolling_l).replace(0, np.nan)
        feat[f"pos_{n}"] = (c - rolling_l) / denom

    # ── Moving average distances ───────────────────────────────────
    for n in [9, 21, 50, 100, 200]:
        ema = _ema(c, n)
        feat[f"ema{n}_dist"] = (c - ema) / ema

    # EMA crosses
    feat["ema9_21_cross"]  = (_ema(c, 9) - _ema(c, 21)) / c
    feat["ema21_50_cross"] = (_ema(c, 21) - _ema(c, 50)) / c
    feat["ema50_200_cross"]= (_ema(c, 50) - _ema(c, 200)) / c

    # ── Momentum ───────────────────────────────────────────────────
    for n in [6, 9, 14, 21]:
        feat[f"rsi_{n}"] = _rsi(c, n)

    # RSI slope
    rsi14 = _rsi(c, 14)
    feat["rsi14_slope"] = rsi14.diff(3)
    feat["rsi14_diff"]  = rsi14 - rsi14.shift(1)

    # MACD
    macd = _ema(c, 12) - _ema(c, 26)
    sig  = _ema(macd, 9)
    feat["macd"]       = macd / c
    feat["macd_sig"]   = sig / c
    feat["macd_hist"]  = (macd - sig) / c
    feat["macd_hist_slope"] = (macd - sig).diff(2) / c

    # Stochastic
    for n in [9, 14]:
        lowest  = l.rolling(n).min()
        highest = h.rolling(n).max()
        denom   = (highest - lowest).replace(0, np.nan)
        k = (c - lowest) / denom * 100
        feat[f"stoch_k_{n}"] = k
        feat[f"stoch_d_{n}"] = k.rolling(3).mean()

    # Williams %R
    for n in [10, 14]:
        hh = h.rolling(n).max()
        ll = l.rolling(n).min()
        feat[f"willr_{n}"] = -100 * (hh - c) / (hh - ll).replace(0, np.nan)

    # CCI
    tp = (h + l + c) / 3
    for n in [14, 20]:
        ma  = tp.rolling(n).mean()
        mad = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
        feat[f"cci_{n}"] = (tp - ma) / (0.015 * mad.replace(0, np.nan))

    # ── Volatility ─────────────────────────────────────────────────
    atr14 = _atr(df, 14)
    feat["atr14_ratio"]  = atr14 / c
    feat["atr14_slope"]  = atr14.pct_change(5)

    for n in [10, 20, 50]:
        std = c.pct_change().rolling(n).std()
        feat[f"vol_{n}"]  = std
        feat[f"vol_{n}_slope"] = std.pct_change(5)

    # Bollinger Bands
    for n, k in [(20, 2.0), (20, 2.2), (10, 1.5)]:
        mid   = c.rolling(n).mean()
        sigma = c.rolling(n).std()
        upper = mid + k * sigma
        lower = mid - k * sigma
        denom = (upper - lower).replace(0, np.nan)
        feat[f"bb_pct_{n}_{k}"] = (c - lower) / denom
        feat[f"bb_width_{n}_{k}"] = denom / mid

    # High-Low range
    feat["hl_range"]       = (h - l) / c
    feat["hl_range_ma10"]  = ((h - l) / c).rolling(10).mean()
    feat["body_ratio"]     = (c - df["open"]).abs() / (h - l).replace(0, np.nan)
    feat["upper_wick"]     = (h - pd.concat([c, df["open"]], axis=1).max(axis=1)) / (h - l).replace(0, np.nan)
    feat["lower_wick"]     = (pd.concat([c, df["open"]], axis=1).min(axis=1) - l) / (h - l).replace(0, np.nan)

    # ── Volume ─────────────────────────────────────────────────────
    vol_ma20 = v.rolling(20).mean().replace(0, np.nan)
    feat["vol_ratio"]     = v / vol_ma20
    feat["vol_ratio_5"]   = v.rolling(5).mean() / vol_ma20
    feat["vol_slope"]     = v.pct_change(5)

    # OBV normalized
    obv = (np.sign(c.diff()) * v).cumsum()
    obv_ma = _ema(obv, 20)
    feat["obv_slope"] = obv.pct_change(10)
    feat["obv_dist"]  = (obv - obv_ma) / obv_ma.abs().replace(0, np.nan)

    # VWAP daily deviation
    vwap = (v * (h + l + c) / 3).rolling(24).sum() / v.rolling(24).sum().replace(0, np.nan)
    feat["vwap_dist"] = (c - vwap) / vwap.replace(0, np.nan)

    # MFI
    mf = (h + l + c) / 3 * v
    pos_mf = mf.where(c > c.shift(), 0).rolling(14).sum()
    neg_mf = mf.where(c < c.shift(), 0).rolling(14).sum()
    feat["mfi14"] = 100 - 100 / (1 + pos_mf / neg_mf.replace(0, np.nan))

    # ── Trend strength ─────────────────────────────────────────────
    # ADX proxy
    up_move   = h.diff()
    down_move = -l.diff()
    plus_dm   = up_move.where((up_move > down_move) & (up_move > 0), 0)
    minus_dm  = down_move.where((down_move > up_move) & (down_move > 0), 0)
    atr_s     = _atr(df, 14)
    plus_di   = 100 * _ema(plus_dm, 14) / atr_s.replace(0, np.nan)
    minus_di  = 100 * _ema(minus_dm, 14) / atr_s.replace(0, np.nan)
    dx        = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    feat["adx14"]     = _ema(dx, 14)
    feat["plus_di"]   = plus_di
    feat["minus_di"]  = minus_di
    feat["di_diff"]   = plus_di - minus_di

    # ── Candlestick features ───────────────────────────────────────
    o = df["open"]
    feat["is_green"]   = (c > o).astype(float)
    feat["green_3"]    = feat["is_green"].rolling(3).sum()   / 3
    feat["green_5"]    = feat["is_green"].rolling(5).sum()   / 5
    feat["green_10"]   = feat["is_green"].rolling(10).sum()  / 10

    # Gap
    feat["gap"] = (o - c.shift()) / c.shift()

    out = pd.DataFrame(feat, index=df.index)
    return out.replace([np.inf, -np.inf], np.nan)


def make_labels(df: pd.DataFrame, tp_pct: float = 0.02, sl_pct: float = 0.01,
                max_bars: int = 48) -> pd.Series:
    """
    Forward-looking label: 1 if price hits +tp_pct before -sl_pct within max_bars.
    Uses the close prices only (realistic, no look-ahead on intrabar).
    """
    c = df["close"].values
    n = len(c)
    labels = np.full(n, np.nan)

    for i in range(n - 1):
        entry = c[i]
        tp = entry * (1 + tp_pct)
        sl = entry * (1 - sl_pct)
        result = np.nan
        for j in range(i + 1, min(i + max_bars + 1, n)):
            if c[j] >= tp:
                result = 1.0
                break
            if c[j] <= sl:
                result = 0.0
                break
        labels[i] = result

    return pd.Series(labels, index=df.index)
