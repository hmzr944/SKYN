#!/usr/bin/env python3
"""
SKYN v5 — MULTI-POSITION ENGINE (Capital Partage)
===================================================
Capital unique 50 EUR, jusqu'a N_MAX_POSITIONS=4 positions simultanees
sur des actifs differents. Effet "journee explosive" : plusieurs breakouts
le meme jour = gains simultanes = effet boule de neige.

Objectif : +200% en 1-2 mois lors des periodes de breakout.

Architecture :
  - Capital partage unique (vs v4 ou chaque symbole avait son propre 50 EUR)
  - Boucle synchronisee sur tous les symboles (index timestamp commun 1h)
  - A chaque barre : exits d'abord, puis entries (rang par score)
  - Max 4 positions ouvertes simultanement sur actifs differents

Strategies :
  BREAKOUT PREMIUM : BB Squeeze + score>=70, TP 12:1, risque 2.5%, lev 2x
  PULLBACK QUALITY : EMA9 wick + score>=42 + MTF, TP 3.5:1, risque 2.5%, lev 3x

Usage :
    cd /home/user/profit-engine/backend
    python paper_test_v5.py
"""
from __future__ import annotations

import sys, os, math, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from config import AppConfig
from engine.analysis.indicators import compute_all, _ema
from engine.strategy.regime_detector import Regime, _adx as _compute_adx
from engine.execution.leverage_manager import LeverageManager

console = Console()

# ── Symbols ───────────────────────────────────────────────────────────────────
SYMBOLS_YF = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "AVAX-USD",
    "ADA-USD", "LINK-USD", "XRP-USD", "DOT-USD", "ATOM-USD", "LTC-USD",
]
SYMBOL_MAP = {
    "BTC-USD": "BTC/USDT", "ETH-USD": "ETH/USDT", "SOL-USD": "SOL/USDT",
    "BNB-USD": "BNB/USDT", "AVAX-USD": "AVAX/USDT", "ADA-USD": "ADA/USDT",
    "LINK-USD": "LINK/USDT", "XRP-USD": "XRP/USDT", "DOT-USD": "DOT/USDT",
    "ATOM-USD": "ATOM/USDT", "LTC-USD": "LTC/USDT",
}

# ── Capital & Multi-Position ──────────────────────────────────────────────────
INITIAL_CAPITAL   = 50.0
INTERVAL          = "1h"
PERIOD            = "2y"
WARMUP            = 210

N_MAX_POSITIONS   = 5       # positions simultanees max
SCORE_FRESH_WINDOW = 6      # fraicheur signal (barres)

# ── Parametres Trade ──────────────────────────────────────────────────────────
RISK_BO  = 0.035;  TP_BO  = 12.0;  SL_BO  = 1.0;  LEV_BO  = 2
RISK_PB  = 0.025;  TP_PB  = 3.5;   SL_PB  = 1.2;  LEV_PB  = 3

SCORE_BO_MIN  = 70
SCORE_PB_MIN  = 999   # pullback desactive (perte nette sur 2 ans, libere slots pour breakout)
MIN_ADX_PB    = 25

# ── BB Squeeze ────────────────────────────────────────────────────────────────
BB_SQUEEZE_WINDOW = 50
BB_SQUEEZE_PCT    = 0.15
VOL_SURGE_MIN     = 3.2
ADX_RISE_MIN_BO   = 3.0
MIN_ADX_BO        = 16
MIN_SQUEEZE_BARS  = 3
BO_BODY_PCT_MIN   = 0.45
BO_COOLDOWN_H     = 8

COMMISSION       = 0.0004
SLIPPAGE         = 0.0005
DAILY_LOSS_LIMIT = 0.10


# ── Data Helpers ──────────────────────────────────────────────────────────────

def download_data(symbol: str) -> Optional[pd.DataFrame]:
    try:
        raw = yf.download(symbol, period=PERIOD, interval=INTERVAL,
                          auto_adjust=True, progress=False)
        if raw is None or len(raw) < WARMUP + 50:
            return None
        df = raw.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0].lower() for col in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        df.index.name = "timestamp"
        return df
    except Exception:
        return None


def resample_daily(df: pd.DataFrame) -> pd.DataFrame:
    d = df.resample("1D").agg({"open": "first", "high": "max",
                                "low": "min", "close": "last", "volume": "sum"}).dropna()
    c = d["close"]
    d["ema9"]   = _ema(c, 9)
    d["ema21"]  = _ema(c, 21)
    d["ema50"]  = _ema(c, 50)
    d["ema200"] = _ema(c, 200)
    return d


def resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    d = df.resample("4h").agg({"open": "first", "high": "max",
                                "low": "min", "close": "last", "volume": "sum"}).dropna()
    c = d["close"]
    d["ema9"]  = _ema(c, 9)
    d["ema21"] = _ema(c, 21)
    return d


def _mtf_daily_check(action: str, df_daily: pd.DataFrame, ts) -> bool:
    try:
        past = df_daily[df_daily.index.normalize() <= pd.Timestamp(ts).normalize()]
        if len(past) < 50: return False
        last = past.iloc[-1]
        def sv(col):
            v = last.get(col)
            if v is None: return None
            try: f = float(v); return None if math.isnan(f) else f
            except: return None
        e9, e21, e50, e200 = sv("ema9"), sv("ema21"), sv("ema50"), sv("ema200")
        price = float(last["close"])
        if None in (e9, e21, e50, e200): return False
        if action == "BUY":  return bool(price > e50 > e200 and e9 > e21)
        if action == "SELL": return bool(price < e50 < e200 and e9 < e21)
        return False
    except Exception: return False


