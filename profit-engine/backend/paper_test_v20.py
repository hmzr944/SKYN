#!/usr/bin/env python3
"""
PRISM v20 — EMA Pullback 1H | OKX REST API | 6 mois | €1000
=============================================================
Port de la stratégie v16 Pattern A (EMA Pullback) sur l'infra OKX/cache :
  - Données 1H via OKX API publique (sans clé), 6 mois
  - Capital €1000 (double de v18/v19)
  - Pattern A seul : rebond EMA21 1H, filtre MACD, ADX, 4H macro
  - SL 2% | TP 8% | R:R 4:1 | Levier 4-6×

Objectif : valider que v16 tient sur les 6 derniers mois de marché réel
avant de passer en live.
"""

import math, os, pickle, time, warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
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

SYMBOLS = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "AVAX-USDT",
    "ADA-USDT", "LINK-USDT", "XRP-USDT", "DOT-USDT", "ATOM-USDT",
    "LTC-USDT", "DOGE-USDT", "NEAR-USDT", "TRX-USDT", "ALGO-USDT",
    "FIL-USDT", "INJ-USDT", "OP-USDT",
]

INITIAL_CAPITAL  = 1000.0
TIMEFRAME        = "1H"
MONTHS           = 6
WARMUP           = 250          # barres 1H pour warmup EMA200d (≈10 jours)
COMMISSION       = 0.001        # 0.1% taker × 2 côtés
SLIPPAGE         = 0.0005
EXIT_SLIPPAGE    = 0.0003

# Pattern A — EMA Pullback (v16 validé : +39.4% / 2 ans)
SL_PCT           = 0.020        # 2% sur prix asset
TP_PCT           = 0.080        # 8% sur prix asset  |  R:R 4:1
TIME_STOP_H      = 72           # 72 heures max (3 jours)
ADX_MIN          = 22
COOLDOWN_BARS    = 16           # 16 barres 1H = 16 heures

EMA21_NEAR       = 0.015        # close doit être ≤ 1.5% de EMA21
EMA21_PRIOR_MIN  = 0.015        # max_dist 5 barres avant doit être > 1.5%

BASE_LEVERAGE    = 4
HIGH_LEVERAGE    = 6

DAILY_LOSS_CAP   = 0.10         # stoppe les entrées si -10% dans la journée

CONFIGS = [
    {"name": "Conservateur", "risk_pct": 0.040, "max_pos": 3, "score_min": 68},
    {"name": "Equilibre",    "risk_pct": 0.055, "max_pos": 4, "score_min": 65},
    {"name": "Agressif",     "risk_pct": 0.065, "max_pos": 5, "score_min": 63},
]

CACHE_DIR        = os.path.join(os.path.dirname(__file__), ".cache_v20")
CACHE_MAX_AGE_H  = 23
OKX_CANDLES_URL  = "https://www.okx.com/api/v5/market/history-candles"


# ---------------------------------------------------------------------------
# Download (OKX 1H, public API)
# ---------------------------------------------------------------------------

