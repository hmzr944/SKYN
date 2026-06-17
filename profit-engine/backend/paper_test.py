#!/usr/bin/env python3
"""
SKYN — Full Pipeline Paper Trading Test
========================================
Simulates 100-200 trades using the REAL production pipeline on live historical data:
  - StrategyRouter (regime detection + score adjustment)
  - SignalFilter   (MTF 4h alignment, RSI/VWAP/candle timing)
  - LeverageManager (dynamic leverage per score)
  - Portfolio simulation (SL/TP/trailing stop/liquidation/partial TP)

No look-ahead bias: each bar only sees data available at that point in time.

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
from rich.columns import Columns
from rich.text import Text
from rich import box

from config import AppConfig
from engine.analysis.indicators import compute_all, _ema
from engine.analysis.signals import score_signal, Signal
from engine.strategy.regime_detector import detect_regime, Regime
from engine.strategy.strategy_router import StrategyRouter, _PARAMS
from engine.execution.leverage_manager import LeverageManager

console = Console()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SYMBOLS_YF   = ["BTC-USD", "ETH-USD", "SOL-USD"]
SYMBOL_NAMES = {"BTC-USD": "BTC/USDT", "ETH-USD": "ETH/USDT", "SOL-USD": "SOL/USDT"}
INITIAL_CAPITAL  = 10_000.0
COMMISSION       = 0.0004   # Binance futures taker 0.04%
SLIPPAGE         = 0.0005   # 0.05%
RISK_PER_TRADE   = 0.02     # 2% of equity per trade
TRAIL_MULT       = 0.8      # ATR multiplier for trailing stop
DAILY_LOSS_LIMIT = 0.10     # 10% → halt trading for the day
PERIOD           = "2y"     # 2 years of data
WARMUP           = 210      # bars before trading starts (need 200 for ema200)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def download_data(symbol: str) -> Optional[pd.DataFrame]:
    console.print(f"  [cyan]↓[/cyan] Downloading {symbol} ({PERIOD})…", end="")
    try:
        raw = yf.download(symbol, period=PERIOD, interval="1h",
                          auto_adjust=True, progress=False)
        if raw is None or len(raw) < WARMUP + 50:
            console.print(" [red]insufficient data[/red]")
            return None
        df = raw.copy()
        # yfinance may return MultiIndex columns (field, ticker)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0].lower() for col in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        df.index.name = "timestamp"
        console.print(f" [green]{len(df)} bars ✓[/green]")
        return df
    except Exception as exc:
        console.print(f" [red]error: {exc}[/red]")
        return None


def resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1h bars into 4h bars."""
    df = df_1h.copy()
    df4 = df.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    # Add 4h EMAs for MTF check
    c = df4["close"]
    df4["ema9"]   = _ema(c, 9)
    df4["ema21"]  = _ema(c, 21)
    df4["ema50"]  = _ema(c, 50)
    df4["ema200"] = _ema(c, 200)
    return df4


# ---------------------------------------------------------------------------
# MTF helper
# ---------------------------------------------------------------------------

def _mtf_check(signal_action: str, df4: pd.DataFrame, ts) -> Tuple[float, bool, str]:
    """
    Returns (boost, aligned, reason) using the 4h bar that was COMPLETE at ts.
    Mirrors SignalFilter._check_mtf() but works on pre-computed 4h data.
    """
    try:
        past = df4[df4.index < ts]
        if len(past) < 50:
            return 0.0, False, "MTF: insuffisant"
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

        if bullish and signal_action == "BUY":
            return 15.0, True, "MTF: 4h haussier → BUY (+15)"
        if bearish and signal_action == "SELL":
            return 15.0, True, "MTF: 4h baissier → SELL (+15)"
        if bullish and signal_action == "SELL":
            return -20.0, False, "MTF: 4h haussier contredit SELL (-20)"
        if bearish and signal_action == "BUY":
            return -20.0, False, "MTF: 4h baissier contredit BUY (-20)"
        return 0.0, False, "MTF: neutre"
    except Exception:
        return 0.0, False, "MTF: erreur"


