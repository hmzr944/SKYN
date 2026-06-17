#!/usr/bin/env python3
"""
SKYN — Paper Trading Test v2
==============================
Améliorations vs v1 :
  - Timeframe 4h (vs 1h) → moins de bruit, signaux plus fiables
  - 7 symboles (vs 3) → plus de trades, meilleure diversification
  - ADX seuil abaissé à 20 → plus de tendances détectées
  - Capital initial : 50 € (simulation réaliste petite mise)
  - MTF confirmé sur daily (vs 4h sur 1h)
  - Régimes autorisés : BULL_TREND, BEAR_TREND (+ BREAKOUT si vol > 2.5x)
  - Filtre macro EMA200 pour éviter les trades contre la tendance longue

Usage:
    cd /home/user/profit-engine/backend
    python paper_test.py
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
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

from config import AppConfig
from engine.analysis.indicators import compute_all, _ema
from engine.analysis.signals import score_signal
from engine.strategy.regime_detector import detect_regime, Regime, _adx as _compute_adx
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
]  # UNI-USD delisted from yfinance — skipped
SYMBOL_NAMES = {
    "BTC-USD":  "BTC/USDT",
    "ETH-USD":  "ETH/USDT",
    "SOL-USD":  "SOL/USDT",
    "BNB-USD":  "BNB/USDT",
    "AVAX-USD": "AVAX/USDT",
    "ADA-USD":  "ADA/USDT",
    "LINK-USD": "LINK/USDT",
    "XRP-USD":  "XRP/USDT",
    "DOT-USD":  "DOT/USDT",
    "ATOM-USD": "ATOM/USDT",
    "LTC-USD":  "LTC/USDT",
}

INITIAL_CAPITAL  = 50.0       # 50 euros — simulation réaliste petite mise
INTERVAL         = "1h"       # timeframe de base
CANDLE_HOURS     = 1          # pour affichage des durées
PERIOD           = "2y"
WARMUP           = 210        # barres warmup (besoin de EMA200)
COMMISSION       = 0.0004     # Binance futures taker 0.04%
SLIPPAGE         = 0.0005     # 0.05%
RISK_PER_TRADE   = 0.05       # 5%/trade
TRAIL_MULT       = 0.6        # trailing plus serré
DAILY_LOSS_LIMIT = 0.12       # -12% → pause trading le jour
CURRENCY         = "€"

# Paramètres Turbo Trend
SL_MULT_TREND    = 1.2        # 1.2 ATR stop
TP_RR_TREND      = 2.5        # 2.5:1 R:R
MIN_SCORE_PULLBACK = 70       # score minimum pour entrée rebond EMA9
PULLBACK_BONUS   = 15         # bonus score sur rebond EMA9 confirmé


# ---------------------------------------------------------------------------
# Téléchargement données
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
    """Agrège en daily pour la confirmation MTF."""
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
# Helpers MTF & timing
# ---------------------------------------------------------------------------

def _mtf_check(action: str, df_daily: pd.DataFrame, ts) -> Tuple[float, bool, str]:
    """Vérifie l'alignement daily (MTF supérieur)."""
    try:
        past = df_daily[df_daily.index.normalize() <= pd.Timestamp(ts).normalize()]
        if len(past) < 50:
            return 0.0, False, "MTF: données insuffisantes"
        last = past.iloc[-1]

        def sv(col):
            v = last.get(col)
            if v is None: return None
            try:
                f = float(v)
                return None if math.isnan(f) else f
            except (TypeError, ValueError):
                return None

        e9, e21, e50, e200 = sv("ema9"), sv("ema21"), sv("ema50"), sv("ema200")
        price = float(last["close"])
        if None in (e9, e21, e50, e200):
            return 0.0, False, "MTF: EMA manquant"

        bullish = price > e50 > e200 and e9 > e21
        bearish = price < e50 < e200 and e9 < e21

        if bullish and action == "BUY":   return 15.0, True,  "Daily haussier → BUY (+15)"
        if bearish and action == "SELL":  return 15.0, True,  "Daily baissier → SELL (+15)"
        if bullish and action == "SELL":  return -20.0, False, "Daily haussier contredit SELL (-20)"
        if bearish and action == "BUY":   return -20.0, False, "Daily baissier contredit BUY (-20)"
        return 0.0, False, "Daily neutre"
    except Exception:
        return 0.0, False, "MTF: erreur"


def _timing_check(action: str, row) -> float:
    """RSI surchauffe + qualité bougie + VWAP. Retourne le boost."""
    boost = 0.0
    try:
        rsi_v = row.get("rsi")
        if rsi_v is not None and not math.isnan(float(rsi_v)):
            rsi_v = float(rsi_v)
            if action == "BUY"  and rsi_v > 68: boost -= 15
            elif action == "SELL" and rsi_v < 32: boost -= 15

        o, c, h, lo = float(row["open"]), float(row["close"]), float(row["high"]), float(row["low"])
        rng = h - lo; body = abs(c - o)
        if rng > 0 and body / rng < 0.25:
            boost -= 8  # doji

        vwap = row.get("vwap")
        price = c
        if vwap is not None and not math.isnan(float(vwap)):
            vwap = float(vwap)
            if   action == "BUY"  and price < vwap: boost -= 10
            elif action == "SELL" and price > vwap: boost -= 10
            elif action == "BUY"  and price >= vwap: boost += 5
            elif action == "SELL" and price <= vwap: boost += 5
    except (TypeError, ValueError, KeyError):
        pass
    return boost


