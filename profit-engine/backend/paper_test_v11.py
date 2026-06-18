#!/usr/bin/env python3
"""
SKYN v11 — MACRO FORTE UNIQUEMENT (±2% divergence)
===================================================
Objectif : éliminer les pertes de fin de tendance en n'opérant QUE
dans les tendances fortement confirmées.

Leçons v10 :
  ✗ adaptive sq_bars en macro "strong" → plus de trades mais WR 35% vs 41%
  ✗ cooldown 2h → re-entrées prématurées sur mauvais setups

Retour à v9 + une seule modification chirurgicale :
  - Macro FORTE seulement : ema50/ema200 doit diverger de ±2% (était ±1%)
    → Élimine les trades perdants en fin de tendance (transition bear/neutral)
  - Cooldown 4h maintenu
  - sq_bars FIXE (pas d'adaptation)
  - 4F exclu, neutral skip — tout hérité de v9
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

# ── 17 Symboles (APT indisponible) ────────────────────────────────────────────
SYMBOLS_YF = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "AVAX-USD",
    "ADA-USD", "LINK-USD", "XRP-USD", "DOT-USD", "ATOM-USD", "LTC-USD",
    "DOGE-USD", "NEAR-USD",
    "TRX-USD", "ALGO-USD", "FIL-USD", "INJ-USD",
]
SYMBOL_MAP = {s: s.replace("-USD", "/USDT") for s in SYMBOLS_YF}

INITIAL_CAPITAL  = 500.0
INTERVAL         = "1h"
PERIOD           = "2y"
WARMUP           = 220
N_MAX_POSITIONS  = 5

# ── Paramètres fixes ──────────────────────────────────────────────────────────
PARTIAL_TP_FRAC   = 0.55
ADX_RISE_MIN      = 3.0
MIN_ADX_BO        = 16
BO_BODY_PCT_MIN   = 0.50
BB_SQUEEZE_WINDOW = 30
BO_COOLDOWN_H     = 4
COMMISSION        = 0.0004
SLIPPAGE          = 0.0005
DAILY_LOSS_LIMIT  = 0.12
FUNDING_MA_BARS   = 48
FUNDING_DEV_BUY   = -0.010
FUNDING_DEV_SELL  =  0.010
OI_VOL_LOOKBACK   = 8
VOL_SURGE_MIN     = 3.0

# ── v9 : seulement 3F et 5F (skip 4F) ────────────────────────────────────────
ALLOWED_FILTER_COUNTS = {3, 5}   # 4F exclu car WR historique < 20%

# ── Tiers risk/TP (5F = conviction maximale) ──────────────────────────────────
RISK_MULT_BY_F = {5: 2.5, 3: 1.0}
TP_PCT_BY_F    = {5: 0.065, 3: 0.045}

# ── 3 Configurations ──────────────────────────────────────────────────────────
CONFIGS = [
    {"name": "Precision", "score_min": 90, "sq_bars": 5,
     "risk_pct": 0.040, "sl_pct": 0.005},
    {"name": "Selectif",  "score_min": 85, "sq_bars": 5,
     "risk_pct": 0.045, "sl_pct": 0.005},
    {"name": "Optimal",   "score_min": 82, "sq_bars": 5,
     "risk_pct": 0.050, "sl_pct": 0.005},
]


def _get_lev(score: int) -> int:
    if score >= 90: return 10
    if score >= 85: return 7
    return 5


# ── Data helpers ──────────────────────────────────────────────────────────────

def download_data(symbol: str) -> Optional[pd.DataFrame]:
    try:
        raw = yf.download(symbol, period=PERIOD, interval=INTERVAL,
                          auto_adjust=True, progress=False)
        if raw is None or len(raw) < WARMUP + 50:
            return None
        df = raw.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        df.index.name = "timestamp"
        return df
    except Exception:
        return None


def resample_daily(df: pd.DataFrame) -> pd.DataFrame:
    d = df.resample("1D").agg({"open": "first", "high": "max",
                                "low": "min", "close": "last",
                                "volume": "sum"}).dropna()
    c = d["close"]
    d["ema9"]   = _ema(c, 9)
    d["ema21"]  = _ema(c, 21)
    d["ema50"]  = _ema(c, 50)
    d["ema200"] = _ema(c, 200)
    return d


# ── Symbol precomputation ─────────────────────────────────────────────────────

def precompute_symbol(sym: str, cfg) -> Optional[dict]:
    raw = download_data(sym)
    if raw is None:
        return None
    df = compute_all(raw.copy(), cfg.strategy)
    df_daily = resample_daily(df)

    if "bb_upper" not in df.columns:
        p = 20; k = 2.0
        df["bb_mid"]   = df["close"].rolling(p).mean()
        df["bb_upper"] = df["bb_mid"] + k * df["close"].rolling(p).std()
        df["bb_lower"] = df["bb_mid"] - k * df["close"].rolling(p).std()
    df["bbw"]     = ((df["bb_upper"] - df["bb_lower"]) /
                     df["bb_mid"].replace(0, np.nan)).fillna(1.0)
    df["bbw_q10"] = df["bbw"].rolling(BB_SQUEEZE_WINDOW).quantile(0.10).fillna(df["bbw"])

    df["macd_hist_slope"] = df["macd_hist"].diff().fillna(0)
    df["obv_slope"]       = df["obv"].diff(5).fillna(0)
    df["ma48"]            = df["close"].rolling(FUNDING_MA_BARS).mean()
    df["funding_dev"]     = (df["close"] - df["ma48"]) / df["ma48"].replace(0, np.nan)
    vol_base              = df["volume"].rolling(50).mean().replace(0, np.nan)
    df["vol_oi_ratio"]    = df["volume"].rolling(OI_VOL_LOOKBACK).mean() / vol_base

    adx_series, di_p_series, di_m_series = _compute_adx(df)

    n = len(df)
    buy_sc  = np.zeros(n, dtype=np.int16)
    sell_sc = np.zeros(n, dtype=np.int16)
    _cls  = df["close"].values
    _e9   = df["ema9"].values
    _e21  = df["ema21"].values
    _e50  = df["ema50"].values
    _e200 = df["ema200"].values
    _rsi  = df["rsi"].fillna(50).values
    _mh   = df["macd_hist"].fillna(0).values
    _ms   = df["macd_hist_slope"].fillna(0).values
    _vwap = df["vwap"].fillna(df["close"]).values
    _sk   = df["stoch_k"].fillna(50).values
    _sd_v = df["stoch_d"].fillna(50).values
    _obv  = df["obv_slope"].fillna(0).values
    _adxa = adx_series.values
    _dipa = di_p_series.values
    _dima = di_m_series.values

    for ii in range(n):
        _p = _cls[ii]; _b = 0; _s = 0
        rb = (int(_e9[ii] > _e21[ii]) + int(_e21[ii] > _e50[ii]) +
              int(_e50[ii] > _e200[ii]) + int(_p > _e21[ii]))
        rs = (int(_e9[ii] < _e21[ii]) + int(_e21[ii] < _e50[ii]) +
              int(_e50[ii] < _e200[ii]) + int(_p < _e21[ii]))
        if rb >= 3: _b += 20
        if rs >= 3: _s += 20
        if _mh[ii] > 0 and _ms[ii] > 0: _b += 15
        elif _mh[ii] < 0 and _ms[ii] < 0: _s += 15
        r = _rsi[ii]
        if 50 <= r <= 72: _b += 10
        elif 28 <= r <= 50: _s += 10
        vw = _vwap[ii] or _p
        if vw > 0:
            if _p > vw * 1.0005: _b += 15
            elif _p < vw * 0.9995: _s += 15
        sk = _sk[ii]; sdv = _sd_v[ii]
        if sk > sdv and sk < 75: _b += 10
        elif sk < sdv and sk > 25: _s += 10
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

    return {
        "name":      SYMBOL_MAP.get(sym, sym),
        "sym_key":   sym,
        "df":        df,
        "df_daily":  df_daily,
        "adx_s":     adx_series,
        "di_p_s":    di_p_series,
        "di_m_s":    di_m_series,
        "buy_sc":    buy_sc,
        "sell_sc":   sell_sc,
        "ts_to_pos": {ts: i for i, ts in enumerate(df.index)},
        "ts_index":  df.index,
    }


# ── BTC Macro Regime ──────────────────────────────────────────────────────────

def _build_btc_macro(btc_sd: dict) -> Dict[pd.Timestamp, str]:
    """
    v11 : seuil ±2% au lieu de ±1% pour éviter les tendances faibles.
    bull  : ema50 > ema200 × 1.02
    bear  : ema50 < ema200 × 0.98
    neutral : tout le reste (transitions filtrées)
    """
    df_d = btc_sd["df_daily"]
    result = {}
    for ts, row in df_d.iterrows():
        try:
            e50  = float(row.get("ema50",  0) or 0)
            e200 = float(row.get("ema200", 0) or 0)
            if e50 <= 0 or e200 <= 0:
                result[ts.date()] = "neutral"
                continue
            ratio = e50 / e200
            if ratio > 1.02:
                result[ts.date()] = "bull"
            elif ratio < 0.98:
                result[ts.date()] = "bear"
            else:
                result[ts.date()] = "neutral"
        except Exception:
            result[ts.date()] = "neutral"
    return result


# ── Breakout detection ────────────────────────────────────────────────────────

def _check_breakout(sd: dict, bar: int, adx_val: float, adx_series: pd.Series,
                    sq_bars: int, score_min: int) -> Tuple[int, Optional[str]]:
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

    if bb_upper <= 0 or bb_lower <= 0 or adx_val < MIN_ADX_BO:
        return 0, None

    # F1 : Squeeze prolongé
    recent = df.iloc[max(0, bar - 12):bar]
    if len(recent) < sq_bars:
        return 0, None
    bbw_v = recent["bbw"].values
    q10_v = recent["bbw_q10"].values
    n_sq  = int(np.sum(bbw_v < q10_v * 1.05))
    if n_sq < sq_bars:
        return 0, None
    min_recent = float(recent["bbw"].min())
    if cur_bbw < min_recent * 1.12:
        return 0, None
    f1 = True

    if vol_r < VOL_SURGE_MIN:
        return 0, None
    rng  = high_p - low_p
    body = abs(price - open_p)
    if rng > 0 and body / rng < BO_BODY_PCT_MIN:
        return 0, None
    if bar >= 5 and not np.isnan(adx_series.iloc[bar - 5]):
        if adx_val < float(adx_series.iloc[bar - 5]) + ADX_RISE_MIN:
            return 0, None

    buy_sc  = int(sd["buy_sc"][bar])
    sell_sc = int(sd["sell_sc"][bar])
    is_buy  = price > bb_upper * 1.001 and price > open_p and buy_sc  >= score_min
    is_sell = price < bb_lower * 0.999 and price < open_p and sell_sc >= score_min
    if not is_buy and not is_sell:
        return 0, None

    action    = "BUY" if is_buy else "SELL"
    dir_score = buy_sc if is_buy else sell_sc
    f2 = dir_score >= score_min

    f3 = (action == "BUY"  and fund_dev <= FUNDING_DEV_BUY) or \
         (action == "SELL" and fund_dev >= FUNDING_DEV_SELL)
    f4 = oi_ratio >= 1.35
    f5 = (action == "BUY"  and price > bb_upper * 1.003) or \
         (action == "SELL" and price < bb_lower * 0.997)

    filters = sum([f1, f2, f3, f4, f5])
    if filters < 3:
        return 0, None
    return filters, action


# ── Engine ────────────────────────────────────────────────────────────────────

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
    filters:      int


def run_engine(sym_data: dict, common_timestamps: List[pd.Timestamp],
               btc_macro: Dict,
               score_min: int, sq_bars: int, risk_pct: float, sl_pct: float,
               n_max_pos: int = N_MAX_POSITIONS) -> Tuple[List[PaperTrade], list, dict]:

    lev_mgr = LeverageManager()
    available_cash = INITIAL_CAPITAL
    positions: Dict[str, dict] = {}
    bo_cooldowns: Dict[str, pd.Timestamp] = {}
    all_trades: List[PaperTrade] = []
    equity_curve = []
    day_wins: Dict[str, list] = {}

    current_day = None; day_start_eq = INITIAL_CAPITAL; day_halted = False

    for ts in common_timestamps:
        day_key  = str(ts)[:10]
        total_eq = available_cash + sum(p["margin_eur"] for p in positions.values())

        if day_key != current_day:
            current_day  = day_key
            day_start_eq = total_eq
            day_halted   = False

        if not day_halted and day_start_eq > 0:
            if (day_start_eq - total_eq) / day_start_eq >= DAILY_LOSS_LIMIT:
                day_halted = True

        macro = btc_macro.get(pd.Timestamp(day_key).date(), "neutral")

        # ── Exits ─────────────────────────────────────────────────────────────
        for sym in list(positions.keys()):
            sd  = sym_data.get(sym)
            if sd is None: continue
            bar = sd["ts_to_pos"].get(ts)
            if bar is None: continue
            row  = sd["df"].iloc[bar]
            pos  = positions[sym]
            high = float(row.get("high", row["close"]))
            low  = float(row.get("low",  row["close"]))

            reason = None
            if pos["side"] == "long"  and low  <= pos["liq"]: reason = "liquidation"
            elif pos["side"] == "short" and high >= pos["liq"]: reason = "liquidation"
            if reason is None:
                if pos["side"] == "long"  and low  <= pos["sl"]: reason = "stop_loss"
                elif pos["side"] == "short" and high >= pos["sl"]: reason = "stop_loss"
            if reason is None and not pos.get("partial_taken"):
                if pos["side"] == "long"  and high >= pos["partial_tp"]:
                    pos["partial_taken"] = True; pos["sl"] = pos["entry"]
                elif pos["side"] == "short" and low  <= pos["partial_tp"]:
                    pos["partial_taken"] = True; pos["sl"] = pos["entry"]
            if reason is None:
                if pos["side"] == "long"  and high >= pos["tp"]: reason = "take_profit"
                elif pos["side"] == "short" and low  <= pos["tp"]: reason = "take_profit"

            if reason is None: continue

            if reason == "liquidation":
                pnl = -pos["margin_eur"]; exit_p = pos["liq"]
            else:
                tgt = pos["tp"] if reason == "take_profit" else pos["sl"]
                if reason == "stop_loss":
                    exit_p = tgt * (1 + SLIPPAGE) if pos["side"] == "long" \
                             else tgt * (1 - SLIPPAGE)
                else:
                    exit_p = tgt * (1 - SLIPPAGE) if pos["side"] == "long" \
                             else tgt * (1 + SLIPPAGE)
                raw = (exit_p - pos["entry"]) * pos["qty"] if pos["side"] == "long" \
                      else (pos["entry"] - exit_p) * pos["qty"]
                pnl = raw - pos["qty"] * exit_p * COMMISSION

            available_cash += pos["margin_eur"] + pnl
            pnl_pct = pnl / pos["margin_eur"] * 100 if pos["margin_eur"] > 0 else 0
            all_trades.append(PaperTrade(
                symbol=sd["name"], side=pos["side"],
                entry_ts=pos["entry_ts"], exit_ts=ts,
                entry_price=pos["entry"], exit_price=exit_p,
                margin_eur=round(pos["margin_eur"], 4),
                leverage=pos["leverage"],
                pnl_eur=round(pnl, 4), pnl_pct=round(pnl_pct, 3),
                exit_reason=reason, score=pos["score"], filters=pos["filters"],
            ))
            if pnl > 0:
                day_wins.setdefault(day_key, []).append(sym)
            if pnl < 0:
                bo_cooldowns[sym] = ts + pd.Timedelta(hours=BO_COOLDOWN_H)
            del positions[sym]

        total_eq = available_cash + sum(p["margin_eur"] for p in positions.values())
        equity_curve.append((ts, total_eq))

        # ── Entries ───────────────────────────────────────────────────────────
        slots = n_max_pos - len(positions)
        if slots <= 0 or day_halted or available_cash < 5.0:
            continue

        # v9 : skip macro neutral (aucune entrée sans direction claire)
        if macro == "neutral":
            continue

        candidates = []
        for sym, sd in sym_data.items():
            if sym in positions: continue
            bar = sd["ts_to_pos"].get(ts)
            if bar is None or bar < WARMUP: continue
            cd = bo_cooldowns.get(sym)
            if cd is not None and ts < cd: continue

            adx_i = float(sd["adx_s"].iloc[bar]) if not np.isnan(sd["adx_s"].iloc[bar]) else 0.0
            nf, action = _check_breakout(sd, bar, adx_i, sd["adx_s"], sq_bars, score_min)

            # v9 : seulement 3F et 5F (4F exclu — WR historique < 20%)
            if nf not in ALLOWED_FILTER_COUNTS or action is None:
                continue

            # Filtre macro BTC
            if macro == "bull" and action == "SELL": continue
            if macro == "bear" and action == "BUY":  continue

            dir_sc = int(sd["buy_sc"][bar]) if action == "BUY" else int(sd["sell_sc"][bar])
            candidates.append({"score": dir_sc, "filters": nf, "sym": sym,
                                "action": action, "bar": bar})

        candidates.sort(key=lambda c: (c["filters"], c["score"]), reverse=True)

        for cand in candidates[:slots]:
            if available_cash < 5.0: break
            sd    = sym_data[cand["sym"]]
            row   = sd["df"].iloc[cand["bar"]]
            price = float(row["close"])
            atr_raw = row.get("atr")
            atr_v   = float(atr_raw) if (atr_raw is not None and not pd.isna(atr_raw)) \
                      else price * 0.015

            # SL adaptatif
            atr_pct = atr_v / price
            eff_sl  = max(sl_pct, min(atr_pct * 0.8, 0.012))

            # TP et risk tiered par filtre (v9 : seulement 3F et 5F)
            tp_pct   = TP_PCT_BY_F.get(cand["filters"], 0.045)
            tp_dist  = eff_sl * (tp_pct / sl_pct)

            risk_mult = RISK_MULT_BY_F.get(cand["filters"], 1.0)
            risk_eur  = total_eq * risk_pct * risk_mult

            lev = _get_lev(cand["score"])

            if cand["action"] == "BUY":
                entry_p    = price * (1 + SLIPPAGE)
                sl_p       = entry_p * (1 - eff_sl)
                tp_p       = entry_p * (1 + tp_dist)
                partial_tp = entry_p * (1 + tp_dist * PARTIAL_TP_FRAC)
                liq_p      = lev_mgr.liquidation_price(entry_p, lev, "long")
                sl_p       = max(sl_p, liq_p * 1.001)
                side       = "long"
            else:
                entry_p    = price * (1 - SLIPPAGE)
                sl_p       = entry_p * (1 + eff_sl)
                tp_p       = entry_p * (1 - tp_dist)
                partial_tp = entry_p * (1 - tp_dist * PARTIAL_TP_FRAC)
                liq_p      = lev_mgr.liquidation_price(entry_p, lev, "short")
                sl_p       = min(sl_p, liq_p * 0.999)
                side       = "short"

            sl_dist    = abs(entry_p - sl_p) or entry_p * eff_sl
            qty        = risk_eur / sl_dist
            margin_eur = qty * entry_p / lev
            if margin_eur > available_cash * 0.90:
                margin_eur = available_cash * 0.90
                qty        = margin_eur * lev / entry_p
            total_cost = margin_eur + qty * entry_p * COMMISSION

            if qty <= 1e-12 or total_cost > available_cash: continue
            available_cash -= total_cost
            positions[cand["sym"]] = {
                "side": side, "entry": entry_p, "qty": qty,
                "margin_eur": margin_eur, "liq": liq_p,
                "sl": sl_p, "tp": tp_p, "partial_tp": partial_tp,
                "leverage": lev, "score": cand["score"], "filters": cand["filters"],
                "entry_ts": ts, "entry_bar": cand["bar"],
                "partial_taken": False, "total_cost": total_cost,
            }

    return all_trades, equity_curve, day_wins


# ── Metrics ───────────────────────────────────────────────────────────────────

def _quick_metrics(trades: List[PaperTrade], equity_curve: list,
                   window_start: pd.Timestamp) -> dict:
    if not trades or not equity_curve:
        return {"net": 0, "ret": 0, "wr": 0, "dd": 100, "sharpe": 0, "trades": 0}

    w_trades = [t for t in trades if t.entry_ts >= window_start]
    w_eq     = [(ts, v) for ts, v in equity_curve if ts >= window_start]

    if not w_eq:
        return {"net": 0, "ret": 0, "wr": 0, "dd": 100, "sharpe": 0, "trades": 0}

    eq_vals = [v for _, v in w_eq]
    start_v = eq_vals[0]; end_v = eq_vals[-1]
    net = end_v - start_v
    ret = net / start_v * 100 if start_v > 0 else 0

    peak = start_v; dd = 0
    for v in eq_vals:
        if v > peak: peak = v
        d = (peak - v) / peak * 100 if peak > 0 else 0
        if d > dd: dd = d

    wins = sum(1 for t in w_trades if t.pnl_eur > 0)
    wr   = wins / len(w_trades) * 100 if w_trades else 0

    eq_s = pd.Series(eq_vals)
    rets = eq_s.pct_change().dropna()
    sh   = (rets.mean() / rets.std() * math.sqrt(8760)) if rets.std() > 0 else 0

    return {"net": net, "ret": ret, "wr": wr, "dd": dd, "sharpe": sh,
            "trades": len(w_trades)}


# ── Rapport complet ───────────────────────────────────────────────────────────

def print_report(trades, equity_curve, day_wins, window_start, params, t0):
    w_trades = [t for t in trades if t.entry_ts >= window_start]
    w_eq     = [(ts, v) for ts, v in equity_curve if ts >= window_start]
    if not w_eq:
        console.print("[red]Aucun trade dans la fenêtre 6 mois.[/red]")
        return

    eq_vals  = [v for _, v in w_eq]
    final_eq = eq_vals[-1]
    start_v  = eq_vals[0]
    net      = final_eq - start_v
    ret_pct  = net / start_v * 100 if start_v > 0 else 0

    peak = start_v; dd = 0
    for v in eq_vals:
        if v > peak: peak = v
        d = (peak - v) / peak * 100 if peak > 0 else 0
        if d > dd: dd = d

    wins   = [t for t in w_trades if t.pnl_eur > 0]
    losses = [t for t in w_trades if t.pnl_eur <= 0]
    wr     = len(wins) / len(w_trades) * 100 if w_trades else 0
    gw     = sum(t.pnl_eur for t in wins)  if wins   else 0
    gl     = abs(sum(t.pnl_eur for t in losses)) if losses else 1
    pf     = gw / gl if gl > 0 else float("inf")

    eq_s   = pd.Series(eq_vals)
    rets   = eq_s.pct_change().dropna()
    sharpe = (rets.mean() / rets.std() * math.sqrt(8760)) if rets.std() > 0 else 0

    avg_lev = sum(t.leverage for t in w_trades) / len(w_trades) if w_trades else 0
    liq_c   = sum(1 for t in w_trades if t.exit_reason == "liquidation")
    f5_c    = sum(1 for t in w_trades if t.filters == 5)
    f3_c    = sum(1 for t in w_trades if t.filters == 3)

    console.print()
    console.rule("[bold yellow]SKYN v11 — RÉSULTATS 6 MOIS / 500 EUR[/bold yellow]")
    console.print()

    params_str = (f"score≥{params['score_min']} | squeeze≥{params['sq_bars']}h | "
                  f"risk_base={params['risk_pct']*100:.1f}% | sl={params['sl_pct']*100:.1f}%")
    console.print(Panel(
        f"[bold]Capital départ  [/bold] {start_v:.2f} EUR\n"
        f"[bold]Capital final   [/bold] {final_eq:.2f} EUR\n"
        f"[{'green' if net >= 0 else 'red'}]Profit net      {'+' if net >= 0 else ''}"
        f"{net:.2f} EUR ({'+' if ret_pct >= 0 else ''}{ret_pct:.2f}%)[/]\n"
        f"[bold]Drawdown max    [/bold] {dd:.1f}%\n"
        f"[bold]Sharpe          [/bold] {sharpe:.3f}\n"
        f"[bold]Profit Factor   [/bold] {pf:.3f}\n"
        f"[bold]Win Rate        [/bold] {wr:.1f}% ({len(wins)}W / {len(losses)}L)\n"
        f"[bold]Trades          [/bold] {len(w_trades)}  (5F:{f5_c} 3F:{f3_c} | 4F exclus)\n"
        f"[bold]Levier moyen    [/bold] {avg_lev:.1f}x  |  Liquidations: {liq_c}\n"
        f"[dim]Params: {params_str}[/dim]",
        title="[bold cyan]6 Derniers Mois · Capital 500 EUR · v11[/bold cyan]",
        border_style="cyan",
    ))

    # Tier breakdown
    for nf, label in [(5, "5F — Haute conviction"), (3, "3F — Standard")]:
        tier_t = [t for t in w_trades if t.filters == nf]
        if not tier_t:
            continue
        tier_wins = sum(1 for t in tier_t if t.pnl_eur > 0)
        tier_wr   = tier_wins / len(tier_t) * 100
        tier_net  = sum(t.pnl_eur for t in tier_t)
        console.print(f"  [bold]{label}[/bold] : {len(tier_t)} trades | "
                      f"WR {tier_wr:.0f}% | Net {'+' if tier_net >= 0 else ''}{tier_net:.0f}EUR")

    # Journées explosives
    ws_naive = window_start.tz_localize(None) if window_start.tzinfo is not None \
               else window_start
    win_counts = [len(s) for d, s in day_wins.items() if pd.Timestamp(d) >= ws_naive]
    max_sim    = max(win_counts) if win_counts else 0
    exp2 = sum(1 for c in win_counts if c >= 2)
    exp3 = sum(1 for c in win_counts if c >= 3)
    console.print(Panel(
        f"[bold]Journées explosives (2+ victoires) :[/bold] {exp2}\n"
        f"[bold]Journées avec 3+ victoires         :[/bold] {exp3}\n"
        f"[bold]Max victoires simultanées          :[/bold] {max_sim}",
        title="[bold magenta]Effet Explosif[/bold magenta]",
        border_style="magenta",
    ))

    # Breakdown mensuel
    df_t = pd.DataFrame([{
        "month": str(t.entry_ts)[:7], "pnl": t.pnl_eur,
        "win": t.pnl_eur > 0, "lev": t.leverage,
    } for t in w_trades])
    eq_df = pd.DataFrame(w_eq, columns=["ts", "eq"])
    eq_df["month"] = eq_df["ts"].dt.strftime("%Y-%m")

    m_table = Table(title="Breakdown Mensuel — 6 Mois Réels", box=box.SIMPLE_HEAVY)
    for col in ["Mois", "Trades", "Win%", "Lev Moy", "Net EUR", "Ret%", "Capital", "Statut"]:
        m_table.add_column(col, justify="right" if col not in ["Mois", "Statut"] else "left")

    prev_eq = start_v
    for m in sorted(df_t["month"].unique()):
        mt     = df_t[df_t["month"] == m]
        net_m  = mt["pnl"].sum()
        wr_m   = mt["win"].sum() / len(mt) * 100 if len(mt) > 0 else 0
        lv_m   = mt["lev"].mean()
        m_eq   = eq_df[eq_df["month"] == m]["eq"]
        end_eq = float(m_eq.iloc[-1]) if len(m_eq) > 0 else prev_eq
        ret_m  = (end_eq - prev_eq) / prev_eq * 100 if prev_eq > 0 else 0
        if ret_m >= 200: stat = "[bold magenta]×3+[/bold magenta]"
        elif ret_m >= 100: stat = "[bold green]×2+[/bold green]"
        elif ret_m >= 50:  stat = "[bold green]×1.5+[/bold green]"
        elif ret_m >= 20:  stat = "[green]+20%+[/green]"
        elif ret_m >= 0:   stat = "[green]+[/green]"
        else:              stat = "[red]-[/red]"
        m_table.add_row(
            m, str(len(mt)), f"{wr_m:.0f}%", f"{lv_m:.1f}x",
            f"[{'green' if net_m >= 0 else 'red'}]{'+' if net_m >= 0 else ''}{net_m:.2f}EUR[/]",
            f"{'+' if ret_m >= 0 else ''}{ret_m:.1f}%",
            f"{end_eq:.0f}EUR", stat,
        )
        prev_eq = end_eq
    console.print(m_table)

    # Top trades
    if w_trades:
        top = sorted(w_trades, key=lambda t: t.pnl_eur, reverse=True)[:10]
        tw = Table(title="Top 10 Meilleurs Trades", box=box.SIMPLE)
        for c in ["Sym", "Side", "Score", "F", "Net EUR", "PnL%", "Lev", "Sortie"]:
            tw.add_column(c)
        for t in top:
            tw.add_row(
                t.symbol.split("/")[0], t.side[:5],
                str(t.score), f"{t.filters}/5",
                f"[green]+{t.pnl_eur:.2f}EUR[/green]",
                f"+{t.pnl_pct:.1f}%", f"{t.leverage}x",
                t.exit_reason[:6],
            )
        console.print(tw)

    # Sparkline
    if eq_vals:
        eq_min = min(eq_vals); eq_max = max(eq_vals)
        W  = 60
        sv = [eq_vals[int(i * len(eq_vals) / W)] for i in range(W)]
        ch = " ▁▂▃▄▅▆▇█"
        def tb(v):
            if eq_max == eq_min: return "▄"
            return ch[min(int((v - eq_min) / (eq_max - eq_min) * 8), 8)]
        console.print(Panel(
            "".join(tb(v) for v in sv) + "\n"
            f"   {start_v:.0f}EUR → {final_eq:.0f}EUR  |  "
            f"Min: {eq_min:.0f}EUR  Max: {eq_max:.0f}EUR",
            title="[bold]Equity 6 Mois[/bold]", border_style="blue",
        ))

    elapsed = time.time() - t0
    console.rule(f"[bold]FIN · {elapsed:.1f}s · {len(w_trades)} trades · 4F exclus · macro ±2%[/bold]")


# ── Test 3 configurations ─────────────────────────────────────────────────────

def run_configs(sym_data, window_timestamps, btc_macro, window_start):
    results = []
    console.print(f"\n[bold cyan]Test de {len(CONFIGS)} configurations "
                  f"(3F+5F, macro ±2%, {N_MAX_POSITIONS} pos)...[/bold cyan]")

    for cfg in CONFIGS:
        t_s = time.time()
        console.print(f"  [{cfg['name']}] score≥{cfg['score_min']} "
                      f"sq≥{cfg['sq_bars']} risk_base={cfg['risk_pct']*100:.0f}% "
                      f"sl={cfg['sl_pct']*100:.1f}%...")

        trades, eq_curve, dw = run_engine(
            sym_data, window_timestamps, btc_macro,
            score_min=cfg["score_min"], sq_bars=cfg["sq_bars"],
            risk_pct=cfg["risk_pct"], sl_pct=cfg["sl_pct"],
        )
        m = _quick_metrics(trades, eq_curve, window_start)
        composite = m["ret"] * (1 - m["dd"] / 200) * max(m["wr"] / 15, 0.1)
        results.append({**cfg, **m, "composite": composite,
                        "trades_obj": trades, "eq_curve": eq_curve, "day_wins": dw})
        console.print(f"    → {'+' if m['ret'] >= 0 else ''}{m['ret']:.1f}%  "
                      f"WR:{m['wr']:.0f}%  DD:{m['dd']:.1f}%  "
                      f"Net:{'+' if m['net'] >= 0 else ''}{m['net']:.0f}EUR  "
                      f"Trades:{m['trades']}  [{time.time()-t_s:.0f}s]")

    results.sort(key=lambda r: r["composite"], reverse=True)
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    console.rule("[bold yellow]SKYN v11 — MACRO ±2% / 3F+5F / NO NEUTRAL[/bold yellow]")

    cfg = AppConfig()
    console.print(f"Téléchargement et calcul ({len(SYMBOLS_YF)} symboles)...")
    sym_data = {}
    for sym in SYMBOLS_YF:
        t_sym = time.time()
        sd = precompute_symbol(sym, cfg)
        if sd is None:
            console.print(f"  [yellow]? {sym} — indisponible (ignoré)[/yellow]")
            continue
        sym_data[sym] = sd
        console.print(f"  [green]✓ {sym}[/green] — {len(sd['df'])} barres [{time.time()-t_sym:.1f}s]")

    if "BTC-USD" not in sym_data:
        console.print("[bold red]BTC-USD obligatoire pour le filtre macro.[/bold red]")
        return

    btc_macro = _build_btc_macro(sym_data["BTC-USD"])

    # Afficher la répartition macro (±2%) sur la période
    macro_counts: dict = {}
    for v in btc_macro.values():
        macro_counts[v] = macro_counts.get(v, 0) + 1
    b = macro_counts.get("bull", 0); r = macro_counts.get("bear", 0)
    n = macro_counts.get("neutral", 0)
    total_d = b + r + n or 1
    console.print(f"\n  Macro BTC (2 ans, ±2%) : "
                  f"bull={b}j  bear={r}j  neutral={n}j  "
                  f"[dim](trading actif : {b+r}j / {total_d}j = {(b+r)*100//total_d}%)[/dim]")

    console.print("\nConstruction de l'index commun...")
    common_set = None
    for sd in sym_data.values():
        s = set(sd["ts_index"])
        common_set = s if common_set is None else common_set & s
    common_timestamps = sorted(common_set)
    console.print(f"  {len(common_timestamps)} barres communes sur {len(sym_data)} symboles")

    last_ts      = common_timestamps[-1]
    window_start = last_ts - pd.DateOffset(months=6)
    console.print(f"  Fenêtre 6 mois : {window_start.strftime('%Y-%m-%d')} → "
                  f"{last_ts.strftime('%Y-%m-%d')}\n")

    window_timestamps = [ts for ts in common_timestamps[WARMUP:] if ts >= window_start]
    console.print(f"  {len(window_timestamps)} barres dans la fenêtre 6 mois\n")

    results = run_configs(sym_data, window_timestamps, btc_macro, window_start)

    console.print()
    cmp_table = Table(title="Comparatif v11 — 3 Configurations (macro ±2%, 4F exclu)",
                      box=box.SIMPLE_HEAVY)
    for col in ["Config", "Score≥", "Sq≥", "RiskBase%", "Ret%", "DD%", "WR%", "Trades", "Net EUR"]:
        cmp_table.add_column(col, justify="right" if col != "Config" else "left")
    for r in results:
        cmp_table.add_row(
            f"[bold]{r['name']}[/bold]",
            str(r["score_min"]), str(r["sq_bars"]),
            f"{r['risk_pct']*100:.0f}%",
            f"[{'green' if r['ret'] >= 0 else 'red'}]{'+' if r['ret'] >= 0 else ''}{r['ret']:.1f}%[/]",
            f"{r['dd']:.1f}%", f"{r['wr']:.0f}%", str(r["trades"]),
            f"[{'green' if r['net'] >= 0 else 'red'}]{'+' if r['net'] >= 0 else ''}{r['net']:.0f}EUR[/]",
        )
    console.print(cmp_table)

    best = results[0]
    console.print(f"\n[bold green]▶ Meilleure config : {best['name']} "
                  f"(score≥{best['score_min']} sq≥{best['sq_bars']} "
                  f"risk_base={best['risk_pct']*100:.0f}%)[/bold green]")

    print_report(
        best["trades_obj"], best["eq_curve"], best["day_wins"],
        window_start, best, t0,
    )


if __name__ == "__main__":
    main()