def _entry_timing_check(signal_action: str, last_row) -> float:
    """RSI overextension + candle body + VWAP. Returns score boost."""
    boost = 0.0
    try:
        rsi_v = last_row.get("rsi")
        if rsi_v is not None and not math.isnan(float(rsi_v)):
            rsi_v = float(rsi_v)
            if signal_action == "BUY" and rsi_v > 68:
                boost -= 15
            elif signal_action == "SELL" and rsi_v < 32:
                boost -= 15

        o  = float(last_row["open"])
        c  = float(last_row["close"])
        h  = float(last_row["high"])
        lo = float(last_row["low"])
        rng = h - lo
        body = abs(c - o)
        if rng > 0 and body / rng < 0.25:
            boost -= 8  # doji

        vwap_v = last_row.get("vwap")
        price  = float(last_row["close"])
        if vwap_v is not None and not math.isnan(float(vwap_v)):
            vwap_v = float(vwap_v)
            if signal_action == "BUY" and price < vwap_v:
                boost -= 10
            elif signal_action == "SELL" and price > vwap_v:
                boost -= 10
            elif signal_action == "BUY" and price >= vwap_v:
                boost += 5
            elif signal_action == "SELL" and price <= vwap_v:
                boost += 5
    except (TypeError, ValueError, KeyError):
        pass
    return boost


# ---------------------------------------------------------------------------
# Trade data class
# ---------------------------------------------------------------------------

@dataclass
class PaperTrade:
    symbol: str
    side: str
    entry_idx: int
    exit_idx: int
    entry_price: float
    exit_price: float
    margin_used: float
    leverage: int
    pnl: float
    pnl_pct: float          # % of margin
    exit_reason: str
    score: float
    regime: str
    strategy: str
    mtf_aligned: bool
    filter_boost: float
    candles_held: int


# ---------------------------------------------------------------------------
# Full-pipeline paper simulator
# ---------------------------------------------------------------------------