def _cache_path(sym: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = sym.replace("/", "_").replace("-", "_")
    return os.path.join(CACHE_DIR, f"{safe}_{TIMEFRAME}_{MONTHS}m.pkl")


def _cache_valid(path: str) -> bool:
    if not os.path.exists(path):
        return False
    return (time.time() - os.path.getmtime(path)) / 3600 < CACHE_MAX_AGE_H


def _fetch_okx_raw(inst_id: str) -> list:
    until_ms = int(time.time() * 1000)
    since_ms  = until_ms - MONTHS * 30 * 24 * 60 * 60 * 1000
    all_rows, after = [], None

    for _ in range(200):
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
        time.sleep(0.08)

    all_rows = [r for r in all_rows if int(r[0]) >= since_ms]
    all_rows.sort(key=lambda x: int(x[0]))
    return all_rows


def download_ohlcv(sym: str, force: bool = False) -> Optional[pd.DataFrame]:
    path = _cache_path(sym)
    if not force and _cache_valid(path):
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass

    raw = _fetch_okx_raw(sym)
    if len(raw) < WARMUP + 50:
        return None

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
    df = df.dropna(subset=["close","open","high","low","volume"])

    with open(path, "wb") as f:
        pickle.dump(df, f)
    return df


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    # EMA 9, 21, 50
    df["ema9"]  = close.ewm(span=9,  adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()

    # MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line   = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist   = macd_line - macd_signal
    df["macd_hist"]  = macd_hist
    df["macd_slope"] = macd_hist.diff()

    # RSI 14
    delta  = close.diff()
    gain   = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss   = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df["rsi14"] = 100 - 100 / (1 + gain / (loss + 1e-10))

    # Bollinger Bands (20, 2)
    bb_mid        = close.rolling(20).mean()
    bb_std        = close.rolling(20).std()
    df["bb_upper"]= bb_mid + 2 * bb_std
    df["bb_lower"]= bb_mid - 2 * bb_std
    bbw           = (df["bb_upper"] - df["bb_lower"]) / (bb_mid + 1e-10)
    df["bbw"]     = bbw
    df["bbw_q15"] = bbw.rolling(40).quantile(0.15)

    # Volume ratio
    df["vol_ratio"] = volume / (volume.rolling(20).mean() + 1e-10)

    # VWAP 24-bar rolling
    tp = (high + low + close) / 3
    df["vwap"] = (tp * volume).rolling(24).sum() / (volume.rolling(24).sum() + 1e-10)

    # Stochastic (14, 3)
    low14  = low.rolling(14).min()
    high14 = high.rolling(14).max()
    stoch_k = 100 * (close - low14) / (high14 - low14 + 1e-10)
    df["stoch_k"] = stoch_k
    df["stoch_d"] = stoch_k.rolling(3).mean()

    # ATR 14
    tr    = pd.concat([high - low,
                       (high - close.shift()).abs(),
                       (low  - close.shift()).abs()], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(com=13, adjust=False).mean()

    # ADX (Wilder smoothing)
    dm_p = (high - high.shift()).clip(lower=0)
    dm_m = (low.shift() - low).clip(lower=0)
    dm_p = dm_p.where(dm_p > dm_m, 0)
    dm_m = dm_m.where(dm_m > dm_p, 0)
    atr14 = tr.ewm(com=13, adjust=False).mean()
    dip   = 100 * dm_p.ewm(com=13, adjust=False).mean() / (atr14 + 1e-10)
    dim   = 100 * dm_m.ewm(com=13, adjust=False).mean() / (atr14 + 1e-10)
    dx    = 100 * (dip - dim).abs() / (dip + dim + 1e-10)
    df["adx"] = dx.ewm(com=13, adjust=False).mean()
    df["di_plus"]  = dip
    df["di_minus"] = dim

    # 4H EMA 20, 50
    df_4h    = df[["close"]].resample("4h").last().dropna()
    ema20_4h = df_4h["close"].ewm(span=20, adjust=False).mean()
    ema50_4h = df_4h["close"].ewm(span=50, adjust=False).mean()
    df["ema20_4h"] = ema20_4h.reindex(df.index, method="ffill")
    df["ema50_4h"] = ema50_4h.reindex(df.index, method="ffill")

    # Daily EMA 50, 200
    df_1d    = df[["close"]].resample("1D").last().dropna()
    ema50d   = df_1d["close"].ewm(span=50,  adjust=False).mean()
    ema200d  = df_1d["close"].ewm(span=200, adjust=False).mean()
    df["ema50d"]  = ema50d.reindex(df.index,  method="ffill")
    df["ema200d"] = ema200d.reindex(df.index, method="ffill")

    return df


# ---------------------------------------------------------------------------
# Score system (from v16 — 100 pts max)
# ---------------------------------------------------------------------------

def _compute_scores(sd: dict, n: int):
    """Compute buy/sell scores [0..100] for all bars. Returns (buy_arr, sell_arr)."""
    buy_sc  = np.zeros(n, dtype=np.int32)
    sell_sc = np.zeros(n, dtype=np.int32)

    close     = sd["close"]
    ema9      = sd["ema9"]
    ema21     = sd["ema21"]
    ema50     = sd["ema50"]
    rsi       = sd["rsi14"]
    mh        = sd["macd_hist"]
    mh_slope  = sd["macd_slope"]
    vol_ratio = sd["vol_ratio"]
    adx_arr   = sd["adx"]
    vwap      = sd["vwap"]
    stoch_k   = sd["stoch_k"]
    stoch_d   = sd["stoch_d"]

    for i in range(n):
        bs = ss = 0

        # 1. EMA stack (25 pts)
        if not any(math.isnan(v) for v in [ema9[i], ema21[i], ema50[i]]):
            if ema9[i] > ema21[i]: bs += 12
            elif ema9[i] < ema21[i]: ss += 12
            if ema21[i] > ema50[i]: bs += 13
            elif ema21[i] < ema50[i]: ss += 13

        # 2. RSI zone (15 pts)
        if not math.isnan(rsi[i]):
            r = rsi[i]
            if 40 <= r <= 65:   bs += 15
            elif 35 <= r < 40:  bs += 8
            elif 65 < r <= 70:  bs += 5
            if 35 <= r <= 60:   ss += 15
            elif 60 < r <= 65:  ss += 8
            elif 30 <= r < 35:  ss += 5

        # 3. MACD (20 pts)
        if not any(math.isnan(v) for v in [mh[i], mh_slope[i]]):
            if mh[i] > 0:       bs += 12
            elif mh[i] < 0:     ss += 12
            if mh_slope[i] > 0: bs += 8
            elif mh_slope[i] < 0: ss += 8

        # 4. Volume (10 pts)
        if not math.isnan(vol_ratio[i]):
            vr = vol_ratio[i]
            pts = 10 if vr >= 1.5 else 6 if vr >= 1.0 else 3 if vr >= 0.7 else 0
            bs += pts; ss += pts

        # 5. ADX (10 pts)
        if not math.isnan(adx_arr[i]):
            av = adx_arr[i]
            pts = 10 if av >= 25 else 6 if av >= 18 else 0
            bs += pts; ss += pts

        # 6. VWAP (10 pts)
        if not any(math.isnan(v) for v in [close[i], vwap[i]]):
            if close[i] > vwap[i]:   bs += 10
            elif close[i] < vwap[i]: ss += 10

        # 7. Stochastic (10 pts)
        if not any(math.isnan(v) for v in [stoch_k[i], stoch_d[i]]):
            sk, sd_ = stoch_k[i], stoch_d[i]
            if sk > sd_ and sk < 75: bs += 10
            if sk < sd_ and sk > 25: ss += 10

        buy_sc[i]  = min(bs, 100)
        sell_sc[i] = min(ss, 100)

    return buy_sc, sell_sc


def precompute(sym: str) -> Optional[dict]:
    df = download_ohlcv(sym)
    if df is None:
        return None
    df = compute_indicators(df)
    n  = len(df)

    # Raw numpy arrays for fast bar access
    sd = {
        "name":      sym,
        "ts_index":  df.index,
        "ts_to_pos": {ts: i for i, ts in enumerate(df.index)},
        "open":      df["open"].values.astype(float),
        "close":     df["close"].values.astype(float),
        "high":      df["high"].values.astype(float),
        "low":       df["low"].values.astype(float),
        "ema9":      df["ema9"].values.astype(float),
        "ema21":     df["ema21"].values.astype(float),
        "ema50":     df["ema50"].values.astype(float),
        "rsi14":     df["rsi14"].values.astype(float),
        "macd_hist": df["macd_hist"].values.astype(float),
        "macd_slope":df["macd_slope"].values.astype(float),
        "vol_ratio": df["vol_ratio"].values.astype(float),
        "vwap":      df["vwap"].values.astype(float),
        "stoch_k":   df["stoch_k"].values.astype(float),
        "stoch_d":   df["stoch_d"].values.astype(float),
        "adx":       df["adx"].values.astype(float),
        "di_plus":   df["di_plus"].values.astype(float),
        "di_minus":  df["di_minus"].values.astype(float),
        "bb_upper":  df["bb_upper"].values.astype(float),
        "bb_lower":  df["bb_lower"].values.astype(float),
        "bbw":       df["bbw"].values.astype(float),
        "bbw_q15":   df["bbw_q15"].values.astype(float),
        "atr14":     df["atr14"].values.astype(float),
        "ema20_4h":  df["ema20_4h"].values.astype(float),
        "ema50_4h":  df["ema50_4h"].values.astype(float),
        "ema50d":    df["ema50d"].values.astype(float),
        "ema200d":   df["ema200d"].values.astype(float),
    }
    buy_sc, sell_sc = _compute_scores(sd, n)
    sd["buy_sc"]  = buy_sc
    sd["sell_sc"] = sell_sc
    return sd


# ---------------------------------------------------------------------------
# Pattern A — EMA Pullback 1H (v16 exact)
# ---------------------------------------------------------------------------

def _check_pattern_a(sd: dict, bar: int, adx_val: float) -> Optional[str]:
    """
    EMA Pullback sur 1H.

    Signal LONG :
      - EMA9 > EMA21 > EMA50 (pile haussière complète)
      - EMA50_4H confirme la tendance macro (4H bull)
      - Daily EMA50/EMA200 > 0.98 (pas en bear macro sévère)
      - Close ≤ 1.5% de EMA21 (actuellement near l'EMA)
      - Max distance des 5 barres précédentes > 1.5% (vrai pullback depuis dessus)
      - RSI 43-62 (zone de pullback sain)
      - MACD hist > 0 et montant (momentum positif)
      - Volume ratio ≥ 1.0
      - ADX ≥ 22 (marché directionnel)
    """
    if bar < 8:
        return None
    try:
        close     = sd["close"][bar]
        ema9      = sd["ema9"][bar]
        ema21     = sd["ema21"][bar]
        ema50     = sd["ema50"][bar]
        rsi       = sd["rsi14"][bar]
        mh_cur    = sd["macd_hist"][bar]
        mh_prev   = sd["macd_hist"][bar - 1]
        vol_ratio = sd["vol_ratio"][bar]
        ema20_4h  = sd["ema20_4h"][bar]
        ema50_4h  = sd["ema50_4h"][bar]
        ema50d    = sd["ema50d"][bar]
        ema200d   = sd["ema200d"][bar]

        vals = [close, ema9, ema21, ema50, rsi, mh_cur, mh_prev,
                vol_ratio, ema20_4h, ema50_4h, ema50d, ema200d, adx_val]
        if any(math.isnan(v) for v in vals):
            return None

        # Max distance to EMA21 in last 5 bars
        cl_arr  = sd["close"]
        e21_arr = sd["ema21"]
        prev5_dists = [
            abs(cl_arr[bar - i] - e21_arr[bar - i]) / max(e21_arr[bar - i], 1e-10)
            for i in range(1, 6)
        ]
        max_dist = max(prev5_dists)

        daily_ratio = ema50d / max(ema200d, 1e-10)
        bull_4h = ema20_4h > ema50_4h
        bear_4h = ema20_4h < ema50_4h

        # ── LONG ──────────────────────────────────────────────────────────
        if (ema9 > ema21
                and ema21 > ema50
                and daily_ratio > 0.98             # pas en bear macro sévère
                and bull_4h
                and abs(close - ema21) / ema21 < EMA21_NEAR
                and max_dist > EMA21_PRIOR_MIN
                and 43 <= rsi <= 62
                and mh_cur > mh_prev
                and mh_cur > 0
                and vol_ratio >= 1.0
                and adx_val >= ADX_MIN):
            return "BUY"

        # ── SHORT ─────────────────────────────────────────────────────────
        if (ema9 < ema21
                and ema21 < ema50
                and daily_ratio < 1.02
                and bear_4h
                and abs(close - ema21) / ema21 < EMA21_NEAR
                and max_dist > EMA21_PRIOR_MIN
                and 38 <= rsi <= 57
                and mh_cur < mh_prev
                and mh_cur < 0
                and vol_ratio >= 1.0
                and adx_val >= ADX_MIN):
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
    score:       int
    trend_4h:    str


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def run_engine(sym_data_list, timestamps, risk_pct, max_pos, score_min):
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

    # BTC macro: bull si EMA50_4H > EMA50_4H × 1.01 (simplifié vs v16 daily)
    btc_sd = sym_lookup.get("BTC-USDT")

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
            open_px     = float(sd["open"][bar])
            side        = p["side"]
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
                "entry_price": entry_price,
                "sl":          sl,
                "tp":          tp,
                "margin":      p["margin"],
                "leverage":    p["leverage"],
                "adx_entry":   p["adx_entry"],
                "score":       p["score"],
                "trend_4h":    p["trend_4h"],
            }

        day_pnl_pct  = (equity - day_start_equity) / (day_start_equity + 1e-10)
        skip_entries = day_pnl_pct <= -DAILY_LOSS_CAP

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

            h  = sd["high"][bar]
            lo = sd["low"][bar]
            cl = sd["close"][bar]

            entry  = pos["entry_price"]
            sl     = pos["sl"]
            tp     = pos["tp"]
            side   = pos["side"]

            exit_price  = None
            exit_reason = None

            if side == "long":
                if h >= tp:    exit_price, exit_reason = tp, "take_profit"
                elif lo <= sl: exit_price, exit_reason = sl, "stop_loss"
            else:
                if lo <= tp:   exit_price, exit_reason = tp, "take_profit"
                elif h >= sl:  exit_price, exit_reason = sl, "stop_loss"

            elapsed_h = (ts - pos["entry_ts"]).total_seconds() / 3600
            if exit_price is None and elapsed_h >= TIME_STOP_H:
                exit_price, exit_reason = cl, "time_stop"

            if exit_price is not None:
                exit_price = (exit_price * (1 - EXIT_SLIPPAGE) if side == "long"
                              else exit_price * (1 + EXIT_SLIPPAGE))
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
                    score       = pos["score"],
                    trend_4h    = pos["trend_4h"],
                ))
                to_remove.append(pos_key)

        for k in to_remove:
            del open_positions[k]

        # ---- New entries ----
        if skip_entries or len(open_positions) + len(pending_entries) >= max_pos:
            continue
        if drawdown_from_peak > 0.20:   # pause si DD > 20%
            continue

        # BTC 4H macro direction
        btc_4h_bull = None
        if btc_sd is not None:
            btc_bar = btc_sd["ts_to_pos"].get(ts)
            if btc_bar is not None:
                b4h_20 = btc_sd["ema20_4h"][btc_bar]
                b4h_50 = btc_sd["ema50_4h"][btc_bar]
                if not (math.isnan(b4h_20) or math.isnan(b4h_50)):
                    btc_4h_bull = b4h_20 > b4h_50

        for sd in sym_data_list:
            if len(open_positions) + len(pending_entries) >= max_pos:
                break

            sym = sd["name"]
            if sym == "BTC-USDT":
                continue

            bar = sd["ts_to_pos"].get(ts)
            if bar is None or bar < WARMUP:
                continue

            last_bar = cooldown_tracker.get(sym, -9999)
            if bar - last_bar < COOLDOWN_BARS:
                continue

            adx_val = float(sd["adx"][bar])
            if math.isnan(adx_val):
                continue

            action = _check_pattern_a(sd, bar, adx_val)
            if action is None:
                continue

            # BTC 4H macro filter (no counter-trend vs BTC macro)
            if btc_4h_bull is not None:
                if action == "BUY"  and not btc_4h_bull:
                    continue
                if action == "SELL" and btc_4h_bull:
                    continue

            score = int(sd["buy_sc"][bar]) if action == "BUY" else int(sd["sell_sc"][bar])
            if score < score_min:
                continue

            # 4H trend label (for reporting)
            e20_4h = sd["ema20_4h"][bar]
            e50_4h = sd["ema50_4h"][bar]
            trend_4h = "bull" if e20_4h > e50_4h else "bear"

            leverage = HIGH_LEVERAGE if (adx_val > 30 and score >= 75) else BASE_LEVERAGE
            dd_scale = max(0.6, 1.0 - drawdown_from_peak * 2)
            margin   = equity * risk_pct * dd_scale

            if sym not in pending_entries:
                pending_entries[sym] = {
                    "sym":       sym,
                    "side":      "long" if action == "BUY" else "short",
                    "margin":    margin,
                    "leverage":  leverage,
                    "adx_entry": adx_val,
                    "score":     score,
                    "trend_4h":  trend_4h,
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
                "profit_factor": 0.0, "sharpe": 0.0}

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
                "profit_factor": 0.0, "sharpe": 0.0}

    wins      = [t for t in trades if t.pnl_eur > 0]
    win_rate  = len(wins) / n
    net_pnl   = sum(t.pnl_eur for t in trades)
    gross_win  = sum(t.pnl_eur for t in wins)
    gross_loss = abs(sum(t.pnl_eur for t in trades if t.pnl_eur <= 0))
    pf        = gross_win / (gross_loss + 1e-10)

    # Sharpe monthly
    monthly: dict = {}
    for t in trades:
        mk = t.exit_ts.strftime("%Y-%m")
        monthly[mk] = monthly.get(mk, 0) + t.pnl_eur
    monthly_rets = list(monthly.values())
    if len(monthly_rets) > 1:
        avg    = sum(monthly_rets) / len(monthly_rets)
        std    = (sum((r - avg) ** 2 for r in monthly_rets) / len(monthly_rets)) ** 0.5
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

