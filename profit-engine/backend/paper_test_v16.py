#!/usr/bin/env python3
"""
PRISM v16 — Multi-Pattern Crypto Strategy
==========================================
Three complementary entry patterns:
  A — EMA Pullback
  B — RSI Momentum Cross
  C — BB Squeeze Breakout

With partial TP, BTC macro filter, and per-pattern cooldowns.
"""

import math, time, warnings, sys, os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich import box

warnings.filterwarnings("ignore")
console = Console()

SYMBOLS_YF = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "AVAX-USD",
    "ADA-USD", "LINK-USD", "XRP-USD", "DOT-USD", "ATOM-USD", "LTC-USD",
    "DOGE-USD", "NEAR-USD", "TRX-USD", "ALGO-USD", "FIL-USD", "INJ-USD",
    "POL-USD", "OP-USD",
]
SYMBOL_MAP = {s: s.replace("-USD", "/USDT") for s in SYMBOLS_YF}

INITIAL_CAPITAL    = 500.0
INTERVAL           = "1h"
PERIOD             = "2y"
WARMUP             = 250
N_MAX_POSITIONS    = 7
COMMISSION         = 0.001      # 0.1% Binance taker per side (fixed from 0.04%)
SLIPPAGE           = 0.0005    # entry slippage (15-min data delay + spread)
EXIT_SLIPPAGE      = 0.0003    # exit slippage (market impact on close)
DAILY_LOSS_LIMIT   = 0.10

PATTERN = {
    "A": {"sl": 0.020, "tp": 0.080, "cooldown_h": 16, "score_min": 70, "lev_max": 4, "risk_mult": 1.0},
    "C": {"sl": 0.015, "tp": 0.090, "cooldown_h": 10, "score_min": 65, "lev_max": 5, "risk_mult": 1.2},
}

BTC_CRASH_THRESH    = 0.88
BTC_EUPHORIA_THRESH = 1.15

