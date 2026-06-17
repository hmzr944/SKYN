#!/usr/bin/env python3
"""
SKYN — Paper Trading Test v3 : MOMENTUM TURBO
==============================================
Stratégie "Solution Miracle" — deux niveaux d'entrée :

  1. BB SQUEEZE BREAKOUT (priorité haute)
     - Risque : 2% du capital
     - TP     : 12:1 R:R  (explosif)
     - Setup  : compression Bollinger + volume 3× + ADX montant
     - Math   : 25% WR × 12 = +3R attendu → +4.5% capital/trade

  2. EMA9 WICK PULLBACK (secondaire)
     - Risque : 3% du capital
     - TP     : 3:1 R:R   (régulier)
     - Setup  : rebond mèche sur EMA9 en trend, alignement daily
     - Math   : 35% WR × 3 = +1.05R attendu → +3.15% capital/trade

Scénario ×2 en 1 mois :
  3 breakouts gagnants × 24%  = +72%   ← cœur de la performance
  6 pullbacks gagnants × 5%   = +30%   ← stabilisateur
  Total envisageable          = +102%  ← ×2 en mois de trend fort

Scénario ×3 (bull run) :
  5 breakouts gagnants × 26%  = +130%
  8 pullbacks gagnants × 5%   = +40%
  Total max                   = +170%  ← ×3

Usage :
    cd /home/user/profit-engine/backend
    python paper_test_v3.py
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
# Config
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
COMMISSION        = 0.0004   # Binance futures taker 0.04%
SLIPPAGE          = 0.0005   # 0.05%
DAILY_LOSS_LIMIT  = 0.10     # -10% → circuit breaker
CURRENCY          = "€"

# --- Breakout (BB Squeeze) — conditions ultra-sélectives ---
BREAKOUT_RISK     = 0.02     # 2% du capital — ticket de loterie à faible risque
SL_MULT_BREAKOUT  = 1.0      # 1 ATR → SL serré = R:R maximal
TP_RR_BREAKOUT    = 12.0     # 12:1 → 1 trade gagnant = +24% du capital !
BB_SQUEEZE_WINDOW = 50       # fenêtre pour le percentile BBW
BB_SQUEEZE_PCT    = 0.15     # compression = BBW < 15e percentile (vrai squeeze)
VOL_SURGE_MIN     = 3.2      # explosion volume : 3.2× moyenne (fort mais atteignable)
ADX_RISE_MIN      = 3.0      # ADX doit monter de 3 pts minimum (accélération confirmée)
MIN_ADX_BREAKOUT  = 16       # ADX minimum (trend au moins naissant)
MIN_SQUEEZE_BARS  = 3        # au moins 3 barres en compression dans les 8 dernières
BO_BODY_PCT_MIN   = 0.45     # corps bougie ≥ 45% (breakout directionnel)
BO_COOLDOWN_H     = 8        # pause de 8h après une perte breakout sur même symbole
MAX_LEV_BREAKOUT  = 2        # 2x levier sur breakout (risque limité)

# --- EMA9 Pullback ---
PULLBACK_RISK     = 0.03     # 3% du capital — risque maîtrisé
SL_MULT_PULLBACK  = 1.2      # 1.2 ATR
TP_RR_PULLBACK    = 3.0      # 3:1 R:R
MIN_ADX_PULLBACK  = 25       # trend solide requis
MAX_LEV_PULLBACK  = 3        # 3x levier


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mtf_check(action: str, df_daily: pd.DataFrame, ts) -> Tuple[float, bool]:
    try:
        past = df_daily[df_daily.index.normalize() <= pd.Timestamp(ts).normalize()]
        if len(past) < 50:
            return 0.0, False
        last = past.iloc[-1]
        def sv(col):
            v = last.get(col)
            if v is None: return None
            try: f = float(v); return None if math.isnan(f) else f
            except: return None
        e9, e21, e50, e200 = sv("ema9"), sv("ema21"), sv("ema50"), sv("ema200")
        price = float(last["close"])
        if None in (e9, e21, e50, e200):
            return 0.0, False
        bullish = price > e50 > e200 and e9 > e21
        bearish = price < e50 < e200 and e9 < e21
        if bullish and action == "BUY":  return 15.0, True
        if bearish and action == "SELL": return 15.0, True
        return 0.0, False
    except Exception:
        return 0.0, False


def _bb_squeeze_breakout(
    df: pd.DataFrame,
    i: int,
    adx_val: float,
    adx_series: pd.Series,
) -> Tuple[bool, Optional[str]]:
    """
    Détecte un breakout de compression Bollinger (BB Squeeze).

    Conditions (BUY) :
      - BBW a été dans le bas des 20% récemment (compression)
      - Clôture au-dessus du BB supérieur (cassure)
      - Volume >= 2.8× la moyenne (explosion)
      - ADX montant (trend naissant)
      - Bougie directionnelle (close > open)

    R:R = 12:1 → 1 seul trade gagnant sur 4 = +profit
    """
    if i < BB_SQUEEZE_WINDOW + 5:
        return False, None

    last = df.iloc[i]

    try:
        price     = float(last["close"])
        open_p    = float(last["open"])
        bb_upper  = float(last.get("bb_upper", 0) or 0)
        bb_lower  = float(last.get("bb_lower", 0) or 0)
        bb_mid    = float(last.get("bb_mid",   0) or 0)
        atr_v     = float(last.get("atr", price * 0.01) or price * 0.01)
        vol_ratio = float(last.get("vol_ratio", 1.0) or 1.0)
        ema50     = float(last.get("ema50",  price) or price)
        ema200    = float(last.get("ema200", price) or price)
    except (TypeError, ValueError, KeyError):
        return False, None

    if bb_upper <= 0 or bb_lower <= 0 or bb_mid <= 0:
        return False, None

    # ---------- ADX minimum requis
    if adx_val < MIN_ADX_BREAKOUT:
        return False, None

    # ---------- Squeeze réel : "était compressé, maintenant ça explose"
    #   1. Min BBW des 8 dernières barres < seuil q10 (compression passée confirmée)
    #   2. BBW actuelle > min récent × 1.2 (décompression en cours = release)
    bbw_col = "bbw"   if "bbw"    in df.columns else None
    q10_col = "bbw_q20" if "bbw_q20" in df.columns else None

    if not (bbw_col and q10_col):
        return False, None

    cur_bbw       = float(last.get("bbw", 1.0) or 1.0)
    q10_threshold = float(last.get("bbw_q20", 1.0) or 1.0)
    recent_slice  = df.iloc[max(0, i - 8):i]
    if len(recent_slice) < MIN_SQUEEZE_BARS:
        return False, None

    min_bbw_recent = float(recent_slice[bbw_col].min())

    # Compression passée : le min récent était bien sous le seuil q10
    if min_bbw_recent > q10_threshold * 1.05:
        return False, None  # pas de vraie compression récente

    # Décompression active : BBW actuelle en expansion par rapport au min
    if cur_bbw < min_bbw_recent * 1.15:
        return False, None  # encore compressé / pas encore de release

    # Comptage de barres en compression : au moins MIN_SQUEEZE_BARS dans les 8 dernières
    bbw_vals = recent_slice[bbw_col].values
    q10_vals = recent_slice[q10_col].values
    n_squeezed = int(np.sum(bbw_vals < q10_vals * 1.05))
    if n_squeezed < MIN_SQUEEZE_BARS:
        return False, None

    # ---------- Volume explosion — signal fort uniquement
    if vol_ratio < VOL_SURGE_MIN:
        return False, None

    # ---------- ADX accélération significative
    if i >= 5 and not np.isnan(adx_series.iloc[i - 5]):
        adx_5 = float(adx_series.iloc[i - 5])
        if adx_val < adx_5 + ADX_RISE_MIN:
            return False, None
    else:
        return False, None

    # ---------- Corps bougie fort (direction claire)
    rng   = float(last.get("high", price)) - float(last.get("low", price))
    body  = abs(price - open_p)
    if rng > 0 and body / rng < BO_BODY_PCT_MIN:
        return False, None

    # ---------- Direction du breakout — cassure nette au-delà du BB
    is_bull_candle = price > open_p
    is_bear_candle = price < open_p

    # BUY : prix clôture clairement au-dessus du band supérieur
    if price > bb_upper * 1.001 and is_bull_candle:
        # Exclure bear macro extrême (prix < EMA200 × 0.90 = crash long-terme)
        if ema200 > 0 and price < ema200 * 0.90:
            return False, None
        return True, "BUY"

    # SELL : prix clôture clairement sous le band inférieur
    if price < bb_lower * 0.999 and is_bear_candle:
        # Exclure bull macro extrême (prix > EMA200 × 1.10 = euphorie long-terme)
        if ema200 > 0 and price > ema200 * 1.10:
            return False, None
        return True, "SELL"

    return False, None


def _ema9_pullback(
    df: pd.DataFrame,
    i: int,
    regime_val: str,
    adx_val: float,
) -> Tuple[bool, Optional[str]]:
    """
    Rebond sur mèche EMA9 en tendance forte — copié de paper_test.py.
    Requiert ADX > 25, RSI 38-62, vol 1.2×, body 40%.
    """
    if i < 2 or adx_val < MIN_ADX_PULLBACK:
        return False, None

    last = df.iloc[i]
    try:
        price     = float(last["close"])
        ema9      = float(last.get("ema9",  0) or 0)
        ema21     = float(last.get("ema21", 0) or 0)
        ema50     = float(last.get("ema50", 0) or 0)
        open_p    = float(last["open"])
        high_p    = float(last["high"])
        low_p     = float(last["low"])
        vol_ratio = float(last.get("vol_ratio", 1.0) or 1.0)
        rsi_raw   = last.get("rsi")
        rsi       = float(rsi_raw) if (rsi_raw is not None and not pd.isna(rsi_raw)) else 50.0
    except (TypeError, ValueError, KeyError):
        return False, None

    if ema9 <= 0 or ema21 <= 0 or ema50 <= 0:
        return False, None

    body     = abs(price - open_p)
    rng      = high_p - low_p
    body_pct = body / rng if rng > 0 else 0
    ema9_5   = float(df.iloc[max(0, i - 5)].get("ema9", ema9) or ema9)

    if regime_val == "bull_trend":
        if not (ema9 > ema21 > 0):                return False, None
        if low_p > ema9 * 1.002:                  return False, None  # mèche touche EMA9
        if price <= open_p:                        return False, None  # bougie haussière
        if price <= ema9:                          return False, None  # clôture au-dessus
        if price > ema9 * 1.02:                   return False, None  # proche de l'EMA9
        if rsi < 38 or rsi > 62:                  return False, None  # zone neutre
        if vol_ratio < 1.2:                        return False, None  # volume expansion
        if body_pct < 0.40:                        return False, None  # bougie forte
        if ema9 < ema9_5 * 1.001:                 return False, None  # EMA9 montante
        return True, "BUY"

    elif regime_val == "bear_trend":
        if not (ema9 < ema21) or ema9 <= 0:       return False, None
        if high_p < ema9 * 0.998:                 return False, None  # mèche touche EMA9
        if price >= open_p:                        return False, None  # bougie baissière
        if price >= ema9:                          return False, None  # clôture en-dessous
        if price < ema9 * 0.98:                   return False, None
        if rsi < 38 or rsi > 62:                  return False, None
        if vol_ratio < 1.2:                        return False, None
        if body_pct < 0.40:                        return False, None
        if ema9 > ema9_5 * 0.999:                 return False, None  # EMA9 baissière
        return True, "SELL"

    return False, None


# ---------------------------------------------------------------------------
# Trade dataclass
# ---------------------------------------------------------------------------

@dataclass
class PaperTrade:
    symbol:        str
    side:          str
    entry_idx:     int
    exit_idx:      int
    entry_price:   float
    exit_price:    float
    margin_eur:    float
    leverage:      int
    pnl_eur:       float
    pnl_pct:       float
    exit_reason:   str
    score:         float
    regime:        str
    candles_held:  int
    entry_ts:      object = None
    trade_type:    str    = "pullback"  # "breakout" | "pullback" | "signal"
    mtf_aligned:   bool   = False


# ---------------------------------------------------------------------------
# Simulateur
# ---------------------------------------------------------------------------

class PaperTrader:
    def __init__(self):
        self.cfg     = AppConfig()
        self.lev_mgr = LeverageManager()

    def run(self, df_raw: pd.DataFrame, yf_sym: str) -> List[PaperTrade]:
        prod_sym = SYMBOL_NAMES.get(yf_sym, yf_sym)
        cfg      = self.cfg

        # Indicateurs
        df       = compute_all(df_raw.copy(), cfg.strategy)
        df_daily = resample_daily(df)

        # --- Pré-calculs O(n) ---

        # Bollinger Band Width (si pas encore dans df)
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

        # BBW quantile 10 sur fenêtre glissante de 50 barres (très sélectif — vrais squeezes uniquement)
        df["bbw_q20"] = df["bbw"].rolling(BB_SQUEEZE_WINDOW).quantile(BB_SQUEEZE_PCT).fillna(df["bbw"])

        # ADX pré-calculé (évite O(n²))
        adx_series, di_p_series, di_m_series = _compute_adx(df)

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
            if atr_pct > 3.5: return Regime.HIGH_VOL
            if adx_v > 20:
                if di_p_v > di_m_v and price > ema50 and ema50 > ema200: return Regime.BULL_TREND
                if di_m_v > di_p_v and price < ema50 and ema50 < ema200: return Regime.BEAR_TREND
            return Regime.RANGING

        # Cache MTF par date+direction
        mtf_cache: Dict[str, Tuple[float, bool]] = {}
        # Cooldown par type : symbole → timestamp minimum de prochaine entrée breakout
        bo_cooldown_until: Optional[pd.Timestamp] = None

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
            atr_v = float(row["atr"]) if not pd.isna(row.get("atr", float("nan"))) else price * 0.02

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
                        if price <= pos["sl"]:               reason = "stop_loss"
                        elif price <= pos.get("trail", -1):  reason = "trailing_stop"
                        elif price >= pos["tp"]:             reason = "take_profit"
                    else:
                        if price >= pos["sl"]:               reason = "stop_loss"
                        elif price >= pos.get("trail", 1e18):reason = "trailing_stop"
                        elif price <= pos["tp"]:             reason = "take_profit"

                if reason:
                    if reason == "liquidation":
                        pnl_eur = -pos["margin_eur"]
                        exit_p  = pos["liq"]
                    else:
                        slip   = (1 - SLIPPAGE) if side == "long" else (1 + SLIPPAGE)
                        exit_p = price * slip
                        raw    = (exit_p - pos["entry"]) * pos["qty"] if side == "long" \
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
                        trade_type=pos.get("trade_type", "pullback"),
                        mtf_aligned=pos.get("mtf_aligned", False),
                    ))
                    # Cooldown après perte sur breakout
                    if pnl_eur < 0 and pos.get("trade_type") == "breakout":
                        bo_cooldown_until = ts + pd.Timedelta(hours=BO_COOLDOWN_H)
                    in_pos = False; partial_taken = False
                    continue

            if in_pos or halted or cash < 0.5:
                continue

            # ---- SÉLECTION DE L'ENTRÉE ----

            # ADX courant
            adx_i = float(adx_series.iloc[i]) if not np.isnan(adx_series.iloc[i]) else 0.0

            # --- PRIORITÉ 1 : BB SQUEEZE BREAKOUT (explosif, 2% risk, 12:1 TP) ---
            # Cooldown actif après une perte breakout
            in_cooldown = (bo_cooldown_until is not None and ts < bo_cooldown_until)
            is_bo, bo_action = (False, None) if in_cooldown else _bb_squeeze_breakout(df, i, adx_i, adx_series)

            if is_bo and bo_action:
                eff_action  = bo_action
                risk        = BREAKOUT_RISK
                sl_mult     = SL_MULT_BREAKOUT
                tp_rr       = TP_RR_BREAKOUT
                max_lev     = MAX_LEV_BREAKOUT
                trade_type  = "breakout"
                mtf_aligned = True   # breakouts initient les trends — pas de MTF requis
                final_score = 92.0

            else:
                # Régime pour pullback
                try:
                    regime = _fast_regime(i)
                    p      = _PARAMS[regime]
                except Exception:
                    continue

                if regime not in (Regime.BULL_TREND, Regime.BEAR_TREND):
                    continue

                # --- PRIORITÉ 2 : EMA9 PULLBACK (trend, 3% risk, 3:1 TP) ---
                is_pb, pb_action = _ema9_pullback(df, i, regime.value, adx_i)

                if not (is_pb and pb_action):
                    continue

                # MTF requis pour pullback
                mtf_key = f"{pb_action}_{day_key}"
                if mtf_key not in mtf_cache:
                    mtf_cache[mtf_key] = _mtf_check(pb_action, df_daily, ts)
                mtf_boost, mtf_aligned = mtf_cache[mtf_key]

                if not mtf_aligned:
                    continue

                eff_action = pb_action
                risk       = PULLBACK_RISK
                sl_mult    = SL_MULT_PULLBACK
                tp_rr      = TP_RR_PULLBACK
                max_lev    = MAX_LEV_PULLBACK
                trade_type = "pullback"
                final_score = 85.0
                mtf_aligned = True

            # ---- Calcul position ----
            lev     = min(self.lev_mgr.get_leverage(final_score, "HIGH"), max_lev)
            sl_dist = atr_v * sl_mult
            tp_dist = sl_dist * tp_rr

            if eff_action == "BUY":
                entry_p    = price * (1 + SLIPPAGE)
                sl, tp     = entry_p - sl_dist, entry_p + tp_dist
                partial_tp = entry_p + (tp - entry_p) * 0.6   # partial à 60% du TP
                liq_p      = self.lev_mgr.liquidation_price(entry_p, lev, "long")
                sl         = max(sl, liq_p * 1.001)
                side       = "long"
            else:
                entry_p    = price * (1 - SLIPPAGE)
                sl, tp     = entry_p + sl_dist, entry_p - tp_dist
                partial_tp = entry_p - (entry_p - tp) * 0.6
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

            entry_comm  = qty * entry_p * COMMISSION
            total_cost  = margin_eur + entry_comm

            if qty <= 1e-12 or total_cost > cash:
                continue

            cash  -= total_cost
            in_pos = True; partial_taken = False
            pos = {
                "side": side, "entry": entry_p, "qty": qty,
                "margin_eur": margin_eur, "liq": liq_p,
                "sl": sl, "tp": tp, "partial_tp": partial_tp,
                "trail": float("nan"),
                "leverage": lev, "score": final_score,
                "idx": i, "regime": ("breakout" if trade_type == "breakout" else regime.value),
                "entry_ts": ts, "trade_type": trade_type, "mtf_aligned": mtf_aligned,
            }

        # Fermeture en fin de données
        if in_pos:
            fp    = float(df.iloc[-1]["close"])
            slip  = (1 - SLIPPAGE) if pos["side"] == "long" else (1 + SLIPPAGE)
            exit_p = fp * slip
            side  = pos["side"]
            raw   = (exit_p - pos["entry"]) * pos["qty"] if side == "long" \
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
                trade_type=pos.get("trade_type", "pullback"),
                mtf_aligned=pos.get("mtf_aligned", False),
            ))
        return trades


# ---------------------------------------------------------------------------
# Métriques
# ---------------------------------------------------------------------------

def metrics(trades: List[PaperTrade], initial: float) -> dict:
    if not trades:
        return {}
    equity = initial; curve = [initial]
    for t in trades:
        equity = equity - t.margin_eur + t.margin_eur + t.pnl_eur if t.exit_reason != "liquidation" \
                 else equity - t.margin_eur
        curve.append(equity)

    # Recalcul propre
    equity = initial; curve = [initial]
    for t in trades:
        if t.exit_reason == "liquidation": equity -= t.margin_eur
        else: equity += t.pnl_eur
        curve.append(equity)

    eq  = np.array(curve, dtype=float)
    ret = (eq[-1] - initial) / initial * 100
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

    regime_counts: Dict[str, int] = {}
    regime_wins:   Dict[str, int] = {}
    for t in trades:
        regime_counts[t.regime] = regime_counts.get(t.regime, 0) + 1
        if t.pnl_eur > 0:
            regime_wins[t.regime] = regime_wins.get(t.regime, 0) + 1

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
        "regime_counts":    regime_counts,
        "regime_wins":      regime_wins,
    }


# ---------------------------------------------------------------------------
# Rapport Rich
# ---------------------------------------------------------------------------

def print_report(all_trades: List[PaperTrade]):
    console.rule("[bold yellow]SKYN v3 — MOMENTUM TURBO : 50 € INITIAL[/bold yellow]")
    console.print()

    m = metrics(all_trades, INITIAL_CAPITAL)
    if not m:
        console.print("[red]Aucun trade.[/red]"); return

    ret    = m["total_return_pct"]
    final  = m["final_equity"]
    profit = final - INITIAL_CAPITAL
    color  = "green" if ret >= 0 else "red"

    # ---- Résultat global ---
    g = Table.grid(padding=(0, 3))
    g.add_row("[bold]Mise de départ[/bold]",  f"[white]{INITIAL_CAPITAL:.2f} {CURRENCY}[/white]")
    g.add_row("[bold]Capital final[/bold]",   f"[{color} bold]{final:.2f} {CURRENCY}[/{color} bold]")
    g.add_row("[bold]Profit net[/bold]",      f"[{color} bold]{profit:+.2f} {CURRENCY} ({ret:+.2f}%)[/{color} bold]")
    g.add_row("[bold]Drawdown max[/bold]",    f"[{'red' if m['max_drawdown_pct']>25 else 'yellow'}]{m['max_drawdown_pct']:.1f}%[/]")
    g.add_row("[bold]Sharpe[/bold]",          f"[cyan]{m['sharpe_ratio']:.3f}[/cyan]")
    g.add_row("[bold]Profit Factor[/bold]",   f"[cyan]{m['profit_factor']:.3f}[/cyan]")
    g.add_row("[bold]Win rate[/bold]",        f"[{'green' if m['win_rate']>=45 else 'red'}]{m['win_rate']:.1f}%[/] ({m['wins']}W / {m['losses']}L)")
    g.add_row("[bold]Trades total[/bold]",    f"{m['total_trades']}  Long:{m['longs']} Court:{m['shorts']}")
    g.add_row("[bold]Liquidations[/bold]",    f"[{'green' if m['liquidations']==0 else 'red bold'}]{m['liquidations']}[/]")
    console.print(Panel(g, title="[bold]Résultat Global · 2 ans · Momentum Turbo[/bold]", border_style="yellow", expand=False))
    console.print()

    # ---- Stats par type de trade ---
    bo_trades = [t for t in all_trades if t.trade_type == "breakout"]
    pb_trades = [t for t in all_trades if t.trade_type == "pullback"]
    si_trades = [t for t in all_trades if t.trade_type == "signal"]

    def type_row(label, lst, color):
        if not lst: return label, "0", "-", "-", "-"
        wins = [t for t in lst if t.pnl_eur > 0]
        net  = sum(t.pnl_eur for t in lst)
        wr   = len(wins) / len(lst) * 100
        avg_win  = np.mean([t.pnl_pct for t in wins]) if wins else 0
        nc   = "green" if net > 0 else "red"
        cw   = "green" if wr >= 45 else "yellow" if wr >= 30 else "red"
        return (
            f"[{color}]{label}[/{color}]",
            str(len(lst)),
            f"[{cw}]{wr:.0f}%[/{cw}]",
            f"[{'green' if net>0 else 'red'}]{net:+.2f}€[/]",
            f"{avg_win:+.1f}% par win",
        )

    tt = Table(title="[bold]Performance par Type de Trade[/bold]", box=box.ROUNDED, border_style="cyan")
    for col in ["Type", "Trades", "Win%", "Net (€)", "Gain moyen/win"]:
        tt.add_column(col, justify="right")
    tt.columns[0].justify = "left"
    tt.add_row(*type_row("🎯 BB SQUEEZE BREAKOUT",  bo_trades, "yellow"))
    tt.add_row(*type_row("📈 EMA9 PULLBACK",         pb_trades, "green"))
    tt.add_row(*type_row("📊 Signal multi-facteur",  si_trades, "blue"))
    console.print(tt)
    console.print()

    # ---- Analyse des breakouts ---
    if bo_trades:
        bo_wins   = [t for t in bo_trades if t.pnl_eur > 0]
        bo_losses = [t for t in bo_trades if t.pnl_eur <= 0]
        avg_win_bo  = np.mean([t.pnl_eur for t in bo_wins])  if bo_wins  else 0
        avg_loss_bo = np.mean([t.pnl_eur for t in bo_losses]) if bo_losses else 0
        bo_net = sum(t.pnl_eur for t in bo_trades)

        console.print(Panel(
            f"[bold yellow]BB SQUEEZE BREAKOUT — L'arme secrète ×2-×3[/bold yellow]\n\n"
            f"  Trades       : {len(bo_trades)}\n"
            f"  Gagnants     : {len(bo_wins)} ({len(bo_wins)/len(bo_trades)*100:.0f}%)\n"
            f"  Gain moyen/win  : [green]{avg_win_bo:+.2f}€[/green]\n"
            f"  Perte moyen/loss: [red]{avg_loss_bo:+.2f}€[/red]\n"
            f"  Gain net     : [{'green' if bo_net>0 else 'red'}]{bo_net:+.2f}€[/]\n"
            f"  R:R théorique : 12:1 (risque 2% → gain 24% par TP)",
            border_style="yellow",
        ))
        console.print()

    # ---- Performance par symbole ---
    t2 = Table(title="Performance par Symbole", box=box.ROUNDED, border_style="magenta")
    for col in ["Symbole", "Trades", "Win%", "Breakouts", "Net (€)", "Sharpe"]:
        t2.add_column(col, justify="right")
    t2.columns[0].justify = "left"

    sym_agg: Dict[str, list] = {}
    for t in all_trades:
        sym_agg.setdefault(t.symbol, []).append(t)

    for sym in sorted(sym_agg.keys()):
        lst   = sym_agg[sym]
        wins  = [t for t in lst if t.pnl_eur > 0]
        wr    = len(wins) / len(lst) * 100 if lst else 0
        net   = sum(t.pnl_eur for t in lst)
        bos   = sum(1 for t in lst if t.trade_type == "breakout")
        sm    = metrics(lst, INITIAL_CAPITAL / len(sym_agg))
        c     = "green" if net > 0 else "red"
        cw    = "green" if wr >= 45 else "red"
        t2.add_row(
            sym.split("/")[0], str(len(lst)),
            f"[{cw}]{wr:.0f}%[/{cw}]",
            f"[yellow]{bos}[/yellow]",
            f"[{c}]{net:+.2f}€[/{c}]",
            f"{sm.get('sharpe_ratio', 0):.2f}",
        )
    console.print(t2)
    console.print()

    # ---- Breakdown mensuel ---
    monthly: Dict[str, list] = {}
    for t in all_trades:
        if t.entry_ts is not None:
            monthly.setdefault(str(t.entry_ts)[:7], []).append(t)

    if monthly:
        tm = Table(title="[bold]Breakdown Mensuel — ×2/×3 en vue ?[/bold]",
                   box=box.ROUNDED, border_style="cyan")
        for col in ["Mois", "Trades", "Win%", "Breakouts (W/T)", "Net €", "Ret%", "Statut"]:
            tm.add_column(col, justify="right")
        tm.columns[0].justify = "left"

        running_eq = INITIAL_CAPITAL
        for key in sorted(monthly.keys()):
            mt    = monthly[key]
            mp    = sum(t.pnl_eur for t in mt)
            mw    = sum(1 for t in mt if t.pnl_eur > 0)
            wr    = mw / len(mt) * 100 if mt else 0
            ret   = mp / running_eq * 100 if running_eq > 0 else 0
            running_eq += mp
            bos   = [t for t in mt if t.trade_type == "breakout"]
            bo_w  = sum(1 for t in bos if t.pnl_eur > 0)
            c     = "green" if mp > 0 else "red"
            cw    = "green" if wr >= 50 else "yellow" if wr >= 35 else "red"
            # Statut
            if ret >= 100: status = "[bold green]×2+ 🚀[/bold green]"
            elif ret >= 50: status = "[green]×1.5+ 🔥[/green]"
            elif ret >= 20: status = "[green]+20%+ ✓[/green]"
            elif ret >= 0:  status = "[yellow]+[/yellow]"
            else:            status = "[red]−[/red]"
            tm.add_row(
                key, str(len(mt)),
                f"[{cw}]{wr:.0f}%[/{cw}]",
                f"[yellow]{bo_w}/{len(bos)}[/yellow]",
                f"[{c}]{mp:+.2f}€[/{c}]",
                f"[{c}]{ret:+.1f}%[/{c}]",
                status,
            )
        console.print(tm)
        console.print()

    # ---- Top/Worst trades ---
    sorted_t = sorted(all_trades, key=lambda x: x.pnl_eur, reverse=True)
    worst = list(reversed(sorted_t[-15:]))
    for title, lst, bc in [
        ("Top 15 Meilleurs Trades", sorted_t[:15], "green"),
        ("Top 15 Pires Trades", worst, "red"),
    ]:
        tt2 = Table(title=title, box=box.SIMPLE, border_style=bc)
        for col in ["Sym", "Side", "Type", "Net €", "PnL%", "Lev", "Sortie", "Durée"]:
            tt2.add_column(col, justify="right" if col not in ["Sym", "Side", "Type", "Sortie"] else "left")
        type_icons = {"breakout": "🎯", "pullback": "📈", "signal": "📊"}
        for t in lst:
            c = "green" if t.pnl_eur > 0 else "red"
            tt2.add_row(
                t.symbol.split("/")[0], t.side,
                type_icons.get(t.trade_type, "?") + " " + t.trade_type[:5],
                f"[{c}]{t.pnl_eur:+.2f}€[/{c}]",
                f"[{c}]{t.pnl_pct:+.1f}%[/{c}]",
                f"{t.leverage}x",
                t.exit_reason[:5],
                f"{t.candles_held * CANDLE_HOURS}h",
            )
        console.print(tt2)
        console.print()

    # ---- Courbe equity ---
    ec = m["equity_curve"]
    if len(ec) > 2:
        n_pts = min(70, len(ec))
        step  = max(1, len(ec) // n_pts)
        pts   = [ec[j * step] for j in range(n_pts)] + [ec[-1]]
        mn, mx = min(pts), max(pts)
        rng  = mx - mn or 1
        blocks = " ▁▂▃▄▅▆▇█"
        chart  = "".join(blocks[max(0, min(8, int((v - mn) / rng * 8)))] for v in pts)
        c = "green" if ec[-1] >= ec[0] else "red"
        console.print(Panel(
            f"[{c}]{chart}[/{c}]\n"
            f"  Départ: {ec[0]:.2f}€  →  Fin: {ec[-1]:.2f}€  |  "
            f"Min: {mn:.2f}€  Max: {mx:.2f}€",
            title="Courbe d'Equity (50€ → ?)",
            border_style=c,
        ))
    console.print()

    # ---- Projection ---
    total_days    = 730
    trades_per_day = m["total_trades"] / total_days
    daily_pnl     = profit / total_days
    console.print(Panel(
        f"Rythme observé : [cyan]{trades_per_day:.2f} trades/jour[/cyan]  ·  "
        f"[cyan]{daily_pnl:+.3f} {CURRENCY}/jour[/cyan]\n\n"
        f"  [bold]1 semaine[/bold] : {INITIAL_CAPITAL:.2f}€ → [{color}]{INITIAL_CAPITAL + daily_pnl*7:.2f}€[/{color}]\n"
        f"  [bold]1 mois[/bold]   : {INITIAL_CAPITAL:.2f}€ → [{color}]{INITIAL_CAPITAL + daily_pnl*30:.2f}€[/{color}]\n"
        f"  [bold]3 mois[/bold]   : {INITIAL_CAPITAL:.2f}€ → [{color}]{INITIAL_CAPITAL + daily_pnl*90:.2f}€[/{color}]\n\n"
        f"  [dim]* Projection linéaire — les mois de breakout dépassent largement cette moyenne[/dim]",
        title="[bold]Projection (base : rythme observé sur 2 ans)[/bold]",
        border_style="cyan",
    ))
    console.print()
    console.rule("[bold yellow]FIN DU RAPPORT[/bold yellow]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    n_syms = len(SYMBOLS_YF)
    console.rule(f"[bold yellow]SKYN v3 — MOMENTUM TURBO · 50€ · {n_syms} Symboles · 2 ans[/bold yellow]")
    console.print(f"[bold]Breakout Risk:[/bold] {BREAKOUT_RISK*100:.0f}%  TP:[bold yellow]{TP_RR_BREAKOUT:.0f}:1[/bold yellow] "
                  f"  [bold]Pullback Risk:[/bold] {PULLBACK_RISK*100:.0f}%  TP:[bold green]{TP_RR_PULLBACK:.0f}:1[/bold green]")
    console.print()

    trader     = PaperTrader()
    all_trades: List[PaperTrade] = []

    console.print("[bold]Téléchargement des données...[/bold]")
    data_map: Dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS_YF:
        console.print(f"  [cyan]↓[/cyan] {sym}…", end="")
        df = download_data(sym)
        if df is not None:
            data_map[sym] = df
            console.print(f" [green]{len(df)} barres ✓[/green]")
        else:
            console.print(f" [red]échec[/red]")

    if not data_map:
        console.print("[red]Aucune donnée.[/red]"); return

    console.print()
    console.print("[bold]Simulation en cours...[/bold]")
    t_total = time.time()

    for sym, df_raw in data_map.items():
        console.print(f"  [cyan]▶[/cyan] {SYMBOL_NAMES.get(sym, sym):<12}", end="")
        t0 = time.time()
        try:
            trades = trader.run(df_raw, sym)
            all_trades.extend(trades)
            bo_cnt = sum(1 for t in trades if t.trade_type == "breakout")
            console.print(f" [green]{len(trades):>3} trades[/green]"
                          f"  [yellow]{bo_cnt} breakouts[/yellow]"
                          f"  [{time.time()-t0:.1f}s]")
        except Exception as exc:
            console.print(f" [red]erreur: {exc}[/red]")
            import traceback; traceback.print_exc()

    elapsed = time.time() - t_total
    total_bo = sum(1 for t in all_trades if t.trade_type == "breakout")
    console.print()
    console.print(f"[bold green]✓ {len(all_trades)} trades simulés en {elapsed:.1f}s"
                  f"  (dont {total_bo} breakouts explosifs)[/bold green]")
    console.print()

    if all_trades:
        print_report(all_trades)
    else:
        console.print("[red]Aucun trade — vérifier les seuils de détection.[/red]")


if __name__ == "__main__":
    main()
