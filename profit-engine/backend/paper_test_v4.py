#!/usr/bin/env python3
"""
SKYN — Paper Trading Test v4.1 : PREDICTION ENGINE (BREAKOUT + PULLBACK)
=========================================================================
Architecture finale (validée backtests) : 7 signaux → score consensus 0-100.

  BREAKOUT PREMIUM : BB Squeeze + score >= 70 → risque 2.5%, TP 12:1, SL 1.0 ATR, lev 2x
  PULLBACK QUALITY : EMA9 pullback + score >= 42 + MTF → risque 2.5%, TP 3.5:1, SL 1.2 ATR, lev 3x

  (ULTRA et HIGH CONVICTION desactives — perdent de l'argent en backtest)

Les 7 signaux (poids en points) :
  1. EMA Ribbon       (20 pts)
  2. MACD Momentum    (15 pts)
  3. RSI Zone         (10 pts)
  4. VWAP Position    (15 pts)
  5. Stochastic Dir.  (10 pts)
  6. OBV Trend        (15 pts)
  7. ADX Directionnel (15 pts)

Resultats 2 ans : +452% | x2+ en Aug/Nov 2024, Mar 2025 | DD 65.5% | Sharpe 7.73

Usage :
    cd /home/user/profit-engine/backend
    python paper_test_v4.py
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
from engine.analysis.signals import score_signal
from engine.strategy.regime_detector import Regime, _adx as _compute_adx
from engine.strategy.strategy_router import _PARAMS
from engine.execution.leverage_manager import LeverageManager

console = Console()

# ---------------------------------------------------------------------------
# Configuration globale
# ---------------------------------------------------------------------------

SYMBOLS_YF = [
    "BTC-USD", "ETH-USD", "SOL-USD",
    "BNB-USD", "AVAX-USD", "ADA-USD", "LINK-USD",
    "XRP-USD", "DOT-USD", "ATOM-USD", "LTC-USD",
]
SYMBOL_NAMES = {
    "BTC-USD": "BTC/USDT", "ETH-USD": "ETH/USDT", "SOL-USD": "SOL/USDT",
    "BNB-USD": "BNB/USDT", "AVAX-USD": "AVAX/USDT", "ADA-USD": "ADA/USDT",
    "LINK-USD": "LINK/USDT", "XRP-USD": "XRP/USDT", "DOT-USD": "DOT/USDT",
    "ATOM-USD": "ATOM/USDT", "LTC-USD": "LTC/USDT",
}

INITIAL_CAPITAL   = 50.0
INTERVAL          = "1h"
CANDLE_HOURS      = 1
PERIOD            = "2y"
WARMUP            = 210
COMMISSION        = 0.0004
SLIPPAGE          = 0.0005
DAILY_LOSS_LIMIT  = 0.10
CURRENCY          = "€"

# ---- Types de trades : risk, TP, SL mult, levier ----
RISK_ULTRA     = 0.035
RISK_HC        = 0.025
RISK_BO        = 0.025   # 2.5% : +25% EV par breakout
RISK_PB        = 0.025

TP_ULTRA       = 5.0
TP_HC          = 4.0
TP_BO          = 12.0   # Restauré à la valeur v3 (12:1) — +52% EV par trade breakout
TP_PB          = 3.5

SL_ULTRA       = 1.2
SL_HC          = 1.2
SL_BO          = 1.0
SL_PB          = 1.2

LEV_ULTRA      = 3
LEV_HC         = 3
LEV_BO         = 2
LEV_PB         = 3

# ---- Seuils de score ----
SCORE_ULTRA    = 80
HC_ENABLED     = False  # HC désactivé
ULTRA_ENABLED  = False  # ULTRA désactivé : perd de l'argent + bloque les BREAKOUT
SCORE_HC       = 65
SCORE_BO_MIN   = 70    # Relevé 42→70 : 17% WR vs 12% → +200€ (efficiency table)
SCORE_PB_MIN   = 42

# ---- Filtres anti-sur-trading ----
# PAS de MIN_BAR_GAP universel : BREAKOUT a son propre cooldown (BO_COOLDOWN_H)
# PULLBACK est naturellement filtré par MTF + régime
MIN_BAR_GAP    = 0    # désactivé — chaque type a son propre mécanisme
SCORE_FRESH_WINDOW = 6

# ---- BB Squeeze ----
BB_SQUEEZE_WINDOW  = 50
BB_SQUEEZE_PCT     = 0.15
VOL_SURGE_MIN      = 3.2
ADX_RISE_MIN_BO    = 3.0
MIN_ADX_BO         = 16
MIN_SQUEEZE_BARS   = 3
BO_BODY_PCT_MIN    = 0.45
BO_COOLDOWN_H      = 8

# ---- EMA9 Pullback ----
MIN_ADX_PULLBACK   = 25


# ---------------------------------------------------------------------------
# Téléchargement
# ---------------------------------------------------------------------------

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
    df_d = df.resample("1D").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    c = df_d["close"]
    df_d["ema9"]   = _ema(c, 9)
    df_d["ema21"]  = _ema(c, 21)
    df_d["ema50"]  = _ema(c, 50)
    df_d["ema200"] = _ema(c, 200)
    return df_d


def resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    """Resample 1h → 4h et calcule EMA9/EMA21."""
    df_4h = df.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    c = df_4h["close"]
    df_4h["ema9"]  = _ema(c, 9)
    df_4h["ema21"] = _ema(c, 21)
    return df_4h


# ---------------------------------------------------------------------------
# Helpers MTF
# ---------------------------------------------------------------------------

def _mtf_daily_check(action: str, df_daily: pd.DataFrame, ts) -> bool:
    """Daily MTF alignment check."""
    try:
        past = df_daily[df_daily.index.normalize() <= pd.Timestamp(ts).normalize()]
        if len(past) < 50:
            return False
        last = past.iloc[-1]
        def sv(col):
            v = last.get(col)
            if v is None: return None
            try: f = float(v); return None if math.isnan(f) else f
            except: return None
        e9, e21, e50, e200 = sv("ema9"), sv("ema21"), sv("ema50"), sv("ema200")
        price = float(last["close"])
        if None in (e9, e21, e50, e200):
            return False
        if action == "BUY":  return bool(price > e50 > e200 and e9 > e21)
        if action == "SELL": return bool(price < e50 < e200 and e9 < e21)
        return False
    except Exception:
        return False


def _mtf_4h_check(action: str, df_4h: pd.DataFrame, ts) -> bool:
    """4h MTF alignment check."""
    try:
        past = df_4h[df_4h.index <= pd.Timestamp(ts)]
        if len(past) < 10:
            return False
        last = past.iloc[-1]
        def sv(col):
            v = last.get(col)
            if v is None: return None
            try: f = float(v); return None if math.isnan(f) else f
            except: return None
        e9, e21 = sv("ema9"), sv("ema21")
        if None in (e9, e21):
            return False
        if action == "BUY":  return bool(e9 > e21)
        if action == "SELL": return bool(e9 < e21)
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 7-Signal Prediction Engine
# ---------------------------------------------------------------------------

def _compute_signals(
    df: pd.DataFrame,
    i: int,
    adx_val: float,
    di_plus: float,
    di_minus: float,
) -> Tuple[int, int]:
    """
    Calcule buy_score et sell_score (0-100 chacun) selon les 7 signaux pondérés.

    Signal 1: EMA Ribbon       (20 pts)
    Signal 2: MACD Momentum    (15 pts)
    Signal 3: RSI Zone         (10 pts)
    Signal 4: VWAP Position    (15 pts)
    Signal 5: Stochastic Dir.  (10 pts)
    Signal 6: OBV Trend        (15 pts)
    Signal 7: ADX Directionnel (15 pts)

    Retourne (buy_score, sell_score).
    """
    buy_score  = 0
    sell_score = 0

    last = df.iloc[i]

    def _fget(col: str, default: float = 0.0) -> float:
        v = last.get(col, default)
        if v is None:
            return default
        try:
            f = float(v)
            return default if math.isnan(f) else f
        except (TypeError, ValueError):
            return default

    price     = _fget("close", 1.0)
    ema9      = _fget("ema9",  price)
    ema21     = _fget("ema21", price)
    ema50     = _fget("ema50", price)
    ema200    = _fget("ema200", price)
    rsi_v     = _fget("rsi", 50.0)
    macd_hist = _fget("macd_hist", 0.0)
    macd_hist_slope = _fget("macd_hist_slope", 0.0)
    vwap_v    = _fget("vwap", price)
    stoch_k   = _fget("stoch_k", 50.0)
    stoch_d   = _fget("stoch_d", 50.0)
    obv_slope = _fget("obv_slope", 0.0)

    # --- Signal 1 : EMA Ribbon (20 pts) ---
    # BUY  : ema9>ema21 AND ema21>ema50 AND ema50>ema200 AND price>ema21 (3/4 conditions)
    # SELL : ema9<ema21 AND ema21<ema50 AND ema50<ema200 AND price<ema21 (3/4 conditions)
    if ema9 > 0 and ema21 > 0 and ema50 > 0 and ema200 > 0:
        buy_ribbon_conds  = sum([
            ema9 > ema21,
            ema21 > ema50,
            ema50 > ema200,
            price > ema21,
        ])
        sell_ribbon_conds = sum([
            ema9 < ema21,
            ema21 < ema50,
            ema50 < ema200,
            price < ema21,
        ])
        if buy_ribbon_conds >= 3:
            buy_score  += 20
        if sell_ribbon_conds >= 3:
            sell_score += 20

    # --- Signal 2 : MACD Momentum (15 pts) ---
    if macd_hist > 0 and macd_hist_slope > 0:
        buy_score  += 15
    elif macd_hist < 0 and macd_hist_slope < 0:
        sell_score += 15

    # --- Signal 3 : RSI Zone (10 pts) ---
    if 50 <= rsi_v <= 72:
        buy_score  += 10
    elif 28 <= rsi_v <= 50:
        sell_score += 10

    # --- Signal 4 : VWAP Position (15 pts) ---
    if vwap_v > 0:
        if price > vwap_v * 1.0005:
            buy_score  += 15
        elif price < vwap_v * 0.9995:
            sell_score += 15

    # --- Signal 5 : Stochastic Direction (10 pts) ---
    if stoch_k > stoch_d and stoch_k < 75:
        buy_score  += 10
    elif stoch_k < stoch_d and stoch_k > 25:
        sell_score += 10

    # --- Signal 6 : OBV Trend (15 pts) ---
    if obv_slope > 0:
        buy_score  += 15
    elif obv_slope < 0:
        sell_score += 15

    # --- Signal 7 : ADX Directionnel (15 pts) ---
    if adx_val >= 18:
        if di_plus > di_minus:
            buy_score  += 15
        elif di_minus > di_plus:
            sell_score += 15

    return int(min(buy_score, 100)), int(min(sell_score, 100))


# ---------------------------------------------------------------------------
# BB Squeeze Breakout Detection
# ---------------------------------------------------------------------------

def _bb_squeeze_breakout(
    df: pd.DataFrame,
    i: int,
    adx_val: float,
    adx_series: pd.Series,
) -> Tuple[bool, Optional[str]]:
    """
    Détecte un breakout de compression Bollinger.
    Retourne (is_breakout, direction).
    """
    if i < BB_SQUEEZE_WINDOW + 5:
        return False, None

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
    except (TypeError, ValueError, KeyError):
        return False, None

    if bb_upper <= 0 or bb_lower <= 0 or bb_mid <= 0:
        return False, None

    # ADX minimum
    if adx_val < MIN_ADX_BO:
        return False, None

    # BBW columns requises
    if "bbw" not in df.columns or "bbw_q15" not in df.columns:
        return False, None

    cur_bbw        = float(last.get("bbw", 1.0) or 1.0)
    q15_threshold  = float(last.get("bbw_q15", 1.0) or 1.0)
    recent_slice   = df.iloc[max(0, i - 8):i]
    if len(recent_slice) < MIN_SQUEEZE_BARS:
        return False, None

    min_bbw_recent = float(recent_slice["bbw"].min())

    # Compression passée
    if min_bbw_recent > q15_threshold * 1.05:
        return False, None

    # Décompression active
    if cur_bbw < min_bbw_recent * 1.15:
        return False, None

    # Comptage barres en squeeze
    bbw_vals = recent_slice["bbw"].values
    q15_vals = recent_slice["bbw_q15"].values
    n_squeezed = int(np.sum(bbw_vals < q15_vals * 1.05))
    if n_squeezed < MIN_SQUEEZE_BARS:
        return False, None

    # Volume explosion
    if vol_ratio < VOL_SURGE_MIN:
        return False, None

    # ADX accélération
    if i >= 5 and not np.isnan(adx_series.iloc[i - 5]):
        adx_5 = float(adx_series.iloc[i - 5])
        if adx_val < adx_5 + ADX_RISE_MIN_BO:
            return False, None
    else:
        return False, None

    # Corps de bougie fort
    rng  = high_p - low_p
    body = abs(price - open_p)
    if rng > 0 and body / rng < BO_BODY_PCT_MIN:
        return False, None

    # Direction du breakout
    if price > bb_upper * 1.001 and price > open_p:
        return True, "BUY"
    if price < bb_lower * 0.999 and price < open_p:
        return True, "SELL"

    return False, None


# ---------------------------------------------------------------------------
# EMA9 Pullback Detection
# ---------------------------------------------------------------------------

def _ema9_pullback(
    df: pd.DataFrame,
    i: int,
    regime_val: str,
    adx_val: float,
) -> Tuple[bool, Optional[str]]:
    """
    Rebond sur mèche EMA9 en tendance forte.
    Requiert ADX >= 25, RSI 38-62, vol 1.2×, body 40%.
    """
    if i < 2 or adx_val < MIN_ADX_PULLBACK:
        return False, None

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
    except (TypeError, ValueError, KeyError):
        return False, None

    if ema9 <= 0 or ema21 <= 0:
        return False, None

    body     = abs(price - open_p)
    rng      = high_p - low_p
    body_pct = body / rng if rng > 0 else 0
    ema9_5   = float(df.iloc[max(0, i - 5)].get("ema9", ema9) or ema9)

    if regime_val == "bull_trend":
        if not (ema9 > ema21 > 0):          return False, None
        if low_p > ema9 * 1.002:            return False, None
        if price <= open_p:                  return False, None
        if price <= ema9:                    return False, None
        if price > ema9 * 1.02:             return False, None
        if rsi_v < 38 or rsi_v > 62:        return False, None
        if vol_ratio < 1.2:                  return False, None
        if body_pct < 0.40:                  return False, None
        if ema9 < ema9_5 * 1.001:           return False, None
        return True, "BUY"

    elif regime_val == "bear_trend":
        if not (ema9 < ema21) or ema9 <= 0: return False, None
        if high_p < ema9 * 0.998:           return False, None
        if price >= open_p:                  return False, None
        if price >= ema9:                    return False, None
        if price < ema9 * 0.98:             return False, None
        if rsi_v < 38 or rsi_v > 62:        return False, None
        if vol_ratio < 1.2:                  return False, None
        if body_pct < 0.40:                  return False, None
        if ema9 > ema9_5 * 0.999:           return False, None
        return True, "SELL"

    return False, None


# ---------------------------------------------------------------------------
# Trade dataclass
# ---------------------------------------------------------------------------

@dataclass
class PaperTrade:
    symbol:           str
    side:             str
    entry_idx:        int
    exit_idx:         int
    entry_price:      float
    exit_price:       float
    margin_eur:       float
    leverage:         int
    pnl_eur:          float
    pnl_pct:          float
    exit_reason:      str
    score:            float
    regime:           str
    candles_held:     int
    entry_ts:         object = None
    trade_type:       str    = "pullback_quality"  # ultra | high_conv | breakout_premium | pullback_quality
    prediction_score: float  = 0.0
    mtf_aligned:      bool   = False


# ---------------------------------------------------------------------------
# Signal contribution tracker
# ---------------------------------------------------------------------------

@dataclass
class SignalStats:
    """Suivi des contributions par signal."""
    fires_buy:  Dict[str, int] = field(default_factory=dict)
    fires_sell: Dict[str, int] = field(default_factory=dict)
    wins_buy:   Dict[str, int] = field(default_factory=dict)
    wins_sell:  Dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Simulateur v4
# ---------------------------------------------------------------------------

class PaperTraderV4:
    def __init__(self):
        self.cfg     = AppConfig()
        self.lev_mgr = LeverageManager()

    def run(self, df_raw: pd.DataFrame, yf_sym: str) -> List[PaperTrade]:
        prod_sym = SYMBOL_NAMES.get(yf_sym, yf_sym)
        cfg      = self.cfg

        # --- Indicateurs ---
        df       = compute_all(df_raw.copy(), cfg.strategy)
        df_daily = resample_daily(df)
        df_4h    = resample_4h(df)

        # --- Pré-calculs O(n) ---

        # BB Width
        if "bb_upper" in df.columns and "bb_lower" in df.columns and "bb_mid" in df.columns:
            df["bbw"] = ((df["bb_upper"] - df["bb_lower"]) /
                         df["bb_mid"].replace(0, np.nan)).fillna(1.0)
        else:
            bb_p = 20; bb_k = 2.0
            df["bb_mid"]   = df["close"].rolling(bb_p).mean()
            df["bb_upper"] = df["bb_mid"] + bb_k * df["close"].rolling(bb_p).std()
            df["bb_lower"] = df["bb_mid"] - bb_k * df["close"].rolling(bb_p).std()
            df["bbw"]      = ((df["bb_upper"] - df["bb_lower"]) /
                               df["bb_mid"].replace(0, np.nan)).fillna(1.0)

        # BBW quantile 15 sur fenêtre glissante de 50 barres
        df["bbw_q15"] = df["bbw"].rolling(BB_SQUEEZE_WINDOW).quantile(BB_SQUEEZE_PCT).fillna(df["bbw"])

        # ADX, DI+, DI- pré-calculés
        adx_series, di_p_series, di_m_series = _compute_adx(df)

        # MACD histogram slope
        df["macd_hist_slope"] = df["macd_hist"].diff().fillna(0)

        # OBV 5-bar slope
        df["obv_slope"] = df["obv"].diff(5).fillna(0)

        # Score pré-calculé (vectorisé) pour détection de "signal frais"
        # On stocke buy_score et sell_score pour chaque barre
        _adx_arr  = adx_series.values
        _dip_arr  = di_p_series.values
        _dim_arr  = di_m_series.values
        _close    = df["close"].values
        _ema9v    = df["ema9"].values
        _ema21v   = df["ema21"].values
        _ema50v   = df["ema50"].values
        _ema200v  = df["ema200"].values
        _rsiv     = df["rsi"].fillna(50).values
        _macdh    = df["macd_hist"].fillna(0).values
        _macds    = df["macd_hist_slope"].fillna(0).values
        _vwapv    = df["vwap"].fillna(df["close"]).values
        _stochk   = df["stoch_k"].fillna(50).values
        _stochd   = df["stoch_d"].fillna(50).values
        _obvsl    = df["obv_slope"].fillna(0).values

        n_bars = len(df)
        _buy_sc  = np.zeros(n_bars, dtype=np.int16)
        _sell_sc = np.zeros(n_bars, dtype=np.int16)
        for _ii in range(n_bars):
            _bs, _ss = 0, 0
            _p   = _close[_ii]
            _e9  = _ema9v[_ii]  or _p
            _e21 = _ema21v[_ii] or _p
            _e50 = _ema50v[_ii] or _p
            _e200= _ema200v[_ii]or _p
            _rb  = int(_e9>_e21)+int(_e21>_e50)+int(_e50>_e200)+int(_p>_e21)
            _rs  = int(_e9<_e21)+int(_e21<_e50)+int(_e50<_e200)+int(_p<_e21)
            if _rb >= 3: _bs += 20
            if _rs >= 3: _ss += 20
            _mh = _macdh[_ii]; _ms = _macds[_ii]
            if _mh > 0 and _ms > 0: _bs += 15
            elif _mh < 0 and _ms < 0: _ss += 15
            _r = _rsiv[_ii]
            if 50 <= _r <= 72: _bs += 10
            elif 28 <= _r <= 50: _ss += 10
            _vw = _vwapv[_ii] or _p
            if _vw > 0:
                if _p > _vw * 1.0005: _bs += 15
                elif _p < _vw * 0.9995: _ss += 15
            _sk = _stochk[_ii]; _sd = _stochd[_ii]
            if _sk > _sd and _sk < 75: _bs += 10
            elif _sk < _sd and _sk > 25: _ss += 10
            _ov = _obvsl[_ii]
            if _ov > 0: _bs += 15
            elif _ov < 0: _ss += 15
            _adxv = float(_adx_arr[_ii]) if not np.isnan(_adx_arr[_ii]) else 0.0
            if _adxv >= 18:
                _dpv = float(_dip_arr[_ii]) if not np.isnan(_dip_arr[_ii]) else 0.0
                _dmv = float(_dim_arr[_ii]) if not np.isnan(_dim_arr[_ii]) else 0.0
                if _dpv > _dmv: _bs += 15
                elif _dmv > _dpv: _ss += 15
            _buy_sc[_ii]  = min(_bs, 100)
            _sell_sc[_ii] = min(_ss, 100)

        def _fast_regime(idx: int) -> Regime:
            row    = df.iloc[idx]
            price  = float(row.get("close", 1) or 1)
            ema50  = float(row.get("ema50",  price) or price)
            ema200 = float(row.get("ema200", price) or price)
            atr_v  = float(row.get("atr", price * 0.01) or price * 0.01)
            atr_pct = atr_v / price * 100 if price > 0 else 1.0
            adx_v  = float(adx_series.iloc[idx])  if not np.isnan(adx_series.iloc[idx])  else 20.0
            di_p_v = float(di_p_series.iloc[idx]) if not np.isnan(di_p_series.iloc[idx]) else 0.0
            di_m_v = float(di_m_series.iloc[idx]) if not np.isnan(di_m_series.iloc[idx]) else 0.0
            if atr_pct > 3.5:    return Regime.HIGH_VOL
            if adx_v > 20:
                if di_p_v > di_m_v and price > ema50 and ema50 > ema200: return Regime.BULL_TREND
                if di_m_v > di_p_v and price < ema50 and ema50 < ema200: return Regime.BEAR_TREND
            return Regime.RANGING

        # Caches MTF
        mtf_daily_cache: Dict[str, bool] = {}
        mtf_4h_cache:    Dict[str, bool] = {}

        # Cooldown breakout
        bo_cooldown_until: Optional[pd.Timestamp] = None

        # Anti-churning: barre de la dernière entrée (toutes stratégies confondues)
        last_entry_bar: int = -MIN_BAR_GAP - 1


        trades: List[PaperTrade] = []
        n = len(df)

        cash          = INITIAL_CAPITAL
        in_pos        = False
        pos: dict     = {}
        partial_taken = False
        day_start_eq  = INITIAL_CAPITAL
        current_day   = None
        halted        = False

        for i in range(WARMUP, n):
            row   = df.iloc[i]
            price = float(row["close"])
            ts    = df.index[i]
            atr_raw = row.get("atr", float("nan"))
            atr_v = float(atr_raw) if (atr_raw is not None and not pd.isna(atr_raw)) else price * 0.02

            # --- Circuit-breaker journalier ---
            day_key = str(ts)[:10]
            if day_key != current_day:
                current_day  = day_key
                day_start_eq = cash + (pos.get("margin_eur", 0) if in_pos else 0)
                halted = False
            if not in_pos and not halted:
                if day_start_eq > 0 and (day_start_eq - cash) / day_start_eq >= DAILY_LOSS_LIMIT:
                    halted = True

            # --- Trailing stop ---
            if in_pos and not math.isnan(pos.get("trail", float("nan"))):
                if pos["side"] == "long":
                    nt = price - atr_v * 0.5
                    if nt > pos["trail"]: pos["trail"] = nt
                else:
                    nt = price + atr_v * 0.5
                    if nt < pos["trail"]: pos["trail"] = nt

            # --- Gestion des sorties ---
            if in_pos:
                side   = pos["side"]
                reason = None

                if side == "long"  and price <= pos["liq"]: reason = "liquidation"
                elif side == "short" and price >= pos["liq"]: reason = "liquidation"

                if not partial_taken and reason is None:
                    if side == "long"  and price >= pos["partial_tp"]:
                        partial_taken = True; pos["sl"] = pos["entry"]
                    elif side == "short" and price <= pos["partial_tp"]:
                        partial_taken = True; pos["sl"] = pos["entry"]

                if reason is None:
                    if side == "long":
                        if price <= pos["sl"]:                reason = "stop_loss"
                        elif price <= pos.get("trail", -1):   reason = "trailing_stop"
                        elif price >= pos["tp"]:              reason = "take_profit"
                    else:
                        if price >= pos["sl"]:                reason = "stop_loss"
                        elif price >= pos.get("trail", 1e18): reason = "trailing_stop"
                        elif price <= pos["tp"]:              reason = "take_profit"

                if reason:
                    if reason == "liquidation":
                        pnl_eur = -pos["margin_eur"]
                        exit_p  = pos["liq"]
                    else:
                        slip    = (1 - SLIPPAGE) if side == "long" else (1 + SLIPPAGE)
                        exit_p  = price * slip
                        raw     = (exit_p - pos["entry"]) * pos["qty"] if side == "long" \
                                  else (pos["entry"] - exit_p) * pos["qty"]
                        pnl_eur = raw - pos["qty"] * exit_p * COMMISSION
                        cash   += pos["margin_eur"] + pnl_eur

                    pnl_pct = pnl_eur / pos["margin_eur"] * 100 if pos["margin_eur"] > 0 else 0.0
                    trades.append(PaperTrade(
                        symbol=prod_sym, side=side,
                        entry_idx=pos["idx"], exit_idx=i,
                        entry_price=pos["entry"], exit_price=exit_p,
                        margin_eur=round(pos["margin_eur"], 4),
                        leverage=pos["leverage"],
                        pnl_eur=round(pnl_eur, 4), pnl_pct=round(pnl_pct, 3),
                        exit_reason=reason, score=pos["score"], regime=pos["regime"],
                        candles_held=i - pos["idx"],
                        entry_ts=pos.get("entry_ts"),
                        trade_type=pos.get("trade_type", "pullback_quality"),
                        prediction_score=pos.get("prediction_score", 0.0),
                        mtf_aligned=pos.get("mtf_aligned", False),
                    ))
                    # Cooldown après perte sur breakout
                    if pnl_eur < 0 and pos.get("trade_type") == "breakout_premium":
                        bo_cooldown_until = ts + pd.Timedelta(hours=BO_COOLDOWN_H)
                    in_pos = False; partial_taken = False
                    continue

            if in_pos or halted or cash < 0.5:
                continue

            # ================================================================
            # SÉLECTION DE L'ENTRÉE — Moteur de Prédiction v4
            # ================================================================

            # ADX / DI courants
            adx_i   = float(adx_series.iloc[i])   if not np.isnan(adx_series.iloc[i])   else 0.0
            di_p_i  = float(di_p_series.iloc[i])  if not np.isnan(di_p_series.iloc[i])  else 0.0
            di_m_i  = float(di_m_series.iloc[i])  if not np.isnan(di_m_series.iloc[i])  else 0.0

            # Anti-churning per-type via cooldowns (global bar gap désactivé)

            # Score prédictif (7 signaux) — utiliser le tableau pré-calculé
            buy_score  = int(_buy_sc[i])
            sell_score = int(_sell_sc[i])
            pred_score = max(buy_score, sell_score)

            # --- Fraîcheur du signal : le score doit être en montée sur les 3 dernières barres ---
            # Évite d'entrer au milieu d'une tendance établie, attend un nouvel alignement
            if i >= SCORE_FRESH_WINDOW:
                prev_buy  = int(max(_buy_sc[max(0, i-SCORE_FRESH_WINDOW):i]))
                prev_sell = int(max(_sell_sc[max(0, i-SCORE_FRESH_WINDOW):i]))
                # Le score actuel doit être >= max précédent (en montée ou stable au sommet)
                # Pour ULTRA : score doit être ≥ SCORE_ULTRA, et n'était pas ≥ SCORE_ULTRA avant
                score_fresh_ultra = (buy_score >= SCORE_ULTRA and
                                     max(_buy_sc[max(0,i-SCORE_FRESH_WINDOW):i]) < SCORE_ULTRA) or \
                                    (sell_score >= SCORE_ULTRA and
                                     max(_sell_sc[max(0,i-SCORE_FRESH_WINDOW):i]) < SCORE_ULTRA)
                score_fresh_hc    = (buy_score >= SCORE_HC and
                                     max(_buy_sc[max(0,i-SCORE_FRESH_WINDOW):i]) < SCORE_HC) or \
                                    (sell_score >= SCORE_HC and
                                     max(_sell_sc[max(0,i-SCORE_FRESH_WINDOW):i]) < SCORE_HC)
            else:
                score_fresh_ultra = buy_score >= SCORE_ULTRA or sell_score >= SCORE_ULTRA
                score_fresh_hc    = buy_score >= SCORE_HC    or sell_score >= SCORE_HC

            # ---- PRIORITÉ 1 : ULTRA TRADE (désactivé — ULTRA_ENABLED=False) ----
            if ULTRA_ENABLED and score_fresh_ultra and (buy_score >= SCORE_ULTRA or sell_score >= SCORE_ULTRA):
                eff_action = "BUY" if buy_score >= sell_score else "SELL"
                # MTF daily requis
                mtf_daily_key = f"{eff_action}_{day_key}"
                if mtf_daily_key not in mtf_daily_cache:
                    mtf_daily_cache[mtf_daily_key] = _mtf_daily_check(eff_action, df_daily, ts)
                if not mtf_daily_cache[mtf_daily_key]:
                    continue
                # MTF 4h requis
                h4_key = f"{eff_action}_{ts.date()}_{ts.hour // 4}"
                if h4_key not in mtf_4h_cache:
                    mtf_4h_cache[h4_key] = _mtf_4h_check(eff_action, df_4h, ts)
                if not mtf_4h_cache[h4_key]:
                    continue
                risk        = RISK_ULTRA
                sl_mult     = SL_ULTRA
                tp_rr       = TP_ULTRA
                max_lev     = LEV_ULTRA
                trade_type  = "ultra"
                final_score = pred_score
                mtf_aligned = True

            # ---- PRIORITÉ 2 : HIGH CONVICTION (désactivé — HC_ENABLED=False) ----
            elif HC_ENABLED and score_fresh_hc and (buy_score >= SCORE_HC or sell_score >= SCORE_HC):
                eff_action = "BUY" if buy_score >= sell_score else "SELL"
                # MTF daily requis (obligatoire pour HC)
                mtf_daily_key = f"{eff_action}_{day_key}"
                if mtf_daily_key not in mtf_daily_cache:
                    mtf_daily_cache[mtf_daily_key] = _mtf_daily_check(eff_action, df_daily, ts)
                if not mtf_daily_cache[mtf_daily_key]:
                    continue
                risk        = RISK_HC
                sl_mult     = SL_HC
                tp_rr       = TP_HC
                max_lev     = LEV_HC
                trade_type  = "high_conv"
                final_score = pred_score
                mtf_aligned = True

            # ---- PRIORITÉ 3 : BREAKOUT PREMIUM (BB squeeze + score >= 40) ----
            else:
                in_cooldown = (bo_cooldown_until is not None and ts < bo_cooldown_until)
                is_bo, bo_action = (False, None) if in_cooldown else _bb_squeeze_breakout(
                    df, i, adx_i, adx_series
                )

                if is_bo and bo_action:
                    bo_dir_score = buy_score if bo_action == "BUY" else sell_score
                    if bo_dir_score >= SCORE_BO_MIN:
                        eff_action  = bo_action
                        risk        = RISK_BO
                        sl_mult     = SL_BO
                        tp_rr       = TP_BO
                        max_lev     = LEV_BO
                        trade_type  = "breakout_premium"
                        final_score = pred_score
                        mtf_aligned = True
                    else:
                        # Breakout mais score insuffisant → essayer pullback
                        is_bo = False
                        bo_action = None

                if not is_bo:
                    # ---- PRIORITÉ 4 : PULLBACK QUALITY ----
                    try:
                        regime = _fast_regime(i)
                    except Exception:
                        continue

                    if regime not in (Regime.BULL_TREND, Regime.BEAR_TREND):
                        continue

                    is_pb, pb_action = _ema9_pullback(df, i, regime.value, adx_i)

                    if not (is_pb and pb_action):
                        continue

                    pb_dir_score = buy_score if pb_action == "BUY" else sell_score
                    if pb_dir_score < SCORE_PB_MIN:
                        continue

                    # MTF daily requis
                    mtf_daily_key = f"{pb_action}_{day_key}"
                    if mtf_daily_key not in mtf_daily_cache:
                        mtf_daily_cache[mtf_daily_key] = _mtf_daily_check(pb_action, df_daily, ts)
                    if not mtf_daily_cache[mtf_daily_key]:
                        continue

                    # MTF 4h requis
                    h4_key = f"{pb_action}_{ts.date()}_{ts.hour // 4}"
                    if h4_key not in mtf_4h_cache:
                        mtf_4h_cache[h4_key] = _mtf_4h_check(pb_action, df_4h, ts)
                    if not mtf_4h_cache[h4_key]:
                        continue

                    eff_action  = pb_action
                    risk        = RISK_PB
                    sl_mult     = SL_PB
                    tp_rr       = TP_PB
                    max_lev     = LEV_PB
                    trade_type  = "pullback_quality"
                    final_score = pred_score
                    mtf_aligned = True

            # ================================================================
            # Calcul de la position
            # ================================================================

            lev     = min(self.lev_mgr.get_leverage(final_score, "HIGH"), max_lev)
            sl_dist = atr_v * sl_mult
            tp_dist = sl_dist * tp_rr

            if eff_action == "BUY":
                entry_p    = price * (1 + SLIPPAGE)
                sl, tp     = entry_p - sl_dist, entry_p + tp_dist
                partial_tp = entry_p + (tp - entry_p) * 0.55
                liq_p      = self.lev_mgr.liquidation_price(entry_p, lev, "long")
                sl         = max(sl, liq_p * 1.001)
                side       = "long"
            else:
                entry_p    = price * (1 - SLIPPAGE)
                sl, tp     = entry_p + sl_dist, entry_p - tp_dist
                partial_tp = entry_p - (entry_p - tp) * 0.55
                liq_p      = self.lev_mgr.liquidation_price(entry_p, lev, "short")
                sl         = min(sl, liq_p * 0.999)
                side       = "short"

            sl_distance = abs(entry_p - sl) or entry_p * 0.02
            risk_eur    = cash * risk
            qty         = risk_eur / sl_distance
            margin_eur  = qty * entry_p / lev

            if margin_eur > cash * 0.95:
                margin_eur = cash * 0.95
                qty        = margin_eur * lev / entry_p

            entry_comm = qty * entry_p * COMMISSION
            total_cost = margin_eur + entry_comm

            if qty <= 1e-12 or total_cost > cash:
                continue

            cash  -= total_cost
            in_pos = True; partial_taken = False
            last_entry_bar = i
            pos = {
                "side": side, "entry": entry_p, "qty": qty,
                "margin_eur": margin_eur, "liq": liq_p,
                "sl": sl, "tp": tp, "partial_tp": partial_tp,
                "trail": float("nan"),
                "leverage": lev, "score": final_score,
                "idx": i,
                "regime": (trade_type if trade_type in ("ultra", "high_conv", "breakout_premium")
                           else regime.value if trade_type == "pullback_quality" else "trend"),
                "entry_ts": ts,
                "trade_type": trade_type,
                "prediction_score": float(pred_score),
                "mtf_aligned": mtf_aligned,
            }

        # Fermeture en fin de données
        if in_pos:
            fp     = float(df.iloc[-1]["close"])
            slip   = (1 - SLIPPAGE) if pos["side"] == "long" else (1 + SLIPPAGE)
            exit_p = fp * slip
            side   = pos["side"]
            raw    = (exit_p - pos["entry"]) * pos["qty"] if side == "long" \
                     else (pos["entry"] - exit_p) * pos["qty"]
            pnl_eur = raw - pos["qty"] * exit_p * COMMISSION
            pnl_pct = pnl_eur / pos["margin_eur"] * 100 if pos["margin_eur"] > 0 else 0.0
            trades.append(PaperTrade(
                symbol=prod_sym, side=side,
                entry_idx=pos["idx"], exit_idx=n - 1,
                entry_price=pos["entry"], exit_price=exit_p,
                margin_eur=round(pos["margin_eur"], 4), leverage=pos["leverage"],
                pnl_eur=round(pnl_eur, 4), pnl_pct=round(pnl_pct, 3),
                exit_reason="end_of_data", score=pos["score"], regime=pos["regime"],
                candles_held=n - 1 - pos["idx"],
                entry_ts=pos.get("entry_ts"),
                trade_type=pos.get("trade_type", "pullback_quality"),
                prediction_score=pos.get("prediction_score", 0.0),
                mtf_aligned=pos.get("mtf_aligned", False),
            ))
        return trades


# ---------------------------------------------------------------------------
# Métriques
# ---------------------------------------------------------------------------

def metrics(trades: List[PaperTrade], initial: float) -> dict:
    if not trades:
        return {}

    equity = initial
    curve  = [initial]
    for t in trades:
        if t.exit_reason == "liquidation":
            equity -= t.margin_eur
        else:
            equity += t.pnl_eur
        curve.append(equity)

    eq   = np.array(curve, dtype=float)
    ret  = (eq[-1] - initial) / initial * 100
    peak = np.maximum.accumulate(eq)
    dd   = (peak - eq) / np.where(peak == 0, 1, peak)
    mdd  = float(dd.max()) * 100

    rets   = np.diff(eq) / np.where(eq[:-1] == 0, 1, eq[:-1])
    sharpe = float(rets.mean() / rets.std() * np.sqrt(8760)) if rets.std() > 1e-10 else 0.0

    wins   = [t for t in trades if t.pnl_eur > 0]
    losses = [t for t in trades if t.pnl_eur <= 0]
    win_rate = len(wins) / len(trades) * 100
    gp   = sum(t.pnl_eur for t in wins)
    gl   = abs(sum(t.pnl_eur for t in losses)) or 1e-9
    pf   = min(gp / gl, 99.0)

    exit_counts: Dict[str, int] = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

    return {
        "total_trades":     len(trades),
        "win_rate":         round(win_rate, 1),
        "total_return_pct": round(ret, 2),
        "final_equity":     round(eq[-1], 2),
        "max_drawdown_pct": round(mdd, 2),
        "sharpe_ratio":     round(sharpe, 3),
        "profit_factor":    round(pf, 3),
        "avg_win_pct":      round(float(np.mean([t.pnl_pct for t in wins])),   2) if wins   else 0.0,
        "avg_loss_pct":     round(float(np.mean([t.pnl_pct for t in losses])), 2) if losses else 0.0,
        "avg_win_eur":      round(float(np.mean([t.pnl_eur for t in wins])),   4) if wins   else 0.0,
        "avg_loss_eur":     round(float(np.mean([t.pnl_eur for t in losses])), 4) if losses else 0.0,
        "avg_leverage":     round(float(np.mean([t.leverage for t in trades])), 2),
        "avg_candles":      round(float(np.mean([t.candles_held for t in trades])), 1),
        "wins":             len(wins),
        "losses":           len(losses),
        "liquidations":     len([t for t in trades if t.exit_reason == "liquidation"]),
        "longs":            len([t for t in trades if t.side == "long"]),
        "shorts":           len([t for t in trades if t.side == "short"]),
        "gross_profit_eur": round(gp, 4),
        "gross_loss_eur":   round(gl, 4),
        "equity_curve":     curve,
        "exit_counts":      exit_counts,
    }


def metrics_by_type(trades: List[PaperTrade], initial: float, type_name: str) -> dict:
    sub = [t for t in trades if t.trade_type == type_name]
    if not sub:
        return {}
    wins   = [t for t in sub if t.pnl_eur > 0]
    losses = [t for t in sub if t.pnl_eur <= 0]
    net    = sum(t.pnl_eur for t in sub)
    wr     = len(wins) / len(sub) * 100 if sub else 0.0
    avg_w  = float(np.mean([t.pnl_pct for t in wins]))   if wins   else 0.0
    avg_l  = float(np.mean([t.pnl_pct for t in losses])) if losses else 0.0
    avg_score = float(np.mean([t.prediction_score for t in sub])) if sub else 0.0
    return {
        "count": len(sub), "wins": len(wins), "losses": len(losses),
        "win_rate": round(wr, 1), "net_eur": round(net, 4),
        "avg_win_pct": round(avg_w, 2), "avg_loss_pct": round(avg_l, 2),
        "avg_score": round(avg_score, 1),
    }


# ---------------------------------------------------------------------------
# Rapport Rich
# ---------------------------------------------------------------------------

def print_report(all_trades: List[PaperTrade]):
    console.rule("[bold yellow]SKYN v4 — PREDICTION ENGINE COMPLET[/bold yellow]")
    console.print()

    m = metrics(all_trades, INITIAL_CAPITAL)
    if not m:
        console.print("[red]Aucun trade.[/red]")
        return

    ret    = m["total_return_pct"]
    final  = m["final_equity"]
    profit = final - INITIAL_CAPITAL
    color  = "green" if ret >= 0 else "red"

    # ---- Résultat global ----
    g = Table.grid(padding=(0, 3))
    g.add_row("[bold]Mise de départ[/bold]",  f"[white]{INITIAL_CAPITAL:.2f} {CURRENCY}[/white]")
    g.add_row("[bold]Capital final[/bold]",   f"[{color} bold]{final:.2f} {CURRENCY}[/{color} bold]")
    g.add_row("[bold]Profit net[/bold]",      f"[{color} bold]{profit:+.2f} {CURRENCY} ({ret:+.2f}%)[/{color} bold]")
    g.add_row("[bold]Drawdown max[/bold]",    f"[{'red' if m['max_drawdown_pct']>30 else 'yellow'}]{m['max_drawdown_pct']:.1f}%[/]")
    g.add_row("[bold]Sharpe[/bold]",          f"[cyan]{m['sharpe_ratio']:.3f}[/cyan]")
    g.add_row("[bold]Profit Factor[/bold]",   f"[cyan]{m['profit_factor']:.3f}[/cyan]")
    g.add_row("[bold]Win rate[/bold]",        f"[{'green' if m['win_rate']>=40 else 'yellow' if m['win_rate']>=30 else 'red'}]{m['win_rate']:.1f}%[/] ({m['wins']}W / {m['losses']}L)")
    g.add_row("[bold]Trades total[/bold]",    f"{m['total_trades']}  Long:{m['longs']} Court:{m['shorts']}")
    g.add_row("[bold]Liquidations[/bold]",    f"[{'green' if m['liquidations']==0 else 'red bold'}]{m['liquidations']}[/]")
    console.print(Panel(g, title="[bold]Resultat Global · 2 ans · Prediction Engine[/bold]", border_style="yellow", expand=False))
    console.print()

    # ---- Performance par type de trade ----
    type_labels = {
        "ultra":            ("ULTRA TRADE",       "bold magenta", 72),
        "high_conv":        ("HIGH CONVICTION",   "bold cyan",    55),
        "breakout_premium": ("BREAKOUT PREMIUM",  "bold yellow",  40),
        "pullback_quality": ("PULLBACK QUALITY",  "bold green",   45),
    }

    tt = Table(title="[bold]Performance par Type de Trade[/bold]", box=box.ROUNDED, border_style="cyan")
    for col in ["Type", "Trades", "Win%", "Score moy.", "Net (EUR)", "Gain moy/win"]:
        tt.add_column(col, justify="right")
    tt.columns[0].justify = "left"

    for ttype, (label, tcolor, thr) in type_labels.items():
        mt = metrics_by_type(all_trades, INITIAL_CAPITAL, ttype)
        if not mt:
            tt.add_row(f"[{tcolor}]{label}[/{tcolor}]", "0", "-", "-", "-", "-")
            continue
        cw  = "green" if mt["win_rate"] >= 40 else "yellow" if mt["win_rate"] >= 30 else "red"
        cn  = "green" if mt["net_eur"] > 0 else "red"
        tt.add_row(
            f"[{tcolor}]{label}[/{tcolor}]",
            str(mt["count"]),
            f"[{cw}]{mt['win_rate']:.0f}%[/{cw}]",
            f"[cyan]{mt['avg_score']:.0f}[/cyan]",
            f"[{cn}]{mt['net_eur']:+.2f}€[/{cn}]",
            f"{mt['avg_win_pct']:+.1f}% par win",
        )
    console.print(tt)
    console.print()

    # ---- Signal Contribution Table ----
    _print_signal_stats(all_trades)

    # ---- Breakdown mensuel ----
    monthly: Dict[str, list] = {}
    for t in all_trades:
        if t.entry_ts is not None:
            monthly.setdefault(str(t.entry_ts)[:7], []).append(t)

    if monthly:
        tm = Table(
            title="[bold]Breakdown Mensuel — Moteur v4[/bold]",
            box=box.ROUNDED, border_style="cyan",
        )
        for col in ["Mois", "Trades", "Win%", "Ultra/HC/BO/PB", "Net EUR", "Ret%", "Statut"]:
            tm.add_column(col, justify="right")
        tm.columns[0].justify = "left"

        running_eq = INITIAL_CAPITAL
        for key in sorted(monthly.keys()):
            mt2   = monthly[key]
            mp    = sum(t.pnl_eur for t in mt2)
            mw    = sum(1 for t in mt2 if t.pnl_eur > 0)
            wr    = mw / len(mt2) * 100 if mt2 else 0
            ret_m = mp / running_eq * 100 if running_eq > 0 else 0
            running_eq += mp
            n_u   = sum(1 for t in mt2 if t.trade_type == "ultra")
            n_h   = sum(1 for t in mt2 if t.trade_type == "high_conv")
            n_bo  = sum(1 for t in mt2 if t.trade_type == "breakout_premium")
            n_pb  = sum(1 for t in mt2 if t.trade_type == "pullback_quality")
            c     = "green" if mp > 0 else "red"
            cw2   = "green" if wr >= 50 else "yellow" if wr >= 35 else "red"
            if ret_m >= 200:  status = "[bold magenta]×3+ [/bold magenta]"
            elif ret_m >= 100: status = "[bold green]×2+ [/bold green]"
            elif ret_m >= 50:  status = "[green]×1.5+ [/green]"
            elif ret_m >= 20:  status = "[green]+20%+ v[/green]"
            elif ret_m >= 0:   status = "[yellow]+[/yellow]"
            else:               status = "[red]-[/red]"
            tm.add_row(
                key, str(len(mt2)),
                f"[{cw2}]{wr:.0f}%[/{cw2}]",
                f"[magenta]{n_u}[/magenta]/[cyan]{n_h}[/cyan]/[yellow]{n_bo}[/yellow]/[green]{n_pb}[/green]",
                f"[{c}]{mp:+.2f}€[/{c}]",
                f"[{c}]{ret_m:+.1f}%[/{c}]",
                status,
            )
        console.print(tm)
        console.print()

    # ---- Beta Test Window — 6 derniers mois ----
    _print_beta_test(all_trades)

    # ---- Courbe equity ----
    ec = m["equity_curve"]
    if len(ec) > 2:
        n_pts = min(70, len(ec))
        step  = max(1, len(ec) // n_pts)
        pts   = [ec[j * step] for j in range(n_pts)] + [ec[-1]]
        mn, mx = min(pts), max(pts)
        rng   = mx - mn or 1
        blocks = " ▁▂▃▄▅▆▇█"
        chart  = "".join(blocks[max(0, min(8, int((v - mn) / rng * 8)))] for v in pts)
        c = "green" if ec[-1] >= ec[0] else "red"
        console.print(Panel(
            f"[{c}]{chart}[/{c}]\n"
            f"  Depart: {ec[0]:.2f}€  ->  Fin: {ec[-1]:.2f}€  |  "
            f"Min: {mn:.2f}€  Max: {mx:.2f}€",
            title="Courbe d'Equity (50€ → ?)",
            border_style=c,
        ))
    console.print()

    # ---- Top/Worst trades ----
    sorted_t = sorted(all_trades, key=lambda x: x.pnl_eur, reverse=True)
    worst    = list(reversed(sorted_t[-15:]))
    type_icons = {
        "ultra":            "U",
        "high_conv":        "H",
        "breakout_premium": "B",
        "pullback_quality": "P",
    }
    for title_str, lst, bc in [
        ("Top 15 Meilleurs Trades", sorted_t[:15], "green"),
        ("Top 15 Pires Trades",     worst,          "red"),
    ]:
        tt2 = Table(title=title_str, box=box.SIMPLE, border_style=bc)
        for col in ["Sym", "Side", "Type", "Score", "Net EUR", "PnL%", "Lev", "Sortie", "Duree"]:
            tt2.add_column(col, justify="right" if col not in ["Sym", "Side", "Type", "Sortie"] else "left")
        for t in lst:
            c = "green" if t.pnl_eur > 0 else "red"
            tt2.add_row(
                t.symbol.split("/")[0], t.side,
                type_icons.get(t.trade_type, "?") + " " + t.trade_type[:5],
                f"[cyan]{t.prediction_score:.0f}[/cyan]",
                f"[{c}]{t.pnl_eur:+.2f}€[/{c}]",
                f"[{c}]{t.pnl_pct:+.1f}%[/{c}]",
                f"{t.leverage}x",
                t.exit_reason[:5],
                f"{t.candles_held * CANDLE_HOURS}h",
            )
        console.print(tt2)
        console.print()

    # ---- Projection ----
    total_days     = 730
    trades_per_day = m["total_trades"] / total_days
    daily_pnl      = profit / total_days
    console.print(Panel(
        f"Rythme observe : [cyan]{trades_per_day:.2f} trades/jour[/cyan]  ·  "
        f"[cyan]{daily_pnl:+.3f} {CURRENCY}/jour[/cyan]\n\n"
        f"  [bold]1 semaine[/bold] : {INITIAL_CAPITAL:.2f}€ → [{color}]{INITIAL_CAPITAL + daily_pnl*7:.2f}€[/{color}]\n"
        f"  [bold]1 mois[/bold]   : {INITIAL_CAPITAL:.2f}€ → [{color}]{INITIAL_CAPITAL + daily_pnl*30:.2f}€[/{color}]\n"
        f"  [bold]3 mois[/bold]   : {INITIAL_CAPITAL:.2f}€ → [{color}]{INITIAL_CAPITAL + daily_pnl*90:.2f}€[/{color}]\n\n"
        f"  [dim]* Projection lineaire — les mois de breakout depassent largement cette moyenne[/dim]",
        title="[bold]Projection (base : rythme observe sur 2 ans)[/bold]",
        border_style="cyan",
    ))
    console.print()
    console.rule("[bold yellow]FIN DU RAPPORT[/bold yellow]")


def _print_signal_stats(all_trades: List[PaperTrade]):
    """Affiche une table de contribution des signaux (proxy via score moyen par type)."""
    if not all_trades:
        return

    ts_table = Table(
        title="[bold]Analyse des Signaux — Distribution des Scores[/bold]",
        box=box.ROUNDED, border_style="blue",
    )
    for col in ["Type de Trade", "N", "Score moy.", "Score min", "Score max", "WR%"]:
        ts_table.add_column(col, justify="right")
    ts_table.columns[0].justify = "left"

    for ttype, label in [
        ("ultra",            "ULTRA TRADE"),
        ("high_conv",        "HIGH CONVICTION"),
        ("breakout_premium", "BREAKOUT PREMIUM"),
        ("pullback_quality", "PULLBACK QUALITY"),
    ]:
        sub = [t for t in all_trades if t.trade_type == ttype]
        if not sub:
            ts_table.add_row(label, "0", "-", "-", "-", "-")
            continue
        scores = [t.prediction_score for t in sub]
        wins   = [t for t in sub if t.pnl_eur > 0]
        wr     = len(wins) / len(sub) * 100
        cw     = "green" if wr >= 40 else "yellow" if wr >= 30 else "red"
        ts_table.add_row(
            label,
            str(len(sub)),
            f"[cyan]{np.mean(scores):.1f}[/cyan]",
            f"{min(scores):.0f}",
            f"{max(scores):.0f}",
            f"[{cw}]{wr:.0f}%[/{cw}]",
        )

    console.print(ts_table)
    console.print()

    # Score threshold effectiveness
    t_eff = Table(
        title="[bold]Efficacite des Seuils de Score[/bold]",
        box=box.SIMPLE, border_style="blue",
    )
    for col in ["Seuil", "Trades", "Win%", "Net EUR"]:
        t_eff.add_column(col, justify="right")

    for thr in [40, 50, 55, 60, 65, 70, 72, 80]:
        sub  = [t for t in all_trades if t.prediction_score >= thr]
        if not sub:
            continue
        wins = [t for t in sub if t.pnl_eur > 0]
        wr   = len(wins) / len(sub) * 100
        net  = sum(t.pnl_eur for t in sub)
        cw   = "green" if wr >= 40 else "yellow" if wr >= 30 else "red"
        cn   = "green" if net > 0 else "red"
        t_eff.add_row(
            f">= {thr}",
            str(len(sub)),
            f"[{cw}]{wr:.0f}%[/{cw}]",
            f"[{cn}]{net:+.2f}€[/{cn}]",
        )
    console.print(t_eff)
    console.print()


def _print_beta_test(all_trades: List[PaperTrade]):
    """Fenetre Beta Test — 6 derniers mois du backtest."""
    if not all_trades:
        return

    # Trouver max timestamp dans les trades
    ts_list = [t.entry_ts for t in all_trades if t.entry_ts is not None]
    if not ts_list:
        return

    max_ts  = max(ts_list)
    min_ts_beta = max_ts - pd.Timedelta(days=180)
    beta_trades = [t for t in all_trades if t.entry_ts is not None and t.entry_ts >= min_ts_beta]

    if not beta_trades:
        console.print("[yellow]Beta Test : aucun trade dans les 6 derniers mois.[/yellow]")
        return

    period_start = min(t.entry_ts for t in beta_trades)
    period_end   = max_ts

    # Calculer l'equity de départ pour la fenêtre beta
    # On recalcule depuis le debut pour trouver l'equity au début de la fenetre
    all_sorted = sorted(all_trades, key=lambda x: (x.entry_ts or pd.Timestamp.min))
    eq_start_beta = INITIAL_CAPITAL
    for t in all_sorted:
        if t.entry_ts is not None and t.entry_ts < min_ts_beta:
            if t.exit_reason == "liquidation":
                eq_start_beta -= t.margin_eur
            else:
                eq_start_beta += t.pnl_eur

    # Métrique beta
    bm = metrics(beta_trades, eq_start_beta)
    if not bm:
        return

    n_ultra = sum(1 for t in beta_trades if t.trade_type == "ultra")
    n_hc    = sum(1 for t in beta_trades if t.trade_type == "high_conv")
    n_bo    = sum(1 for t in beta_trades if t.trade_type == "breakout_premium")
    n_pb    = sum(1 for t in beta_trades if t.trade_type == "pullback_quality")

    beta_ret     = bm["total_return_pct"]
    beta_profit  = bm["final_equity"] - eq_start_beta
    achieved_x2  = beta_ret >= 100
    achieved_x3  = beta_ret >= 200

    x2_color  = "bold green" if achieved_x2  else "red"
    x3_color  = "bold magenta" if achieved_x3 else "dim"

    beta_text = (
        f"  Periode    : {str(period_start)[:10]} → {str(period_end)[:10]}\n"
        f"  Trades     : {len(beta_trades)}  "
        f"([magenta]{n_ultra} ultra[/magenta] / [cyan]{n_hc} hc[/cyan] / "
        f"[yellow]{n_bo} breakout[/yellow] / [green]{n_pb} pullback[/green])\n"
        f"  Capital de depart (beta) : {eq_start_beta:.2f}€\n"
        f"  Resultat   : [bold]{beta_profit:+.2f}€ ({beta_ret:+.1f}%)[/bold]\n"
        f"  Win Rate   : {bm['win_rate']:.1f}%  |  DD: {bm['max_drawdown_pct']:.1f}%  |  "
        f"Sharpe: {bm['sharpe_ratio']:.3f}\n\n"
        f"  ×2 atteint ?  [{x2_color}]{'OUI' if achieved_x2 else 'NON'} ({beta_ret:+.1f}%)[/{x2_color}]\n"
        f"  ×3 atteint ?  [{x3_color}]{'OUI' if achieved_x3 else 'NON'} ({beta_ret:+.1f}%)[/{x3_color}]"
    )

    console.print(Panel(
        beta_text,
        title="[bold yellow]Beta Test — Fenetre 6 Derniers Mois[/bold yellow]",
        border_style="yellow",
    ))
    console.print()

    # Comparaison mensuelle dans la fenêtre beta
    beta_monthly: Dict[str, list] = {}
    for t in beta_trades:
        if t.entry_ts is not None:
            beta_monthly.setdefault(str(t.entry_ts)[:7], []).append(t)

    if len(beta_monthly) > 1:
        tbm = Table(
            title="[bold]Beta Test — Breakdown Mensuel[/bold]",
            box=box.SIMPLE, border_style="yellow",
        )
        for col in ["Mois", "Trades", "Win%", "Net EUR", "Ret%", "Statut"]:
            tbm.add_column(col, justify="right")
        tbm.columns[0].justify = "left"

        run_eq = eq_start_beta
        for key in sorted(beta_monthly.keys()):
            mt3   = beta_monthly[key]
            mp    = sum(t.pnl_eur for t in mt3)
            mw    = sum(1 for t in mt3 if t.pnl_eur > 0)
            wr    = mw / len(mt3) * 100 if mt3 else 0
            ret_m = mp / run_eq * 100 if run_eq > 0 else 0
            run_eq += mp
            c     = "green" if mp > 0 else "red"
            cw2   = "green" if wr >= 50 else "yellow" if wr >= 35 else "red"
            if ret_m >= 200:   status = "[bold magenta]×3+[/bold magenta]"
            elif ret_m >= 100: status = "[bold green]×2+[/bold green]"
            elif ret_m >= 50:  status = "[green]×1.5+[/green]"
            elif ret_m >= 20:  status = "[green]+20%+[/green]"
            elif ret_m >= 0:   status = "[yellow]+[/yellow]"
            else:               status = "[red]-[/red]"
            tbm.add_row(
                key, str(len(mt3)),
                f"[{cw2}]{wr:.0f}%[/{cw2}]",
                f"[{c}]{mp:+.2f}€[/{c}]",
                f"[{c}]{ret_m:+.1f}%[/{c}]",
                status,
            )
        console.print(tbm)
        console.print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    n_syms = len(SYMBOLS_YF)
    console.rule(f"[bold yellow]SKYN v4 — PREDICTION ENGINE · 50€ · {n_syms} Symboles · 2 ans[/bold yellow]")
    active = []
    if ULTRA_ENABLED:
        active.append(f"  ULTRA      : score>={SCORE_ULTRA}  risk={RISK_ULTRA*100:.1f}%  TP {TP_ULTRA:.0f}:1  lev {LEV_ULTRA}×")
    if HC_ENABLED:
        active.append(f"  HIGH CONV  : score>={SCORE_HC}  risk={RISK_HC*100:.1f}%  TP {TP_HC:.0f}:1  lev {LEV_HC}×")
    active.append(f"  BREAKOUT   : BB squeeze + score>={SCORE_BO_MIN}  risk={RISK_BO*100:.1f}%  TP {TP_BO:.0f}:1  lev {LEV_BO}×")
    active.append(f"  PULLBACK   : EMA9 + score>={SCORE_PB_MIN} + MTF  risk={RISK_PB*100:.1f}%  TP {TP_PB:.1f}:1  lev {LEV_PB}×")
    console.print("\n".join(active))
    console.print()

    trader     = PaperTraderV4()
    all_trades: List[PaperTrade] = []

    console.print("[bold]Telechargement des donnees...[/bold]")
    data_map: Dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS_YF:
        console.print(f"  [cyan]v[/cyan] {sym}...", end="")
        df = download_data(sym)
        if df is not None:
            data_map[sym] = df
            console.print(f" [green]{len(df)} barres OK[/green]")
        else:
            console.print(f" [red]echec[/red]")

    if not data_map:
        console.print("[red]Aucune donnee.[/red]")
        return

    console.print()
    console.print("[bold]Simulation en cours...[/bold]")
    t_total = time.time()

    for sym, df_raw in data_map.items():
        console.print(f"  [cyan]>[/cyan] {SYMBOL_NAMES.get(sym, sym):<12}", end="")
        t0 = time.time()
        try:
            trades = trader.run(df_raw, sym)
            all_trades.extend(trades)
            n_u  = sum(1 for t in trades if t.trade_type == "ultra")
            n_h  = sum(1 for t in trades if t.trade_type == "high_conv")
            n_bo = sum(1 for t in trades if t.trade_type == "breakout_premium")
            n_pb = sum(1 for t in trades if t.trade_type == "pullback_quality")
            console.print(
                f" [green]{len(trades):>3} trades[/green]"
                f"  U:[magenta]{n_u}[/magenta]"
                f" H:[cyan]{n_h}[/cyan]"
                f" B:[yellow]{n_bo}[/yellow]"
                f" P:[green]{n_pb}[/green]"
                f"  [{time.time()-t0:.1f}s]"
            )
        except Exception as exc:
            console.print(f" [red]erreur: {exc}[/red]")
            import traceback; traceback.print_exc()

    elapsed = time.time() - t_total
    n_ultra = sum(1 for t in all_trades if t.trade_type == "ultra")
    n_hc    = sum(1 for t in all_trades if t.trade_type == "high_conv")
    n_bo    = sum(1 for t in all_trades if t.trade_type == "breakout_premium")
    n_pb    = sum(1 for t in all_trades if t.trade_type == "pullback_quality")
    console.print()
    console.print(
        f"[bold green]OK {len(all_trades)} trades simules en {elapsed:.1f}s[/bold green]  "
        f"([magenta]{n_ultra} ultra[/magenta] / [cyan]{n_hc} hc[/cyan] / "
        f"[yellow]{n_bo} breakout[/yellow] / [green]{n_pb} pullback[/green])"
    )
    console.print()

    if all_trades:
        print_report(all_trades)
    else:
        console.print("[red]Aucun trade — verifier les seuils de detection.[/red]")


if __name__ == "__main__":
    main()