def print_report(trades, eq_curve, cfg_name: str, t0: float):
    m = _metrics(trades, eq_curve)
    rc = "green" if m["ret"] >= 0 else "red"

    console.print(f"\n[bold cyan]━━━ PRISM v20 EMA Pullback 1H | {cfg_name} ━━━[/bold cyan]")
    console.print(
        f"  Capital: €{INITIAL_CAPITAL:.0f} → [bold]€{m['final_equity']:.2f}[/bold]  "
        f"Return: [{rc}]{m['ret']:+.1%}[/]  "
        f"MaxDD: [red]{m['max_dd']:.1%}[/]  "
        f"WinRate: {m['win_rate']:.0%}  "
        f"PF: {m.get('profit_factor',0):.2f}  "
        f"Sharpe: {m.get('sharpe',0):.2f}  "
        f"Trades: {m['n_trades']}"
    )

    # Monthly breakdown
    monthly = m.get("monthly", {})
    if monthly:
        mtbl = Table(title=f"Mensuel — {MONTHS} mois", box=box.SIMPLE_HEAD)
        mtbl.add_column("Mois",    style="cyan")
        mtbl.add_column("Trades",  justify="right")
        mtbl.add_column("Win%",    justify="right")
        mtbl.add_column("PnL €",   justify="right")
        mtbl.add_column("Return",  justify="right")
        eq_running = INITIAL_CAPITAL
        for mk in sorted(monthly):
            tl  = [t for t in trades if t.exit_ts.strftime("%Y-%m") == mk]
            ws  = sum(1 for t in tl if t.pnl_eur > 0)
            wr  = ws / len(tl) if tl else 0
            pnl = monthly[mk]
            ret = pnl / (eq_running + 1e-10)
            eq_running += pnl
            col = "green" if pnl >= 0 else "red"
            mtbl.add_row(mk, str(len(tl)), f"{wr:.0%}",
                         f"[{col}]{pnl:+.2f}[/]", f"[{col}]{ret:+.1%}[/]")
        all_wins = sum(1 for t in trades if t.pnl_eur > 0)
        n = len(trades)
        mtbl.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold]{n}[/bold]",
            f"[bold]{all_wins/n:.0%}[/bold]" if n else "—",
            f"[bold][{rc}]{m['net_pnl']:+.2f}[/][/bold]",
            f"[bold][{rc}]{m['ret']:+.1%}[/][/bold]",
        )
        console.print(mtbl)

    # Exit breakdown
    if trades:
        etbl = Table(title="Sorties", box=box.SIMPLE_HEAD)
        etbl.add_column("Raison",  style="cyan")
        etbl.add_column("Count",   justify="right")
        etbl.add_column("Win%",    justify="right")
        etbl.add_column("Avg PnL", justify="right")
        etbl.add_column("Avg Lev", justify="right")
        for reason in ["take_profit", "stop_loss", "time_stop"]:
            tl = [t for t in trades if t.exit_reason == reason]
            if not tl: continue
            ws  = sum(1 for t in tl if t.pnl_eur > 0)
            avg = sum(t.pnl_eur for t in tl) / len(tl)
            lev = sum(t.leverage for t in tl) / len(tl)
            col = "green" if avg >= 0 else "red"
            etbl.add_row(reason, str(len(tl)), f"{ws/len(tl):.0%}",
                         f"[{col}]{avg:+.2f}[/]", f"{lev:.1f}×")
        console.print(etbl)

    # Top symbols
    if trades:
        sym_pnl: dict = {}
        sym_cnt: dict = {}
        for t in trades:
            sym_pnl[t.symbol] = sym_pnl.get(t.symbol, 0) + t.pnl_eur
            sym_cnt[t.symbol] = sym_cnt.get(t.symbol, 0) + 1
        ranked = sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True)
        stbl = Table(title="PnL par Symbole", box=box.SIMPLE_HEAD)
        stbl.add_column("Symbol", style="cyan")
        stbl.add_column("Trades", justify="right")
        stbl.add_column("PnL €",  justify="right")
        for sym, pnl in ranked:
            col = "green" if pnl >= 0 else "red"
            stbl.add_row(sym, str(sym_cnt[sym]), f"[{col}]{pnl:+.2f}[/]")
        console.print(stbl)

    # Score stats
    if trades:
        scores = [t.score for t in trades]
        avg_s  = sum(scores) / len(scores)
        wins   = [t.score for t in trades if t.pnl_eur > 0]
        loss   = [t.score for t in trades if t.pnl_eur <= 0]
        console.print(
            f"\n  Score moyen: {avg_s:.0f}  |  "
            f"Winners: {sum(wins)/len(wins):.0f}  |  "
            f"Losers: {sum(loss)/len(loss):.0f}" if (wins and loss) else ""
        )

    if monthly:
        profit_months = sum(1 for v in monthly.values() if v > 0)
        total_months  = len(monthly)
        console.print(
            f"  Mois profitables: {profit_months}/{total_months} "
            f"({profit_months/total_months:.0%})  |  "
            f"Elapsed: {time.time()-t0:.1f}s"
        )

    # Equity curve
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

