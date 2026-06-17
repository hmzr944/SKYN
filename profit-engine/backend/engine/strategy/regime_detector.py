"""
Market regime detector.

Classifies the current market into one of 5 regimes using:
  - ADX (trend strength)
  - ATR% (relative volatility)
  - EMA alignment (price position vs ema50/ema200)
  - Volume ratio (breakout confirmation)

Regimes:
  BULL_TREND   → trend up, ADX > 25, price > EMA50 > EMA200
  BEAR_TREND   → trend down, ADX > 25, price < EMA50 < EMA200
  RANGING      → ADX < 20, price oscillates in a band
  BREAKOUT     → volume spike, price crossing key level, ADX rising
  HIGH_VOL     → ATR% > 3.5%, extreme moves — reduce risk
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class Regime(str, Enum):
    BULL_TREND = "bull_trend"
    BEAR_TREND = "bear_trend"
    RANGING    = "ranging"
    BREAKOUT   = "breakout"
    HIGH_VOL   = "high_volatility"


@dataclass
class RegimeResult:
    regime: Regime
    strength: float          # 0-100, how confident we are
    adx: float
    atr_pct: float
    trend_direction: str     # "up" | "down" | "neutral"
    vol_surge: bool          # volume > 1.8× average


# ---------------------------------------------------------------------------

def _adx(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (adx, di_plus, di_minus)."""
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)

    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    up   = h.diff().clip(lower=0)
    down = (-l.diff()).clip(lower=0)
    dm_p = up.where(up > down, 0.0)
    dm_m = down.where(down > up, 0.0)

    atr_s  = tr.ewm(com=period - 1, adjust=False).mean()
    di_p   = 100 * dm_p.ewm(com=period - 1, adjust=False).mean() / atr_s.replace(0, np.nan)
    di_m   = 100 * dm_m.ewm(com=period - 1, adjust=False).mean() / atr_s.replace(0, np.nan)

    dx     = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)
    adx_s  = dx.ewm(com=period - 1, adjust=False).mean()
    return adx_s, di_p, di_m


def detect_regime(df: pd.DataFrame) -> RegimeResult:
    """
    Detect market regime from OHLCV dataframe.
    Assumes compute_all() has already been called (ema9, ema50, ema200, atr, vol_ratio present).
    """
    if len(df) < 50:
        return RegimeResult(Regime.RANGING, 50.0, 20.0, 1.0, "neutral", False)

    adx_s, di_p, di_m = _adx(df)
    last = df.iloc[-1]

    price    = float(last.get("close", 0))
    ema9     = float(last.get("ema9",   price))
    ema50    = float(last.get("ema50",  price))
    ema200   = float(last.get("ema200", price))
    atr_val  = float(last.get("atr",    price * 0.01))
    vol_rat  = float(last.get("vol_ratio", 1.0))
    atr_pct  = atr_val / price * 100 if price > 0 else 1.0

    adx_val  = float(adx_s.iloc[-1]) if not np.isnan(adx_s.iloc[-1]) else 20.0
    di_plus  = float(di_p.iloc[-1])  if not np.isnan(di_p.iloc[-1])  else 0.0
    di_minus = float(di_m.iloc[-1])  if not np.isnan(di_m.iloc[-1])  else 0.0

    # EMA slope over last 10 bars (% change)
    ema200_slope = 0.0
    if len(df) >= 10 and not np.isnan(df["ema200"].iloc[-10]):
        ema200_slope = (df["ema200"].iloc[-1] - df["ema200"].iloc[-10]) / df["ema200"].iloc[-10] * 100

    vol_surge    = vol_rat > 1.8
    trend_up     = price > ema50 and ema50 > ema200
    trend_down   = price < ema50 and ema50 < ema200
    trend_dir    = "up" if trend_up else "down" if trend_down else "neutral"

    # --- Classify ---

    # 1. Extreme volatility → protect capital first
    if atr_pct > 3.5:
        return RegimeResult(Regime.HIGH_VOL, min(atr_pct * 20, 100), adx_val, atr_pct, trend_dir, vol_surge)

    # 2. Strong trend — lowered to ADX > 22 to capture more valid trends
    if adx_val > 22:
        if di_plus > di_minus and trend_up:
            strength = min(adx_val * 2, 100)
            return RegimeResult(Regime.BULL_TREND, strength, adx_val, atr_pct, "up", vol_surge)
        if di_minus > di_plus and trend_down:
            strength = min(adx_val * 2, 100)
            return RegimeResult(Regime.BEAR_TREND, strength, adx_val, atr_pct, "down", vol_surge)

    # 3. Breakout candidate: strong volume surge + clear ADX acceleration
    # Require vol_ratio > 2.5 (real surge, not noise) AND ADX rising by ≥3 pts
    strong_surge = vol_rat > 2.5
    if strong_surge and 18 < adx_val < 35:
        recent_adx = float(adx_s.iloc[-5]) if len(adx_s) >= 5 and not np.isnan(adx_s.iloc[-5]) else adx_val
        if adx_val > recent_adx + 3:      # ADX must accelerate meaningfully
            return RegimeResult(Regime.BREAKOUT, min(vol_rat * 25, 100), adx_val, atr_pct, trend_dir, True)

    # 4. Ranging / sideways
    return RegimeResult(Regime.RANGING, max(0, 100 - adx_val * 3), adx_val, atr_pct, trend_dir, vol_surge)
