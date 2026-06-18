#!/usr/bin/env python3
"""
SKYN v6 — SCALP FILTRE LASER (5 Couches)
=========================================
Stratégie ultra-sélective qui prédit les explosions avant qu'elles se produisent.

5 filtres en cascade :
  1. BB Squeeze prolongé (≥5 barres)    → compression = énergie accumulée
  2. Score consensus ≥ 80               → momentum multi-signal aligné
  3. Funding Rate Proxy                 → marché mal positionné = squeeze imminent
  4. OI Proxy (volume monte pendant sq) → accumulation silencieuse = smart money
  5. Clôture confirmée au-delà des BB   → breakout réel, pas faux signal

Position sizing intelligent :
  - 3 filtres passés → risk 3%
  - 4 filtres passés → risk 3.8%
  - 5 filtres passés (setup parfait) → risk 5%
  - Levier 5-10x auto selon score (5x@80, 7x@85, 10x@90+)
  - SL serré 0.4% — liquidation à -10%/lev : impossible à atteindre
  - TP 4% (10:1 RR)
  - Max 3 positions simultanées (qualité > quantité)

Vérification SL/TP sur range HIGH/LOW de la bougie (plus précis pour SL serrés).

Veille continue : état actuel de tous les symboles (dashboard temps réel)

Usage :
    cd /home/user/profit-engine/backend
    python paper_test_v6.py
"""
from __future__ import annotations

import sys, os, math, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
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

# ── Capital ───────────────────────────────────────────────────────────────────
INITIAL_CAPITAL   = 50.0
INTERVAL          = "1h"
PERIOD            = "2y"
WARMUP            = 220
N_MAX_POSITIONS   = 3          # ultra-sélectif

# ── Risk uniforme (le levier auto est l'amplificateur, pas le risk) ──────────
RISK_3F = 0.040   # risque fixe 4% pour tous — levier = seul amplificateur
RISK_4F = 0.040
RISK_5F = 0.055   # bonus si setup parfait 5/5 (rarement atteint)

# ── Levier auto selon score ───────────────────────────────────────────────────
LEV_80  = 5    # score 80-84
LEV_85  = 7    # score 85-89
LEV_90  = 10   # score 90+

# ── SL / TP en % fixe ────────────────────────────────────────────────────────
SL_PCT          = 0.004    # 0.4% — SL serré, loin de la liquidation (>10x éloignée)
TP_PCT          = 0.040    # 4.0% — 10:1 RR
PARTIAL_TP_FRAC = 0.55     # breakeven quand prix atteint 55% du chemin vers TP

# ── BB Squeeze (plus strict qu'en v5) ────────────────────────────────────────
BB_SQUEEZE_WINDOW = 30
BB_SQUEEZE_PCT    = 0.10   # 10e percentile (vs 15e en v5)
MIN_SQUEEZE_BARS  = 5      # tenir 5+ barres (vs 3 en v5)
VOL_SURGE_MIN     = 4.0    # volume 4× (vs 3.2× en v5)
BO_BODY_PCT_MIN   = 0.50   # corps bougie ≥ 50%
ADX_RISE_MIN      = 3.0
MIN_ADX_BO        = 16

# ── Score seuil ───────────────────────────────────────────────────────────────
SCORE_MIN = 80             # seulement le top (vs 70 en v5)

# ── Funding Rate Proxy ────────────────────────────────────────────────────────
# Prix sous MA48h → shorts dominant → potentiel short squeeze → BUY
# Prix sur MA48h  → longs dominant  → potentiel long squeeze  → SELL
FUNDING_MA_BARS   = 48     # 2 jours de barres 1h
FUNDING_DEV_BUY   = -0.012 # prix -1.2% sous MA = shorts chargés → signal BUY
FUNDING_DEV_SELL  =  0.012 # prix +1.2% sur MA  = longs chargés  → signal SELL

# ── OI Proxy (volume montant pendant le squeeze) ──────────────────────────────
OI_VOL_LOOKBACK = 8        # dernières 8 barres
OI_VOL_RATIO    = 1.35     # volume moyen pendant sq > 135% du volume normal

# ── Cooldown ──────────────────────────────────────────────────────────────────
BO_COOLDOWN_H = 4

# ── Frais ─────────────────────────────────────────────────────────────────────
COMMISSION       = 0.0004
SLIPPAGE         = 0.0005
DAILY_LOSS_LIMIT = 0.12


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
    filters:      int      # nombre de filtres passés (3, 4 ou 5)
    candles_held: int


# ── Symbol Precomputation ─────────────────────────────────────────────────────