CONFIGS = [
    {"name": "Actif",    "score_min": 63, "risk_pct": 0.045, "max_pos": 5},
    {"name": "Equilibre","score_min": 65, "risk_pct": 0.040, "max_pos": 4},
    {"name": "Premium",  "score_min": 68, "risk_pct": 0.050, "max_pos": 3},
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    name: str
    score_min: int
    risk_pct: float
    max_pos: int


@dataclass
class Trade:
    symbol: str
    side: str           # "long" / "short"
    pattern: str        # "A", "B", "C"
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    entry_price: float
    exit_price: float
    margin_eur: float
    pnl_eur: float
    pnl_pct: float
    exit_reason: str    # "take_profit" / "stop_loss" / "time_stop"
    score: int
    leverage: int
    adx_entry: float
    asset_trend: str    # "bull" / "bear"
    btc_macro: str      # "bull" / "bear" / "neutral"


# ---------------------------------------------------------------------------
# Data download
# ---------------------------------------------------------------------------

def download_data(sym: str) -> Optional[pd.DataFrame]:
    """Download OHLCV from yfinance, flatten MultiIndex, normalise timezone."""
    try:
        df = yf.download(sym, period=PERIOD, interval=INTERVAL, progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None

        # Flatten MultiIndex columns (yfinance sometimes returns ticker as second level)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower() for col in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]

        # Normalise timezone → UTC, then tz-naive
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)

        df = df.dropna(subset=["close", "open", "high", "low", "volume"])
        if len(df) < WARMUP + 10:
            return None
        return df
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Indicator computation
# ---------------------------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical indicators in-place on df."""
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    # ---- EMA 9, 21, 50 ----
    df["ema9"]  = close.ewm(span=9,  adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()

    # ---- RSI 14 (EWM smoothing) ----
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + gain / (loss + 1e-10))

    # ---- MACD (12, 26, 9) ----
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line   = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist   = macd_line - macd_signal
    df["macd_line"]       = macd_line
    df["macd_signal"]     = macd_signal
    df["macd_hist"]       = macd_hist
    df["macd_hist_slope"] = macd_hist.diff()

    # ---- Bollinger Bands (20, 2.0) ----
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df["bb_upper"] = bb_mid + 2 * bb_std
    df["bb_lower"] = bb_mid - 2 * bb_std
    df["bb_mid"]   = bb_mid
    bbw = (df["bb_upper"] - df["bb_lower"]) / (bb_mid + 1e-10)
    df["bbw"]      = bbw
    df["bbw_q15"]  = bbw.rolling(40).quantile(0.15)

    # ---- VWAP (24-bar rolling) ----
    tp = (high + low + close) / 3
    df["vwap"] = (tp * volume).rolling(24).sum() / (volume.rolling(24).sum() + 1e-10)

    # ---- OBV ----
    obv_vals = np.where(
        close > close.shift(1), volume,
        np.where(close < close.shift(1), -volume, 0)
    )
    obv = pd.Series(obv_vals, index=df.index).cumsum()
    df["obv"]       = obv
    df["obv_slope"] = obv.diff(5)

    # ---- Stochastic (14, 3) ----
    low14  = low.rolling(14).min()
    high14 = high.rolling(14).max()
    stoch_k = 100 * (close - low14) / (high14 - low14 + 1e-10)
    df["stoch_k"] = stoch_k
    df["stoch_d"] = stoch_k.rolling(3).mean()

    # ---- Volume ratio ----
    df["vol_ratio"] = volume / (volume.rolling(20).mean() + 1e-10)

    # ---- 4H EMA 20, 50 (resample → reindex) ----
    df_4h = df[["close"]].resample("4h").last().dropna()
    ema20_4h = df_4h["close"].ewm(span=20, adjust=False).mean()
    ema50_4h = df_4h["close"].ewm(span=50, adjust=False).mean()
    df["ema20_4h"] = ema20_4h.reindex(df.index, method="ffill")
    df["ema50_4h"] = ema50_4h.reindex(df.index, method="ffill")

    # ---- Daily EMA 50, 200 (resample → reindex) ----
    df_1d = df[["close"]].resample("1D").last().dropna()
    ema50d  = df_1d["close"].ewm(span=50,  adjust=False).mean()
    ema200d = df_1d["close"].ewm(span=200, adjust=False).mean()
    df["ema50d"]  = ema50d.reindex(df.index,  method="ffill")
    df["ema200d"] = ema200d.reindex(df.index, method="ffill")

    # ---- Asset trend ----
    cond_bull = df["ema50d"] > df["ema200d"] * 1.005
    cond_bear = df["ema50d"] < df["ema200d"] * 0.995
    df["asset_trend"] = "neutral"
    df.loc[cond_bull, "asset_trend"] = "bull"
    df.loc[cond_bear, "asset_trend"] = "bear"

    # ---- MA48 and funding deviation ----
    df["ma48"]        = close.rolling(48).mean()
    df["funding_dev"] = (close - df["ma48"]) / (df["ma48"] + 1e-10)

    return df


# ---------------------------------------------------------------------------
# ADX computation
# ---------------------------------------------------------------------------

def _compute_adx(df: pd.DataFrame, period: int = 14):
    """Compute ADX, DI+, DI- using Wilder smoothing. Returns (adx, di_plus, di_minus)."""
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    prev_close = close.shift(1)
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)

    # True Range
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Directional Movement
    up_move   = high.diff()
    down_move = (-low.diff())

    dm_plus  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    dm_minus = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    dm_plus_s  = pd.Series(dm_plus,  index=df.index)
    dm_minus_s = pd.Series(dm_minus, index=df.index)

    alpha = 1.0 / period

    # Wilder smoothing via EWM
    tr_smooth      = tr.ewm(alpha=alpha, adjust=False).mean()
    dm_plus_smooth = dm_plus_s.ewm(alpha=alpha, adjust=False).mean()
    dm_minus_smooth= dm_minus_s.ewm(alpha=alpha, adjust=False).mean()

    di_plus  = 100 * dm_plus_smooth  / (tr_smooth + 1e-10)
    di_minus = 100 * dm_minus_smooth / (tr_smooth + 1e-10)

    dx  = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus + 1e-10)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()

    # Store in df for pattern checks
    df["adx"]      = adx.values
    df["di_plus"]  = di_plus.values
    df["di_minus"] = di_minus.values

    return adx, di_plus, di_minus


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def compute_scores(df, adx_s, di_p_s, di_m_s):
    """Compute buy/sell scores (0-100) for every bar. Returns (buy_arr, sell_arr)."""
    n = len(df)
    buy_sc  = np.zeros(n, dtype=np.int32)
    sell_sc = np.zeros(n, dtype=np.int32)

    close     = df["close"].values
    ema9      = df["ema9"].values
    ema21     = df["ema21"].values
    ema50     = df["ema50"].values
    rsi       = df["rsi"].values
    macd_hist = df["macd_hist"].values
    mh_slope  = df["macd_hist_slope"].values
    vol_ratio = df["vol_ratio"].values
    adx_arr   = adx_s.values
    vwap      = df["vwap"].values
    stoch_k   = df["stoch_k"].values
    stoch_d   = df["stoch_d"].values

    for i in range(n):
        bs = 0
        ss = 0

        # 1. EMA stack (25 pts)
        if not (math.isnan(ema9[i]) or math.isnan(ema21[i]) or math.isnan(ema50[i])):
            if ema9[i] > ema21[i]:
                bs += 12
            elif ema9[i] < ema21[i]:
                ss += 12
            if ema21[i] > ema50[i]:
                bs += 13
            elif ema21[i] < ema50[i]:
                ss += 13

        # 2. RSI zone (15 pts)
        if not math.isnan(rsi[i]):
            r = rsi[i]
            if 40 <= r <= 65:
                bs += 15
            elif 35 <= r < 40:
                bs += 8
            elif 65 < r <= 70:
                bs += 5

            if 35 <= r <= 60:
                ss += 15
            elif 60 < r <= 65:
                ss += 8
            elif 30 <= r < 35:
                ss += 5

        # 3. MACD (20 pts)
        if not (math.isnan(macd_hist[i]) or math.isnan(mh_slope[i])):
            if macd_hist[i] > 0:
                bs += 12
            elif macd_hist[i] < 0:
                ss += 12
            if mh_slope[i] > 0:
                bs += 8
            elif mh_slope[i] < 0:
                ss += 8

        # 4. Volume (10 pts) — same for both
        if not math.isnan(vol_ratio[i]):
            vr = vol_ratio[i]
            if vr >= 1.5:
                pts = 10
            elif vr >= 1.0:
                pts = 6
            elif vr >= 0.7:
                pts = 3
            else:
                pts = 0
            bs += pts
            ss += pts

        # 5. ADX (10 pts) — same for both
        if not math.isnan(adx_arr[i]):
            av = adx_arr[i]
            if av >= 25:
                pts = 10
            elif av >= 18:
                pts = 6
            else:
                pts = 0
            bs += pts
            ss += pts

        # 6. VWAP (10 pts)
        if not (math.isnan(close[i]) or math.isnan(vwap[i])):
            if close[i] > vwap[i]:
                bs += 10
            elif close[i] < vwap[i]:
                ss += 10

        # 7. Stochastic (10 pts)
        if not (math.isnan(stoch_k[i]) or math.isnan(stoch_d[i])):
            sk = stoch_k[i]
            sd = stoch_d[i]
            if sk > sd and sk < 75:
                bs += 10
            if sk < sd and sk > 25:
                ss += 10

        buy_sc[i]  = min(bs, 100)
        sell_sc[i] = min(ss, 100)

    return buy_sc, sell_sc