def _mtf_4h_check(action: str, df_4h: pd.DataFrame, ts) -> bool:
    try:
        past = df_4h[df_4h.index <= pd.Timestamp(ts)]
        if len(past) < 10: return False
        last = past.iloc[-1]
        def sv(col):
            v = last.get(col)
            if v is None: return None
            try: f = float(v); return None if math.isnan(f) else f
            except: return None
        e9, e21 = sv("ema9"), sv("ema21")
        if None in (e9, e21): return False
        if action == "BUY":  return bool(e9 > e21)
        if action == "SELL": return bool(e9 < e21)
        return False
    except Exception: return False


# ── BB Squeeze Detection ──────────────────────────────────────────────────────

def _bb_squeeze_breakout(df: pd.DataFrame, i: int,
                          adx_val: float, adx_series: pd.Series) -> Tuple[bool, Optional[str]]:
    if i < BB_SQUEEZE_WINDOW + 5: return False, None
    last = df.iloc[i]
    try:
        price     = float(last["close"])
        open_p    = float(last["open"])
        high_p    = float(last["high"])
        low_p     = float(last["low"])
        bb_upper  = float(last.get("bb_upper", 0) or 0)
        bb_lower  = float(last.get("bb_lower", 0) or 0)
        bb_mid    = float(last.get("bb_mid",   0) or 0)
        vol_ratio = float(last.get("vol_ratio", 1.0) or 1.0)
    except (TypeError, ValueError, KeyError): return False, None
    if bb_upper <= 0 or bb_lower <= 0 or bb_mid <= 0: return False, None
    if adx_val < MIN_ADX_BO: return False, None
    if "bbw" not in df.columns or "bbw_q15" not in df.columns: return False, None

    cur_bbw       = float(last.get("bbw", 1.0) or 1.0)
    q15_threshold = float(last.get("bbw_q15", 1.0) or 1.0)
    recent        = df.iloc[max(0, i - 8):i]
    if len(recent) < MIN_SQUEEZE_BARS: return False, None

    min_bbw_recent = float(recent["bbw"].min())
    if min_bbw_recent > q15_threshold * 1.05: return False, None
    if cur_bbw < min_bbw_recent * 1.15:       return False, None

    bbw_vals = recent["bbw"].values
    q15_vals = recent["bbw_q15"].values
    n_sq = int(np.sum(bbw_vals < q15_vals * 1.05))
    if n_sq < MIN_SQUEEZE_BARS: return False, None
    if vol_ratio < VOL_SURGE_MIN: return False, None

    if i >= 5 and not np.isnan(adx_series.iloc[i - 5]):
        adx_5 = float(adx_series.iloc[i - 5])
        if adx_val < adx_5 + ADX_RISE_MIN_BO: return False, None
    else:
        return False, None

    rng  = high_p - low_p
    body = abs(price - open_p)
    if rng > 0 and body / rng < BO_BODY_PCT_MIN: return False, None

    if price > bb_upper * 1.001 and price > open_p:  return True, "BUY"
    if price < bb_lower * 0.999 and price < open_p:  return True, "SELL"
    return False, None


# ── EMA9 Pullback Detection ───────────────────────────────────────────────────

def _ema9_pullback(df: pd.DataFrame, i: int,
                   regime_val: str, adx_val: float) -> Tuple[bool, Optional[str]]:
    if i < 2 or adx_val < MIN_ADX_PB: return False, None
    last = df.iloc[i]
    try:
        price     = float(last["close"])
        ema9      = float(last.get("ema9",  0) or 0)
        ema21     = float(last.get("ema21", 0) or 0)
        open_p    = float(last["open"])
        high_p    = float(last["high"])
        low_p     = float(last["low"])
        vol_ratio = float(last.get("vol_ratio", 1.0) or 1.0)
        rsi_raw   = last.get("rsi")
        rsi_v     = float(rsi_raw) if (rsi_raw is not None and not pd.isna(rsi_raw)) else 50.0
    except (TypeError, ValueError, KeyError): return False, None
    if ema9 <= 0 or ema21 <= 0: return False, None

    body    = abs(price - open_p)
    rng     = high_p - low_p
    bpct    = body / rng if rng > 0 else 0
    ema9_5  = float(df.iloc[max(0, i - 5)].get("ema9", ema9) or ema9)

    if regime_val == "bull_trend":
        if not (ema9 > ema21 > 0):      return False, None
        if low_p > ema9 * 1.002:        return False, None
        if price <= open_p:              return False, None
        if price <= ema9:                return False, None
        if price > ema9 * 1.02:         return False, None
        if rsi_v < 38 or rsi_v > 62:    return False, None
        if vol_ratio < 1.2:              return False, None
        if bpct < 0.40:                  return False, None
        if ema9 < ema9_5 * 1.001:       return False, None
        return True, "BUY"
    elif regime_val == "bear_trend":
        if not (ema9 < ema21) or ema9 <= 0: return False, None
        if high_p < ema9 * 0.998:       return False, None
        if price >= open_p:              return False, None
        if price >= ema9:                return False, None
        if price < ema9 * 0.98:         return False, None
        if rsi_v < 38 or rsi_v > 62:    return False, None
        if vol_ratio < 1.2:              return False, None
        if bpct < 0.40:                  return False, None
        if ema9 > ema9_5 * 0.999:       return False, None
        return True, "SELL"
    return False, None


# ── Trade Dataclass ───────────────────────────────────────────────────────────

@dataclass
class PaperTrade:
    symbol:       str
    side:         str
    entry_ts:     pd.Timestamp
    exit_ts:      pd.Timestamp
    entry_price:  float
    exit_price:   float
    margin_eur:   float
    leverage:     int
    pnl_eur:      float
    pnl_pct:      float
    exit_reason:  str
    score:        int
    trade_type:   str
    candles_held: int


# ── Symbol Precomputation ─────────────────────────────────────────────────────