def precompute_symbol(sym: str, cfg) -> Optional[dict]:
    raw = download_data(sym)
    if raw is None:
        return None

    df = compute_all(raw.copy(), cfg.strategy)
    df_daily = resample_daily(df)

    # BB Width
    if "bb_upper" not in df.columns:
        p = 20; k = 2.0
        df["bb_mid"]   = df["close"].rolling(p).mean()
        df["bb_upper"] = df["bb_mid"] + k * df["close"].rolling(p).std()
        df["bb_lower"] = df["bb_mid"] - k * df["close"].rolling(p).std()
    df["bbw"]      = ((df["bb_upper"] - df["bb_lower"]) /
                      df["bb_mid"].replace(0, np.nan)).fillna(1.0)
    df["bbw_q10"]  = df["bbw"].rolling(BB_SQUEEZE_WINDOW).quantile(BB_SQUEEZE_PCT).fillna(df["bbw"])

    df["macd_hist_slope"] = df["macd_hist"].diff().fillna(0)
    df["obv_slope"]       = df["obv"].diff(5).fillna(0)

    # Funding Rate Proxy : déviation du prix par rapport à MA48
    df["ma48"]            = df["close"].rolling(FUNDING_MA_BARS).mean()
    df["funding_dev"]     = (df["close"] - df["ma48"]) / df["ma48"].replace(0, np.nan)

    # OI Proxy : ratio volume moyen sur dernières N barres vs baseline
    vol_baseline          = df["volume"].rolling(50).mean().replace(0, np.nan)
    df["vol_oi_ratio"]    = df["volume"].rolling(OI_VOL_LOOKBACK).mean() / vol_baseline

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
        sk = _sk[ii]; sd_v = _sd[ii]
        if sk > sd_v and sk < 75: _b += 10
        elif sk < sd_v and sk > 25: _s += 10
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
        "name":       SYMBOL_MAP.get(sym, sym),
        "df":         df,
        "df_daily":   df_daily,
        "adx_s":      adx_series,
        "di_p_s":     di_p_series,
        "di_m_s":     di_m_series,
        "buy_sc":     buy_sc,
        "sell_sc":    sell_sc,
        "ts_to_pos":  ts_to_pos,
        "ts_index":   df.index,
    }


# ── 5-Layer Filter ────────────────────────────────────────────────────────────

def _five_layer_filter(sd: dict, bar: int, adx_val: float, adx_series: pd.Series
                        ) -> Tuple[int, Optional[str]]:
    """
    Returns (filters_passed: 0-5, action: "BUY"|"SELL"|None).
    Minimum 3 filters must pass to trade.
    """
    if bar < BB_SQUEEZE_WINDOW + 10:
        return 0, None

    df   = sd["df"]
    last = df.iloc[bar]

    try:
        price    = float(last["close"])
        open_p   = float(last["open"])
        high_p   = float(last["high"])
        low_p    = float(last["low"])
        vol_r    = float(last.get("vol_ratio", 1.0) or 1.0)
        bb_upper = float(last.get("bb_upper", 0) or 0)
        bb_lower = float(last.get("bb_lower", 0) or 0)
        bb_mid   = float(last.get("bb_mid",   0) or 0)
        cur_bbw  = float(last.get("bbw",     1.0) or 1.0)
        q10_thr  = float(last.get("bbw_q10", 1.0) or 1.0)
        fund_dev = float(last.get("funding_dev", 0.0) or 0.0)
        oi_ratio = float(last.get("vol_oi_ratio", 1.0) or 1.0)
    except (TypeError, ValueError, KeyError):
        return 0, None

    if bb_upper <= 0 or bb_lower <= 0 or bb_mid <= 0:
        return 0, None
    if adx_val < MIN_ADX_BO:
        return 0, None

    # ── Filter 1 : BB Squeeze prolongé ────────────────────────────────────────
    recent = df.iloc[max(0, bar - 10):bar]
    if len(recent) < MIN_SQUEEZE_BARS:
        return 0, None
    bbw_vals = recent["bbw"].values
    q10_vals = recent["bbw_q10"].values
    n_sq = int(np.sum(bbw_vals < q10_vals * 1.05))
    if n_sq < MIN_SQUEEZE_BARS:
        return 0, None
    # Squeeze qui s'élargit maintenant (breakout en cours)
    min_recent_bbw = float(recent["bbw"].min())
    if cur_bbw < min_recent_bbw * 1.15:
        return 0, None
    f1 = True

    # Bougie de breakout confirmée
    if vol_r < VOL_SURGE_MIN:
        return 0, None
    rng  = high_p - low_p
    body = abs(price - open_p)
    if rng > 0 and body / rng < BO_BODY_PCT_MIN:
        return 0, None

    # Direction du breakout (filtre ADX accélération)
    if bar >= 5 and not np.isnan(adx_series.iloc[bar - 5]):
        adx_5 = float(adx_series.iloc[bar - 5])
        if adx_val < adx_5 + ADX_RISE_MIN:
            return 0, None

    # ── Déterminer direction (BUY/SELL) ───────────────────────────────────────
    buy_score  = int(sd["buy_sc"][bar])
    sell_score = int(sd["sell_sc"][bar])

    is_buy  = price > bb_upper * 1.001 and price > open_p and buy_score  >= SCORE_MIN
    is_sell = price < bb_lower * 0.999 and price < open_p and sell_score >= SCORE_MIN

    if not is_buy and not is_sell:
        return 0, None

    action    = "BUY" if is_buy else "SELL"
    dir_score = buy_score if is_buy else sell_score

    # ── Filter 2 : Score ≥ 80 ─────────────────────────────────────────────────
    f2 = dir_score >= SCORE_MIN

    # ── Filter 3 : Funding Rate Proxy ─────────────────────────────────────────
    if action == "BUY":
        f3 = fund_dev <= FUNDING_DEV_BUY   # prix déprimé = shorts chargés = squeeze BUY
    else:
        f3 = fund_dev >= FUNDING_DEV_SELL  # prix élevé = longs chargés = squeeze SELL

    # ── Filter 4 : OI Proxy (volume montant pendant squeeze) ──────────────────
    f4 = oi_ratio >= OI_VOL_RATIO

    # ── Filter 5 : Clôture CLAIREMENT au-delà des BB (breakout réel) ─────────
    if action == "BUY":
        f5 = price > bb_upper * 1.003    # 0.3% au-delà, pas juste toucher
    else:
        f5 = price < bb_lower * 0.997

    filters = sum([f1, f2, f3, f4, f5])

    if filters < 3:
        return 0, None

    return filters, action