# ---------------------------------------------------------------------------
# Symbol pre-computation
# ---------------------------------------------------------------------------

def precompute_symbol_v16(sym: str, cfg: dict) -> Optional[dict]:
    """Download, compute indicators, scores. Returns data dict or None."""
    df = download_data(sym)
    if df is None:
        return None

    df = compute_indicators(df)
    adx_s, di_p_s, di_m_s = _compute_adx(df)
    buy_sc, sell_sc = compute_scores(df, adx_s, di_p_s, di_m_s)

    ts_to_pos = {ts: i for i, ts in enumerate(df.index)}

    return {
        "name":      sym,
        "sym_key":   SYMBOL_MAP[sym],
        "df":        df,
        "adx_s":     adx_s,
        "di_p_s":    di_p_s,
        "di_m_s":    di_m_s,
        "buy_sc":    buy_sc,
        "sell_sc":   sell_sc,
        "ts_to_pos": ts_to_pos,
        "ts_index":  df.index,
        # Precomputed numpy arrays — fast O(1) bar access in engine loops
        "open":       df["open"].values.astype(float),
        "close":      df["close"].values.astype(float),
        "high":       df["high"].values.astype(float),
        "low":        df["low"].values.astype(float),
        "ema9":       df["ema9"].values.astype(float),
        "ema21":      df["ema21"].values.astype(float),
        "ema50":      df["ema50"].values.astype(float),
        "rsi":        df["rsi"].values.astype(float),
        "macd_hist":  df["macd_hist"].values.astype(float),
        "vol_ratio":  df["vol_ratio"].values.astype(float),
        "bbw":        df["bbw"].values.astype(float),
        "bbw_q15":    df["bbw_q15"].values.astype(float),
        "adx":        df["adx"].values.astype(float),
        "bb_upper":   df["bb_upper"].values.astype(float),
        "bb_lower":   df["bb_lower"].values.astype(float),
        "ema50d":     df["ema50d"].values.astype(float),
        "ema200d":    df["ema200d"].values.astype(float),
        "ema20_4h":   df["ema20_4h"].values.astype(float),
        "ema50_4h":   df["ema50_4h"].values.astype(float),
        "asset_trend": df["asset_trend"].values,
    }


# ---------------------------------------------------------------------------
# Pattern checkers
# ---------------------------------------------------------------------------

def _check_pattern_a(sd: dict, bar: int, adx_val: float) -> Optional[str]:
    """EMA Pullback pattern. Returns 'BUY', 'SELL', or None."""
    if bar < 6:
        return None
    try:
        close     = sd["close"][bar]
        ema9      = sd["ema9"][bar]
        ema21     = sd["ema21"][bar]
        ema50     = sd["ema50"][bar]
        rsi       = sd["rsi"][bar]
        mh_cur    = sd["macd_hist"][bar]
        mh_prev   = sd["macd_hist"][bar - 1]

        if any(math.isnan(v) for v in [close, ema9, ema21, ema50, rsi, mh_cur, mh_prev, adx_val]):
            return None

        cl_arr  = sd["close"]
        e21_arr = sd["ema21"]
        prev5_dists = [
            abs(cl_arr[bar - i] - e21_arr[bar - i]) / max(e21_arr[bar - i], 1e-10)
            for i in range(1, 6)
        ]
        max_dist = max(prev5_dists)

        vol_ratio = sd["vol_ratio"][bar]
        ema20_4h  = sd["ema20_4h"][bar] if "ema20_4h" in sd else float("nan")
        ema50_4h  = sd["ema50_4h"][bar] if "ema50_4h" in sd else float("nan")
        ema50d    = sd["ema50d"][bar]
        ema200d   = sd["ema200d"][bar]

        if any(math.isnan(v) for v in [vol_ratio, ema50d, ema200d]):
            return None

        daily_ratio = ema50d / max(ema200d, 1e-10)

        # LONG: strong bull on daily + 4H confirmation
        use_4h = not (math.isnan(ema20_4h) or math.isnan(ema50_4h))
        bull_4h = (ema20_4h > ema50_4h) if use_4h else True
        bear_4h = (ema20_4h < ema50_4h) if use_4h else True

        if (ema9 > ema21
                and ema21 > ema50
                and daily_ratio > 1.02
                and bull_4h
                and abs(close - ema21) / ema21 < 0.015
                and max_dist > 0.015
                and 43 <= rsi <= 60
                and mh_cur > mh_prev
                and mh_cur > 0
                and vol_ratio >= 1.0
                and adx_val >= 22):
            return "BUY"

        if (ema9 < ema21
                and ema21 < ema50
                and daily_ratio < 0.98
                and bear_4h
                and abs(close - ema21) / ema21 < 0.015
                and max_dist > 0.015
                and 40 <= rsi <= 57
                and mh_cur < mh_prev
                and mh_cur < 0
                and vol_ratio >= 1.0
                and adx_val >= 22):
            return "SELL"

    except Exception:
        pass
    return None