def precompute_symbol(sym: str, cfg) -> Optional[dict]:
    """Downloads data, computes all indicators, pre-builds score arrays."""
    raw = download_data(sym)
    if raw is None:
        return None

    df = compute_all(raw.copy(), cfg.strategy)
    df_daily = resample_daily(df)
    df_4h    = resample_4h(df)

    # BB Width
    if "bb_upper" in df.columns and "bb_lower" in df.columns and "bb_mid" in df.columns:
        df["bbw"] = ((df["bb_upper"] - df["bb_lower"]) /
                     df["bb_mid"].replace(0, np.nan)).fillna(1.0)
    else:
        p = 20; k = 2.0
        df["bb_mid"]   = df["close"].rolling(p).mean()
        df["bb_upper"] = df["bb_mid"] + k * df["close"].rolling(p).std()
        df["bb_lower"] = df["bb_mid"] - k * df["close"].rolling(p).std()
        df["bbw"]      = ((df["bb_upper"] - df["bb_lower"]) /
                           df["bb_mid"].replace(0, np.nan)).fillna(1.0)

    df["bbw_q15"]        = df["bbw"].rolling(BB_SQUEEZE_WINDOW).quantile(BB_SQUEEZE_PCT).fillna(df["bbw"])
    df["macd_hist_slope"] = df["macd_hist"].diff().fillna(0)
    df["obv_slope"]       = df["obv"].diff(5).fillna(0)

    adx_series, di_p_series, di_m_series = _compute_adx(df)

    # Vectorized score arrays
    n = len(df)
    buy_sc  = np.zeros(n, dtype=np.int16)
    sell_sc = np.zeros(n, dtype=np.int16)

    _cls   = df["close"].values
    _e9    = df["ema9"].values
    _e21   = df["ema21"].values
    _e50   = df["ema50"].values
    _e200  = df["ema200"].values
    _rsi   = df["rsi"].fillna(50).values
    _mh    = df["macd_hist"].fillna(0).values
    _ms    = df["macd_hist_slope"].fillna(0).values
    _vwap  = df["vwap"].fillna(df["close"]).values
    _sk    = df["stoch_k"].fillna(50).values
    _sd    = df["stoch_d"].fillna(50).values
    _obv   = df["obv_slope"].fillna(0).values
    _adxa  = adx_series.values
    _dipa  = di_p_series.values
    _dima  = di_m_series.values

    for ii in range(n):
        _p = _cls[ii]; _b = 0; _s = 0
        _rb = int(_e9[ii]>_e21[ii])+int(_e21[ii]>_e50[ii])+int(_e50[ii]>_e200[ii])+int(_p>_e21[ii])
        _rs = int(_e9[ii]<_e21[ii])+int(_e21[ii]<_e50[ii])+int(_e50[ii]<_e200[ii])+int(_p<_e21[ii])
        if _rb >= 3: _b += 20
        if _rs >= 3: _s += 20
        if _mh[ii] > 0 and _ms[ii] > 0: _b += 15
        elif _mh[ii] < 0 and _ms[ii] < 0: _s += 15
        r = _rsi[ii]
        if 50 <= r <= 72: _b += 10
        elif 28 <= r <= 50: _s += 10
        vw = _vwap[ii] or _p
        if vw > 0:
            if _p > vw * 1.0005: _b += 15
            elif _p < vw * 0.9995: _s += 15
        sk = _sk[ii]; sd = _sd[ii]
        if sk > sd and sk < 75: _b += 10
        elif sk < sd and sk > 25: _s += 10
        if _obv[ii] > 0: _b += 15
        elif _obv[ii] < 0: _s += 15
        adxv = float(_adxa[ii]) if not np.isnan(_adxa[ii]) else 0.0
        if adxv >= 18:
            dpv = float(_dipa[ii]) if not np.isnan(_dipa[ii]) else 0.0
            dmv = float(_dima[ii]) if not np.isnan(_dima[ii]) else 0.0
            if dpv > dmv: _b += 15
            elif dmv > dpv: _s += 15
        buy_sc[ii]  = min(_b, 100)
        sell_sc[ii] = min(_s, 100)

    ts_to_pos = {ts: i for i, ts in enumerate(df.index)}

    return {
        "name":        SYMBOL_MAP.get(sym, sym),
        "df":          df,
        "df_daily":    df_daily,
        "df_4h":       df_4h,
        "adx_s":       adx_series,
        "di_p_s":      di_p_series,
        "di_m_s":      di_m_series,
        "buy_sc":      buy_sc,
        "sell_sc":     sell_sc,
        "ts_to_pos":   ts_to_pos,
        "ts_index":    df.index,
    }


# ── Fast Regime ───────────────────────────────────────────────────────────────

def _fast_regime(sd: dict, bar: int) -> Regime:
    row = sd["df"].iloc[bar]
    price = float(row.get("close", 1) or 1)
    e50   = float(row.get("ema50", price) or price)
    e200  = float(row.get("ema200", price) or price)
    atr_v = float(row.get("atr", price * 0.01) or price * 0.01)
    atr_p = atr_v / price * 100 if price > 0 else 1.0
    adx_v = float(sd["adx_s"].iloc[bar]) if not np.isnan(sd["adx_s"].iloc[bar]) else 20.0
    dip   = float(sd["di_p_s"].iloc[bar]) if not np.isnan(sd["di_p_s"].iloc[bar]) else 0.0
    dim   = float(sd["di_m_s"].iloc[bar]) if not np.isnan(sd["di_m_s"].iloc[bar]) else 0.0
    if atr_p > 3.5: return Regime.HIGH_VOL
    if adx_v > 20:
        if dip > dim and price > e50 and e50 > e200: return Regime.BULL_TREND
        if dim > dip and price < e50 and e50 < e200: return Regime.BEAR_TREND
    return Regime.RANGING