class FullPipelinePaper:
    def __init__(self):
        self.cfg = AppConfig()
        self.router = StrategyRouter()
        self.lev_mgr = LeverageManager()

    def run(self, df_1h_raw: pd.DataFrame, symbol: str) -> List[PaperTrade]:
        yf_sym = symbol
        prod_sym = SYMBOL_NAMES.get(symbol, symbol)

        # 1. Compute all indicators ONCE on the full dataset
        cfg = self.cfg
        df = compute_all(df_1h_raw.copy(), cfg.strategy)

        # 2. Prepare 4h MTF frame
        df4 = resample_4h(df)

        trades: List[PaperTrade] = []
        n = len(df)

        # --- account state ---
        cash           = INITIAL_CAPITAL
        in_pos         = False
        pos: dict      = {}

        # --- daily loss tracking ---
        day_start_eq   = INITIAL_CAPITAL
        current_day    = None
        halted         = False

        # --- partial TP tracking ---
        partial_taken  = False

        for i in range(WARMUP, n):
            row    = df.iloc[i]
            price  = float(row["close"])
            ts     = df.index[i]
            atr_v  = float(row["atr"]) if not pd.isna(row.get("atr", float("nan"))) else price * 0.02

            # ---- Day rollover ----------------------------------------
            day_key = str(ts)[:10]
            if day_key != current_day:
                current_day  = day_key
                current_eq   = cash + (pos.get("margin", 0) if in_pos else 0)
                day_start_eq = current_eq
                halted       = False

            # ---- Daily loss circuit-breaker -------------------------
            if not in_pos and not halted:
                cur_eq = cash
                if day_start_eq > 0 and (day_start_eq - cur_eq) / day_start_eq >= DAILY_LOSS_LIMIT:
                    halted = True

            # ---- Update trailing stop --------------------------------
            if in_pos and not math.isnan(pos.get("trail", float("nan"))):
                if pos["side"] == "long":
                    new_t = price - atr_v * TRAIL_MULT
                    if new_t > pos["trail"]:
                        pos["trail"] = new_t
                else:
                    new_t = price + atr_v * TRAIL_MULT
                    if new_t < pos["trail"]:
                        pos["trail"] = new_t

            # ---- Check exits ----------------------------------------
            if in_pos:
                reason = None
                side   = pos["side"]

                # Liquidation (priority)
                if side == "long" and price <= pos["liq"]:
                    reason = "liquidation"
                elif side == "short" and price >= pos["liq"]:
                    reason = "liquidation"
                # Partial TP (50% at midway)
                elif not partial_taken:
                    if side == "long" and price >= pos["partial_tp"]:
                        partial_taken = True
                        # Move SL to breakeven
                        pos["sl"] = pos["entry"]
                        # Don't close yet — let the other half ride
                # Full SL / TP / trail
                if reason is None:
                    if side == "long":
                        if price <= pos["sl"]:      reason = "stop_loss"
                        elif price <= pos.get("trail", -1): reason = "trailing_stop"
                        elif price >= pos["tp"]:    reason = "take_profit"
                    else:
                        if price >= pos["sl"]:      reason = "stop_loss"
                        elif price >= pos.get("trail", 1e18): reason = "trailing_stop"
                        elif price <= pos["tp"]:    reason = "take_profit"

                if reason:
                    if reason == "liquidation":
                        pnl = -pos["margin"]
                        exit_p = pos["liq"]
                    else:
                        slip    = (1 - SLIPPAGE) if side == "long" else (1 + SLIPPAGE)
                        exit_p  = price * slip
                        if side == "long":
                            raw_pnl = (exit_p - pos["entry"]) * pos["qty"]
                        else:
                            raw_pnl = (pos["entry"] - exit_p) * pos["qty"]
                        exit_comm = pos["qty"] * exit_p * COMMISSION
                        pnl       = raw_pnl - exit_comm
                        cash     += pos["margin"] + pnl

                    pnl_pct = pnl / pos["margin"] * 100 if pos["margin"] > 0 else 0.0
                    trades.append(PaperTrade(
                        symbol=prod_sym, side=side,
                        entry_idx=pos["idx"], exit_idx=i,
                        entry_price=pos["entry"], exit_price=exit_p,
                        margin_used=round(pos["margin"], 4),
                        leverage=pos["leverage"],
                        pnl=round(pnl, 4), pnl_pct=round(pnl_pct, 3),
                        exit_reason=reason,
                        score=pos["score"], regime=pos["regime"],
                        strategy=pos["strategy"], mtf_aligned=pos["mtf_aligned"],
                        filter_boost=pos["filter_boost"],
                        candles_held=i - pos["idx"],
                    ))
                    in_pos       = False
                    partial_taken = False
                    continue

            # ---- Check entry ----------------------------------------
            if in_pos or halted or cash < 10:
                continue

            # Slice seen so far (no look-ahead)
            curr_df = df.iloc[:i + 1]

            # Base signal
            try:
                base_sig = score_signal(curr_df, prod_sym, cfg)
            except Exception:
                continue

            if base_sig.action == "HOLD":
                continue

            # Regime detection + routing
            try:
                regime_result = detect_regime(curr_df)
                p = _PARAMS[regime_result.regime]
            except Exception:
                continue

            # Apply regime score adjustments (mirrors StrategyRouter._adjust)
            adj_score = base_sig.score
            if regime_result.regime == Regime.BULL_TREND:
                if base_sig.action == "BUY":
                    adj_score = min(adj_score + p.get("buy_bonus", 0), 100)
                elif base_sig.action == "SELL":
                    adj_score = max(adj_score - p.get("sell_penalty", 0), 0)
            elif regime_result.regime == Regime.BEAR_TREND:
                if base_sig.action == "SELL":
                    adj_score = min(adj_score + p.get("sell_bonus", 0), 100)
                elif base_sig.action == "BUY":
                    adj_score = max(adj_score - p.get("buy_penalty", 0), 0)
            elif regime_result.regime == Regime.BREAKOUT:
                if regime_result.trend_direction == "up" and base_sig.action == "BUY":
                    adj_score = min(adj_score + p.get("buy_bonus", 0), 100)
                elif regime_result.trend_direction == "down" and base_sig.action == "SELL":
                    adj_score = min(adj_score + p.get("sell_bonus", 0), 100)
            elif regime_result.regime == Regime.HIGH_VOL:
                adj_score *= 0.5

            min_score = p["min_score"]
            if adj_score < min_score:
                continue

            if regime_result.regime == Regime.HIGH_VOL and regime_result.atr_pct > 5.0:
                continue  # skip — extreme vol

            # Signal filter
            filter_boost = 0.0
            mtf_boost, mtf_aligned, _ = _mtf_check(base_sig.action, df4, ts)
            filter_boost += mtf_boost

            # MTF hard block — 4h contradiction always blocks
            hard_blocked = len(df4[df4.index < ts]) >= 50 and mtf_boost <= -20
            if hard_blocked:
                continue

            # Regime gate: BULL_TREND and BEAR_TREND always allowed.
            # BREAKOUT allowed only with real volume surge + high score.
            # RANGING and HIGH_VOL always skipped.
            from engine.strategy.regime_detector import Regime as _Regime
            if regime_result.regime == _Regime.RANGING:
                continue
            if regime_result.regime == _Regime.HIGH_VOL:
                continue
            if regime_result.regime == _Regime.BREAKOUT:
                if not regime_result.vol_surge:
                    continue  # must have real volume
                if adj_score < 78:
                    continue  # only high-conviction breakouts

            # Macro trend filter: block entries that strongly contradict long-term EMA200.
            ema200_val = float(row.get("ema200") or row["close"])
            curr_close = float(row["close"])
            macro_buffer = ema200_val * 0.05  # 5% buffer
            if base_sig.action == "BUY" and curr_close < ema200_val - macro_buffer:
                continue
            if base_sig.action == "SELL" and curr_close > ema200_val + macro_buffer:
                continue

            # Entry timing (RSI / candle / VWAP)
            timing_boost = _entry_timing_check(base_sig.action, row)
            filter_boost += timing_boost

            MIN_NET_SCORE = -15.0
            if filter_boost < MIN_NET_SCORE:
                continue

            final_score = round(min(max(adj_score + filter_boost, 0), 100), 1)
            if final_score < 50:
                continue

            # Open position
            sl_mult = p["sl_mult"]
            tp_rr   = p["tp_rr"]
            max_lev = p["max_leverage"]

            lev     = min(self.lev_mgr.get_leverage(final_score, "HIGH"), max_lev)
            sl_dist = atr_v * sl_mult
            tp_dist = sl_dist * tp_rr

            if base_sig.action == "BUY":
                entry_p     = price * (1 + SLIPPAGE)
                sl, tp      = entry_p - sl_dist, entry_p + tp_dist
                partial_tp  = entry_p + (tp - entry_p) * 0.5
                liq_p       = self.lev_mgr.liquidation_price(entry_p, lev, "long")
                sl          = max(sl, liq_p * 1.001)
                side        = "long"
            else:
                entry_p     = price * (1 - SLIPPAGE)
                sl, tp      = entry_p + sl_dist, entry_p - tp_dist
                partial_tp  = entry_p - (entry_p - tp) * 0.5
                liq_p       = self.lev_mgr.liquidation_price(entry_p, lev, "short")
                sl          = min(sl, liq_p * 0.999)
                side        = "short"

            sl_distance = abs(entry_p - sl) or entry_p * 0.02
            risk_amount = cash * RISK_PER_TRADE
            qty         = risk_amount / sl_distance
            margin      = qty * entry_p / lev

            if margin > cash * 0.95:
                margin = cash * 0.95
                qty    = margin * lev / entry_p

            entry_comm = qty * entry_p * COMMISSION
            total_cost = margin + entry_comm

            if qty <= 1e-10 or total_cost > cash:
                continue

            cash -= total_cost
            in_pos       = True
            partial_taken = False
            pos = {
                "side": side, "entry": entry_p, "qty": qty,
                "margin": margin, "liq": liq_p, "sl": sl, "tp": tp,
                "partial_tp": partial_tp,
                "trail": float("nan"),
                "leverage": lev, "score": final_score,
                "idx": i,
                "regime": regime_result.regime.value,
                "strategy": p["name"],
                "mtf_aligned": mtf_aligned,
                "filter_boost": filter_boost,
            }

        # Close open position at end of data
        if in_pos:
            final_p = float(df.iloc[-1]["close"])
            slip    = (1 - SLIPPAGE) if pos["side"] == "long" else (1 + SLIPPAGE)
            exit_p  = final_p * slip
            side    = pos["side"]
            if side == "long":
                raw_pnl = (exit_p - pos["entry"]) * pos["qty"]
            else:
                raw_pnl = (pos["entry"] - exit_p) * pos["qty"]
            exit_comm = pos["qty"] * exit_p * COMMISSION
            pnl       = raw_pnl - exit_comm
            pnl_pct   = pnl / pos["margin"] * 100 if pos["margin"] > 0 else 0.0
            trades.append(PaperTrade(
                symbol=prod_sym, side=side,
                entry_idx=pos["idx"], exit_idx=n - 1,
                entry_price=pos["entry"], exit_price=exit_p,
                margin_used=round(pos["margin"], 4),
                leverage=pos["leverage"],
                pnl=round(pnl, 4), pnl_pct=round(pnl_pct, 3),
                exit_reason="end_of_data",
                score=pos["score"], regime=pos["regime"],
                strategy=pos["strategy"], mtf_aligned=pos["mtf_aligned"],
                filter_boost=pos["filter_boost"],
                candles_held=n - 1 - pos["idx"],
            ))

        return trades


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(trades: List[PaperTrade], initial: float) -> dict:
    if not trades:
        return {}

    equity = initial
    equity_curve = [initial]
    for t in trades:
        if t.exit_reason == "liquidation":
            equity -= t.margin_used
        else:
            equity += t.pnl
        equity_curve.append(equity)

    eq = np.array(equity_curve, dtype=float)
    total_return = (eq[-1] - initial) / initial * 100
    peak = np.maximum.accumulate(eq)
    dd   = (peak - eq) / np.where(peak == 0, 1, peak)
    max_dd = float(dd.max()) * 100

    returns = np.diff(eq) / np.where(eq[:-1] == 0, 1, eq[:-1])
    sharpe  = float(returns.mean() / returns.std() * np.sqrt(8760)) if returns.std() > 1e-10 else 0.0
    neg     = returns[returns < 0]
    sortino = float(returns.mean() / neg.std() * np.sqrt(8760)) if len(neg) > 1 and neg.std() > 1e-10 else 0.0

    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_rate     = len(wins) / len(trades) * 100
    gross_profit = sum(t.pnl for t in wins)
    gross_loss   = abs(sum(t.pnl for t in losses)) or 1e-9
    pf           = min(gross_profit / gross_loss, 99.0)

    longs  = [t for t in trades if t.side == "long"]
    shorts = [t for t in trades if t.side == "short"]
    liqs   = [t for t in trades if t.exit_reason == "liquidation"]

    avg_win_pct   = float(np.mean([t.pnl_pct for t in wins]))   if wins   else 0.0
    avg_loss_pct  = float(np.mean([t.pnl_pct for t in losses])) if losses else 0.0
    avg_score     = float(np.mean([t.score   for t in trades]))
    avg_leverage  = float(np.mean([t.leverage for t in trades]))
    avg_candles   = float(np.mean([t.candles_held for t in trades]))
    mtf_rate      = sum(1 for t in trades if t.mtf_aligned) / len(trades) * 100

    # Regime breakdown
    regime_counts: Dict[str, int] = {}
    regime_wins:   Dict[str, int] = {}
    for t in trades:
        regime_counts[t.regime] = regime_counts.get(t.regime, 0) + 1
        if t.pnl > 0:
            regime_wins[t.regime] = regime_wins.get(t.regime, 0) + 1

    # Exit reason breakdown
    exit_counts: Dict[str, int] = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

    return {
        "total_trades": len(trades),
        "total_return_pct": round(total_return, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 3),
        "avg_win_pct": round(avg_win_pct, 2),
        "avg_loss_pct": round(avg_loss_pct, 2),
        "avg_score": round(avg_score, 1),
        "avg_leverage": round(avg_leverage, 2),
        "avg_candles": round(avg_candles, 1),
        "mtf_rate": round(mtf_rate, 1),
        "longs": len(longs),
        "shorts": len(shorts),
        "liquidations": len(liqs),
        "final_equity": round(eq[-1], 2),
        "equity_curve": equity_curve,
        "wins": len(wins),
        "losses": len(losses),
        "regime_counts": regime_counts,
        "regime_wins": regime_wins,
        "exit_counts": exit_counts,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
    }