def _check_pattern_b(sd: dict, bar: int, adx_val: float) -> Optional[str]:
    """RSI Extreme Recovery — mean reversion after genuine oversold/overbought.
    BUY:  RSI < 32 in last 6 bars (truly washed out), now crosses 48 upward.
    SELL: RSI > 68 in last 6 bars (truly euphoric),   now crosses 52 downward.
    """
    if bar < 8:
        return None
    try:
        rsi_arr   = sd["rsi"]
        rsi_prev  = rsi_arr[bar - 1]
        rsi_cur   = rsi_arr[bar]
        close     = sd["close"][bar]
        ema21     = sd["ema21"][bar]
        vol_ratio = sd["vol_ratio"][bar]
        bb_lower  = sd["bb_lower"][bar]
        bb_upper  = sd["bb_upper"][bar]

        if any(math.isnan(v) for v in [rsi_prev, rsi_cur, close, ema21, vol_ratio,
                                        bb_lower, bb_upper]):
            return None
        if vol_ratio < 1.8 or math.isnan(adx_val):
            return None

        # BUY: was truly oversold recently, now recovering
        had_oversold = any(
            not math.isnan(rsi_arr[bar - i]) and rsi_arr[bar - i] < 32
            for i in range(1, 7)
        )
        if (had_oversold
                and rsi_prev < 48
                and rsi_cur >= 48
                and close > bb_lower * 1.005
                and adx_val >= 15):
            return "BUY"

        # SELL: was truly overbought recently, now collapsing
        had_overbought = any(
            not math.isnan(rsi_arr[bar - i]) and rsi_arr[bar - i] > 68
            for i in range(1, 7)
        )
        if (had_overbought
                and rsi_prev > 52
                and rsi_cur <= 52
                and close < bb_upper * 0.995
                and adx_val >= 15):
            return "SELL"

    except Exception:
        pass
    return None


def _check_pattern_c(sd: dict, bar: int, sq_bars: int = 5) -> Optional[str]:
    """BB Squeeze Breakout. Returns 'BUY', 'SELL', or None."""
    if bar < sq_bars + 2:
        return None
    try:
        bbw_arr  = sd["bbw"]
        bbwq_arr = sd["bbw_q15"]
        bbw_cur  = bbw_arr[bar]
        bbwq_cur = bbwq_arr[bar]

        if math.isnan(bbw_cur) or math.isnan(bbwq_cur):
            return None

        for i in range(1, sq_bars + 1):
            bw = bbw_arr[bar - i]
            bq = bbwq_arr[bar - i]
            if math.isnan(bw) or math.isnan(bq):
                return None
            if bw >= bq:
                return None

        if bbw_cur <= bbwq_cur:
            return None

        adx_arr  = sd["adx"]
        adx_cur  = adx_arr[bar]
        adx_prev2= adx_arr[bar - 2]
        if math.isnan(adx_cur) or math.isnan(adx_prev2):
            return None
        if adx_cur <= adx_prev2 + 2.0:
            return None

        close     = sd["close"][bar]
        bb_upper  = sd["bb_upper"][bar]
        bb_lower  = sd["bb_lower"][bar]
        vol_ratio = sd["vol_ratio"][bar]

        if any(math.isnan(v) for v in [close, bb_upper, bb_lower, vol_ratio]):
            return None

        if close > bb_upper and vol_ratio >= 2.5:
            return "BUY"
        if close < bb_lower and vol_ratio >= 2.5:
            return "SELL"

    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Leverage helper
# ---------------------------------------------------------------------------

def _get_leverage(score: int, pattern: str) -> int:
    if pattern == "C":
        return 8
    if pattern == "B":
        return 7 if score >= 80 else 6
    # pattern A
    return 6 if score >= 80 else 5


# ---------------------------------------------------------------------------
# Main backtest engine
# ---------------------------------------------------------------------------