def run_backtest(cfg_name: str = "Equilibre") -> dict:
    t0  = time.time()
    cfg = next((c for c in CONFIGS if c["name"] == cfg_name), CONFIGS[1])

    console.print(f"\n[bold]PRISM v20 — EMA Pullback 1H | {cfg_name}[/bold]")
    console.print(
        f"  OKX REST API | {MONTHS} mois | {TIMEFRAME} | Capital €{INITIAL_CAPITAL:.0f}\n"
        f"  SL: {SL_PCT:.1%} | TP: {TP_PCT:.1%} | R:R {TP_PCT/SL_PCT:.0f}:1 | "
        f"Score min: {cfg['score_min']} | Risk: {cfg['risk_pct']:.1%} | "
        f"Levier: {BASE_LEVERAGE}-{HIGH_LEVERAGE}×"
    )
    console.print(f"\n  Téléchargement {len(SYMBOLS)} symboles (1H)...")

    results_map: dict = {}

    def _fetch(sym):
        cached_before = _cache_valid(_cache_path(sym))
        sd = precompute(sym)
        return sym, sd, cached_before

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch, sym): sym for sym in SYMBOLS}
        for future in as_completed(futures):
            sym, sd, was_cached = future.result()
            status = "ok" if sd else "FAIL"
            tag    = " [dim](cache)[/dim]" if was_cached else ""
            idx    = SYMBOLS.index(sym) + 1
            console.print(f"    [{idx:2d}/{len(SYMBOLS)}] {sym:<12} {status}{tag}")
            if sd:
                results_map[sym] = sd

    sym_data_list = [results_map[s] for s in SYMBOLS if s in results_map]
    if not sym_data_list:
        console.print("[red]No data.[/red]")
        return {}

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
        score_min     = cfg["score_min"],
    )

    metrics = _metrics(trades, eq_curve)
    print_report(trades, eq_curve, cfg_name, t0)
    return {"config": cfg_name, "metrics": metrics}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    console.print(
        "[bold yellow]PRISM v20 — EMA Pullback 1H | OKX | 6 mois | €1000[/bold yellow]"
    )
    console.print(
        "[dim]Port de v16 Pattern A sur infra OKX — "
        "validation 6 mois marché réel[/dim]\n"
    )

    results = []
    for cfg in CONFIGS:
        r = run_backtest(cfg_name=cfg["name"])
        if r and r.get("metrics"):
            results.append((cfg["name"], r["metrics"]))

    if results:
        console.print("\n")
        tbl = Table(title="Comparaison configs — 6 mois", box=box.ROUNDED)
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
        best_m = best[1]
        console.print(
            f"\n  Meilleure config: [bold green]{best[0]}[/bold green]  "
            f"Return: [bold green]{best_m['ret']:+.1%}[/bold green]  "
            f"sur €{INITIAL_CAPITAL:.0f}"
        )

        # Verdict live
        console.print()
        if best_m["ret"] > 0 and best_m.get("profit_factor", 0) > 1.0:
            console.print(
                "[bold green]  ✓ Stratégie rentable sur 6 mois récents "
                "→ GO live avec config [/bold green]"
                f"[bold white]{best[0]}[/bold white]"
            )
        elif best_m["ret"] > -0.05:
            console.print(
                "[yellow]  ~ Performance modeste — surveille 1 mois en paper "
                "avant le vrai capital[/yellow]"
            )
        else:
            console.print(
                "[bold red]  ✗ Underperformance sur le marché récent "
                "— ajuste les paramètres[/bold red]"
            )
        console.print(
            "\n  [dim]Cache .cache_v20/ — re-téléchargement auto dans 23h[/dim]"
        )
