#!/usr/bin/env python3
"""
PRISM v18 — 15-Minute Volatility Breakout (CCXT / Binance)
===========================================================
Même stratégie Pattern D que v17, mais avec :
  - Données Binance via CCXT (API publique, sans clés)
  - Historique 12 mois de bougies 15m (vs 60 jours yfinance)
  - Rapport mensuel détaillé
  - Cache disque pour éviter le re-téléchargement

Le but : valider que le Win Rate ~20-25% et P.Factor ~0.80 tiennent
sur un horizon qui inclut bull market, bear market et consolidation.
"""

import math, os, pickle, time, warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich import box

warnings.filterwarnings("ignore")
console = Console()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# OKX uses "BTC-USDT" format
SYMBOLS = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "AVAX-USDT",
    "ADA-USDT", "LINK-USDT", "XRP-USDT", "DOT-USDT", "ATOM-USDT",
    "LTC-USDT", "DOGE-USDT", "NEAR-USDT", "TRX-USDT", "ALGO-USDT",
    "FIL-USDT", "INJ-USDT", "OP-USDT",
]
# Note: BNB-USDT excluded — Binance token, not listed on OKX spot

INITIAL_CAPITAL  = 500.0
TIMEFRAME        = "15m"
MONTHS           = 12             # validation window
WARMUP           = 60             # bars for indicator warmup
COMMISSION       = 0.001          # 0.1% Binance taker per side
SLIPPAGE         = 0.0003
EXIT_SLIPPAGE    = 0.0002

# Pattern D — identical to v17 (validated on 60-day window)
SL_PCT           = 0.006
TP_PCT           = 0.022          # R:R = 3.67:1  |  break-even WR = 21.4%
BREAKEVEN_TRIG   = 0.013
SQUEEZE_BARS     = 5
ADX_MIN          = 22
VOL_RATIO_MIN    = 2.0
TIME_STOP_BARS   = 16
COOLDOWN_BARS    = 12

DAILY_PROFIT_CAP = 0.03
DAILY_LOSS_CAP   = 0.015

BASE_LEVERAGE    = 2
HIGH_LEVERAGE    = 3

CONFIGS = [
    {"name": "Conservateur", "risk_pct": 0.030, "max_pos": 3},
    {"name": "Equilibre",    "risk_pct": 0.040, "max_pos": 4},
    {"name": "Agressif",     "risk_pct": 0.055, "max_pos": 5},
]

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache_v18")
CACHE_MAX_AGE_H = 23   # refresh cache if older than 23 hours

OKX_CANDLES_URL = "https://www.okx.com/api/v5/market/history-candles"
OKX_BAR_MAP    = {"15m": "15m", "1h": "1H", "4h": "4H"}


# ---------------------------------------------------------------------------
# Data download with disk cache (OKX REST API — no auth needed)
# ---------------------------------------------------------------------------