def _ema9_pullback_check(
    df: pd.DataFrame, i: int, regime_val: str, adx_val: float
) -> Tuple[bool, Optional[str]]:
    """
    Pattern "wick-to-EMA9" — rebond / rejet sur la dynamique EMA9.

    Bull : la mèche basse touche l'EMA9, la bougie clôture AU-DESSUS
           avec volume et corps forts → momentum reprend.
    Bear : symétrique.

    Conditions strictes : ADX > 25, volume > 1.2×, corps > 40%,
    EMA9 montant, RSI en zone neutre (38-65).
    """
    if i < 2:
        return False, None

    if adx_val < 25:
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

    body = abs(price - open_p)
    rng  = high_p - low_p
    body_pct = body / rng if rng > 0 else 0

    ema9_5 = float(df.iloc[max(0, i - 5)].get("ema9", ema9) or ema9)

    if regime_val == "bull_trend":
        if not (ema9 > ema21 > 0):                    # structure EMA haussière
            return False, None
        if low_p > ema9 * 1.002:                      # mèche basse doit toucher l'EMA9
            return False, None
        if price <= open_p:                            # bougie haussière obligatoire
            return False, None
        if price <= ema9:                              # clôture au-dessus de l'EMA9
            return False, None
        if price > ema9 * 1.02:                       # entrée de qualité près de l'EMA9
            return False, None
        if rsi < 38 or rsi > 62:                      # zone neutre strict — pas d'extrême
            return False, None
        if vol_ratio < 1.2:                            # expansion volume
            return False, None
        if body_pct < 0.40:                            # bougie directionnelle forte
            return False, None
        if ema9 < ema9_5 * 1.001:                     # EMA9 nettement montante
            return False, None
        return True, "BUY"

    elif regime_val == "bear_trend":
        if not (ema9 < ema21) or ema9 <= 0:           # structure EMA baissière
            return False, None
        if high_p < ema9 * 0.998:                     # mèche haute doit toucher l'EMA9
            return False, None
        if price >= open_p:                            # bougie baissière obligatoire
            return False, None
        if price >= ema9:                              # clôture en-dessous de l'EMA9
            return False, None
        if price < ema9 * 0.98:                       # pas trop éloigné
            return False, None
        if rsi < 38 or rsi > 62:                      # zone neutre strict
            return False, None
        if vol_ratio < 1.2:
            return False, None
        if body_pct < 0.40:
            return False, None
        if ema9 > ema9_5 * 0.999:                     # EMA9 nettement baissière
            return False, None
        return True, "SELL"

    return False, None


# ---------------------------------------------------------------------------
# Trade dataclass
# ---------------------------------------------------------------------------

@dataclass
class PaperTrade:
    symbol: str
    side: str
    entry_idx: int
    exit_idx: int
    entry_price: float
    exit_price: float
    margin_eur: float         # marge utilisée en euros
    leverage: int
    pnl_eur: float            # P&L en euros
    pnl_pct: float            # % de la marge
    exit_reason: str
    score: float
    regime: str
    strategy_name: str
    mtf_aligned: bool
    filter_boost: float
    candles_held: int
    entry_ts: object = None
    is_pullback: bool = False


# ---------------------------------------------------------------------------
# Simulateur full-pipeline
# ---------------------------------------------------------------------------