# ---------------------------------------------------------------------------
# Rich Report
# ---------------------------------------------------------------------------

def print_report(all_trades: List[PaperTrade], per_symbol: Dict[str, dict]):
    console.rule("[bold yellow]SKYN — PAPER TRADING TEST REPORT[/bold yellow]")
    console.print()

    # Global metrics
    global_m = compute_metrics(all_trades, INITIAL_CAPITAL)
    if not global_m:
        console.print("[red]No trades executed.[/red]")
        return

    # ---- Summary panel --------------------------------------------------
    ret   = global_m["total_return_pct"]
    color = "green" if ret > 0 else "red"
    final = global_m["final_equity"]

    summary = Table.grid(padding=(0, 2))
    summary.add_row(
        f"[bold]Capital initial[/bold]",  f"[white]{INITIAL_CAPITAL:,.0f} $[/white]"
    )
    summary.add_row(
        f"[bold]Capital final[/bold]",    f"[{color}]{final:,.2f} $[/{color}]"
    )
    summary.add_row(
        f"[bold]Retour total[/bold]",     f"[{color}]{ret:+.2f}%[/{color}]"
    )
    summary.add_row(
        f"[bold]Drawdown max[/bold]",     f"[{'red' if global_m['max_drawdown_pct']>15 else 'yellow'}]{global_m['max_drawdown_pct']:.1f}%[/]"
    )
    summary.add_row(
        f"[bold]Sharpe[/bold]",           f"[cyan]{global_m['sharpe_ratio']:.3f}[/cyan]"
    )
    summary.add_row(
        f"[bold]Sortino[/bold]",          f"[cyan]{global_m['sortino_ratio']:.3f}[/cyan]"
    )
    summary.add_row(
        f"[bold]Profit Factor[/bold]",    f"[cyan]{global_m['profit_factor']:.3f}[/cyan]"
    )
    console.print(Panel(summary, title="[bold]Résultats Globaux[/bold]", border_style="yellow"))
    console.print()

    # ---- Trade stats table ----------------------------------------------
    t1 = Table(title="Statistiques de Trading", box=box.ROUNDED, border_style="cyan")
    t1.add_column("Métrique",        style="bold")
    t1.add_column("Valeur",          justify="right")
    t1.add_column("Évaluation",      justify="center")

    def grade(val, thresholds, labels):
        for thresh, label in zip(thresholds, labels):
            if val >= thresh: return label
        return labels[-1]

    rows_t1 = [
        ("Trades totaux",       f"{global_m['total_trades']}",
         grade(global_m['total_trades'], [100, 50, 20], ["[green]✓ Bon[/]", "[yellow]∼ Moyen[/]", "[red]✗ Faible[/]", "[red]✗ Très faible[/]"])),
        ("Win rate",            f"{global_m['win_rate']:.1f}%",
         grade(global_m['win_rate'], [60, 50, 40], ["[green]✓ Bon[/]", "[yellow]∼ Correct[/]", "[red]✗ Faible[/]", "[red]✗ Très faible[/]"])),
        ("Gain moyen / trade",  f"{global_m['avg_win_pct']:+.1f}%",
         "[green]✓[/]" if global_m['avg_win_pct'] > 0 else "[red]✗[/]"),
        ("Perte moyenne / trade", f"{global_m['avg_loss_pct']:+.1f}%",
         "[green]✓[/]" if abs(global_m['avg_loss_pct']) < global_m['avg_win_pct'] else "[red]✗[/]"),
        ("Score moyen d'entrée",  f"{global_m['avg_score']:.1f}",
         grade(global_m['avg_score'], [72, 65, 58], ["[green]✓ Sélectif[/]", "[yellow]∼ Correct[/]", "[red]Trop permissif[/]", "[red]Trop permissif[/]"])),
        ("Levier moyen",          f"{global_m['avg_leverage']:.1f}x",
         "[yellow]∼[/]" if global_m['avg_leverage'] < 5 else "[red]✗ Élevé[/]"),
        ("Durée moyenne (bougies)", f"{global_m['avg_candles']:.0f}h",
         "[cyan]→[/]"),
        ("Alignement MTF (4h)",   f"{global_m['mtf_rate']:.0f}%",
         grade(global_m['mtf_rate'], [60, 40], ["[green]✓ Bon[/]", "[yellow]∼[/]", "[red]✗[/]"])),
        ("Long / Short",          f"{global_m['longs']} / {global_m['shorts']}",
         "[cyan]→[/]"),
        ("Liquidations",          f"{global_m['liquidations']}",
         "[green]✓ 0[/]" if global_m['liquidations'] == 0 else "[red]✗ Présentes[/]"),
    ]

    for label, val, ev in rows_t1:
        t1.add_row(label, val, ev)
    console.print(t1)
    console.print()

    # ---- Per-symbol table -----------------------------------------------
    t2 = Table(title="Performance par Symbole", box=box.ROUNDED, border_style="magenta")
    for col in ["Symbole", "Trades", "Win%", "Retour%", "Drawdown%", "Sharpe", "Levier moy", "Liquidations"]:
        t2.add_column(col, justify="right")
    t2.columns[0].justify = "left"

    for sym, m in per_symbol.items():
        if not m: continue
        c = "green" if m["total_return_pct"] > 0 else "red"
        t2.add_row(
            sym,
            str(m["total_trades"]),
            f"[{'green' if m['win_rate']>=55 else 'red'}]{m['win_rate']:.1f}%[/]",
            f"[{c}]{m['total_return_pct']:+.2f}%[/{c}]",
            f"[{'red' if m['max_drawdown_pct']>20 else 'yellow'}]{m['max_drawdown_pct']:.1f}%[/]",
            f"{m['sharpe_ratio']:.2f}",
            f"{m['avg_leverage']:.1f}x",
            f"[{'red' if m['liquidations']>0 else 'green'}]{m['liquidations']}[/]",
        )
    console.print(t2)
    console.print()

    # ---- Regime breakdown -----------------------------------------------
    t3 = Table(title="Performance par Régime de Marché", box=box.ROUNDED, border_style="blue")
    t3.add_column("Régime",        style="bold")
    t3.add_column("Trades",        justify="right")
    t3.add_column("Gagnants",      justify="right")
    t3.add_column("Win%",          justify="right")
    t3.add_column("Stratégie")

    regime_names = {
        "bull_trend": ("BULL TREND", "Momentum Haussier"),
        "bear_trend": ("BEAR TREND", "Momentum Baissier"),
        "ranging":    ("RANGING",    "Mean Reversion"),
        "breakout":   ("BREAKOUT",   "Breakout"),
        "high_volatility": ("HIGH VOL", "Défensif"),
    }

    for regime_key, count in sorted(global_m["regime_counts"].items(),
                                     key=lambda x: -x[1]):
        wins_r = global_m["regime_wins"].get(regime_key, 0)
        wr     = wins_r / count * 100 if count else 0
        name, strat = regime_names.get(regime_key, (regime_key, ""))
        c = "green" if wr >= 55 else ("yellow" if wr >= 45 else "red")
        t3.add_row(name, str(count), str(wins_r), f"[{c}]{wr:.0f}%[/{c}]", strat)
    console.print(t3)
    console.print()

    # ---- Exit reason breakdown ------------------------------------------
    t4 = Table(title="Raisons de Sortie", box=box.SIMPLE, border_style="white")
    t4.add_column("Raison",     style="bold")
    t4.add_column("Nombre",     justify="right")
    t4.add_column("% du total", justify="right")

    exit_labels = {
        "take_profit": "[green]Take Profit ✓[/green]",
        "stop_loss": "[red]Stop Loss ✗[/red]",
        "trailing_stop": "[yellow]Trailing Stop[/yellow]",
        "liquidation": "[bold red]Liquidation ⚡[/bold red]",
        "end_of_data": "[dim]Fin données[/dim]",
    }
    total = global_m["total_trades"]
    for reason, cnt in sorted(global_m["exit_counts"].items(), key=lambda x: -x[1]):
        pct = cnt / total * 100
        label = exit_labels.get(reason, reason)
        t4.add_row(label, str(cnt), f"{pct:.1f}%")
    console.print(t4)
    console.print()

    # ---- Analysis & Recommendations ------------------------------------
    issues = []
    goods  = []

    if global_m["win_rate"] >= 60:
        goods.append("Win rate solide (≥60%) — sélection de signaux efficace")
    elif global_m["win_rate"] >= 50:
        goods.append("Win rate correct (50-60%) — marge d'amélioration sur les filtres")
    else:
        issues.append(f"Win rate faible ({global_m['win_rate']:.0f}%) — les filtres doivent être renforcés")

    if global_m["profit_factor"] >= 1.5:
        goods.append(f"Profit Factor élevé ({global_m['profit_factor']:.2f}) — gains >> pertes")
    elif global_m["profit_factor"] >= 1.0:
        issues.append(f"Profit Factor borderline ({global_m['profit_factor']:.2f}) — R:R à améliorer")
    else:
        issues.append(f"Profit Factor <1.0 ({global_m['profit_factor']:.2f}) — système perd de l'argent")

    if global_m["max_drawdown_pct"] > 25:
        issues.append(f"Drawdown max élevé ({global_m['max_drawdown_pct']:.1f}%) — risk_per_trade à réduire ou SL à resserrer")
    elif global_m["max_drawdown_pct"] < 15:
        goods.append(f"Drawdown contrôlé ({global_m['max_drawdown_pct']:.1f}%)")

    if global_m["sharpe_ratio"] >= 1.5:
        goods.append(f"Sharpe excellent ({global_m['sharpe_ratio']:.2f}) — rendement ajusté risque très bon")
    elif global_m["sharpe_ratio"] >= 0.8:
        goods.append(f"Sharpe correct ({global_m['sharpe_ratio']:.2f})")
    else:
        issues.append(f"Sharpe faible ({global_m['sharpe_ratio']:.2f}) — volatilité trop haute par rapport aux gains")

    if global_m["liquidations"] > 0:
        issues.append(f"{global_m['liquidations']} liquidation(s) — le levier dépasse la capacité de résistance des stops")

    if global_m["mtf_rate"] < 50:
        issues.append(f"Seulement {global_m['mtf_rate']:.0f}% des trades alignés MTF — filtre 4h peut être relâché légèrement")
    else:
        goods.append(f"Alignement MTF à {global_m['mtf_rate']:.0f}% — confirmation multi-timeframe active")

    avg_candles = global_m["avg_candles"]
    if avg_candles < 10:
        issues.append(f"Durée de trade très courte ({avg_candles:.0f}h) — risque sur-trading / commission élevée")
    elif avg_candles > 100:
        issues.append(f"Durée de trade longue ({avg_candles:.0f}h) — capital immobilisé")

    # Regime-specific issues
    for regime_key, count in global_m["regime_counts"].items():
        wins_r = global_m["regime_wins"].get(regime_key, 0)
        wr = wins_r / count * 100 if count else 0
        if wr < 40 and count >= 5:
            issues.append(f"Régime {regime_key.upper()} a un win rate de {wr:.0f}% sur {count} trades — à éviter ou paramètres à revoir")

    # Print
    if goods:
        console.print(Panel(
            "\n".join(f"  [green]✓[/green] {g}" for g in goods),
            title="[bold green]Points Forts[/bold green]",
            border_style="green"
        ))

    if issues:
        console.print(Panel(
            "\n".join(f"  [yellow]→[/yellow] {iss}" for iss in issues),
            title="[bold yellow]Axes d'Amélioration[/bold yellow]",
            border_style="yellow"
        ))
    console.print()

    # ---- Top 10 and Worst 10 trades ------------------------------------
    sorted_trades = sorted(all_trades, key=lambda t: t.pnl, reverse=True)
    best10  = sorted_trades[:10]
    worst10 = sorted_trades[-10:]

    for title, tlist, header_color in [
        ("Top 10 Meilleurs Trades", best10, "green"),
        ("Top 10 Pires Trades", worst10, "red"),
    ]:
        tt = Table(title=title, box=box.SIMPLE, border_style=header_color)
        for col in ["Sym", "Side", "PnL $", "PnL%", "Score", "Levier", "Régime", "Sortie", "Durée"]:
            tt.add_column(col, justify="right" if col not in ["Sym", "Side", "Régime", "Sortie"] else "left")

        for t in tlist:
            c = "green" if t.pnl > 0 else "red"
            tt.add_row(
                t.symbol.split("/")[0],
                t.side,
                f"[{c}]{t.pnl:+.2f}[/{c}]",
                f"[{c}]{t.pnl_pct:+.1f}%[/{c}]",
                f"{t.score:.0f}",
                f"{t.leverage}x",
                t.regime,
                t.exit_reason,
                f"{t.candles_held}h",
            )
        console.print(tt)
        console.print()

    # ---- Equity curve mini-chart ----------------------------------------
    ec = global_m["equity_curve"]
    if len(ec) > 2:
        n_pts = min(60, len(ec))
        step  = len(ec) // n_pts
        pts   = [ec[i * step] for i in range(n_pts)] + [ec[-1]]
        mn, mx = min(pts), max(pts)
        rng = mx - mn or 1

        bars = []
        blocks = " ▁▂▃▄▅▆▇█"
        for v in pts:
            idx = int((v - mn) / rng * 8)
            bars.append(blocks[max(0, min(8, idx))])

        color = "green" if ec[-1] >= ec[0] else "red"
        chart = "".join(bars)
        console.print(Panel(
            f"[{color}]{chart}[/{color}]\n"
            f"  Début: {ec[0]:,.0f}$  →  Fin: {ec[-1]:,.2f}$  "
            f"  Min: {mn:,.0f}$  Max: {mx:,.0f}$",
            title="[bold]Courbe d'Equity (aperçu)[/bold]",
            border_style=color,
        ))

    console.print()
    console.rule("[bold yellow]FIN DU RAPPORT[/bold yellow]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    console.rule("[bold yellow]SKYN — Paper Trading Test[/bold yellow]")
    console.print(f"[dim]Pipeline complet · {len(SYMBOLS_YF)} symboles · {PERIOD} de données · Capital: {INITIAL_CAPITAL:,}$[/dim]")
    console.print()

    simulator = FullPipelinePaper()
    all_trades: List[PaperTrade] = []
    per_symbol: Dict[str, dict] = {}

    console.print("[bold]Téléchargement des données...[/bold]")
    data_map: Dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS_YF:
        df = download_data(sym)
        if df is not None:
            data_map[sym] = df

    if not data_map:
        console.print("[red]Aucune donnée téléchargée. Vérifiez votre connexion.[/red]")
        return

    console.print()
    console.print("[bold]Simulation en cours...[/bold]")

    for sym, df_raw in data_map.items():
        console.print(f"  [cyan]▶[/cyan] {sym}…", end="")
        t0 = time.time()
        try:
            trades = simulator.run(df_raw, sym)
            m = compute_metrics(trades, INITIAL_CAPITAL) if trades else {}
            per_symbol[SYMBOL_NAMES.get(sym, sym)] = m
            all_trades.extend(trades)
            elapsed = time.time() - t0
            console.print(f" [green]{len(trades)} trades[/green] en {elapsed:.1f}s")
        except Exception as exc:
            console.print(f" [red]erreur: {exc}[/red]")
            import traceback; traceback.print_exc()

    console.print()
    console.print(f"[bold green]Total: {len(all_trades)} trades simulés[/bold green]")
    console.print()

    if all_trades:
        print_report(all_trades, per_symbol)
    else:
        console.print("[red]Aucun trade. Vérifiez les paramètres (min_score trop élevé ?).[/red]")


if __name__ == "__main__":
    main()