def _cache_path(sym: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = sym.replace("/", "_").replace("-", "_")
    return os.path.join(CACHE_DIR, f"{safe}_{TIMEFRAME}_{MONTHS}m.pkl")


def _cache_valid(path: str) -> bool:
    if not os.path.exists(path):
        return False
    age_h = (time.time() - os.path.getmtime(path)) / 3600
    return age_h < CACHE_MAX_AGE_H


def _fetch_okx_raw(inst_id: str) -> list:
    """
    Paginate OKX history-candles going back MONTHS months.
    Returns list of [ts_ms, open, high, low, close, volume, ...] strings.
    OKX returns newest-first per page; we sort oldest-first at the end.
    """
    until_ms = int(time.time() * 1000)
    since_ms  = until_ms - MONTHS * 30 * 24 * 60 * 60 * 1000
    all_rows  = []
    after     = None   # pagination: fetch candles OLDER than this timestamp

    for _ in range(500):   # safety cap (~34k candles / 100 per page = 346 pages)
        params = {"instId": inst_id, "bar": TIMEFRAME, "limit": 100}
        if after:
            params["after"] = after

        try:
            r    = requests.get(OKX_CANDLES_URL, params=params, timeout=15)
            data = r.json()
        except Exception:
            break

        if data.get("code") != "0" or not data.get("data"):
            break

        batch = data["data"]
        all_rows.extend(batch)

        oldest_ts = int(batch[-1][0])
        if oldest_ts <= since_ms:
            break
        after = batch[-1][0]
        time.sleep(0.08)   # ~12 req/s — well within OKX limits

    # Filter to requested window, sort oldest→newest
    all_rows = [r for r in all_rows if int(r[0]) >= since_ms]
    all_rows.sort(key=lambda x: int(x[0]))
    return all_rows


def download_ohlcv(sym: str, force: bool = False) -> Optional[pd.DataFrame]:
    """
    Download MONTHS of 15m OHLCV from OKX (public API, no keys required).
    Results cached to disk — re-used if < CACHE_MAX_AGE_H hours old.
    """
    path = _cache_path(sym)
    if not force and _cache_valid(path):
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass

    raw = _fetch_okx_raw(sym)
    if len(raw) < WARMUP + 100:
        return None

    # OKX format: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    df = pd.DataFrame(raw, columns=[
        "timestamp","open","high","low","close","volume","vol_ccy","vol_quote","confirm"
    ])
    df = df[["timestamp","open","high","low","close","volume"]]
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_datetime(
        df["timestamp"].astype(int), unit="ms", utc=True
    ).dt.tz_localize(None)
    df = df.set_index("timestamp")
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df = df.dropna(subset=["close", "open", "high", "low", "volume"])

    with open(path, "wb") as f:
        pickle.dump(df, f)

    return df


# ---------------------------------------------------------------------------
# Indicators (identical to v17)
# ---------------------------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    df["ema9"]  = close.ewm(span=9,  adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()

    bb_mid        = close.rolling(20).mean()
    bb_std        = close.rolling(20).std()
    df["bb_upper"]= bb_mid + 2 * bb_std
    df["bb_lower"]= bb_mid - 2 * bb_std
    bbw           = (df["bb_upper"] - df["bb_lower"]) / (bb_mid + 1e-10)
    df["bbw"]     = bbw
    df["bbw_q20"] = bbw.rolling(40).quantile(0.20)

    df["vol_ratio"] = volume / (volume.rolling(20).mean() + 1e-10)

    delta  = close.diff()
    gain   = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss   = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df["rsi14"] = 100 - 100 / (1 + gain / (loss + 1e-10))

    tr   = pd.concat([high - low,
                      (high - close.shift()).abs(),
                      (low  - close.shift()).abs()], axis=1).max(axis=1)
    dm_p = (high - high.shift()).clip(lower=0)
    dm_m = (low.shift() - low).clip(lower=0)
    dm_p = dm_p.where(dm_p > dm_m, 0)
    dm_m = dm_m.where(dm_m > dm_p, 0)
    atr14 = tr.ewm(com=13, adjust=False).mean()
    dip   = 100 * dm_p.ewm(com=13, adjust=False).mean() / (atr14 + 1e-10)
    dim   = 100 * dm_m.ewm(com=13, adjust=False).mean() / (atr14 + 1e-10)
    dx    = 100 * (dip - dim).abs() / (dip + dim + 1e-10)
    df["adx"] = dx.ewm(com=13, adjust=False).mean()

    # 1H trend
    df_1h     = df[["close"]].resample("1h").last().dropna()
    ema20_1h  = df_1h["close"].ewm(span=20, adjust=False).mean()
    ema50_1h  = df_1h["close"].ewm(span=50, adjust=False).mean()
    df["ema20_1h"] = ema20_1h.reindex(df.index, method="ffill")
    df["ema50_1h"] = ema50_1h.reindex(df.index, method="ffill")

    # 4H trend + ADX
    df_4h = df[["open","high","low","close"]].resample("4h").agg(
                {"open":"first","high":"max","low":"min","close":"last"}
            ).dropna()
    ema9_4h  = df_4h["close"].ewm(span=9,  adjust=False).mean()
    ema21_4h = df_4h["close"].ewm(span=21, adjust=False).mean()
    df["ema9_4h"]  = ema9_4h.reindex(df.index,  method="ffill")
    df["ema21_4h"] = ema21_4h.reindex(df.index, method="ffill")

    _tr4   = pd.concat([df_4h["high"] - df_4h["low"],
                        (df_4h["high"] - df_4h["close"].shift()).abs(),
                        (df_4h["low"]  - df_4h["close"].shift()).abs()], axis=1).max(axis=1)
    _dmp4  = (df_4h["high"] - df_4h["high"].shift()).clip(lower=0)
    _dmm4  = (df_4h["low"].shift() - df_4h["low"]).clip(lower=0)
    _dmp4  = _dmp4.where(_dmp4 > _dmm4, 0)
    _dmm4  = _dmm4.where(_dmm4 > _dmp4, 0)
    _atr4  = _tr4.ewm(com=13, adjust=False).mean()
    _dip4  = 100 * _dmp4.ewm(com=13, adjust=False).mean() / (_atr4 + 1e-10)
    _dim4  = 100 * _dmm4.ewm(com=13, adjust=False).mean() / (_atr4 + 1e-10)
    _dx4   = 100 * (_dip4 - _dim4).abs() / (_dip4 + _dim4 + 1e-10)
    adx4h  = _dx4.ewm(com=13, adjust=False).mean()
    df["adx_4h"] = adx4h.reindex(df.index, method="ffill")

    return df