# ── Multi-Position Engine ─────────────────────────────────────────────────────

class LaserEngine:
    """
    Capital unique, boucle synchronisée.
    Entrées ultra-sélectives à 3-5 filtres, levier 5-10x, SL serré.
    Vérification SL/TP sur HIGH/LOW de la bougie (précision accrue).
    """

    def __init__(self, sym_data: dict):
        self.sym_data = sym_data
        self.lev_mgr  = LeverageManager()

    def _get_leverage(self, score: int) -> int:
        if score >= 90: return LEV_90
        if score >= 85: return LEV_85
        return LEV_80

    def _get_risk(self, filters: int) -> float:
        if filters >= 5: return RISK_5F
        if filters >= 4: return RISK_4F
        return RISK_3F

    def _try_enter(self, sym: str, action: str, filters: int, score: int,
                   bar: int, ts: pd.Timestamp,
                   available_cash: float, total_equity: float) -> Optional[dict]:
        sd  = self.sym_data[sym]
        row = sd["df"].iloc[bar]
        price = float(row["close"])

        lev       = self._get_leverage(score)
        risk_frac = self._get_risk(filters)
        risk_eur  = total_equity * risk_frac

        if action == "BUY":
            entry_p    = price * (1 + SLIPPAGE)
            sl         = entry_p * (1 - SL_PCT)
            tp         = entry_p * (1 + TP_PCT)
            partial_tp = entry_p * (1 + TP_PCT * PARTIAL_TP_FRAC)
            liq_p      = self.lev_mgr.liquidation_price(entry_p, lev, "long")
            sl         = max(sl, liq_p * 1.001)
            side       = "long"
        else:
            entry_p    = price * (1 - SLIPPAGE)
            sl         = entry_p * (1 + SL_PCT)
            tp         = entry_p * (1 - TP_PCT)
            partial_tp = entry_p * (1 - TP_PCT * PARTIAL_TP_FRAC)
            liq_p      = self.lev_mgr.liquidation_price(entry_p, lev, "short")
            sl         = min(sl, liq_p * 0.999)
            side       = "short"

        sl_distance = abs(entry_p - sl) or entry_p * SL_PCT
        qty         = risk_eur / sl_distance
        margin_eur  = qty * entry_p / lev

        # Cap margin à 90% du cash disponible
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
            "leverage": lev, "score": score, "filters": filters,
            "entry_ts": ts, "entry_bar": bar,
            "partial_taken": False,
            "total_cost": total_cost,
        }

    def _check_exit(self, pos: dict, row: pd.Series,
                    ts: pd.Timestamp) -> Optional[Tuple[float, float, str]]:
        """
        Vérifie SL/TP sur le HIGH/LOW de la bougie pour précision maximale
        sur des stops serrés. Priorité : liquidation > SL > TP.
        """
        side   = pos["side"]
        high_p = float(row.get("high", row["close"]))
        low_p  = float(row.get("low",  row["close"]))

        reason = None

        # Liquidation (cas extrême)
        if side == "long"  and low_p  <= pos["liq"]: reason = "liquidation"
        elif side == "short" and high_p >= pos["liq"]: reason = "liquidation"

        if reason is None:
            # SL check sur range (conservateur)
            if side == "long"  and low_p  <= pos["sl"]: reason = "stop_loss"
            elif side == "short" and high_p >= pos["sl"]: reason = "stop_loss"

        # Partial TP → breakeven (exécuté avant vérification TP)
        if reason is None and not pos.get("partial_taken"):
            if side == "long"  and high_p >= pos["partial_tp"]:
                pos["partial_taken"] = True; pos["sl"] = pos["entry"]
            elif side == "short" and low_p  <= pos["partial_tp"]:
                pos["partial_taken"] = True; pos["sl"] = pos["entry"]

        if reason is None:
            # TP check sur range
            if side == "long"  and high_p >= pos["tp"]: reason = "take_profit"
            elif side == "short" and low_p  <= pos["tp"]: reason = "take_profit"

        if reason is None:
            return None

        if reason == "liquidation":
            return -pos["margin_eur"], pos["liq"], reason

        exit_target = pos["tp"] if reason == "take_profit" else pos["sl"]
        # Slippage défavorable sur SL (rempli plus loin dans la direction défavorable)
        if reason == "stop_loss":
            exit_p = exit_target * (1 + SLIPPAGE) if side == "long" else exit_target * (1 - SLIPPAGE)
        else:
            exit_p = exit_target * (1 - SLIPPAGE) if side == "long" else exit_target * (1 + SLIPPAGE)

        raw = (exit_p - pos["entry"]) * pos["qty"] if side == "long" \
              else (pos["entry"] - exit_p) * pos["qty"]
        pnl = raw - pos["qty"] * exit_p * COMMISSION
        return pnl, exit_p, reason

    def run(self, common_timestamps: List[pd.Timestamp]) -> Tuple[List[PaperTrade], list, dict]:
        available_cash  = INITIAL_CAPITAL
        positions:      Dict[str, dict] = {}
        bo_cooldowns:   Dict[str, pd.Timestamp] = {}
        all_trades:     List[PaperTrade] = []
        equity_curve    = []

        current_day      = None
        day_start_equity = INITIAL_CAPITAL
        day_halted       = False
        day_wins:        Dict[str, list] = {}

        for ts in common_timestamps:
            day_key  = str(ts)[:10]
            total_eq = available_cash + sum(p["margin_eur"] for p in positions.values())

            if day_key != current_day:
                current_day      = day_key
                day_start_equity = total_eq
                day_halted       = False

            if not day_halted and day_start_equity > 0:
                if (day_start_equity - total_eq) / day_start_equity >= DAILY_LOSS_LIMIT:
                    day_halted = True

            # ── Step 1 : Exits ────────────────────────────────────────────────
            for sym in list(positions.keys()):
                sd  = self.sym_data.get(sym)
                if sd is None: continue
                bar = sd["ts_to_pos"].get(ts)
                if bar is None: continue
                row = sd["df"].iloc[bar]
                pos = positions[sym]

                result = self._check_exit(pos, row, ts)
                if result is None:
                    continue

                pnl_eur, exit_p, reason = result
                available_cash += pos["margin_eur"] + pnl_eur
                pnl_pct = pnl_eur / pos["margin_eur"] * 100 if pos["margin_eur"] > 0 else 0

                all_trades.append(PaperTrade(
                    symbol=sd["name"], side=pos["side"],
                    entry_ts=pos["entry_ts"], exit_ts=ts,
                    entry_price=pos["entry"], exit_price=exit_p,
                    margin_eur=round(pos["margin_eur"], 4),
                    leverage=pos["leverage"],
                    pnl_eur=round(pnl_eur, 4), pnl_pct=round(pnl_pct, 3),
                    exit_reason=reason, score=pos["score"],
                    filters=pos["filters"],
                    candles_held=bar - pos["entry_bar"],
                ))

                if pnl_eur > 0:
                    day_wins.setdefault(day_key, []).append(sym)
                if pnl_eur < 0:
                    bo_cooldowns[sym] = ts + pd.Timedelta(hours=BO_COOLDOWN_H)
                del positions[sym]

            total_eq = available_cash + sum(p["margin_eur"] for p in positions.values())
            equity_curve.append((ts, total_eq))

            # ── Step 2 : Entries ──────────────────────────────────────────────
            slots_free = N_MAX_POSITIONS - len(positions)
            if slots_free <= 0 or day_halted or available_cash < 1.0:
                continue

            candidates = []
            for sym, sd in self.sym_data.items():
                if sym in positions: continue
                bar = sd["ts_to_pos"].get(ts)
                if bar is None or bar < WARMUP: continue
                cd = bo_cooldowns.get(sym)
                if cd is not None and ts < cd: continue

                adx_i = float(sd["adx_s"].iloc[bar]) if not np.isnan(sd["adx_s"].iloc[bar]) else 0.0

                filters_n, action = _five_layer_filter(sd, bar, adx_i, sd["adx_s"])
                if filters_n < 3 or action is None:
                    continue

                dir_sc = int(sd["buy_sc"][bar]) if action == "BUY" else int(sd["sell_sc"][bar])
                candidates.append({
                    "score": dir_sc, "filters": filters_n,
                    "sym": sym, "action": action, "bar": bar,
                })

            # Trier : filtres d'abord, puis score
            candidates.sort(key=lambda c: (c["filters"], c["score"]), reverse=True)

            for cand in candidates[:slots_free]:
                if available_cash < 1.0: break
                pos = self._try_enter(
                    sym=cand["sym"], action=cand["action"],
                    filters=cand["filters"], score=cand["score"],
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
                 day_wins: dict, sym_data: dict, t0: float):
    if not trades:
        console.print("[red]Aucun trade.[/red]")
        return

    eq_vals  = [v for _, v in equity_curve]
    final_eq = eq_vals[-1] if eq_vals else INITIAL_CAPITAL

    peak = INITIAL_CAPITAL; max_dd = 0.0
    for v in eq_vals:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        if dd > max_dd: max_dd = dd

    wins   = [t for t in trades if t.pnl_eur > 0]
    losses = [t for t in trades if t.pnl_eur <= 0]
    wr     = len(wins) / len(trades) * 100 if trades else 0
    net    = final_eq - INITIAL_CAPITAL
    ret_pct = net / INITIAL_CAPITAL * 100

    if len(equity_curve) > 1:
        eq_s   = pd.Series(eq_vals)
        rets   = eq_s.pct_change().dropna()
        sharpe = (rets.mean() / rets.std() * math.sqrt(8760)) if rets.std() > 0 else 0
    else:
        sharpe = 0

    gross_win  = sum(t.pnl_eur for t in wins)  if wins   else 0
    gross_loss = abs(sum(t.pnl_eur for t in losses)) if losses else 1
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    liq_count = sum(1 for t in trades if t.exit_reason == "liquidation")
    avg_lev   = sum(t.leverage for t in trades) / len(trades) if trades else 0
    f5_trades = [t for t in trades if t.filters == 5]
    f4_trades = [t for t in trades if t.filters == 4]
    f3_trades = [t for t in trades if t.filters == 3]

    console.print()
    console.rule("[bold yellow]SKYN v6 — SCALP FILTRE LASER[/bold yellow]")
    console.print()

    res_panel = Panel(
        f"[bold]Mise de depart  [/bold] {INITIAL_CAPITAL:.2f} EUR\n"
        f"[bold]Capital final   [/bold] {final_eq:.2f} EUR\n"
        f"[{'green' if net >= 0 else 'red'}]Profit net      {'+' if net >= 0 else ''}{net:.2f} EUR ({'+' if ret_pct >= 0 else ''}{ret_pct:.2f}%)[/]\n"
        f"[bold]Drawdown max    [/bold] {max_dd:.1f}%\n"
        f"[bold]Sharpe          [/bold] {sharpe:.3f}\n"
        f"[bold]Profit Factor   [/bold] {pf:.3f}\n"
        f"[bold]Win Rate        [/bold] {wr:.1f}% ({len(wins)}W / {len(losses)}L)\n"
        f"[bold]Trades total    [/bold] {len(trades)}  (5F:{len(f5_trades)} 4F:{len(f4_trades)} 3F:{len(f3_trades)})\n"
        f"[bold]Levier moyen    [/bold] {avg_lev:.1f}x\n"
        f"[bold]Liquidations    [/bold] {liq_count}",
        title="[bold cyan]Resultat Global · 2 ans · Filtre Laser[/bold cyan]",
        border_style="cyan",
    )
    console.print(res_panel)

    # Performance par niveau de filtre
    f_table = Table(title="Performance par Nombre de Filtres Passes", box=box.SIMPLE_HEAVY)
    f_table.add_column("Filtres", style="bold")
    f_table.add_column("Trades", justify="right")
    f_table.add_column("Win%", justify="right")
    f_table.add_column("Net EUR", justify="right")
    f_table.add_column("Risk/trade", justify="right")
    f_table.add_column("Lev moy", justify="right")
    for label, lst, risk in [
        ("5/5 (Setup Parfait)", f5_trades, f"{RISK_5F*100:.1f}%"),
        ("4/5",                 f4_trades, f"{RISK_4F*100:.1f}%"),
        ("3/5",                 f3_trades, f"{RISK_3F*100:.1f}%"),
    ]:
        if not lst: continue
        wr_t  = sum(1 for t in lst if t.pnl_eur > 0) / len(lst) * 100
        net_t = sum(t.pnl_eur for t in lst)
        lv    = sum(t.leverage for t in lst) / len(lst)
        f_table.add_row(label, str(len(lst)), f"{wr_t:.0f}%",
                        f"[{'green' if net_t >= 0 else 'red'}]{'+' if net_t >= 0 else ''}{net_t:.2f}EUR[/]",
                        risk, f"{lv:.1f}x")
    console.print(f_table)

    # Explosive days
    explosive = {d: s for d, s in day_wins.items() if len(s) >= 2}
    max_sim   = max((len(s) for s in day_wins.values()), default=0)
    exp3 = sum(1 for s in day_wins.values() if len(s) >= 3)

    exp_panel = Panel(
        f"[bold]Max victoires simultanées le même jour :[/bold] {max_sim}\n"
        f"[bold]Journées avec 2+ victoires             :[/bold] {len(explosive)}\n"
        f"[bold]Journées avec 3+ victoires             :[/bold] {exp3}",
        title="[bold magenta]Effet Explosif — Journées Multi-Victoires[/bold magenta]",
        border_style="magenta",
    )
    console.print(exp_panel)

    # Monthly breakdown
    df_trades = pd.DataFrame([{
        "month": str(t.entry_ts)[:7],
        "pnl":   t.pnl_eur,
        "win":   t.pnl_eur > 0,
        "lev":   t.leverage,
        "f":     t.filters,
    } for t in trades])
    eq_df = pd.DataFrame(equity_curve, columns=["ts", "eq"])
    eq_df["month"] = eq_df["ts"].dt.strftime("%Y-%m")

    m_table = Table(title="Breakdown Mensuel — Filtre Laser", box=box.SIMPLE_HEAVY)
    for col in ["Mois", "Trades", "Win%", "5F/4F/3F", "Net EUR", "Ret%", "Statut"]:
        m_table.add_column(col, justify="right" if col not in ["Mois", "Statut"] else "left")

    months = sorted(df_trades["month"].unique())
    prev_eq = INITIAL_CAPITAL
    for m in months:
        mt    = df_trades[df_trades["month"] == m]
        net_m = mt["pnl"].sum()
        wr_m  = mt["win"].sum() / len(mt) * 100 if len(mt) > 0 else 0
        f5_m  = (mt["f"] == 5).sum()
        f4_m  = (mt["f"] == 4).sum()
        f3_m  = (mt["f"] == 3).sum()
        m_eq  = eq_df[eq_df["month"] == m]["eq"]
        end_eq = float(m_eq.iloc[-1]) if len(m_eq) > 0 else prev_eq
        ret_m  = (end_eq - prev_eq) / prev_eq * 100 if prev_eq > 0 else 0
        if ret_m >= 200: stat = "[bold magenta]×3![/bold magenta]"
        elif ret_m >= 100: stat = "[bold green]×2+[/bold green]"
        elif ret_m >= 50:  stat = "[bold green]×1.5+[/bold green]"
        elif ret_m >= 20:  stat = "[green]+20%+[/green]"
        elif ret_m >= 0:   stat = "[green]+[/green]"
        else:              stat = "[red]-[/red]"
        m_table.add_row(
            m, str(len(mt)), f"{wr_m:.0f}%",
            f"{f5_m}/{f4_m}/{f3_m}",
            f"[{'green' if net_m >= 0 else 'red'}]{'+' if net_m >= 0 else ''}{net_m:.2f}EUR[/]",
            f"{'+' if ret_m >= 0 else ''}{ret_m:.1f}%", stat,
        )
        prev_eq = end_eq
    console.print(m_table)

    # Beta test (6 derniers mois)
    if equity_curve:
        last_ts = equity_curve[-1][0]
        beta_start_ts = last_ts - pd.DateOffset(months=6)
        beta_trades = [t for t in trades if t.entry_ts >= beta_start_ts]
        beta_eq     = [(ts, v) for ts, v in equity_curve if ts >= beta_start_ts]
        if beta_trades and beta_eq:
            b_start = beta_eq[0][1]; b_end = beta_eq[-1][1]
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
            b_sh   = (b_rets.mean() / b_rets.std() * math.sqrt(8760)) if b_rets.std() > 0 else 0
            console.print(Panel(
                f"Periode    : {beta_eq[0][0].strftime('%Y-%m-%d')} → {beta_eq[-1][0].strftime('%Y-%m-%d')}\n"
                f"Trades     : {len(beta_trades)}  |  Win Rate : {b_wr:.1f}%\n"
                f"Capital depart : {b_start:.2f}EUR\n"
                f"[{'green' if b_net >= 0 else 'red'}]Resultat   : {'+' if b_net >= 0 else ''}{b_net:.2f}EUR ({'+' if b_ret >= 0 else ''}{b_ret:.1f}%)[/]\n"
                f"DD: {b_dd:.1f}%  |  Sharpe: {b_sh:.3f}\n\n"
                f"×2 atteint ? {'[bold green]OUI[/bold green]' if b_ret >= 100 else '[red]NON[/red]'} ({b_ret:.1f}%)\n"
                f"×3 atteint ? {'[bold magenta]OUI[/bold magenta]' if b_ret >= 200 else '[red]NON[/red]'} ({b_ret:.1f}%)",
                title="[bold yellow]Beta Test — 6 Derniers Mois[/bold yellow]",
                border_style="yellow",
            ))

    # Equity sparkline
    if eq_vals:
        eq_min = min(eq_vals); eq_max = max(eq_vals)
        W = 80
        spark_vals = [eq_vals[int(i * len(eq_vals) / W)] for i in range(W)]
        bars = " ▁▂▃▄▅▆▇█"
        def to_bar(v):
            if eq_max == eq_min: return "▄"
            return bars[min(int((v - eq_min) / (eq_max - eq_min) * 8), 8)]
        console.print(Panel(
            "".join(to_bar(v) for v in spark_vals) + "\n"
            f"   Depart: {INITIAL_CAPITAL:.2f}EUR  →  Fin: {final_eq:.2f}EUR  |  "
            f"Min: {eq_min:.2f}EUR  Max: {eq_max:.2f}EUR",
            title="[bold]Courbe d'Equity[/bold]", border_style="blue",
        ))

    # Top trades
    if trades:
        top10 = sorted(trades, key=lambda t: t.pnl_eur, reverse=True)[:10]
        tw = Table(title="Top 10 Meilleurs Trades", box=box.SIMPLE)
        for c in ["Sym", "Side", "Score", "Filtres", "Net EUR", "PnL%", "Lev", "Sortie", "Durée"]:
            tw.add_column(c)
        for t in top10:
            tw.add_row(t.symbol.split("/")[0], t.side[:5], str(t.score),
                       f"{t.filters}/5",
                       f"[green]+{t.pnl_eur:.2f}EUR[/green]",
                       f"+{t.pnl_pct:.1f}%", f"{t.leverage}x",
                       t.exit_reason[:6], f"{t.candles_held}h")
        console.print(tw)

    # ── VEILLE — état actuel de tous les symboles ─────────────────────────────
    console.print()
    console.rule("[bold red]VEILLE TEMPS RÉEL — État Actuel des Marchés[/bold red]")
    console.print()

    veille_table = Table(
        title="Tableau de Bord Veille — Squeezes en Formation",
        box=box.SIMPLE_HEAVY,
        caption="Symboles classés par potentiel explosif (durée squeeze × intensité)"
    )
    for col in ["Symbole", "Durée Squeeze", "Intensité BB", "Funding Dev", "OI Ratio",
                "Score BUY", "Score SELL", "Filtres", "Statut"]:
        veille_table.add_column(col)

    # Analyser l'état actuel (dernière barre de chaque symbole)
    veille_rows = []
    for sym, sd in sym_data.items():
        df = sd["df"]
        if len(df) < BB_SQUEEZE_WINDOW + 10:
            continue
        bar   = len(df) - 1
        last  = df.iloc[bar]

        try:
            price     = float(last["close"])
            cur_bbw   = float(last.get("bbw",     1.0) or 1.0)
            q10_thr   = float(last.get("bbw_q10", 1.0) or 1.0)
            fund_dev  = float(last.get("funding_dev", 0.0) or 0.0)
            oi_ratio  = float(last.get("vol_oi_ratio", 1.0) or 1.0)
            vol_r     = float(last.get("vol_ratio", 1.0) or 1.0)
            bb_upper  = float(last.get("bb_upper", 0) or 0)
            bb_lower  = float(last.get("bb_lower", 0) or 0)
        except Exception:
            continue

        # Compter les barres en squeeze
        n_sq_bars = 0
        for back in range(1, min(30, bar)):
            try:
                bw = float(df.iloc[bar - back].get("bbw", 9999) or 9999)
                qt = float(df.iloc[bar - back].get("bbw_q10", 0) or 0)
                if bw < qt * 1.05:
                    n_sq_bars += 1
                else:
                    break
            except Exception:
                break

        buy_sc  = int(sd["buy_sc"][bar])
        sell_sc = int(sd["sell_sc"][bar])

        # Calculer le nombre de filtres actifs
        is_in_squeeze = (n_sq_bars >= MIN_SQUEEZE_BARS) and (cur_bbw < q10_thr * 1.05)
        f3_active = fund_dev <= FUNDING_DEV_BUY or fund_dev >= FUNDING_DEV_SELL
        f4_active = oi_ratio >= OI_VOL_RATIO
        f5_long   = bb_upper > 0 and price > bb_upper * 1.003
        f5_short  = bb_lower > 0 and price < bb_lower * 0.997
        score_ok  = buy_sc >= SCORE_MIN or sell_sc >= SCORE_MIN

        filters_forming = sum([
            is_in_squeeze,
            score_ok,
            f3_active,
            f4_active,
            (f5_long or f5_short),
        ])

        intensity = q10_thr / cur_bbw if cur_bbw > 0 else 0

        if fund_dev <= FUNDING_DEV_BUY:
            fund_str = f"[green]{fund_dev:.3f}[/green] → BUY"
        elif fund_dev >= FUNDING_DEV_SELL:
            fund_str = f"[red]{fund_dev:.3f}[/red] → SELL"
        else:
            fund_str = f"{fund_dev:.3f}"

        oi_str = f"[green]{oi_ratio:.2f}×[/green]" if oi_ratio >= OI_VOL_RATIO else f"{oi_ratio:.2f}×"

        if n_sq_bars >= MIN_SQUEEZE_BARS:
            sq_str   = f"[yellow]{n_sq_bars}h[/yellow]"
            int_str  = f"[yellow]{intensity:.2f}×[/yellow]"
        else:
            sq_str   = f"{n_sq_bars}h"
            int_str  = f"{intensity:.2f}×"

        if filters_forming >= 4:
            stat = "[bold yellow]⚡ SETUP IMMINENT[/bold yellow]"
        elif filters_forming == 3:
            stat = "[yellow]▲ Surveillance[/yellow]"
        elif is_in_squeeze:
            stat = "[blue]~ Squeeze actif[/blue]"
        else:
            stat = "[dim]Normal[/dim]"

        veille_rows.append((filters_forming, n_sq_bars * intensity, {
            "sym":   sd["name"], "sq": sq_str, "int": int_str,
            "fund":  fund_str, "oi": oi_str,
            "bsc":   str(buy_sc), "ssc": str(sell_sc),
            "nf":    f"{filters_forming}/5", "stat": stat,
        }))

    # Trier par potentiel explosif
    veille_rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    for _, _, row in veille_rows:
        veille_table.add_row(
            row["sym"], row["sq"], row["int"], row["fund"], row["oi"],
            row["bsc"], row["ssc"], row["nf"], row["stat"],
        )
    console.print(veille_table)

    elapsed = time.time() - t0
    console.rule(f"[bold]FIN · {elapsed:.1f}s · {len(trades)} trades[/bold]")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    console.rule("[bold yellow]SKYN v6 — SCALP FILTRE LASER · 50EUR · 11 Symboles · 2 ans[/bold yellow]")
    console.print(
        f"  Capital        : {INITIAL_CAPITAL:.0f}EUR unique\n"
        f"  Max positions  : {N_MAX_POSITIONS} (ultra-sélectif)\n"
        f"  Levier         : {LEV_80}x@80 / {LEV_85}x@85 / {LEV_90}x@90+\n"
        f"  SL/TP          : {SL_PCT*100:.1f}% / {TP_PCT*100:.1f}% ({int(TP_PCT/SL_PCT)}:1 RR)\n"
        f"  Risk           : {RISK_3F*100:.0f}%(3F) / {RISK_4F*100:.1f}%(4F) / {RISK_5F*100:.0f}%(5F)\n"
        f"  Filtres        : BB Squeeze {MIN_SQUEEZE_BARS}+h + Score≥{SCORE_MIN} + Funding + OI + Close confirmée\n"
    )

    cfg = AppConfig()
    console.print("Telechargement et calcul des indicateurs...")
    sym_data = {}
    for sym in SYMBOLS_YF:
        t_sym = time.time()
        sd = precompute_symbol(sym, cfg)
        if sd is None:
            console.print(f"  [red]× {sym} — echec[/red]")
            continue
        sym_data[sym] = sd
        console.print(f"  [green]✓ {sym}[/green] — {len(sd['df'])} barres [{time.time()-t_sym:.1f}s]")

    if not sym_data:
        console.print("[bold red]Aucun symbole disponible.[/bold red]")
        return

    console.print("\nConstruction de l'index commun...")
    common_set = None
    for sd in sym_data.values():
        s = set(sd["ts_index"])
        common_set = s if common_set is None else common_set & s
    common_timestamps = sorted(common_set)
    console.print(f"  {len(common_timestamps)} barres communes\n")

    console.print("[bold cyan]Simulation filtre laser en cours...[/bold cyan]")
    engine = LaserEngine(sym_data)
    trades, equity_curve, day_wins = engine.run(common_timestamps[WARMUP:])
    console.print(f"  OK {len(trades)} trades simules en {time.time()-t0:.1f}s\n")

    print_report(trades, equity_curve, day_wins, sym_data, t0)


if __name__ == "__main__":
    main()
