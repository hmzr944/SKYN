"""
Volume analysis utilities.

Functions
---------
calc_cvd(df)                    → pd.Series  — Cumulative Volume Delta
cvd_trend(df, lookback)         → str         — CVD vs price divergence
poc_level(df, bins)             → float       — Point of Control
near_poc(price, df, threshold)  → bool        — within threshold% of POC
oi_momentum(cur_oi, prev_oi, price_change_pct) → str — OI / price signal
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Cumulative Volume Delta
# ---------------------------------------------------------------------------

def calc_cvd(df: pd.DataFrame) -> pd.Series:
    """
    Per-candle volume delta:
        close > open  → +volume (net buying pressure)
        close < open  → -volume (net selling pressure)
        close == open → 0

    Returns a running cumulative sum aligned with df.index.
    """
    delta = pd.Series(
        np.where(df["close"] > df["open"],  df["volume"],
        np.where(df["close"] < df["open"], -df["volume"], 0.0)),
        index=df.index,
        dtype=float,
    )
    return delta.cumsum()


def cvd_trend(df: pd.DataFrame, lookback: int = 20) -> str:
    """
    Compare CVD slope vs price slope over the last *lookback* bars.

    Returns one of:
        "bullish_divergence"  — price falling but CVD rising (hidden buying)
        "bearish_divergence"  — price rising but CVD falling (hidden selling)
        "confirmed"           — price and CVD moving in the same direction
        "neutral"             — insufficient data
    """
    if len(df) < lookback + 1:
        return "neutral"

    cvd = calc_cvd(df)
    window_cvd   = cvd.iloc[-lookback:]
    window_price = df["close"].iloc[-lookback:]

    # Linear slope via least-squares (fast with numpy)
    x = np.arange(lookback, dtype=float)
    price_slope = float(np.polyfit(x, window_price.values, 1)[0])
    cvd_slope   = float(np.polyfit(x, window_cvd.values,   1)[0])

    price_up = price_slope > 0
    cvd_up   = cvd_slope   > 0

    if price_up and not cvd_up:
        return "bearish_divergence"
    if not price_up and cvd_up:
        return "bullish_divergence"
    if price_up == cvd_up:
        return "confirmed"
    return "neutral"


# ---------------------------------------------------------------------------
# Volume Profile — Point of Control
# ---------------------------------------------------------------------------

def poc_level(df: pd.DataFrame, bins: int = 20) -> float:
    """
    Compute the Point of Control — the price level (bin midpoint) that
    traded the highest total volume across *bins* equally-spaced price buckets.

    Returns the midpoint price of the highest-volume bin, or the last close
    if there is insufficient data.
    """
    if len(df) < 2:
        return float(df["close"].iloc[-1])

    lo = df["low"].min()
    hi = df["high"].max()
    if hi <= lo:
        return float(df["close"].iloc[-1])

    edges = np.linspace(lo, hi, bins + 1)
    mid_prices = 0.5 * (edges[:-1] + edges[1:])

    # Distribute each candle's volume proportionally across the bins it spans
    vol_profile = np.zeros(bins, dtype=float)
    for _, row in df.iterrows():
        c_lo = float(row["low"])
        c_hi = float(row["high"])
        vol  = float(row["volume"])
        if c_hi <= c_lo:
            c_hi = c_lo + 1e-12  # avoid zero-width

        # Bins this candle touches
        i_lo = int(np.searchsorted(edges, c_lo, side="right")) - 1
        i_hi = int(np.searchsorted(edges, c_hi, side="left"))
        i_lo = max(0, min(i_lo, bins - 1))
        i_hi = max(0, min(i_hi, bins - 1))

        span = i_hi - i_lo + 1
        if span > 0:
            vol_profile[i_lo : i_hi + 1] += vol / span

    return float(mid_prices[int(np.argmax(vol_profile))])


def near_poc(price: float, df: pd.DataFrame, threshold_pct: float = 0.008) -> bool:
    """Return True if *price* is within *threshold_pct* (default 0.8%) of the POC."""
    poc = poc_level(df)
    if poc == 0.0:
        return False
    return abs(price - poc) / poc <= threshold_pct


# ---------------------------------------------------------------------------
# Open Interest Momentum
# ---------------------------------------------------------------------------

def oi_momentum(current_oi: float, prev_oi: float, price_change_pct: float) -> str:
    """
    Classify OI/price relationship into one of four regimes:

    OI up  + price up   → "long_momentum"      (real buying)
    OI up  + price down → "short_momentum"     (real selling / short build)
    OI down + price up  → "short_covering"     (weak rally — shorts bailing)
    OI down + price down→ "long_liquidation"   (forced deleveraging — potential reversal)

    *current_oi* and *prev_oi* can be in any consistent unit.
    *price_change_pct* should be e.g. +1.5 for a 1.5% up move.
    """
    if prev_oi <= 0:
        return "neutral"

    oi_up    = current_oi > prev_oi
    price_up = price_change_pct > 0

    if oi_up and price_up:
        return "long_momentum"
    if oi_up and not price_up:
        return "short_momentum"
    if not oi_up and price_up:
        return "short_covering"
    # not oi_up and not price_up
    return "long_liquidation"