def precompute(sym: str) -> Optional[dict]:
    df = download_ohlcv(sym)
    if df is None:
        return None
    df = compute_indicators(df)
    return {
        "name":      sym,
        "df":        df,
        "ts_index":  df.index,
        "ts_to_pos": {ts: i for i, ts in enumerate(df.index)},
        "open":      df["open"].values.astype(float),
        "close":     df["close"].values.astype(float),
        "high":      df["high"].values.astype(float),
        "low":       df["low"].values.astype(float),
        "ema9":      df["ema9"].values.astype(float),
        "ema21":     df["ema21"].values.astype(float),
        "bb_upper":  df["bb_upper"].values.astype(float),
        "bb_lower":  df["bb_lower"].values.astype(float),
        "bbw":       df["bbw"].values.astype(float),
        "bbw_q20":   df["bbw_q20"].values.astype(float),
        "vol_ratio": df["vol_ratio"].values.astype(float),
        "rsi14":     df["rsi14"].values.astype(float),
        "adx":       df["adx"].values.astype(float),
        "ema20_1h":  df["ema20_1h"].values.astype(float),
        "ema50_1h":  df["ema50_1h"].values.astype(float),
        "ema9_4h":   df["ema9_4h"].values.astype(float),
        "ema21_4h":  df["ema21_4h"].values.astype(float),
        "adx_4h":    df["adx_4h"].values.astype(float),
    }


# ---------------------------------------------------------------------------
# Pattern D (identical to v17 — two-bar confirmation)
# ---------------------------------------------------------------------------

def _check_pattern_d(sd: dict, bar: int) -> Optional[str]:
    if bar < SQUEEZE_BARS + 4:
        return None
    try:
        bbw_arr  = sd["bbw"]
        bbwq_arr = sd["bbw_q20"]
        bbw_cur  = bbw_arr[bar]
        bbwq_cur = bbwq_arr[bar]
        if math.isnan(bbw_cur) or math.isnan(bbwq_cur):
            return None

        # Squeeze for SQUEEZE_BARS ending 2 bars ago
        for i in range(2, SQUEEZE_BARS + 2):
            bw = bbw_arr[bar - i]
            bq = bbwq_arr[bar - i]
            if math.isnan(bw) or math.isnan(bq) or bw >= bq:
                return None

        # bar-1: first escape bar
        bbw_prev = bbw_arr[bar - 1]
        bbwq_prev = bbwq_arr[bar - 1]
        if math.isnan(bbw_prev) or math.isnan(bbwq_prev) or bbw_prev <= bbwq_prev:
            return None

        # Current bar: squeeze still released
        if bbw_cur <= bbwq_cur:
            return None

        adx_cur = sd["adx"][bar]
        if math.isnan(adx_cur) or adx_cur < ADX_MIN:
            return None

        close      = sd["close"][bar]
        bb_upper   = sd["bb_upper"][bar]
        bb_lower   = sd["bb_lower"][bar]
        vol_ratio  = sd["vol_ratio"][bar]
        ema9       = sd["ema9"][bar]
        ema21      = sd["ema21"][bar]
        rsi        = sd["rsi14"][bar]
        prev_close = sd["close"][bar - 1]
        prev_upper = sd["bb_upper"][bar - 1]
        prev_lower = sd["bb_lower"][bar - 1]

        vals = [close, bb_upper, bb_lower, vol_ratio, ema9, ema21, rsi,
                prev_close, prev_upper, prev_lower]
        if any(math.isnan(v) for v in vals):
            return None

        if vol_ratio < VOL_RATIO_MIN:
            return None

        band_margin = 0.002
        if (close > bb_upper * (1 + band_margin)
                and prev_close > prev_upper
                and ema9 > ema21
                and 50 < rsi < 78):
            return "BUY"
        if (close < bb_lower * (1 - band_margin)
                and prev_close < prev_lower
                and ema9 < ema21
                and 22 < rsi < 50):
            return "SELL"

    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    symbol:      str
    side:        str
    entry_ts:    pd.Timestamp
    exit_ts:     pd.Timestamp
    entry_price: float
    exit_price:  float
    margin_eur:  float
    pnl_eur:     float
    exit_reason: str
    leverage:    int
    adx_entry:   float
    trend_1h:    str