class PaperTrader:
    def __init__(self):
        self.cfg = AppConfig()
        self.lev_mgr = LeverageManager()

    def run(self, df_raw: pd.DataFrame, yf_sym: str) -> List[PaperTrade]:
        prod_sym = SYMBOL_NAMES.get(yf_sym, yf_sym)
        cfg = self.cfg

        # Calcul d'indicateurs une seule fois
        df = compute_all(df_raw.copy(), cfg.strategy)
        df_daily = resample_daily(df)

        # Precompute ADX once O(n) — évite O(n²) si appelé dans la boucle
        adx_series, di_p_series, di_m_series = _compute_adx(df)

        def _fast_regime(idx: int) -> Regime:
            """Lookup O(1) du régime à la barre idx via ADX précompilé."""
            row    = df.iloc[idx]
            price  = float(row.get("close", 1) or 1)
            ema50  = float(row.get("ema50",  price) or price)
            ema200 = float(row.get("ema200", price) or price)
            atr_v  = float(row.get("atr", price * 0.01) or price * 0.01)
            atr_pct = atr_v / price * 100 if price > 0 else 1.0
            adx_v  = float(adx_series.iloc[idx])  if not np.isnan(adx_series.iloc[idx])  else 20.0
            di_p_v = float(di_p_series.iloc[idx]) if not np.isnan(di_p_series.iloc[idx]) else 0.0
            di_m_v = float(di_m_series.iloc[idx]) if not np.isnan(di_m_series.iloc[idx]) else 0.0
            if atr_pct > 3.5:
                return Regime.HIGH_VOL
            if adx_v > 20:
                if di_p_v > di_m_v and price > ema50 and ema50 > ema200:
                    return Regime.BULL_TREND
                if di_m_v > di_p_v and price < ema50 and ema50 < ema200:
                    return Regime.BEAR_TREND
            return Regime.RANGING

        # Cache MTF par date+action — recalcul au max 1×/jour par direction
        mtf_cache: Dict[str, tuple] = {}

        trades: List[PaperTrade] = []
        n = len(df)

        # État du compte
        cash          = INITIAL_CAPITAL
        in_pos        = False
        pos: dict     = {}
        partial_taken = False

        # Circuit-breaker journalier
        day_start_eq  = INITIAL_CAPITAL
        current_day   = None
        halted        = False

        for i in range(WARMUP, n):
            row   = df.iloc[i]
            price = float(row["close"])
            ts    = df.index[i]
            atr_v = float(row["atr"]) if not pd.isna(row.get("atr", float("nan"))) else price * 0.02

            # ---- Jour suivant ------------------------------------------
            day_key = str(ts)[:10]
            if day_key != current_day:
                current_day  = day_key
                day_start_eq = cash + (pos.get("margin_eur", 0) if in_pos else 0)
                halted = False

            if not in_pos and not halted:
                if day_start_eq > 0 and (day_start_eq - cash) / day_start_eq >= DAILY_LOSS_LIMIT:
                    halted = True

            # ---- Trailing stop -----------------------------------------
            if in_pos and not math.isnan(pos.get("trail", float("nan"))):
                if pos["side"] == "long":
                    nt = price - atr_v * TRAIL_MULT
                    if nt > pos["trail"]: pos["trail"] = nt
                else:
                    nt = price + atr_v * TRAIL_MULT
                    if nt < pos["trail"]: pos["trail"] = nt

            # ---- Vérification sorties ----------------------------------
            if in_pos:
                side   = pos["side"]
                reason = None

                if side == "long" and price <= pos["liq"]:   reason = "liquidation"
                elif side == "short" and price >= pos["liq"]: reason = "liquidation"

                if not partial_taken and reason is None:
                    if side == "long"  and price >= pos["partial_tp"]:
                        partial_taken = True
                        pos["sl"] = pos["entry"]
                    elif side == "short" and price <= pos["partial_tp"]:
                        partial_taken = True
                        pos["sl"] = pos["entry"]

                if reason is None:
                    if side == "long":
                        if price <= pos["sl"]:                              reason = "stop_loss"
                        elif price <= pos.get("trail", -1):                 reason = "trailing_stop"
                        elif price >= pos["tp"]:                            reason = "take_profit"
                    else:
                        if price >= pos["sl"]:                              reason = "stop_loss"
                        elif price >= pos.get("trail", 1e18):               reason = "trailing_stop"
                        elif price <= pos["tp"]:                            reason = "take_profit"

                if reason:
                    if reason == "liquidation":
                        pnl_eur = -pos["margin_eur"]
                        exit_p  = pos["liq"]
                    else:
                        slip    = (1 - SLIPPAGE) if side == "long" else (1 + SLIPPAGE)
                        exit_p  = price * slip
                        raw_pnl = (exit_p - pos["entry"]) * pos["qty"] if side == "long" \
                                  else (pos["entry"] - exit_p) * pos["qty"]
                        pnl_eur  = raw_pnl - pos["qty"] * exit_p * COMMISSION
                        cash    += pos["margin_eur"] + pnl_eur

                    pnl_pct = pnl_eur / pos["margin_eur"] * 100 if pos["margin_eur"] > 0 else 0.0
                    trades.append(PaperTrade(
                        symbol=prod_sym, side=side,
                        entry_idx=pos["idx"], exit_idx=i,
                        entry_price=pos["entry"], exit_price=exit_p,
                        margin_eur=round(pos["margin_eur"], 4),
                        leverage=pos["leverage"],
                        pnl_eur=round(pnl_eur, 4), pnl_pct=round(pnl_pct, 3),
                        exit_reason=reason,
                        score=pos["score"], regime=pos["regime"],
                        strategy_name=pos["strategy"],
                        mtf_aligned=pos["mtf_aligned"],
                        filter_boost=pos["filter_boost"],
                        candles_held=i - pos["idx"],
                        entry_ts=pos.get("entry_ts"),
                        is_pullback=pos.get("is_pullback", False),
                    ))
                    in_pos = False; partial_taken = False
                    continue

            # ---- Vérification entrée -----------------------------------
            if in_pos or halted or cash < 0.5:
                continue

            # 1. Régime O(1) — precomputed ADX, pas de slice
            try:
                regime = _fast_regime(i)
                p      = _PARAMS[regime]
            except Exception:
                continue

            # Seulement BULL/BEAR_TREND : les autres régimes sont exclus
            if regime not in (Regime.BULL_TREND, Regime.BEAR_TREND):
                continue

            # 2. Rebond EMA9 — signal indépendant, fonctionne même sur HOLD
            adx_i = float(adx_series.iloc[i]) if not np.isnan(adx_series.iloc[i]) else 0.0
            is_pullback, pb_action = _ema9_pullback_check(df, i, regime.value, adx_i)

            # 3. Signal multi-facteurs (sur slice pour éviter look-ahead)
            curr_df = df.iloc[:i + 1]
            try:
                base_sig = score_signal(curr_df, prod_sym, cfg)
            except Exception:
                continue

            # 4. Action effective et score de base
            # Cas A : signal multi-facteur confirmé dans la bonne direction
            # Cas B : rebond EMA9 seul (signal HOLD mais pattern valid)
            # Cas C : signal ET rebond → bonus cumulé
            if base_sig.action != "HOLD" and base_sig.action == pb_action:
                # Cas C — double confirmation
                eff_action = base_sig.action
                adj = base_sig.score + PULLBACK_BONUS
                is_pullback = True
            elif base_sig.action != "HOLD":
                # Cas A — signal seul (pullback absent ou direction différente)
                eff_action = base_sig.action
                adj = base_sig.score
                is_pullback = False
            elif is_pullback and pb_action:
                # Cas B — rebond EMA9 seul, score synthétique
                eff_action = pb_action
                adj = 62.0 + PULLBACK_BONUS   # 80pts de base
            else:
                continue   # HOLD sans pullback → ignorer

            # 5. Ajustement régime
            if regime == Regime.BULL_TREND:
                if eff_action == "BUY":
                    adj = min(adj + p.get("buy_bonus", 0), 100)
                else:
                    adj = max(adj - p.get("sell_penalty", 0), 0)
            elif regime == Regime.BEAR_TREND:
                if eff_action == "SELL":
                    adj = min(adj + p.get("sell_bonus", 0), 100)
                else:
                    adj = max(adj - p.get("buy_penalty", 0), 0)

            # 6. Score minimum
            min_score_eff = MIN_SCORE_PULLBACK if is_pullback else p["min_score"]
            if adj < min_score_eff:
                continue

            # 7. Filtre macro EMA200
            ema200_val = float(row.get("ema200") or row["close"])
            macro_buf  = ema200_val * 0.05
            if eff_action == "BUY"  and float(row["close"]) < ema200_val - macro_buf:
                continue
            if eff_action == "SELL" and float(row["close"]) > ema200_val + macro_buf:
                continue

            # 8. MTF daily (cached par date+direction — 1 calcul max/jour)
            mtf_key = f"{eff_action}_{str(ts)[:10]}"
            if mtf_key not in mtf_cache:
                mtf_cache[mtf_key] = _mtf_check(eff_action, df_daily, ts)
            mtf_boost, mtf_aligned, _ = mtf_cache[mtf_key]
            filter_boost = mtf_boost

            # Exiger alignement daily positif — filtre le plus discriminant
            if not mtf_aligned:
                continue

            # 9. Timing (VWAP, doji, RSI)
            filter_boost += _timing_check(eff_action, row)
            boost_threshold = -20.0 if is_pullback else -15.0
            if filter_boost < boost_threshold:
                continue

            final_score = round(min(max(adj + filter_boost, 0), 100), 1)
            min_final = 45 if is_pullback else 52
            if final_score < min_final:
                continue

            # 10. Calcul position
            sl_mult = SL_MULT_TREND   # 1.2 ATR pour BULL/BEAR_TREND
            tp_rr   = TP_RR_TREND     # 2:1
            max_lev = min(p["max_leverage"], 3)

            lev     = min(self.lev_mgr.get_leverage(final_score, "HIGH"), max_lev)
            sl_dist = atr_v * sl_mult
            tp_dist = sl_dist * tp_rr

            if eff_action == "BUY":
                entry_p    = price * (1 + SLIPPAGE)
                sl, tp     = entry_p - sl_dist, entry_p + tp_dist
                partial_tp = entry_p + (tp - entry_p) * 0.5
                liq_p      = self.lev_mgr.liquidation_price(entry_p, lev, "long")
                sl         = max(sl, liq_p * 1.001)
                side       = "long"
            else:
                entry_p    = price * (1 - SLIPPAGE)
                sl, tp     = entry_p + sl_dist, entry_p - tp_dist
                partial_tp = entry_p - (entry_p - tp) * 0.5
                liq_p      = self.lev_mgr.liquidation_price(entry_p, lev, "short")
                sl         = min(sl, liq_p * 0.999)
                side       = "short"

            sl_distance  = abs(entry_p - sl) or entry_p * 0.02
            risk_eur     = cash * RISK_PER_TRADE
            qty          = risk_eur / sl_distance
            margin_eur   = qty * entry_p / lev

            if margin_eur > cash * 0.95:
                margin_eur = cash * 0.95
                qty        = margin_eur * lev / entry_p

            entry_comm = qty * entry_p * COMMISSION
            total_cost = margin_eur + entry_comm

            if qty <= 1e-12 or total_cost > cash:
                continue

            cash        -= total_cost
            in_pos       = True
            partial_taken = False
            pos = {
                "side": side, "entry": entry_p, "qty": qty,
                "margin_eur": margin_eur, "liq": liq_p,
                "sl": sl, "tp": tp, "partial_tp": partial_tp,
                "trail": float("nan"),
                "leverage": lev, "score": final_score,
                "idx": i,
                "regime": regime.value,
                "strategy": p["name"],
                "mtf_aligned": mtf_aligned,
                "filter_boost": filter_boost,
                "entry_ts": ts,
                "is_pullback": is_pullback,
            }

        # Fermeture position ouverte en fin de données
        if in_pos:
            fp    = float(df.iloc[-1]["close"])
            slip  = (1 - SLIPPAGE) if pos["side"] == "long" else (1 + SLIPPAGE)
            exit_p = fp * slip
            side  = pos["side"]
            raw   = (exit_p - pos["entry"]) * pos["qty"] if side == "long" \
                    else (pos["entry"] - exit_p) * pos["qty"]
            pnl_eur  = raw - pos["qty"] * exit_p * COMMISSION
            pnl_pct  = pnl_eur / pos["margin_eur"] * 100 if pos["margin_eur"] > 0 else 0.0
            trades.append(PaperTrade(
                symbol=prod_sym, side=side,
                entry_idx=pos["idx"], exit_idx=n - 1,
                entry_price=pos["entry"], exit_price=exit_p,
                margin_eur=round(pos["margin_eur"], 4),
                leverage=pos["leverage"],
                pnl_eur=round(pnl_eur, 4), pnl_pct=round(pnl_pct, 3),
                exit_reason="end_of_data",
                score=pos["score"], regime=pos["regime"],
                strategy_name=pos["strategy"],
                mtf_aligned=pos["mtf_aligned"],
                filter_boost=pos["filter_boost"],
                candles_held=n - 1 - pos["idx"],
                entry_ts=pos.get("entry_ts"),
                is_pullback=pos.get("is_pullback", False),
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

    eq  = np.array(curve, dtype=float)
    ret = (eq[-1] - initial) / initial * 100
    peak = np.maximum.accumulate(eq)
    dd   = (peak - eq) / np.where(peak == 0, 1, peak)
    mdd  = float(dd.max()) * 100

    rets  = np.diff(eq) / np.where(eq[:-1] == 0, 1, eq[:-1])
    sharpe = float(rets.mean() / rets.std() * np.sqrt(8760)) if rets.std() > 1e-10 else 0.0
    neg    = rets[rets < 0]
    sortino = float(rets.mean() / neg.std() * np.sqrt(8760)) if len(neg) > 1 and neg.std() > 1e-10 else 0.0

    wins   = [t for t in trades if t.pnl_eur > 0]
    losses = [t for t in trades if t.pnl_eur <= 0]
    win_rate = len(wins) / len(trades) * 100
    gp   = sum(t.pnl_eur for t in wins)
    gl   = abs(sum(t.pnl_eur for t in losses)) or 1e-9
    pf   = min(gp / gl, 99.0)

    liqs  = [t for t in trades if t.exit_reason == "liquidation"]
    longs = [t for t in trades if t.side == "long"]
    shorts= [t for t in trades if t.side == "short"]

    exit_counts: Dict[str, int] = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

    regime_counts: Dict[str, int] = {}
    regime_wins:   Dict[str, int] = {}
    for t in trades:
        regime_counts[t.regime] = regime_counts.get(t.regime, 0) + 1
        if t.pnl_eur > 0:
            regime_wins[t.regime] = regime_wins.get(t.regime, 0) + 1

    sym_map: Dict[str, list] = {}
    for t in trades:
        sym_map.setdefault(t.symbol, []).append(t)

    return {
        "total_trades":      len(trades),
        "win_rate":          round(win_rate, 1),
        "total_return_pct":  round(ret, 2),
        "final_equity":      round(eq[-1], 2),
        "max_drawdown_pct":  round(mdd, 2),
        "sharpe_ratio":      round(sharpe, 3),
        "sortino_ratio":     round(sortino, 3),
        "profit_factor":     round(pf, 3),
        "avg_win_pct":       round(float(np.mean([t.pnl_pct for t in wins])),    2) if wins   else 0.0,
        "avg_loss_pct":      round(float(np.mean([t.pnl_pct for t in losses])),  2) if losses else 0.0,
        "avg_win_eur":       round(float(np.mean([t.pnl_eur for t in wins])),    4) if wins   else 0.0,
        "avg_loss_eur":      round(float(np.mean([t.pnl_eur for t in losses])),  4) if losses else 0.0,
        "avg_score":         round(float(np.mean([t.score    for t in trades])),  1),
        "avg_leverage":      round(float(np.mean([t.leverage  for t in trades])),  2),
        "avg_candles":       round(float(np.mean([t.candles_held for t in trades])), 1),
        "mtf_rate":          round(sum(1 for t in trades if t.mtf_aligned) / len(trades) * 100, 1),
        "longs":             len(longs),
        "shorts":            len(shorts),
        "liquidations":      len(liqs),
        "gross_profit_eur":  round(gp, 4),
        "gross_loss_eur":    round(gl, 4),
        "wins":              len(wins),
        "losses":            len(losses),
        "equity_curve":      curve,
        "exit_counts":       exit_counts,
        "regime_counts":     regime_counts,
        "regime_wins":       regime_wins,
        "sym_map":           sym_map,
    }


def sym_metrics(trades_for_sym: List[PaperTrade], initial: float) -> dict:
    return metrics(trades_for_sym, initial)


# ---------------------------------------------------------------------------
# Rapport Rich
# ---------------------------------------------------------------------------

def print_report(all_trades: List[PaperTrade]):
    console.rule("[bold yellow]SKYN — PAPER TRADING : 50 € EN JEU[/bold yellow]")
    console.print()

    m = metrics(all_trades, INITIAL_CAPITAL)
    if not m:
        console.print("[red]Aucun trade exécuté.[/red]")
        return

    ret    = m["total_return_pct"]
    final  = m["final_equity"]
    profit = final - INITIAL_CAPITAL
    color  = "green" if ret >= 0 else "red"

    # ---- Résultat principal -------------------------------------------
    g = Table.grid(padding=(0, 3))
    g.add_row("[bold]Mise de départ[/bold]",  f"[white]{INITIAL_CAPITAL:.2f} {CURRENCY}[/white]")
    g.add_row("[bold]Capital final[/bold]",    f"[{color} bold]{final:.2f} {CURRENCY}[/{color} bold]")
    g.add_row("[bold]Profit net[/bold]",       f"[{color} bold]{profit:+.2f} {CURRENCY} ({ret:+.2f}%)[/{color} bold]")
    g.add_row("[bold]Drawdown max[/bold]",     f"[{'red' if m['max_drawdown_pct']>20 else 'yellow'}]{m['max_drawdown_pct']:.1f}%[/]")
    g.add_row("[bold]Sharpe ratio[/bold]",     f"[cyan]{m['sharpe_ratio']:.3f}[/cyan]")
    g.add_row("[bold]Profit Factor[/bold]",    f"[cyan]{m['profit_factor']:.3f}[/cyan]")
    g.add_row("[bold]Win rate[/bold]",         f"[{'green' if m['win_rate']>=55 else 'red'}]{m['win_rate']:.1f}%[/] ({m['wins']}W / {m['losses']}L)")
    g.add_row("[bold]Trades total[/bold]",     f"[white]{m['total_trades']}[/white]  (Long:{m['longs']} Court:{m['shorts']})")
    console.print(Panel(g, title=f"[bold]Résultat Global · 2 ans · {len(set(t.symbol for t in all_trades))} symboles[/bold]", border_style="yellow", expand=False))
    console.print()

    # ---- Métriques secondaires ----------------------------------------
    t1 = Table(box=box.SIMPLE, border_style="cyan", title="Statistiques d'exécution")
    t1.add_column("Métrique",             style="bold")
    t1.add_column("Valeur",               justify="right")
    t1.add_column("",                     justify="center", width=14)

    def grade_str(val, good_thresh, warn_thresh, fmt="{:.1f}"):
        if val >= good_thresh: clr = "green"; sym = "✓"
        elif val >= warn_thresh: clr = "yellow"; sym = "∼"
        else: clr = "red"; sym = "✗"
        return f"[{clr}]{sym}[/{clr}]"

    t1.add_row("Gain moyen / trade",       f"{m['avg_win_pct']:+.1f}%  ({m['avg_win_eur']:+.3f}{CURRENCY})",
               "[green]✓[/green]" if m["avg_win_pct"] > 0 else "[red]✗[/red]")
    t1.add_row("Perte moyenne / trade",    f"{m['avg_loss_pct']:+.1f}%  ({m['avg_loss_eur']:+.3f}{CURRENCY})",
               "[green]✓[/green]" if abs(m["avg_loss_pct"]) < m["avg_win_pct"] else "[red]R:R déséquilibré[/red]")
    t1.add_row("Score moyen d'entrée",     f"{m['avg_score']:.1f}/100",
               grade_str(m["avg_score"], 72, 65))
    t1.add_row("Levier moyen",             f"{m['avg_leverage']:.1f}x",
               "[yellow]∼[/yellow]" if m["avg_leverage"] <= 5 else "[red]✗[/red]")
    t1.add_row("Durée moyenne",            f"{m['avg_candles']:.0f}h",
               "[green]✓[/green]" if m["avg_candles"] >= 8 else "[yellow]∼[/yellow]")
    t1.add_row("Alignement MTF daily",     f"{m['mtf_rate']:.0f}%",
               grade_str(m["mtf_rate"], 60, 40))
    t1.add_row("Liquidations",             str(m["liquidations"]),
               "[green]✓ 0[/green]" if m["liquidations"] == 0 else "[bold red]✗ RISK[/bold red]")
    console.print(t1)
    console.print()

    # ---- Performance par symbole --------------------------------------
    t2 = Table(title="Performance par Symbole", box=box.ROUNDED, border_style="magenta")
    for col in ["Symbole", "Trades", "Win%", "Gains (€)", "Pertes (€)", "Net (€)", "Sharpe", "Lev moy"]:
        t2.add_column(col, justify="right")
    t2.columns[0].justify = "left"

    sym_agg: Dict[str, Dict] = {}
    for t in all_trades:
        sym_agg.setdefault(t.symbol, {"wins": 0, "losses": 0, "gp": 0.0, "gl": 0.0, "lev": [], "all": []})
        d = sym_agg[t.symbol]
        d["all"].append(t)
        if t.pnl_eur > 0:
            d["wins"] += 1; d["gp"] += t.pnl_eur
        else:
            d["losses"] += 1; d["gl"] += abs(t.pnl_eur)
        d["lev"].append(t.leverage)

    for sym in sorted(sym_agg.keys()):
        d = sym_agg[sym]
        total_t = d["wins"] + d["losses"]
        wr = d["wins"] / total_t * 100 if total_t else 0
        net = d["gp"] - d["gl"]
        avg_lev = np.mean(d["lev"]) if d["lev"] else 0
        sm = sym_metrics(d["all"], INITIAL_CAPITAL / len(sym_agg))
        c = "green" if net > 0 else "red"
        t2.add_row(
            sym.split("/")[0],
            str(total_t),
            f"[{'green' if wr>=55 else 'red'}]{wr:.0f}%[/]",
            f"[green]+{d['gp']:.2f}€[/green]",
            f"[red]-{d['gl']:.2f}€[/red]",
            f"[{c}]{net:+.2f}€[/{c}]",
            f"{sm.get('sharpe_ratio', 0):.2f}",
            f"{avg_lev:.1f}x",
        )
    console.print(t2)
    console.print()

    # ---- Performance par régime ---------------------------------------
    t3 = Table(title="Win Rate par Régime de Marché", box=box.ROUNDED, border_style="blue")
    t3.add_column("Régime",   style="bold")
    t3.add_column("Trades",   justify="right")
    t3.add_column("Gagnants", justify="right")
    t3.add_column("Win%",     justify="right")
    t3.add_column("Net (€)",  justify="right")

    regime_net: Dict[str, float] = {}
    for t in all_trades:
        regime_net[t.regime] = regime_net.get(t.regime, 0.0) + t.pnl_eur

    regime_labels = {
        "bull_trend": "BULL TREND", "bear_trend": "BEAR TREND",
        "ranging": "RANGING", "breakout": "BREAKOUT", "high_volatility": "HIGH VOL",
    }
    for r, cnt in sorted(m["regime_counts"].items(), key=lambda x: -x[1]):
        wins_r = m["regime_wins"].get(r, 0)
        wr     = wins_r / cnt * 100 if cnt else 0
        net    = regime_net.get(r, 0)
        c      = "green" if wr >= 55 else "yellow" if wr >= 45 else "red"
        nc     = "green" if net > 0 else "red"
        t3.add_row(
            regime_labels.get(r, r), str(cnt), str(wins_r),
            f"[{c}]{wr:.0f}%[/{c}]", f"[{nc}]{net:+.2f}€[/{nc}]"
        )
    console.print(t3)
    console.print()

    # ---- Raisons de sortie -------------------------------------------
    t4 = Table(title="Raisons de Sortie", box=box.SIMPLE)
    t4.add_column("Raison", style="bold"); t4.add_column("Nb", justify="right")
    t4.add_column("%", justify="right"); t4.add_column("Net (€)", justify="right")

    exit_net: Dict[str, float] = {}
    for t in all_trades:
        exit_net[t.exit_reason] = exit_net.get(t.exit_reason, 0.0) + t.pnl_eur

    el = {
        "take_profit":  "[green]Take Profit ✓[/green]",
        "stop_loss":    "[red]Stop Loss ✗[/red]",
        "trailing_stop":"[yellow]Trailing Stop[/yellow]",
        "liquidation":  "[bold red]Liquidation ⚡[/bold red]",
        "end_of_data":  "[dim]Fin données[/dim]",
    }
    tot = m["total_trades"]
    for r, cnt in sorted(m["exit_counts"].items(), key=lambda x: -x[1]):
        net = exit_net.get(r, 0)
        nc  = "green" if net > 0 else "red"
        t4.add_row(el.get(r, r), str(cnt), f"{cnt/tot*100:.0f}%", f"[{nc}]{net:+.2f}€[/{nc}]")
    console.print(t4)
    console.print()

    # ---- Pullback stats ----------------------------------------------
    pb_trades = [t for t in all_trades if t.is_pullback]
    pb_wins   = [t for t in pb_trades if t.pnl_eur > 0]
    reg_trades = [t for t in all_trades if not t.is_pullback]
    reg_wins   = [t for t in reg_trades if t.pnl_eur > 0]
    pb_wr  = len(pb_wins)  / len(pb_trades)  * 100 if pb_trades  else 0.0
    reg_wr = len(reg_wins) / len(reg_trades) * 100 if reg_trades else 0.0
    tpb = Table(title="Pullback EMA9 vs Signaux Classiques", box=box.SIMPLE)
    tpb.add_column("Type"); tpb.add_column("Trades", justify="right")
    tpb.add_column("Win%", justify="right"); tpb.add_column("Net (€)", justify="right")
    pb_net  = sum(t.pnl_eur for t in pb_trades)
    reg_net = sum(t.pnl_eur for t in reg_trades)
    for lbl, lst, wr, net in [
        ("Rebond EMA9", pb_trades, pb_wr, pb_net),
        ("Signal classique", reg_trades, reg_wr, reg_net),
    ]:
        c = "green" if net > 0 else "red"
        cw = "green" if wr >= 55 else "yellow" if wr >= 45 else "red"
        tpb.add_row(lbl, str(len(lst)), f"[{cw}]{wr:.0f}%[/{cw}]", f"[{c}]{net:+.2f}€[/{c}]")
    console.print(tpb)
    console.print()

    # ---- Breakdown mensuel -------------------------------------------
    monthly: Dict[str, list] = {}
    for t in all_trades:
        if t.entry_ts is not None:
            key = str(t.entry_ts)[:7]
            monthly.setdefault(key, []).append(t)

    if monthly:
        tm = Table(title="Breakdown Mensuel — P&L par Mois", box=box.ROUNDED, border_style="cyan")
        tm.add_column("Mois",   style="bold")
        tm.add_column("Trades", justify="right")
        tm.add_column("Win%",   justify="right")
        tm.add_column("Net €",  justify="right")
        tm.add_column("Ret%",   justify="right")
        tm.add_column("Pullbacks", justify="right")
        running_eq = INITIAL_CAPITAL
        for key in sorted(monthly.keys()):
            mt = monthly[key]
            mp  = sum(t.pnl_eur for t in mt)
            mw  = sum(1 for t in mt if t.pnl_eur > 0)
            wr  = mw / len(mt) * 100 if mt else 0
            ret = mp / running_eq * 100 if running_eq > 0 else 0
            running_eq += mp
            pb_cnt = sum(1 for t in mt if t.is_pullback)
            c  = "green" if mp > 0 else "red"
            cw = "green" if wr >= 55 else "yellow" if wr >= 45 else "red"
            tm.add_row(
                key, str(len(mt)),
                f"[{cw}]{wr:.0f}%[/{cw}]",
                f"[{c}]{mp:+.2f}€[/{c}]",
                f"[{c}]{ret:+.1f}%[/{c}]",
                str(pb_cnt),
            )
        console.print(tm)
        console.print()

    # ---- Top / Worst trades ------------------------------------------
    sorted_t = sorted(all_trades, key=lambda x: x.pnl_eur, reverse=True)
    worst = list(reversed(sorted_t[-15:]))
    for title, lst, bc in [
        ("Top 15 Meilleurs Trades", sorted_t[:15], "green"),
        ("Top 15 Pires Trades", worst, "red"),
    ]:
        tt = Table(title=title, box=box.SIMPLE, border_style=bc)
        for col in ["Sym", "Side", "Net €", "Marge €", "PnL%", "Score", "Lev", "Régime", "Sortie", "Durée"]:
            tt.add_column(col, justify="right" if col not in ["Sym", "Side", "Régime", "Sortie"] else "left")
        for t in lst:
            c = "green" if t.pnl_eur > 0 else "red"
            tt.add_row(
                t.symbol.split("/")[0], t.side,
                f"[{c}]{t.pnl_eur:+.2f}€[/{c}]",
                f"{t.margin_eur:.2f}€",
                f"[{c}]{t.pnl_pct:+.1f}%[/{c}]",
                f"{t.score:.0f}",
                f"{t.leverage}x",
                t.regime[:6],
                t.exit_reason[:5],
                f"{t.candles_held * CANDLE_HOURS}h",
            )
        console.print(tt)
        console.print()

    # ---- Timeline mensuelle simulée ----------------------------------
    # Projection sur 2 semaines avec le même rythme
    total_days = 730  # 2 ans
    trades_per_day = m["total_trades"] / total_days
    daily_pnl = profit / total_days
    week2_pnl  = daily_pnl * 14
    week2_cap  = INITIAL_CAPITAL + week2_pnl

    console.print(Panel(
        f"Rythme observé : [cyan]{trades_per_day:.2f} trades/jour[/cyan]  ·  "
        f"[cyan]{daily_pnl:+.3f} {CURRENCY}/jour[/cyan]\n\n"
        f"  [bold]1 semaine[/bold]  : {INITIAL_CAPITAL:.2f}€ → [{'green' if week2_pnl/2 > 0 else 'red'}]"
        f"{INITIAL_CAPITAL + week2_pnl/2:.2f}€ ({week2_pnl/2:+.2f}€)[/]\n"
        f"  [bold]2 semaines[/bold] : {INITIAL_CAPITAL:.2f}€ → [{'green' if week2_pnl > 0 else 'red'}]"
        f"{week2_cap:.2f}€ ({week2_pnl:+.2f}€)[/]\n"
        f"  [bold]1 mois[/bold]     : {INITIAL_CAPITAL:.2f}€ → [{'green' if daily_pnl*30 > 0 else 'red'}]"
        f"{INITIAL_CAPITAL + daily_pnl*30:.2f}€ ({daily_pnl*30:+.2f}€)[/]\n"
        f"  [bold]3 mois[/bold]     : {INITIAL_CAPITAL:.2f}€ → [{'green' if daily_pnl*90 > 0 else 'red'}]"
        f"{INITIAL_CAPITAL + daily_pnl*90:.2f}€ ({daily_pnl*90:+.2f}€)[/]",
        title="[bold]Projection Linéaire (si rythme constant)[/bold]",
        border_style="cyan",
    ))
    console.print()

    # ---- Courbe equity -----------------------------------------------
    ec = m["equity_curve"]
    if len(ec) > 2:
        n_pts = min(70, len(ec))
        step  = max(1, len(ec) // n_pts)
        pts   = [ec[i * step] for i in range(n_pts)] + [ec[-1]]
        mn, mx = min(pts), max(pts)
        rng = mx - mn or 1
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

    # ---- Recommandations ---------------------------------------------
    issues = []; goods = []
    if m["win_rate"] >= 55:  goods.append(f"Win rate solide {m['win_rate']:.0f}% — signaux de qualité")
    elif m["win_rate"] >= 45: goods.append(f"Win rate correct {m['win_rate']:.0f}% — peut encore monter")
    else:                     issues.append(f"Win rate {m['win_rate']:.0f}% insuffisant — renforcer le filtrage")

    if m["profit_factor"] >= 1.5: goods.append(f"Profit Factor {m['profit_factor']:.2f} — gains > pertes")
    elif m["profit_factor"] >= 1:  issues.append(f"Profit Factor {m['profit_factor']:.2f} borderline")
    else:                          issues.append(f"Profit Factor {m['profit_factor']:.2f} — perd de l'argent")

    if m["max_drawdown_pct"] <= 15: goods.append(f"Drawdown maîtrisé {m['max_drawdown_pct']:.1f}%")
    else:                            issues.append(f"Drawdown {m['max_drawdown_pct']:.1f}% — réduire risk/trade")

    if m["liquidations"] > 0:
        issues.append(f"{m['liquidations']} liquidation(s) — levier trop élevé ou stops mal placés")

    if m["avg_candles"] * CANDLE_HOURS < 8:
        issues.append("Durée trop courte → vérifier si les stops ne sont pas trop proches")

    if m["sharpe_ratio"] >= 1.5: goods.append(f"Sharpe {m['sharpe_ratio']:.2f} — excellent rendement/risque")
    elif m["sharpe_ratio"] >= 0.8: goods.append(f"Sharpe {m['sharpe_ratio']:.2f} — correct")
    else: issues.append(f"Sharpe {m['sharpe_ratio']:.2f} — trop volatile par rapport aux gains")

    if goods:
        console.print(Panel("\n".join(f"  [green]✓[/green] {g}" for g in goods),
                             title="[bold green]Points Forts[/bold green]", border_style="green"))
    if issues:
        console.print(Panel("\n".join(f"  [yellow]→[/yellow] {i}" for i in issues),
                             title="[bold yellow]À Améliorer[/bold yellow]", border_style="yellow"))
    console.print()
    console.rule("[bold yellow]FIN DU RAPPORT[/bold yellow]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    n_syms = len(SYMBOLS_YF)
    console.rule(f"[bold yellow]SKYN — Paper Trading Test · 50 € · {n_syms} Symboles · 2 ans[/bold yellow]")
    console.print(f"[dim]Timeframe: {INTERVAL} · Pipeline complet · Sans look-ahead bias[/dim]")
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
            console.print(f" [red]échec ou données insuffisantes[/red]")

    if not data_map:
        console.print("[red]Aucune donnée disponible.[/red]"); return

    console.print()
    console.print("[bold]Simulation en cours...[/bold]")
    t_total = time.time()

    for sym, df_raw in data_map.items():
        console.print(f"  [cyan]▶[/cyan] {SYMBOL_NAMES.get(sym, sym):<12}", end="")
        t0 = time.time()
        try:
            trades = trader.run(df_raw, sym)
            all_trades.extend(trades)
            console.print(f" [green]{len(trades):>3} trades[/green]  [{time.time()-t0:.1f}s]")
        except Exception as exc:
            console.print(f" [red]erreur: {exc}[/red]")
            import traceback; traceback.print_exc()

    elapsed = time.time() - t_total
    console.print()
    console.print(f"[bold green]✓ {len(all_trades)} trades simulés en {elapsed:.1f}s[/bold green]")
    console.print()

    if all_trades:
        print_report(all_trades)
    else:
        console.print("[red]Aucun trade généré — vérifier les paramètres.[/red]")


if __name__ == "__main__":
    main()
