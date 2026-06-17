import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class CandlePattern:
    name: str
    bullish: bool
    strength: float


def _body(o, c): return abs(c - o)
def _upper_wick(o, c, h): return h - max(o, c)
def _lower_wick(o, c, l): return min(o, c) - l
def _bull(o, c): return c > o


def detect_candlestick(df: pd.DataFrame) -> List[CandlePattern]:
    if len(df) < 3:
        return []
    patterns: List[CandlePattern] = []

    l0 = df.iloc[-1]
    l1 = df.iloc[-2]
    l2 = df.iloc[-3]
    o, h, l, c = l0["open"], l0["high"], l0["low"], l0["close"]
    po, ph, pl, pc = l1["open"], l1["high"], l1["low"], l1["close"]
    po2, ph2, pl2, pc2 = l2["open"], l2["high"], l2["low"], l2["close"]

    body = _body(o, c)
    avg_body = (_body(po, pc) + _body(po2, pc2)) / 2 or 1e-9
    up_w = _upper_wick(o, c, h)
    lo_w = _lower_wick(o, c, l)

    if body < avg_body * 0.1:
        patterns.append(CandlePattern("Doji", True, 0.5))

    if lo_w > body * 2 and up_w < body * 0.5 and not _bull(po, pc):
        patterns.append(CandlePattern("Marteau", True, 0.8))

    if up_w > body * 2 and lo_w < body * 0.5 and _bull(po, pc):
        patterns.append(CandlePattern("Étoile Filante", False, 0.8))

    if not _bull(po, pc) and _bull(o, c) and o < pc and c > po and body > _body(po, pc):
        patterns.append(CandlePattern("Engulfing Haussier", True, 0.9))

    if _bull(po, pc) and not _bull(o, c) and o > pc and c < po and body > _body(po, pc):
        patterns.append(CandlePattern("Engulfing Baissier", False, 0.9))

    if not _bull(po, pc) and _bull(o, c) and o > pc and c < po and body < _body(po, pc) * 0.5:
        patterns.append(CandlePattern("Harami Haussier", True, 0.7))

    if (not _bull(po2, pc2)
            and _body(po, pc) < _body(po2, pc2) * 0.3
            and _bull(o, c)
            and c > (po2 + pc2) / 2):
        patterns.append(CandlePattern("Morning Star", True, 0.95))

    if (_bull(po2, pc2)
            and _body(po, pc) < _body(po2, pc2) * 0.3
            and not _bull(o, c)
            and c < (po2 + pc2) / 2):
        patterns.append(CandlePattern("Evening Star", False, 0.95))

    return patterns


def detect_support_resistance(df: pd.DataFrame, window: int = 20) -> Tuple[List[float], List[float]]:
    pivot_h = df["high"].rolling(window=window, center=True).max()
    pivot_l = df["low"].rolling(window=window, center=True).min()

    def _round(v):
        if v <= 0:
            return v
        mag = int(np.floor(np.log10(abs(v))))
        return round(v, max(0, 2 - mag))

    resistances = sorted({_round(v) for v in pivot_h.dropna().tail(10).values}, reverse=True)[:3]
    supports = sorted({_round(v) for v in pivot_l.dropna().tail(10).values})[:3]
    return supports, resistances


def trend_direction(df: pd.DataFrame) -> str:
    last = df.iloc[-1]
    cols = ["ema9", "ema21", "ema50"]
    if all(c in df.columns for c in cols):
        if last["ema9"] > last["ema21"] > last["ema50"]:
            return "uptrend"
        if last["ema9"] < last["ema21"] < last["ema50"]:
            return "downtrend"
    return "sideways"