# ---------------------------------------------------------------------------
# Engine (identical to v17)
# ---------------------------------------------------------------------------

def run_engine(sym_data_list, timestamps, risk_pct, max_pos):
    equity           = INITIAL_CAPITAL
    open_positions   = {}
    pending_entries  = {}
    trades           = []
    eq_curve         = []
    day_wins         = {}

    current_day      = ""
    day_start_equity = INITIAL_CAPITAL
    equity_peak      = INITIAL_CAPITAL
    cooldown_tracker = {}

    sym_lookup = {sd["name"]: sd for sd in sym_data_list}

    for ts in timestamps:
        eq_curve.append(equity)
        ts_day = str(ts)[:10]

        if ts_day != current_day:
            current_day      = ts_day
            day_start_equity = equity
            day_wins.setdefault(ts_day, {"wins": 0, "losses": 0})

        # ---- Execute pending entries (1-bar delay) ----
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
            entry_price = (open_px * (1 + SLIPPAGE) if side == "long"
                           else open_px * (1 - SLIPPAGE))
            sl = (entry_price * (1 - SL_PCT)  if side == "long"
                  else entry_price * (1 + SL_PCT))
            tp = (entry_price * (1 + TP_PCT)  if side == "long"
                  else entry_price * (1 - TP_PCT))
            open_positions[p["sym"] + str(ts)] = {
                "sym":         p["sym"],
                "side":        side,
                "entry_ts":    ts,
                "entry_bar":   bar,
                "entry_price": entry_price,
                "sl":          sl,
                "tp":          tp,
                "sl_at_be":    False,
                "margin":      p["margin"],
                "leverage":    p["leverage"],
                "adx_entry":   p["adx_entry"],
                "trend_1h":    p["trend_1h"],
            }

        day_pnl_pct   = (equity - day_start_equity) / (day_start_equity + 1e-10)
        skip_entries  = day_pnl_pct >= DAILY_PROFIT_CAP or day_pnl_pct <= -DAILY_LOSS_CAP

        if equity > equity_peak:
            equity_peak = equity
        drawdown_from_peak = (equity_peak - equity) / (equity_peak + 1e-10)

        # ---- Process exits ----
        to_remove = []
        for pos_key, pos in list(open_positions.items()):
            sym = pos["sym"]
            sd  = sym_lookup.get(sym)
            if sd is None:
                continue
            bar = sd["ts_to_pos"].get(ts)
            if bar is None:
                continue

            h   = sd["high"][bar]
            lo  = sd["low"][bar]
            cl  = sd["close"][bar]
            entry  = pos["entry_price"]
            sl     = pos["sl"]
            tp     = pos["tp"]
            side   = pos["side"]

            if not pos["sl_at_be"]:
                if side == "long"  and h >= entry * (1 + BREAKEVEN_TRIG):
                    pos["sl"]      = entry * 1.0001
                    pos["sl_at_be"] = True
                    sl              = pos["sl"]
                elif side == "short" and lo <= entry * (1 - BREAKEVEN_TRIG):
                    pos["sl"]      = entry * 0.9999
                    pos["sl_at_be"] = True
                    sl              = pos["sl"]

            exit_price  = None
            exit_reason = None

            if side == "long":
                if h >= tp:    exit_price, exit_reason = tp, "take_profit"
                elif lo <= sl: exit_price, exit_reason = sl, "stop_loss"
            else:
                if lo <= tp:   exit_price, exit_reason = tp, "take_profit"
                elif h >= sl:  exit_price, exit_reason = sl, "stop_loss"

            bars_held = bar - pos["entry_bar"]
            if exit_price is None and bars_held >= TIME_STOP_BARS:
                exit_price, exit_reason = cl, "time_stop"

            if exit_price is not None:
                if side == "long":
                    exit_price *= (1 - EXIT_SLIPPAGE)
                else:
                    exit_price *= (1 + EXIT_SLIPPAGE)

                side_mult = 1 if side == "long" else -1
                notional  = pos["margin"] * pos["leverage"]
                raw_pnl   = (exit_price - entry) / (entry + 1e-10) * side_mult * notional
                fees      = notional * COMMISSION * 2
                net_pnl   = raw_pnl - fees

                equity   += net_pnl
                day_wins[ts_day]["wins" if net_pnl > 0 else "losses"] += 1

                trades.append(Trade(
                    symbol      = sym,
                    side        = side,
                    entry_ts    = pos["entry_ts"],
                    exit_ts     = ts,
                    entry_price = entry,
                    exit_price  = exit_price,
                    margin_eur  = pos["margin"],
                    pnl_eur     = net_pnl,
                    exit_reason = exit_reason,
                    leverage    = pos["leverage"],
                    adx_entry   = pos["adx_entry"],
                    trend_1h    = pos["trend_1h"],
                ))
                to_remove.append(pos_key)

        for k in to_remove:
            del open_positions[k]

        # ---- New entries ----
        if skip_entries or len(open_positions) + len(pending_entries) >= max_pos:
            continue
        if drawdown_from_peak > 0.15:
            continue

        for sd in sym_data_list:
            if len(open_positions) + len(pending_entries) >= max_pos:
                break

            sym = sd["name"]
            bar = sd["ts_to_pos"].get(ts)
            if bar is None or bar < WARMUP:
                continue

            last_bar = cooldown_tracker.get(sym, -9999)
            if bar - last_bar < COOLDOWN_BARS:
                continue

            # 1H trend filter
            e20_1h = sd["ema20_1h"][bar]
            e50_1h = sd["ema50_1h"][bar]
            if math.isnan(e20_1h) or math.isnan(e50_1h):
                continue
            trend_1h_bull = e20_1h > e50_1h
            trend_1h = "bull" if trend_1h_bull else "bear"
            if abs(e20_1h - e50_1h) / (e50_1h + 1e-10) < 0.003:
                continue

            # 4H trend filter + ADX regime gate
            e9_4h  = sd["ema9_4h"][bar]
            e21_4h = sd["ema21_4h"][bar]
            if not (math.isnan(e9_4h) or math.isnan(e21_4h)):
                trend_4h_bull = e9_4h > e21_4h
                if trend_1h_bull and not trend_4h_bull:
                    continue
                if not trend_1h_bull and trend_4h_bull:
                    continue
                if abs(e9_4h - e21_4h) / (e21_4h + 1e-10) < 0.003:
                    continue

            adx_4h_val = sd["adx_4h"][bar]
            if not math.isnan(adx_4h_val) and adx_4h_val < 20:
                continue

            adx_val = float(sd["adx"][bar])
            if math.isnan(adx_val):
                continue

            action = _check_pattern_d(sd, bar)
            if action is None:
                continue

            if action == "BUY"  and not trend_1h_bull:
                continue
            if action == "SELL" and trend_1h_bull:
                continue

            vol_ratio = sd["vol_ratio"][bar]
            leverage  = HIGH_LEVERAGE if (adx_val > 30 and vol_ratio > 2.5) else BASE_LEVERAGE
            dd_scale  = max(0.6, 1.0 - drawdown_from_peak * 3)
            margin    = equity * risk_pct * dd_scale

            if sym not in pending_entries:
                pending_entries[sym] = {
                    "sym":       sym,
                    "side":      "long" if action == "BUY" else "short",
                    "margin":    margin,
                    "leverage":  leverage,
                    "adx_entry": adx_val,
                    "trend_1h":  trend_1h,
                }
                cooldown_tracker[sym] = bar

    return trades, eq_curve, day_wins


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _metrics(trades, eq_curve) -> dict:
    if not eq_curve:
        return {"n_trades": 0, "ret": 0.0, "max_dd": 0.0,
                "win_rate": 0.0, "net_pnl": 0.0, "final_equity": INITIAL_CAPITAL,
                "profit_factor": 0.0}

    final_eq = eq_curve[-1]
    ret      = (final_eq - INITIAL_CAPITAL) / INITIAL_CAPITAL

    peak   = INITIAL_CAPITAL
    max_dd = 0.0
    for e in eq_curve:
        if e > peak: peak = e
        dd = (peak - e) / (peak + 1e-10)
        if dd > max_dd: max_dd = dd

    n = len(trades)
    if n == 0:
        return {"n_trades": 0, "ret": ret, "max_dd": max_dd,
                "win_rate": 0.0, "net_pnl": 0.0, "final_equity": final_eq,
                "profit_factor": 0.0}

    wins      = [t for t in trades if t.pnl_eur > 0]
    win_rate  = len(wins) / n
    net_pnl   = sum(t.pnl_eur for t in trades)
    gross_win  = sum(t.pnl_eur for t in wins)
    gross_loss = abs(sum(t.pnl_eur for t in trades if t.pnl_eur <= 0))
    pf        = gross_win / (gross_loss + 1e-10)

    # Simple Sharpe on monthly returns
    monthly: dict = {}
    for t in trades:
        mk = t.exit_ts.strftime("%Y-%m")
        monthly[mk] = monthly.get(mk, 0) + t.pnl_eur
    monthly_rets = list(monthly.values())
    if len(monthly_rets) > 1:
        avg   = sum(monthly_rets) / len(monthly_rets)
        std   = (sum((r - avg) ** 2 for r in monthly_rets) / len(monthly_rets)) ** 0.5
        sharpe = (avg / (std + 1e-10)) * (12 ** 0.5)
    else:
        sharpe = 0.0

    return {
        "n_trades":      n,
        "ret":           ret,
        "max_dd":        max_dd,
        "win_rate":      win_rate,
        "net_pnl":       net_pnl,
        "profit_factor": pf,
        "final_equity":  final_eq,
        "sharpe":        sharpe,
        "monthly":       monthly,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(trades, eq_curve, day_wins, cfg_name: str, t0: float):
    m = _metrics(trades, eq_curve)

    ret_col = "green" if m["ret"] >= 0 else "red"
    console.print(f"\n[bold cyan]━━━ PRISM v18 15m | Config: {cfg_name} ━━━[/bold cyan]")
    console.print(
        f"  Capital: €{INITIAL_CAPITAL:.0f} → [bold]€{m['final_equity']:.2f}[/bold]  "
        f"Return: [{ret_col}]{m['ret']:+.1%}[/]  "
        f"MaxDD: [red]{m['max_dd']:.1%}[/]  "
        f"WinRate: {m['win_rate']:.0%}  "
        f"PF: {m.get('profit_factor',0):.2f}  "
        f"Sharpe: {m.get('sharpe',0):.2f}  "
        f"Trades: {m['n_trades']}"
    )

    # Monthly breakdown
    monthly = m.get("monthly", {})
    if monthly:
        mtbl = Table(title=f"Monthly Breakdown — {MONTHS} months", box=box.SIMPLE_HEAD)
        mtbl.add_column("Month",   style="cyan")
        mtbl.add_column("Trades",  justify="right")
        mtbl.add_column("Win%",    justify="right")
        mtbl.add_column("PnL €",   justify="right")
        mtbl.add_column("Return",  justify="right")

        eq_running = INITIAL_CAPITAL
        for mk in sorted(monthly):
            tl   = [t for t in trades if t.exit_ts.strftime("%Y-%m") == mk]
            ws   = sum(1 for t in tl if t.pnl_eur > 0)
            wr   = ws / len(tl) if tl else 0
            pnl  = monthly[mk]
            ret  = pnl / (eq_running + 1e-10)
            eq_running += pnl
            col  = "green" if pnl >= 0 else "red"
            mtbl.add_row(
                mk, str(len(tl)), f"{wr:.0%}",
                f"[{col}]{pnl:+.2f}[/]",
                f"[{col}]{ret:+.1%}[/]",
            )

        # Summary row
        total_trades = len(trades)
        all_wins = sum(1 for t in trades if t.pnl_eur > 0)
        mtbl.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold]{total_trades}[/bold]",
            f"[bold]{all_wins/total_trades:.0%}[/bold]" if total_trades else "—",
            f"[bold][{ret_col}]{m['net_pnl']:+.2f}[/][/bold]",
            f"[bold][{ret_col}]{m['ret']:+.1%}[/][/bold]",
        )
        console.print(mtbl)

    # Exit breakdown
    if trades:
        etbl = Table(title="Exit Breakdown", box=box.SIMPLE_HEAD)
        etbl.add_column("Reason", style="cyan")
        etbl.add_column("Count",  justify="right")
        etbl.add_column("Win%",   justify="right")
        etbl.add_column("Avg €",  justify="right")
        for reason in ["take_profit", "stop_loss", "time_stop"]:
            tl = [t for t in trades if t.exit_reason == reason]
            if not tl: continue
            ws  = sum(1 for t in tl if t.pnl_eur > 0)
            avg = sum(t.pnl_eur for t in tl) / len(tl)
            col = "green" if avg >= 0 else "red"
            etbl.add_row(reason, str(len(tl)),
                         f"{ws/len(tl):.0%}", f"[{col}]{avg:+.2f}[/]")
        console.print(etbl)

    # Top symbols
    if trades:
        sym_pnl: dict = {}
        sym_cnt: dict = {}
        for t in trades:
            sym_pnl[t.symbol] = sym_pnl.get(t.symbol, 0) + t.pnl_eur
            sym_cnt[t.symbol] = sym_cnt.get(t.symbol, 0) + 1
        ranked = sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True)[:8]
        stbl = Table(title="Top Symbols by PnL", box=box.SIMPLE_HEAD)
        stbl.add_column("Symbol", style="cyan")
        stbl.add_column("Trades", justify="right")
        stbl.add_column("PnL €",  justify="right")
        for sym, pnl in ranked:
            col = "green" if pnl >= 0 else "red"
            stbl.add_row(sym, str(sym_cnt[sym]), f"[{col}]{pnl:+.2f}[/]")
        console.print(stbl)

    # Profitable months stat
    if monthly:
        profit_months = sum(1 for v in monthly.values() if v > 0)
        total_months  = len(monthly)
        console.print(
            f"\n  Profitable months: {profit_months}/{total_months} "
            f"({profit_months/total_months:.0%})  |  "
            f"Elapsed: {time.time()-t0:.1f}s"
        )

    # ASCII equity curve
    if len(eq_curve) > 10:
        console.print("\n[bold]Equity Curve[/bold]")
        sample  = eq_curve[::max(1, len(eq_curve) // 70)]
        min_eq  = min(sample)
        max_eq  = max(sample)
        rng     = max_eq - min_eq + 1e-10
        rows    = 8
        grid    = [[" " for _ in range(len(sample))] for _ in range(rows)]
        for c, val in enumerate(sample):
            r = rows - 1 - int((val - min_eq) / rng * (rows - 1))
            grid[max(0, min(rows-1, r))][c] = "█"
        for row in grid:
            console.print("".join(row))
        console.print(f"  €{min_eq:.0f}{'':>66}€{max_eq:.0f}")


# ---------------------------------------------------------------------------
# Full backtest
# ---------------------------------------------------------------------------

def run_backtest(cfg_name: str = "Conservateur") -> dict:
    t0  = time.time()
    cfg = next((c for c in CONFIGS if c["name"] == cfg_name), CONFIGS[0])

    console.print(f"\n[bold]PRISM v18 — 15m Breakout | {cfg_name}[/bold]")
    console.print(
        f"  Données: Binance via CCXT | {MONTHS} mois | {TIMEFRAME}\n"
        f"  SL: {SL_PCT:.1%} | TP: {TP_PCT:.1%} | R:R {TP_PCT/SL_PCT:.1f}:1 | "
        f"BE: +{BREAKEVEN_TRIG:.1%}"
    )
    console.print(f"\n  Téléchargement {len(SYMBOLS)} symboles...")

    # Parallel download: 4 workers (≈30 req/s total, under OKX 40 req/s limit)
    # Already-cached symbols return instantly; only missing ones hit the network.
    results_map: dict = {}

    def _fetch(sym):
        cached_before = _cache_valid(_cache_path(sym))
        sd = precompute(sym)
        return sym, sd, cached_before

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch, sym): sym for sym in SYMBOLS}
        done_count = 0
        for future in as_completed(futures):
            sym, sd, was_cached = future.result()
            done_count += 1
            status = "ok" if sd else "FAIL"
            tag    = " [dim](cache)[/dim]" if was_cached else ""
            idx    = SYMBOLS.index(sym) + 1
            console.print(f"    [{idx:2d}/{len(SYMBOLS)}] {sym:<12} {status}{tag}")
            if sd:
                results_map[sym] = sd

    # Preserve original symbol order
    sym_data_list = [results_map[s] for s in SYMBOLS if s in results_map]

    if not sym_data_list:
        console.print("[red]No data.[/red]")
        return {}

    # Common timestamps
    ts_sets   = [set(sd["ts_index"]) for sd in sym_data_list]
    common_ts = ts_sets[0]
    for s in ts_sets[1:]:
        common_ts = common_ts.intersection(s)
    timestamps = sorted(common_ts)[WARMUP:]

    first_ts = timestamps[0].strftime("%Y-%m-%d") if timestamps else "?"
    last_ts  = timestamps[-1].strftime("%Y-%m-%d") if timestamps else "?"
    console.print(
        f"\n  Moteur: {len(timestamps):,} barres | "
        f"{len(sym_data_list)} symboles | {first_ts} → {last_ts}"
    )

    trades, eq_curve, day_wins = run_engine(
        sym_data_list = sym_data_list,
        timestamps    = timestamps,
        risk_pct      = cfg["risk_pct"],
        max_pos       = cfg["max_pos"],
    )

    metrics = _metrics(trades, eq_curve)
    print_report(trades, eq_curve, day_wins, cfg_name, t0)
    return {"config": cfg_name, "metrics": metrics}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    console.print(
        "[bold yellow]PRISM v18 — 15m BB Squeeze | Binance CCXT | 12 mois[/bold yellow]"
    )
    console.print(
        "[dim]Validation longue durée : bull market, bear market, consolidation[/dim]\n"
    )

    results = []
    for cfg in CONFIGS:
        r = run_backtest(cfg_name=cfg["name"])
        if r and r.get("metrics"):
            results.append((cfg["name"], r["metrics"]))

    if results:
        console.print("\n")
        tbl = Table(title="Comparaison des 3 configs — 12 mois", box=box.ROUNDED)
        tbl.add_column("Config",   style="cyan")
        tbl.add_column("Trades",   justify="right")
        tbl.add_column("Return",   justify="right")
        tbl.add_column("MaxDD",    justify="right")
        tbl.add_column("WinRate",  justify="right")
        tbl.add_column("P.Factor", justify="right")
        tbl.add_column("Sharpe",   justify="right")
        for name, m in results:
            rc = "green" if m["ret"] >= 0 else "red"
            tbl.add_row(
                name,
                str(m["n_trades"]),
                f"[{rc}]{m['ret']:+.1%}[/]",
                f"{m['max_dd']:.1%}",
                f"{m['win_rate']:.0%}",
                f"{m.get('profit_factor',0):.2f}",
                f"{m.get('sharpe',0):.2f}",
            )
        console.print(tbl)

        best = max(results, key=lambda x: x[1]["ret"])
        console.print(
            f"\n  Meilleure config: [bold green]{best[0]}[/bold green]  "
            f"Return: [bold green]{best[1]['ret']:+.1%}[/bold green]"
        )
        console.print(
            "\n  [dim]Données en cache dans .cache_v18/ — "
            "re-téléchargement auto dans 23h[/dim]"
        )