def run_engine(sym_data_list, timestamps, btc_macro_dict, btc_rsi_dict,
               score_min, risk_pct, max_pos):
    """
    Core backtest loop.
    Returns (trades, eq_curve, day_wins).
    """
    equity          = INITIAL_CAPITAL
    open_positions  = {}
    pending_entries = {}   # key: sym+pattern → params, executed at next bar open (1-bar delay)
    trades          = []
    eq_curve        = []
    day_wins        = {}

    current_day       = ""
    day_start_equity  = INITIAL_CAPITAL
    cooldown_tracker  = {}   # key: sym+pattern → last fire ts
    last_b_bar        = {}   # key: sym → last bar index where pattern B fired

    # Build fast lookup: sym → sym_data
    sym_lookup = {sd["name"]: sd for sd in sym_data_list}

    for ts in timestamps:
        eq_curve.append(equity)

        ts_day = str(ts)[:10]

        # Daily reset
        if ts_day != current_day:
            current_day      = ts_day
            day_start_equity = equity
            if ts_day not in day_wins:
                day_wins[ts_day] = {"wins": 0, "losses": 0}

        # ------------------------------------------------------------------ #
        # 0. EXECUTE PENDING ENTRIES AT THIS BAR'S OPEN (1-bar delay)         #
        # ------------------------------------------------------------------ #
        for pk in list(pending_entries.keys()):
            if len(open_positions) >= max_pos:
                break
            p   = pending_entries.pop(pk)
            sd  = sym_lookup.get(p["sym"])
            if sd is None:
                continue
            bar = sd["ts_to_pos"].get(ts)
            if bar is None:
                continue
            open_px = float(sd["open"][bar])
            side    = p["side"]
            entry_price = open_px * (1 + SLIPPAGE) if side == "long" else open_px * (1 - SLIPPAGE)
            sl_pct = PATTERN[p["pattern"]]["sl"]
            tp_pct = PATTERN[p["pattern"]]["tp"]
            if side == "long":
                sl = entry_price * (1 - sl_pct)
                tp = entry_price * (1 + tp_pct)
            else:
                sl = entry_price * (1 + sl_pct)
                tp = entry_price * (1 - tp_pct)
            pos_key = p["sym"] + p["pattern"] + str(ts)
            open_positions[pos_key] = {
                "sym":         p["sym"],
                "side":        side,
                "pattern":     p["pattern"],
                "entry_ts":    ts,
                "entry_price": entry_price,
                "sl":          sl,
                "tp":          tp,
                "margin":      p["margin"],
                "leverage":    p["leverage"],
                "score":       p["score"],
                "adx_entry":   p["adx_entry"],
                "asset_trend": p["asset_trend"],
                "btc_macro":   p["btc_macro"],
            }

        daily_loss = (day_start_equity - equity) / (day_start_equity + 1e-10)
        skip_entries = daily_loss > DAILY_LOSS_LIMIT

        # ------------------------------------------------------------------ #
        # 1. PROCESS EXITS                                                     #
        # ------------------------------------------------------------------ #
        pos_keys_to_remove = []
        for pos_key, pos in list(open_positions.items()):
            sym      = pos["sym"]
            sd       = sym_lookup.get(sym)
            if sd is None:
                continue

            bar = sd["ts_to_pos"].get(ts)
            if bar is None:
                continue

            h  = sd["high"][bar]
            lo = sd["low"][bar]
            cl = sd["close"][bar]

            entry  = pos["entry_price"]
            sl     = pos["sl"]
            tp     = pos["tp"]
            side   = pos["side"]

            exit_price  = None
            exit_reason = None

            # Simple SL / TP exit (no partial — cleaner expected value math)
            if side == "long":
                if h >= tp:
                    exit_price  = tp
                    exit_reason = "take_profit"
                elif lo <= sl:
                    exit_price  = sl
                    exit_reason = "stop_loss"
            else:  # short
                if lo <= tp:
                    exit_price  = tp
                    exit_reason = "take_profit"
                elif h >= sl:
                    exit_price  = sl
                    exit_reason = "stop_loss"

            # Time stop: 36 hours max
            elapsed = (ts - pos["entry_ts"]).total_seconds()
            if exit_price is None and elapsed > 36 * 3600:
                exit_price  = cl
                exit_reason = "time_stop"

            if exit_price is not None:
                # Adverse exit slippage (price moves against you when closing)
                if side == "long":
                    exit_price = exit_price * (1 - EXIT_SLIPPAGE)
                else:
                    exit_price = exit_price * (1 + EXIT_SLIPPAGE)
                side_mult = 1 if side == "long" else -1
                raw_pnl   = (exit_price - entry) / (entry + 1e-10) * side_mult * pos["leverage"] * pos["margin"]
                notional  = pos["margin"] * pos["leverage"]
                commission_cost = notional * COMMISSION * 2   # 0.1% entry + 0.1% exit on full notional
                net_pnl   = raw_pnl - commission_cost
                pnl_pct   = net_pnl / (pos["margin"] + 1e-10)

                equity += net_pnl

                # Track day wins/losses
                if ts_day not in day_wins:
                    day_wins[ts_day] = {"wins": 0, "losses": 0}
                if net_pnl > 0:
                    day_wins[ts_day]["wins"] += 1
                else:
                    day_wins[ts_day]["losses"] += 1

                trades.append(Trade(
                    symbol      = sym,
                    side        = side,
                    pattern     = pos["pattern"],
                    entry_ts    = pos["entry_ts"],
                    exit_ts     = ts,
                    entry_price = entry,
                    exit_price  = exit_price,
                    margin_eur  = pos["margin"],
                    pnl_eur     = net_pnl,
                    pnl_pct     = pnl_pct,
                    exit_reason = exit_reason,
                    score       = pos["score"],
                    leverage    = pos["leverage"],
                    adx_entry   = pos["adx_entry"],
                    asset_trend = pos["asset_trend"],
                    btc_macro   = pos["btc_macro"],
                ))
                pos_keys_to_remove.append(pos_key)

        for k in pos_keys_to_remove:
            del open_positions[k]

        # ------------------------------------------------------------------ #
        # 2. NEW ENTRIES                                                       #
        # ------------------------------------------------------------------ #
        if skip_entries or len(open_positions) + len(pending_entries) >= max_pos:
            continue

        btc_macro = btc_macro_dict.get(ts_day, "neutral")

        # Get BTC daily + 4H trend for macro filtering
        btc_sd = sym_lookup.get("BTC-USD")
        btc_ema50  = None
        btc_ema200 = None
        btc_4h_bull = None   # True=bull, False=bear, None=unknown
        if btc_sd is not None:
            btc_bar = btc_sd["ts_to_pos"].get(ts)
            if btc_bar is not None and btc_bar < len(btc_sd["ema50d"]):
                e50  = btc_sd["ema50d"][btc_bar]
                e200 = btc_sd["ema200d"][btc_bar]
                if not math.isnan(e50):
                    btc_ema50 = e50
                if not math.isnan(e200):
                    btc_ema200 = e200
                # 4H BTC trend
                b4h_20 = btc_sd["ema20_4h"][btc_bar]
                b4h_50 = btc_sd["ema50_4h"][btc_bar]
                if not (math.isnan(b4h_20) or math.isnan(b4h_50)):
                    btc_4h_bull = b4h_20 > b4h_50

        for sd in sym_data_list:
            if len(open_positions) + len(pending_entries) >= max_pos:
                break

            sym = sd["name"]
            if sym == "BTC-USD":
                continue

            bar = sd["ts_to_pos"].get(ts)
            if bar is None or bar < WARMUP:
                continue

            adx_val     = float(sd["adx"][bar])
            asset_trend = str(sd["asset_trend"][bar])
            close       = sd["close"][bar]

            if math.isnan(adx_val):
                adx_val = 0.0

            # Try patterns in order: C, A only (B removed)
            for pattern in ["C", "A"]:
                # Skip if pattern not in active config
                if pattern not in PATTERN:
                    continue

                # Cooldown check
                ck = sym + pattern
                last_fire = cooldown_tracker.get(ck)
                if last_fire is not None:
                    hours_since = (ts - last_fire).total_seconds() / 3600
                    if hours_since < PATTERN[pattern]["cooldown_h"]:
                        continue

                # Detect pattern signal
                action = None
                if pattern == "A":
                    action = _check_pattern_a(sd, bar, adx_val)
                elif pattern == "C":
                    action = _check_pattern_c(sd, bar)

                if action is None:
                    continue

                        # Asset trend alignment
                if pattern == "A":
                    if action == "BUY"  and asset_trend != "bull":
                        continue
                    if action == "SELL" and asset_trend != "bear":
                        continue
                else:  # Pattern C (BB squeeze)
                    sc_chk = sd["buy_sc"][bar] if action == "BUY" else sd["sell_sc"][bar]
                    if sc_chk < 72:
                        if action == "BUY"  and asset_trend == "bear":
                            continue
                        if action == "SELL" and asset_trend == "bull":
                            continue

                # Score check
                score = int(sd["buy_sc"][bar]) if action == "BUY" else int(sd["sell_sc"][bar])
                required_score = max(score_min, PATTERN[pattern]["score_min"])
                if score < required_score:
                    continue

                # BTC macro filters
                if btc_ema50 is not None and btc_ema200 is not None:
                    be50  = float(btc_ema50)
                    be200 = float(btc_ema200)
                    if action == "BUY"  and btc_macro == "bear" and be50 < be200 * BTC_CRASH_THRESH:
                        continue
                    if action == "SELL" and btc_macro == "bull" and be50 > be200 * BTC_EUPHORIA_THRESH:
                        continue

                # BTC 4H trend filter — avoid counter-trend unless very high conviction
                if btc_4h_bull is not None and score < 82:
                    if action == "BUY"  and not btc_4h_bull:
                        continue
                    if action == "SELL" and btc_4h_bull:
                        continue

                # Signal confirmed — queue for execution at next bar open (1-bar delay)
                side = "long" if action == "BUY" else "short"
                leverage    = _get_leverage(score, pattern)
                risk_mult   = PATTERN[pattern]["risk_mult"]
                margin      = equity * risk_pct * risk_mult

                pk = sym + pattern
                if pk not in pending_entries:
                    pending_entries[pk] = {
                        "sym":         sym,
                        "side":        side,
                        "pattern":     pattern,
                        "margin":      margin,
                        "leverage":    leverage,
                        "score":       score,
                        "adx_entry":   adx_val,
                        "asset_trend": asset_trend,
                        "btc_macro":   btc_macro,
                    }

                # Update cooldown and last-B-bar
                cooldown_tracker[ck] = ts
                if pattern == "B":
                    last_b_bar[sym] = bar

                break  # one entry per symbol per bar

    return trades, eq_curve, day_wins


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _quick_metrics(trades, eq_curve, window_start) -> dict:
    if not eq_curve:
        return {
            "n_trades": 0, "ret": 0.0, "max_dd": 0.0,
            "win_rate": 0.0, "net_pnl": 0.0, "sharpe": 0.0,
            "profit_factor": 0.0, "final_equity": INITIAL_CAPITAL,
        }

    final_equity = eq_curve[-1]
    ret = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL

    # Max drawdown
    peak = INITIAL_CAPITAL
    max_dd = 0.0
    for e in eq_curve:
        if e > peak:
            peak = e
        dd = (peak - e) / (peak + 1e-10)
        if dd > max_dd:
            max_dd = dd

    n_trades = len(trades)
    if n_trades == 0:
        return {
            "n_trades": 0, "ret": ret, "max_dd": max_dd,
            "win_rate": 0.0, "net_pnl": 0.0, "sharpe": 0.0,
            "profit_factor": 0.0, "final_equity": final_equity,
        }

    wins       = [t for t in trades if t.pnl_eur > 0]
    losses     = [t for t in trades if t.pnl_eur <= 0]
    win_rate   = len(wins) / n_trades
    net_pnl    = sum(t.pnl_eur for t in trades)

    # Sharpe — daily returns sampled every 24 bars
    daily_eq = eq_curve[::24]
    if len(daily_eq) > 1:
        daily_rets = np.diff(daily_eq) / (np.array(daily_eq[:-1]) + 1e-10)
        mean_r  = float(np.mean(daily_rets))
        std_r   = float(np.std(daily_rets)) + 1e-10
        sharpe  = (mean_r / std_r) * math.sqrt(365)
    else:
        sharpe = 0.0

    # Profit factor
    gross_win  = sum(t.pnl_eur for t in wins)
    gross_loss = abs(sum(t.pnl_eur for t in losses))
    profit_factor = gross_win / (gross_loss + 1e-10)

    return {
        "n_trades":      n_trades,
        "ret":           ret,
        "max_dd":        max_dd,
        "win_rate":      win_rate,
        "net_pnl":       net_pnl,
        "sharpe":        sharpe,
        "profit_factor": profit_factor,
        "final_equity":  final_equity,
    }


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_report(trades, eq_curve, day_wins, window_start, best_cfg: str, t0: float):
    m = _quick_metrics(trades, eq_curve, window_start)

    console.print(f"\n[bold cyan]━━━ PRISM v16 | Config: {best_cfg} ━━━[/bold cyan]")
    console.print(
        f"  Capital: €{INITIAL_CAPITAL:.0f} → €{m['final_equity']:.2f}  "
        f"Return: [{'green' if m['ret']>=0 else 'red'}]{m['ret']:.1%}[/]  "
        f"DrawDown: [red]{m['max_dd']:.1%}[/]  "
        f"Sharpe: {m.get('sharpe', 0):.2f}  "
        f"Trades: {m['n_trades']}"
    )

    # ---- Monthly breakdown ----
    if trades:
        mtbl = Table(title="Monthly Breakdown", box=box.SIMPLE_HEAD)
        mtbl.add_column("Month",   style="cyan")
        mtbl.add_column("Trades",  justify="right")
        mtbl.add_column("Win%",    justify="right")
        mtbl.add_column("PnL €",   justify="right")

        monthly: dict = {}
        for t in trades:
            mk = t.exit_ts.strftime("%Y-%m")
            if mk not in monthly:
                monthly[mk] = []
            monthly[mk].append(t)

        for mk in sorted(monthly):
            tl   = monthly[mk]
            wins = sum(1 for t in tl if t.pnl_eur > 0)
            wr   = wins / len(tl) if tl else 0
            pnl  = sum(t.pnl_eur for t in tl)
            color = "green" if pnl >= 0 else "red"
            mtbl.add_row(mk, str(len(tl)), f"{wr:.0%}", f"[{color}]{pnl:+.2f}[/]")
        console.print(mtbl)

    # ---- Pattern breakdown ----
    if trades:
        ptbl = Table(title="Pattern Breakdown", box=box.SIMPLE_HEAD)
        ptbl.add_column("Pattern", style="cyan")
        ptbl.add_column("Count",   justify="right")
        ptbl.add_column("Win%",    justify="right")
        ptbl.add_column("Avg PnL", justify="right")

        for pat in ["A", "B", "C"]:
            tl   = [t for t in trades if t.pattern == pat]
            if not tl:
                continue
            wins = sum(1 for t in tl if t.pnl_eur > 0)
            wr   = wins / len(tl)
            avg  = sum(t.pnl_eur for t in tl) / len(tl)
            color = "green" if avg >= 0 else "red"
            ptbl.add_row(pat, str(len(tl)), f"{wr:.0%}", f"[{color}]{avg:+.2f}[/]")
        console.print(ptbl)

    # ---- Top 10 trades ----
    if trades:
        top10 = sorted(trades, key=lambda t: t.pnl_eur, reverse=True)[:10]
        ttbl  = Table(title="Top 10 Trades", box=box.SIMPLE_HEAD)
        ttbl.add_column("Symbol",  style="cyan")
        ttbl.add_column("Side",    style="magenta")
        ttbl.add_column("Pat",     justify="center")
        ttbl.add_column("PnL €",   justify="right")
        ttbl.add_column("Exit",    justify="center")
        for t in top10:
            color = "green" if t.pnl_eur >= 0 else "red"
            ttbl.add_row(
                t.symbol, t.side, t.pattern,
                f"[{color}]{t.pnl_eur:+.2f}[/]",
                t.exit_reason,
            )
        console.print(ttbl)

    # ---- ASCII equity chart ----
    if len(eq_curve) > 10:
        console.print("\n[bold]Equity Curve (ASCII)[/bold]")
        sample  = eq_curve[::max(1, len(eq_curve) // 50)]
        min_eq  = min(sample)
        max_eq  = max(sample)
        rng     = max_eq - min_eq + 1e-10
        rows    = 10
        cols    = len(sample)
        # Build grid
        grid = [[" " for _ in range(cols)] for _ in range(rows)]
        for c, val in enumerate(sample):
            row_idx = rows - 1 - int((val - min_eq) / rng * (rows - 1))
            row_idx = max(0, min(rows - 1, row_idx))
            grid[row_idx][c] = "█"

        for row in grid:
            console.print("".join(row))
        console.print(
            f"  €{min_eq:.0f}{'':>46}€{max_eq:.0f}"
        )

    console.print(f"\n  Elapsed: {time.time() - t0:.1f}s")


# ---------------------------------------------------------------------------
# BTC macro dict builder
# ---------------------------------------------------------------------------

def _build_btc_macro_dict(btc_df: pd.DataFrame) -> dict:
    """Build {date_str: 'bull'|'bear'|'neutral'} from BTC daily EMA50/200."""
    macro = {}
    if btc_df is None or btc_df.empty:
        return macro

    df_1d = btc_df[["close"]].resample("1D").last().dropna()
    ema50d  = df_1d["close"].ewm(span=50,  adjust=False).mean()
    ema200d = df_1d["close"].ewm(span=200, adjust=False).mean()

    for ts, e50, e200 in zip(df_1d.index, ema50d, ema200d):
        if math.isnan(e50) or math.isnan(e200):
            label = "neutral"
        elif e50 > e200 * 1.01:
            label = "bull"
        elif e50 < e200 * 0.99:
            label = "bear"
        else:
            label = "neutral"
        macro[str(ts)[:10]] = label

    return macro


# ---------------------------------------------------------------------------
# Full backtest
# ---------------------------------------------------------------------------

def run_full_backtest(cfg_name: str = "Equilibre") -> dict:
    t0 = time.time()

    cfg_dict = next((c for c in CONFIGS if c["name"] == cfg_name), CONFIGS[1])
    cfg = AppConfig(
        name      = cfg_dict["name"],
        score_min = cfg_dict["score_min"],
        risk_pct  = cfg_dict["risk_pct"],
        max_pos   = cfg_dict["max_pos"],
    )

    console.print(f"  Downloading {len(SYMBOLS_YF)} symbols...")
    sym_data_list = []
    for i, sym in enumerate(SYMBOLS_YF):
        sd = precompute_symbol_v16(sym, cfg_dict)
        status = "ok" if sd else "FAIL"
        console.print(f"    [{i+1:2d}/{len(SYMBOLS_YF)}] {sym:<14} {status}")
        if sd:
            sym_data_list.append(sd)

    if not sym_data_list:
        console.print("[red]No data downloaded.[/red]")
        return {}

    # Build BTC macro dict
    btc_sd = next((s for s in sym_data_list if s["name"] == "BTC-USD"), None)
    btc_macro_dict = _build_btc_macro_dict(btc_sd["df"] if btc_sd else None)
    btc_rsi_dict   = {}

    # Common timestamps — intersection, after WARMUP offset
    ts_sets = [set(sd["ts_index"]) for sd in sym_data_list]
    common_ts = ts_sets[0]
    for s in ts_sets[1:]:
        common_ts = common_ts.intersection(s)

    if not common_ts:
        console.print("[red]No common timestamps found.[/red]")
        return {}

    timestamps = sorted(common_ts)

    # Drop first WARMUP bars
    timestamps = timestamps[WARMUP:]

    console.print(f"  Running engine: {len(timestamps):,} bars, {len(sym_data_list)} symbols...")
    trades, eq_curve, day_wins = run_engine(
        sym_data_list = sym_data_list,
        timestamps    = timestamps,
        btc_macro_dict= btc_macro_dict,
        btc_rsi_dict  = btc_rsi_dict,
        score_min     = cfg.score_min,
        risk_pct      = cfg.risk_pct,
        max_pos       = cfg.max_pos,
    )

    metrics = _quick_metrics(trades, eq_curve, timestamps[0] if timestamps else None)

    print_report(trades, eq_curve, day_wins,
                 window_start = timestamps[0] if timestamps else None,
                 best_cfg     = cfg.name,
                 t0           = t0)

    return {
        "config":       cfg_name,
        "metrics":      metrics,
        "trades":       [t.__dict__ for t in trades],
        "equity_curve": eq_curve,
    }


# ---------------------------------------------------------------------------
# Live signal scanner
# ---------------------------------------------------------------------------

def scan_live_signals(capital: float = 500.0, cfg_name: str = "Equilibre") -> dict:
    """Scan current bar for live trade signals across all symbols."""
    cfg_dict = next((c for c in CONFIGS if c["name"] == cfg_name), CONFIGS[1])

    signals = []
    btc_sd  = None

    sym_data_list = []
    for sym in SYMBOLS_YF:
        sd = precompute_symbol_v16(sym, cfg_dict)
        if sd:
            sym_data_list.append(sd)
            if sym == "BTC-USD":
                btc_sd = sd

    btc_macro_dict = _build_btc_macro_dict(btc_sd["df"] if btc_sd else None)
    now_day = str(datetime.now(timezone.utc))[:10]
    btc_macro = btc_macro_dict.get(now_day, "neutral")

    btc_ema50 = btc_ema200 = None
    if btc_sd is not None and len(btc_sd["ema50d"]) > 0:
        e50  = btc_sd["ema50d"][-1]
        e200 = btc_sd["ema200d"][-1]
        if not math.isnan(e50):
            btc_ema50 = e50
        if not math.isnan(e200):
            btc_ema200 = e200

    for sd in sym_data_list:
        sym = sd["name"]
        if sym == "BTC-USD":
            continue

        df  = sd["df"]
        bar = len(df) - 1
        if bar < WARMUP:
            continue

        adx_val     = float(sd["adx"][bar])
        asset_trend = str(sd["asset_trend"][bar])
        close       = float(sd["close"][bar])

        if math.isnan(adx_val):
            adx_val = 0.0

        for pattern in ["C", "B", "A"]:
            action = None
            if pattern == "A":
                action = _check_pattern_a(sd, bar, adx_val)
            elif pattern == "B":
                action = _check_pattern_b(sd, bar, adx_val)
            elif pattern == "C":
                action = _check_pattern_c(sd, bar)

            if action is None:
                continue

            score = int(sd["buy_sc"][bar]) if action == "BUY" else int(sd["sell_sc"][bar])
            required = max(cfg_dict["score_min"], PATTERN[pattern]["score_min"])
            if score < required:
                continue

            lev = _get_leverage(score, pattern)

            signals.append({
                "symbol":      sym,
                "sym_key":     SYMBOL_MAP[sym],
                "side":        action,
                "pattern":     pattern,
                "score":       score,
                "leverage":    lev,
                "asset_trend": asset_trend,
                "btc_macro":   btc_macro,
                "close":       close,
            })
            break  # one signal per symbol

    return {
        "signals":   signals,
        "timestamp": str(datetime.now(timezone.utc)),
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    t0 = time.time()
    console.print("[bold cyan]PRISM v16 — Multi-Pattern Crypto Strategy[/bold cyan]")

    results = {}
    for cfg in CONFIGS:
        console.print(f"\n[yellow]Running config: {cfg['name']}[/yellow]")
        results[cfg["name"]] = run_full_backtest(cfg["name"])

    # Comparison table
    tbl = Table(title="Config Comparison", box=box.ROUNDED)
    tbl.add_column("Config")
    tbl.add_column("Trades")
    tbl.add_column("Return")
    tbl.add_column("DrawDown")
    tbl.add_column("WinRate")
    tbl.add_column("Sharpe")

    best_cfg = None
    best_ret = -999

    for name, r in results.items():
        if not r or "metrics" not in r:
            continue
        m = r["metrics"]
        tbl.add_row(
            name,
            str(m["n_trades"]),
            f"{m['ret']:.1%}",
            f"{m['max_dd']:.1%}",
            f"{m['win_rate']:.1%}",
            f"{m.get('sharpe', 0):.2f}",
        )
        if m["ret"] > best_ret:
            best_ret = m["ret"]
            best_cfg = name

    console.print(tbl)
    console.print(f"\nBest config: [green]{best_cfg}[/green] | Total time: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