# ── Multi-Position Engine ─────────────────────────────────────────────────────

class MultiPositionEngine:
    """
    Capital unique partage, boucle synchronisee sur tous les symboles.
    Jusqu'a N_MAX_POSITIONS positions simultanees.
    """

    def __init__(self, sym_data: dict):
        self.sym_data = sym_data
        self.cfg      = AppConfig()
        self.lev_mgr  = LeverageManager()

        # Caches MTF par symbole et par jour
        self._daily_mtf: Dict[str, bool] = {}
        self._4h_mtf:    Dict[str, bool]  = {}

    def _get_total_equity(self, positions: dict, available_cash: float) -> float:
        return available_cash + sum(p["margin_eur"] for p in positions.values())

    def _check_exit(self, pos: dict, price: float, atr_v: float,
                    ts: pd.Timestamp) -> Optional[Tuple[float, float, str]]:
        """Returns (pnl_eur, exit_price, reason) or None."""
        side = pos["side"]
        reason = None

        if side == "long"  and price <= pos["liq"]: reason = "liquidation"
        elif side == "short" and price >= pos["liq"]: reason = "liquidation"

        if not pos.get("partial_taken") and reason is None:
            if side == "long"  and price >= pos["partial_tp"]:
                pos["partial_taken"] = True; pos["sl"] = pos["entry"]
            elif side == "short" and price <= pos["partial_tp"]:
                pos["partial_taken"] = True; pos["sl"] = pos["entry"]

        # Trailing stop update
        trail = pos.get("trail", float("nan"))
        if not math.isnan(trail):
            if side == "long":
                nt = price - atr_v * 0.5
                if nt > trail: pos["trail"] = nt
            else:
                nt = price + atr_v * 0.5
                if nt < trail: pos["trail"] = nt

        if reason is None:
            trail = pos.get("trail", float("nan"))
            if side == "long":
                if price <= pos["sl"]:                          reason = "stop_loss"
                elif not math.isnan(trail) and price <= trail:  reason = "trailing_stop"
                elif price >= pos["tp"]:                        reason = "take_profit"
            else:
                if price >= pos["sl"]:                          reason = "stop_loss"
                elif not math.isnan(trail) and price >= trail:  reason = "trailing_stop"
                elif price <= pos["tp"]:                        reason = "take_profit"

        if reason is None:
            return None

        if reason == "liquidation":
            return -pos["margin_eur"], pos["liq"], reason

        slip   = (1 - SLIPPAGE) if side == "long" else (1 + SLIPPAGE)
        exit_p = price * slip
        raw    = (exit_p - pos["entry"]) * pos["qty"] if side == "long" \
                 else (pos["entry"] - exit_p) * pos["qty"]
        pnl    = raw - pos["qty"] * exit_p * COMMISSION
        return pnl, exit_p, reason

    def _try_enter(self, sym: str, action: str, trade_type: str, score: int,
                   bar: int, ts: pd.Timestamp,
                   available_cash: float, total_equity: float) -> Optional[dict]:
        """Returns a new position dict, or None if can't enter."""
        sd  = self.sym_data[sym]
        row = sd["df"].iloc[bar]
        price  = float(row["close"])
        atr_raw = row.get("atr")
        atr_v  = float(atr_raw) if (atr_raw is not None and not pd.isna(atr_raw)) else price * 0.02

        if trade_type == "breakout_premium":
            risk_frac = RISK_BO; sl_mult = SL_BO; tp_rr = TP_BO; max_lev = LEV_BO
        else:
            risk_frac = RISK_PB; sl_mult = SL_PB; tp_rr = TP_PB; max_lev = LEV_PB

        lev      = min(self.lev_mgr.get_leverage(score, "HIGH"), max_lev)
        sl_dist  = atr_v * sl_mult
        tp_dist  = sl_dist * tp_rr
        risk_eur = total_equity * risk_frac

        if action == "BUY":
            entry_p   = price * (1 + SLIPPAGE)
            sl        = entry_p - sl_dist
            tp        = entry_p + tp_dist
            partial_tp = entry_p + (tp - entry_p) * 0.55
            liq_p     = self.lev_mgr.liquidation_price(entry_p, lev, "long")
            sl        = max(sl, liq_p * 1.001)
            side      = "long"
        else:
            entry_p   = price * (1 - SLIPPAGE)
            sl        = entry_p + sl_dist
            tp        = entry_p - tp_dist
            partial_tp = entry_p - (entry_p - tp) * 0.55
            liq_p     = self.lev_mgr.liquidation_price(entry_p, lev, "short")
            sl        = min(sl, liq_p * 0.999)
            side      = "short"

        sl_distance = abs(entry_p - sl) or entry_p * 0.02
        qty         = risk_eur / sl_distance
        margin_eur  = qty * entry_p / lev

        if margin_eur > available_cash * 0.90:
            margin_eur = available_cash * 0.90
            qty        = margin_eur * lev / entry_p

        entry_comm = qty * entry_p * COMMISSION
        total_cost = margin_eur + entry_comm

        if qty <= 1e-12 or total_cost > available_cash:
            return None

        return {
            "side": side, "entry": entry_p, "qty": qty,
            "margin_eur": margin_eur, "liq": liq_p,
            "sl": sl, "tp": tp, "partial_tp": partial_tp,
            "trail": float("nan"),
            "leverage": lev, "score": score,
            "entry_ts": ts, "entry_bar": bar,
            "trade_type": trade_type,
            "partial_taken": False,
            "total_cost": total_cost,
        }

    def run(self, common_timestamps: List[pd.Timestamp]) -> Tuple[List[PaperTrade], list]:
        """
        Main synchronized multi-position loop.
        Returns (trades, equity_curve).
        """
        available_cash  = INITIAL_CAPITAL
        positions: Dict[str, dict] = {}    # sym -> pos_dict
        bo_cooldowns: Dict[str, pd.Timestamp] = {}
        all_trades: List[PaperTrade] = []
        equity_curve = []

        # Daily tracking
        current_day     = None
        day_start_equity = INITIAL_CAPITAL
        day_halted      = False

        # Explosive day tracking (day -> list of winning syms)
        day_wins: Dict[str, list] = {}

        # MTF cache (sym, action, day/4hkey -> bool)
        mtf_d_cache: Dict[str, bool] = {}
        mtf_4_cache: Dict[str, bool] = {}

        for ts in common_timestamps:
            day_key = str(ts)[:10]
            total_eq = available_cash + sum(p["margin_eur"] for p in positions.values())

            # Day reset
            if day_key != current_day:
                current_day      = day_key
                day_start_equity = total_eq
                day_halted       = False

            # Daily circuit-breaker
            if not day_halted and day_start_equity > 0:
                day_loss_frac = (day_start_equity - total_eq) / day_start_equity
                if day_loss_frac >= DAILY_LOSS_LIMIT:
                    day_halted = True

            # ── Step 1: Process exits ──────────────────────────────────────
            for sym in list(positions.keys()):
                sd  = self.sym_data.get(sym)
                if sd is None: continue
                bar = sd["ts_to_pos"].get(ts)
                if bar is None: continue
                row   = sd["df"].iloc[bar]
                price = float(row["close"])
                atr_raw = row.get("atr")
                atr_v  = float(atr_raw) if (atr_raw is not None and not pd.isna(atr_raw)) else price * 0.02
                pos    = positions[sym]

                result = self._check_exit(pos, price, atr_v, ts)
                if result is None:
                    continue

                pnl_eur, exit_p, reason = result
                available_cash += pos["margin_eur"] + pnl_eur
                pnl_pct = pnl_eur / pos["margin_eur"] * 100 if pos["margin_eur"] > 0 else 0.0

                all_trades.append(PaperTrade(
                    symbol=sd["name"], side=pos["side"],
                    entry_ts=pos["entry_ts"], exit_ts=ts,
                    entry_price=pos["entry"], exit_price=exit_p,
                    margin_eur=round(pos["margin_eur"], 4),
                    leverage=pos["leverage"],
                    pnl_eur=round(pnl_eur, 4), pnl_pct=round(pnl_pct, 3),
                    exit_reason=reason, score=pos["score"],
                    trade_type=pos["trade_type"],
                    candles_held=bar - pos["entry_bar"],
                ))

                if pnl_eur > 0:
                    day_wins.setdefault(day_key, []).append(sym)
                if pnl_eur < 0 and pos["trade_type"] == "breakout_premium":
                    bo_cooldowns[sym] = ts + pd.Timedelta(hours=BO_COOLDOWN_H)
                del positions[sym]

            # Update equity curve
            total_eq = available_cash + sum(p["margin_eur"] for p in positions.values())
            equity_curve.append((ts, total_eq))

            # ── Step 2: Entry candidates ────────────────────────────────────
            slots_free = N_MAX_POSITIONS - len(positions)
            if slots_free <= 0 or day_halted or available_cash < 1.0:
                continue

            total_eq = available_cash + sum(p["margin_eur"] for p in positions.values())
            candidates = []

            for sym, sd in self.sym_data.items():
                if sym in positions: continue
                bar = sd["ts_to_pos"].get(ts)
                if bar is None or bar < WARMUP: continue

                # Cooldown check
                cd = bo_cooldowns.get(sym)
                if cd is not None and ts < cd: continue

                adx_i  = float(sd["adx_s"].iloc[bar]) if not np.isnan(sd["adx_s"].iloc[bar]) else 0.0
                buy_sc = int(sd["buy_sc"][bar])
                sell_sc = int(sd["sell_sc"][bar])

                # ── Breakout ──
                is_bo, bo_action = _bb_squeeze_breakout(
                    sd["df"], bar, adx_i, sd["adx_s"])
                if is_bo and bo_action:
                    dir_sc = buy_sc if bo_action == "BUY" else sell_sc
                    if dir_sc >= SCORE_BO_MIN:
                        candidates.append({
                            "score": dir_sc, "sym": sym, "action": bo_action,
                            "tt": "breakout_premium", "bar": bar,
                        })
                        continue  # prefer breakout over pullback for same bar

                # ── Pullback ──
                try:
                    regime = _fast_regime(sd, bar)
                except Exception:
                    continue
                if regime not in (Regime.BULL_TREND, Regime.BEAR_TREND):
                    continue

                is_pb, pb_action = _ema9_pullback(
                    sd["df"], bar, regime.value, adx_i)
                if is_pb and pb_action:
                    dir_sc = buy_sc if pb_action == "BUY" else sell_sc
                    if dir_sc < SCORE_PB_MIN: continue

                    # MTF daily check
                    dk = f"{sym}_{pb_action}_{day_key}"
                    if dk not in mtf_d_cache:
                        mtf_d_cache[dk] = _mtf_daily_check(pb_action, sd["df_daily"], ts)
                    if not mtf_d_cache[dk]: continue

                    # MTF 4h check
                    h4k = f"{sym}_{pb_action}_{day_key}_{ts.hour // 4}"
                    if h4k not in mtf_4_cache:
                        mtf_4_cache[h4k] = _mtf_4h_check(pb_action, sd["df_4h"], ts)
                    if not mtf_4_cache[h4k]: continue

                    candidates.append({
                        "score": dir_sc, "sym": sym, "action": pb_action,
                        "tt": "pullback_quality", "bar": bar,
                    })

            # Rank by score descending, take top N
            candidates.sort(key=lambda c: c["score"], reverse=True)

            for cand in candidates[:slots_free]:
                if available_cash < 1.0: break
                pos = self._try_enter(
                    sym=cand["sym"], action=cand["action"],
                    trade_type=cand["tt"], score=cand["score"],
                    bar=cand["bar"], ts=ts,
                    available_cash=available_cash,
                    total_equity=total_eq,
                )
                if pos is None: continue
                available_cash -= pos["total_cost"]
                positions[cand["sym"]] = pos

        return all_trades, equity_curve, day_wins


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(trades: List[PaperTrade], equity_curve: list,
                 day_wins: dict, t0: float):
    if not trades:
        console.print("[red]Aucun trade.[/red]")
        return

    eq_vals = [v for _, v in equity_curve]
    final_eq = eq_vals[-1] if eq_vals else INITIAL_CAPITAL

    # Max drawdown
    peak = INITIAL_CAPITAL
    max_dd = 0.0
    for v in eq_vals:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        if dd > max_dd: max_dd = dd

    wins = [t for t in trades if t.pnl_eur > 0]
    losses = [t for t in trades if t.pnl_eur <= 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    net = final_eq - INITIAL_CAPITAL
    ret_pct = net / INITIAL_CAPITAL * 100

    # Sharpe
    if len(equity_curve) > 1:
        eq_s = pd.Series(eq_vals)
        rets = eq_s.pct_change().dropna()
        sharpe = (rets.mean() / rets.std() * math.sqrt(8760)) if rets.std() > 0 else 0
    else:
        sharpe = 0

    # Profit factor
    gross_win  = sum(t.pnl_eur for t in wins) if wins else 0
    gross_loss = abs(sum(t.pnl_eur for t in losses)) if losses else 1
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    # Trade types
    bo = [t for t in trades if t.trade_type == "breakout_premium"]
    pb = [t for t in trades if t.trade_type == "pullback_quality"]
    bo_wins = [t for t in bo if t.pnl_eur > 0]
    pb_wins = [t for t in pb if t.pnl_eur > 0]

    long_c  = sum(1 for t in trades if t.side == "long")
    short_c = sum(1 for t in trades if t.side == "short")

    # Max simultaneous positions (from equity curve timing)
    liq_count = sum(1 for t in trades if t.exit_reason == "liquidation")

    console.print()
    console.rule("[bold yellow]SKYN v5 — MULTI-POSITION ENGINE COMPLET[/bold yellow]")
    console.print()

    res_panel = Panel(
        f"[bold]Mise de depart[/bold]   {INITIAL_CAPITAL:.2f} EUR\n"
        f"[bold]Capital final  [/bold]   {final_eq:.2f} EUR\n"
        f"[{'green' if net >= 0 else 'red'}]Profit net       {'+' if net >= 0 else ''}{net:.2f} EUR ({'+' if ret_pct >= 0 else ''}{ret_pct:.2f}%)[/]\n"
        f"[bold]Drawdown max   [/bold]   {max_dd:.1f}%\n"
        f"[bold]Sharpe         [/bold]   {sharpe:.3f}\n"
        f"[bold]Profit Factor  [/bold]   {pf:.3f}\n"
        f"[bold]Win rate       [/bold]   {wr:.1f}% ({len(wins)}W / {len(losses)}L)\n"
        f"[bold]Trades total   [/bold]   {len(trades)}  Long:{long_c} Court:{short_c}\n"
        f"[bold]Liquidations   [/bold]   {liq_count}",
        title="[bold cyan]Resultat Global · 2 ans · Multi-Position[/bold cyan]",
        border_style="cyan",
    )
    console.print(res_panel)

    # Per-type performance
    t_table = Table(title="Performance par Type de Trade", box=box.SIMPLE_HEAVY)
    t_table.add_column("Type", style="bold")
    t_table.add_column("Trades", justify="right")
    t_table.add_column("Win%", justify="right")
    t_table.add_column("Net (EUR)", justify="right")
    t_table.add_column("Gain moy/win", justify="right")
    for label, lst, wlist in [
        ("BREAKOUT PREMIUM", bo, bo_wins),
        ("PULLBACK QUALITY", pb, pb_wins),
    ]:
        wr_t = len(wlist) / len(lst) * 100 if lst else 0
        net_t = sum(t.pnl_eur for t in lst)
        avg_w = sum(t.pnl_pct for t in wlist) / len(wlist) if wlist else 0
        t_table.add_row(
            label, str(len(lst)),
            f"{wr_t:.0f}%",
            f"[{'green' if net_t >= 0 else 'red'}]{'+' if net_t >= 0 else ''}{net_t:.2f}EUR[/]",
            f"+{avg_w:.1f}% par win",
        )
    console.print(t_table)

    # Explosive days
    explosive = {d: s for d, s in day_wins.items() if len(s) >= 2}
    max_sim   = max((len(s) for s in day_wins.values()), default=0)
    exp3      = sum(1 for s in day_wins.values() if len(s) >= 3)
    exp4      = sum(1 for s in day_wins.values() if len(s) >= 4)

    exp_panel = Panel(
        f"[bold]Max positions gagnantes le meme jour :[/bold] {max_sim}\n"
        f"[bold]Journees avec 2+ victoires simultanees :[/bold] {len(explosive)}\n"
        f"[bold]Journees avec 3+ victoires simultanees :[/bold] {exp3}\n"
        f"[bold]Journees avec 4+ victoires simultanees :[/bold] {exp4}",
        title="[bold magenta]Effet Explosif — Journees Multi-Victoires[/bold magenta]",
        border_style="magenta",
    )
    console.print(exp_panel)

    # Monthly breakdown
    df_trades = pd.DataFrame([{
        "month": str(t.entry_ts)[:7],
        "pnl":   t.pnl_eur,
        "win":   t.pnl_eur > 0,
        "tt":    t.trade_type,
    } for t in trades])

    # Monthly equity from curve
    eq_df = pd.DataFrame(equity_curve, columns=["ts", "eq"])
    eq_df["month"] = eq_df["ts"].dt.strftime("%Y-%m")

    m_table = Table(title="Breakdown Mensuel — Multi-Position", box=box.SIMPLE_HEAVY)
    for col in ["Mois", "Trades", "Win%", "BO/PB", "Net EUR", "Ret%", "Statut"]:
        m_table.add_column(col, justify="right" if col not in ["Mois", "Statut"] else "left")

    months = sorted(df_trades["month"].unique())
    prev_eq = INITIAL_CAPITAL
    for m in months:
        mt = df_trades[df_trades["month"] == m]
        net_m = mt["pnl"].sum()
        wins_m = mt["win"].sum()
        wr_m   = wins_m / len(mt) * 100 if len(mt) > 0 else 0
        bo_m   = (mt["tt"] == "breakout_premium").sum()
        pb_m   = (mt["tt"] == "pullback_quality").sum()

        # Get equity at end of month
        m_eq = eq_df[eq_df["month"] == m]["eq"]
        end_eq = float(m_eq.iloc[-1]) if len(m_eq) > 0 else prev_eq
        ret_m  = (end_eq - prev_eq) / prev_eq * 100 if prev_eq > 0 else 0

        if ret_m >= 200: stat = "[bold magenta]×3![/bold magenta]"
        elif ret_m >= 100: stat = "[bold green]×2+[/bold green]"
        elif ret_m >= 50:  stat = "[bold green]×1.5+[/bold green]"
        elif ret_m >= 20:  stat = "[green]+20%+ v[/green]"
        elif ret_m >= 0:   stat = "[green]+[/green]"
        else:              stat = "[red]-[/red]"

        m_table.add_row(
            m, str(len(mt)), f"{wr_m:.0f}%",
            f"{bo_m}/{pb_m}",
            f"[{'green' if net_m >= 0 else 'red'}]{'+' if net_m >= 0 else ''}{net_m:.2f}EUR[/]",
            f"{'+' if ret_m >= 0 else ''}{ret_m:.1f}%",
            stat,
        )
        prev_eq = end_eq

    console.print(m_table)

    # Beta test (last 6 months)
    if len(equity_curve) > 0:
        last_ts = equity_curve[-1][0]
        beta_start_ts = last_ts - pd.DateOffset(months=6)
        beta_trades = [t for t in trades if t.entry_ts >= beta_start_ts]
        beta_eq = [(ts, v) for ts, v in equity_curve if ts >= beta_start_ts]

        if beta_trades and beta_eq:
            b_start = beta_eq[0][1]
            b_end   = beta_eq[-1][1]
            b_net   = b_end - b_start
            b_ret   = b_net / b_start * 100 if b_start > 0 else 0
            b_wins  = [t for t in beta_trades if t.pnl_eur > 0]
            b_wr    = len(b_wins) / len(beta_trades) * 100 if beta_trades else 0

            b_eq_vals = [v for _, v in beta_eq]
            b_peak = b_eq_vals[0]; b_dd = 0
            for v in b_eq_vals:
                if v > b_peak: b_peak = v
                dd = (b_peak - v) / b_peak * 100 if b_peak > 0 else 0
                if dd > b_dd: b_dd = dd

            b_rets = pd.Series(b_eq_vals).pct_change().dropna()
            b_sh = (b_rets.mean() / b_rets.std() * math.sqrt(8760)) if b_rets.std() > 0 else 0

            b_bo = sum(1 for t in beta_trades if t.trade_type == "breakout_premium")
            b_pb = sum(1 for t in beta_trades if t.trade_type == "pullback_quality")

            beta_panel = Panel(
                f"Periode    : {beta_eq[0][0].strftime('%Y-%m-%d')} -> {beta_eq[-1][0].strftime('%Y-%m-%d')}\n"
                f"Trades     : {len(beta_trades)}  (breakout:{b_bo} / pullback:{b_pb})\n"
                f"Capital de depart : {b_start:.2f}EUR\n"
                f"[{'green' if b_net >= 0 else 'red'}]Resultat   : {'+' if b_net >= 0 else ''}{b_net:.2f}EUR ({'+' if b_ret >= 0 else ''}{b_ret:.1f}%)[/]\n"
                f"Win Rate   : {b_wr:.1f}%  |  DD: {b_dd:.1f}%  |  Sharpe: {b_sh:.3f}\n\n"
                f"x2 atteint ?  {'[bold green]OUI[/bold green]' if b_ret >= 100 else '[red]NON[/red]'} ({b_ret:.1f}%)\n"
                f"x3 atteint ?  {'[bold magenta]OUI[/bold magenta]' if b_ret >= 200 else '[red]NON[/red]'} ({b_ret:.1f}%)",
                title="[bold yellow]Beta Test — Fenetre 6 Derniers Mois[/bold yellow]",
                border_style="yellow",
            )
            console.print(beta_panel)

            # Beta monthly
            b_table = Table(title="Beta Test — Breakdown Mensuel", box=box.SIMPLE)
            for col in ["Mois", "Trades", "Win%", "Net EUR", "Ret%", "Statut"]:
                b_table.add_column(col, justify="right" if col != "Mois" and col != "Statut" else "left")

            b_months = sorted(set(str(t.entry_ts)[:7] for t in beta_trades))
            b_prev_eq = b_start
            for bm in b_months:
                bmt = [t for t in beta_trades if str(t.entry_ts)[:7] == bm]
                bnet = sum(t.pnl_eur for t in bmt)
                bwin = sum(1 for t in bmt if t.pnl_eur > 0)
                bwr  = bwin / len(bmt) * 100 if bmt else 0
                beq  = [v for ts, v in beta_eq if ts.strftime("%Y-%m") == bm]
                bend = float(beq[-1]) if beq else b_prev_eq
                bret = (bend - b_prev_eq) / b_prev_eq * 100 if b_prev_eq > 0 else 0
                if bret >= 100:   bst = "[bold green]×2+[/bold green]"
                elif bret >= 50:  bst = "[green]×1.5+[/green]"
                elif bret >= 20:  bst = "[green]+20%+[/green]"
                elif bret >= 0:   bst = "[green]+[/green]"
                else:             bst = "[red]-[/red]"
                b_table.add_row(bm, str(len(bmt)), f"{bwr:.0f}%",
                                f"[{'green' if bnet>=0 else 'red'}]{'+' if bnet>=0 else ''}{bnet:.2f}EUR[/]",
                                f"{'+' if bret>=0 else ''}{bret:.1f}%", bst)
                b_prev_eq = bend
            console.print(b_table)

    # Equity curve sparkline
    if eq_vals:
        eq_min = min(eq_vals); eq_max = max(eq_vals)
        W = 80
        spark_vals = [eq_vals[int(i * len(eq_vals) / W)] for i in range(W)]
        bars = " ▁▂▃▄▅▆▇█"
        def to_bar(v):
            if eq_max == eq_min: return "▄"
            idx = int((v - eq_min) / (eq_max - eq_min) * 8)
            return bars[min(idx, 8)]
        sparkline = "".join(to_bar(v) for v in spark_vals)
        console.print(Panel(
            f"{sparkline}\n"
            f"   Depart: {INITIAL_CAPITAL:.2f}EUR  ->  Fin: {final_eq:.2f}EUR  |  Min: {eq_min:.2f}EUR  Max: {eq_max:.2f}EUR",
            title="[bold]Courbe d'Equity (50EUR -> ?)[/bold]",
            border_style="blue",
        ))

    # Top trades
    if trades:
        top5 = sorted(trades, key=lambda t: t.pnl_eur, reverse=True)[:10]
        bot5 = sorted(trades, key=lambda t: t.pnl_eur)[:10]

        tw = Table(title="Top 10 Meilleurs Trades", box=box.SIMPLE)
        for c in ["Sym", "Side", "Type", "Score", "Net EUR", "PnL%", "Lev", "Sortie", "Duree"]:
            tw.add_column(c)
        for t in top5:
            tw.add_row(t.symbol.split("/")[0], t.side[:5],
                       t.trade_type[:6], str(t.score),
                       f"[green]+{t.pnl_eur:.2f}EUR[/green]",
                       f"+{t.pnl_pct:.1f}%", f"{t.leverage}x",
                       t.exit_reason[:6], f"{t.candles_held}h")
        console.print(tw)

        tb = Table(title="Top 10 Pires Trades", box=box.SIMPLE)
        for c in ["Sym", "Side", "Type", "Score", "Net EUR", "PnL%", "Lev", "Sortie", "Duree"]:
            tb.add_column(c)
        for t in bot5:
            tb.add_row(t.symbol.split("/")[0], t.side[:5],
                       t.trade_type[:6], str(t.score),
                       f"[red]{t.pnl_eur:.2f}EUR[/red]",
                       f"{t.pnl_pct:.1f}%", f"{t.leverage}x",
                       t.exit_reason[:6], f"{t.candles_held}h")
        console.print(tb)

    elapsed = time.time() - t0
    console.rule(f"[bold]FIN · {elapsed:.1f}s · {len(trades)} trades[/bold]")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    console.rule("[bold yellow]SKYN v5 — MULTI-POSITION ENGINE · 50EUR · 11 Symboles · 2 ans[/bold yellow]")
    console.print(
        f"  Capital partage : {INITIAL_CAPITAL:.0f}EUR unique\n"
        f"  Max simultane   : {N_MAX_POSITIONS} positions\n"
        f"  BREAKOUT        : BB Squeeze + score>={SCORE_BO_MIN}  TP {TP_BO:.0f}:1  risque {RISK_BO*100:.1f}%\n"
        f"  PULLBACK        : EMA9 + score>={SCORE_PB_MIN} + MTF  TP {TP_PB:.1f}:1  risque {RISK_PB*100:.1f}%"
    )
    console.print()

    cfg = AppConfig()

    # Load & precompute all symbols
    console.print("Telechargement et calcul des indicateurs...")
    sym_data = {}
    for sym in SYMBOLS_YF:
        t_sym = time.time()
        sd = precompute_symbol(sym, cfg)
        if sd is None:
            console.print(f"  [red]x {sym} — echec[/red]")
            continue
        sym_data[sym] = sd
        console.print(f"  [green]v {sym}[/green] — {len(sd['df'])} barres [{time.time()-t_sym:.1f}s]")

    if not sym_data:
        console.print("[bold red]Aucun symbole disponible.[/bold red]")
        return

    # Build common timestamp index (intersection)
    console.print("\nConstruction de l'index commun...")
    common_set = None
    for sd in sym_data.values():
        s = set(sd["ts_index"])
        common_set = s if common_set is None else common_set & s
    common_timestamps = sorted(common_set)
    console.print(f"  {len(common_timestamps)} barres communes sur {len(SYMBOLS_YF)} symboles\n")

    # Run multi-position engine
    console.print("[bold cyan]Simulation multi-position en cours...[/bold cyan]")
    engine = MultiPositionEngine(sym_data)
    trades, equity_curve, day_wins = engine.run(common_timestamps[WARMUP:])
    console.print(f"  OK {len(trades)} trades simules en {time.time()-t0:.1f}s")

    # Report
    print_report(trades, equity_curve, day_wins, t0)


if __name__ == "__main__":
    main()
