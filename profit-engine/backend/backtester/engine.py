"""
Core backtesting engine — numpy-accelerated.
Row-by-row pandas access replaced with pre-extracted numpy arrays for ~20x speedup.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from engine.analysis.indicators import compute_all


@dataclass
class BTrade:
    symbol: str
    side: str
    entry_idx: int
    exit_idx: int
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    entry_score: float
    candles_held: int


@dataclass
class BacktestResult:
    symbol: str
    total_trades: int
    win_rate: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    profit_factor: float
    avg_win_pct: float
    avg_loss_pct: float
    avg_trade_pct: float
    avg_candles_held: float
    equity_curve: List[float]
    trades: List[BTrade]
    params: dict
    composite_score: float = 0.0


def _metrics(equity_curve: List[float], trades: List[BTrade], initial: float) -> dict:
    if not equity_curve or len(equity_curve) < 2:
        return {k: 0.0 for k in [
            "total_return_pct", "max_drawdown_pct", "sharpe_ratio", "sortino_ratio",
            "win_rate", "profit_factor", "avg_win_pct", "avg_loss_pct",
            "avg_trade_pct", "avg_candles_held",
        ]}

    eq = np.array(equity_curve, dtype=float)
    returns = np.diff(eq) / np.where(eq[:-1] == 0, 1, eq[:-1])

    total_return_pct = (eq[-1] - initial) / initial * 100

    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / np.where(peak == 0, 1, peak)
    max_dd = float(dd.max()) * 100

    if returns.std() > 1e-10:
        sharpe = float(returns.mean() / returns.std() * np.sqrt(8760))
    else:
        sharpe = 0.0

    neg = returns[returns < 0]
    sortino = float(returns.mean() / neg.std() * np.sqrt(8760)) if len(neg) > 1 and neg.std() > 1e-10 else 0.0

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0.0
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    profit_factor = min(profit_factor, 99.0)

    avg_win = float(np.mean([t.pnl_pct for t in wins])) if wins else 0.0
    avg_loss = float(np.mean([t.pnl_pct for t in losses])) if losses else 0.0
    avg_trade = float(np.mean([t.pnl_pct for t in trades])) if trades else 0.0
    avg_held = float(np.mean([t.candles_held for t in trades])) if trades else 0.0

    return {
        "total_return_pct": round(total_return_pct, 3),
        "max_drawdown_pct": round(max_dd, 3),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 4),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "avg_trade_pct": round(avg_trade, 3),
        "avg_candles_held": round(avg_held, 1),
    }


def composite_score(m: dict, n_trades: int) -> float:
    """
    Composite score to maximize during optimization.
    Heavily penalizes high drawdown and too-few trades (overfitting).
    """
    if n_trades < 8:
        return -999.0
    if m.get("max_drawdown_pct", 100) > 35:
        return -999.0
    sharpe = max(m.get("sharpe_ratio", 0.0), -3.0)
    pf = min(m.get("profit_factor", 0.0), 10.0)
    wr = m.get("win_rate", 0.0) / 100
    ret = m.get("total_return_pct", 0.0) / 100
    dd_penalty = max(0.0, m.get("max_drawdown_pct", 0.0) - 10.0) * 0.08
    pf_penalty = max(0.0, pf - 5.0) * 0.1
    score = sharpe * 1.5 + pf * 0.6 + wr * 0.5 + ret * 0.3 - dd_penalty - pf_penalty
    return round(score, 5)


def _get_col(df: pd.DataFrame, name: str) -> np.ndarray:
    if name in df.columns:
        return df[name].to_numpy(dtype=float, na_value=np.nan)
    return np.full(len(df), np.nan)


class Backtester:
    def __init__(self, commission: float = 0.001, slippage: float = 0.0005):
        self.commission = commission
        self.slippage = slippage

    def run(self, df: pd.DataFrame, cfg, symbol: str = "SYM") -> BacktestResult:
        if df is None or len(df) < 60:
            return self._empty(symbol, cfg)

        df_ind = compute_all(df, cfg.strategy)
        s = cfg.strategy
        r = cfg.risk
        initial = cfg.initial_capital
        n = len(df_ind)

        # Pre-extract all columns to numpy arrays — eliminates slow iloc/get per row
        close  = df_ind["close"].to_numpy(dtype=float)
        atr    = _get_col(df_ind, "atr")
        rsi    = _get_col(df_ind, "rsi")
        mhist  = _get_col(df_ind, "macd_hist")
        bbpct  = _get_col(df_ind, "bb_pct")
        ema9   = _get_col(df_ind, "ema9")
        ema21  = _get_col(df_ind, "ema21")
        ema50  = _get_col(df_ind, "ema50")
        sk     = _get_col(df_ind, "stoch_k")
        sd_arr = _get_col(df_ind, "stoch_d")
        volr   = _get_col(df_ind, "vol_ratio")

        # Strategy / risk params (local vars = faster)
        min_score   = float(s.min_score_buy)
        rsi_os      = float(s.rsi_oversold)
        rsi_ob      = float(s.rsi_overbought)
        sl_mult     = float(r.stop_loss_atr_mult)
        tp_rr       = float(r.take_profit_rr)
        trail_mult  = float(r.trailing_stop_atr_mult)
        risk_pct    = float(r.risk_per_trade_pct)
        commission  = self.commission
        slippage    = self.slippage

        cash = float(initial)
        equity_curve = [cash]
        trades: List[BTrade] = []

        in_pos = False
        pos_side = 0      # 1=long, -1=short
        pos_entry = 0.0
        pos_qty = 0.0
        pos_sl = 0.0
        pos_tp = 0.0
        pos_trail = np.nan
        pos_idx = 0
        pos_score = 0.0

        warmup = max(getattr(s, "ema_trend", 200), getattr(s, "bb_period", 20), 50)

        for i in range(warmup, n):
            price  = close[i]
            atr_v  = atr[i] if not np.isnan(atr[i]) else price * 0.02

            # Update trailing stop
            if in_pos and not np.isnan(pos_trail):
                if pos_side == 1:
                    new_t = price - atr_v * trail_mult
                    if new_t > pos_trail:
                        pos_trail = new_t
                else:
                    new_t = price + atr_v * trail_mult
                    if new_t < pos_trail:
                        pos_trail = new_t

            # Check exits
            if in_pos:
                reason = None
                if pos_side == 1:
                    if price <= pos_sl:
                        reason = "stop_loss"
                    elif not np.isnan(pos_trail) and price <= pos_trail:
                        reason = "trailing_stop"
                    elif price >= pos_tp:
                        reason = "take_profit"
                else:
                    if price >= pos_sl:
                        reason = "stop_loss"
                    elif not np.isnan(pos_trail) and price >= pos_trail:
                        reason = "trailing_stop"
                    elif price <= pos_tp:
                        reason = "take_profit"

                if reason:
                    slip = (1 - slippage) if pos_side == 1 else (1 + slippage)
                    exit_p = price * slip
                    if pos_side == 1:
                        pnl = exit_p * pos_qty * (1 - commission) - pos_entry * pos_qty * (1 + commission)
                        cash += exit_p * pos_qty * (1 - commission)
                    else:
                        pnl = pos_entry * pos_qty * (1 - commission) - exit_p * pos_qty * (1 + commission)
                        # Return margin + P&L: margin returned + short profit - cover cost
                        cash += pos_entry * pos_qty * (1 - commission) - exit_p * pos_qty * (1 + commission) + pos_entry * pos_qty
                    pnl_pct = pnl / (pos_entry * pos_qty) * 100
                    trades.append(BTrade(
                        symbol=symbol, side="long" if pos_side == 1 else "short",
                        entry_idx=pos_idx, exit_idx=i,
                        entry_price=pos_entry, exit_price=exit_p,
                        quantity=pos_qty, pnl=round(pnl, 4),
                        pnl_pct=round(pnl_pct, 3), exit_reason=reason,
                        entry_score=pos_score, candles_held=i - pos_idx,
                    ))
                    in_pos = False

            # Check entry
            if not in_pos and cash > 0:
                buy_s, sell_s = _score_fast(
                    i, rsi, mhist, bbpct, ema9, ema21, ema50, sk, sd_arr, volr,
                    price, rsi_os, rsi_ob
                )

                action = 0
                score = 0.0
                if buy_s >= min_score and buy_s > sell_s:
                    action = 1; score = buy_s
                elif sell_s >= min_score and sell_s > buy_s:
                    action = -1; score = sell_s

                if action != 0:
                    sl_dist = atr_v * sl_mult
                    tp_dist = sl_dist * tp_rr

                    if action == 1:
                        entry_p = price * (1 + slippage)
                        sl = entry_p - sl_dist
                        tp = entry_p + tp_dist
                    else:
                        entry_p = price * (1 - slippage)
                        sl = entry_p + sl_dist
                        tp = entry_p - tp_dist

                    sl_distance = abs(entry_p - sl) or entry_p * 0.02
                    qty = (cash * risk_pct) / sl_distance
                    max_qty = (cash * 0.20) / entry_p
                    if qty > max_qty:
                        qty = max_qty
                    cost = entry_p * qty * (1 + commission)

                    if qty > 1e-10 and cost <= cash:
                        cash -= cost
                        in_pos = True
                        pos_side = action
                        pos_entry = entry_p
                        pos_qty = qty
                        pos_sl = sl
                        pos_tp = tp
                        pos_trail = np.nan
                        pos_idx = i
                        pos_score = score

            equity_curve.append(cash + (price * pos_qty if in_pos else 0.0))

        # Close at end of data
        if in_pos:
            final_p = close[-1]
            slip = (1 - slippage) if pos_side == 1 else (1 + slippage)
            exit_p = final_p * slip
            if pos_side == 1:
                pnl = exit_p * pos_qty * (1 - commission) - pos_entry * pos_qty * (1 + commission)
                cash += exit_p * pos_qty * (1 - commission)
            else:
                pnl = pos_entry * pos_qty * (1 - commission) - exit_p * pos_qty * (1 + commission)
                cash += pos_entry * pos_qty * (1 - commission) - exit_p * pos_qty * (1 + commission) + pos_entry * pos_qty
            pnl_pct = pnl / (pos_entry * pos_qty) * 100
            trades.append(BTrade(
                symbol=symbol, side="long" if pos_side == 1 else "short",
                entry_idx=pos_idx, exit_idx=n - 1,
                entry_price=pos_entry, exit_price=exit_p,
                quantity=pos_qty, pnl=round(pnl, 4),
                pnl_pct=round(pnl_pct, 3), exit_reason="end_of_data",
                entry_score=pos_score, candles_held=n - 1 - pos_idx,
            ))

        m = _metrics(equity_curve, trades, initial)
        cs = composite_score(m, len(trades))

        return BacktestResult(
            symbol=symbol,
            total_trades=len(trades),
            win_rate=m["win_rate"],
            total_return_pct=m["total_return_pct"],
            max_drawdown_pct=m["max_drawdown_pct"],
            sharpe_ratio=m["sharpe_ratio"],
            sortino_ratio=m["sortino_ratio"],
            profit_factor=m["profit_factor"],
            avg_win_pct=m["avg_win_pct"],
            avg_loss_pct=m["avg_loss_pct"],
            avg_trade_pct=m["avg_trade_pct"],
            avg_candles_held=m["avg_candles_held"],
            equity_curve=equity_curve,
            trades=trades,
            params={},
            composite_score=cs,
        )

    def _empty(self, symbol: str, cfg) -> BacktestResult:
        return BacktestResult(
            symbol=symbol, total_trades=0, win_rate=0.0, total_return_pct=0.0,
            max_drawdown_pct=0.0, sharpe_ratio=0.0, sortino_ratio=0.0,
            profit_factor=0.0, avg_win_pct=0.0, avg_loss_pct=0.0,
            avg_trade_pct=0.0, avg_candles_held=0.0,
            equity_curve=[], trades=[], params={}, composite_score=-999.0,
        )


def _score_fast(
    i: int,
    rsi: np.ndarray, mhist: np.ndarray, bbpct: np.ndarray,
    ema9: np.ndarray, ema21: np.ndarray, ema50: np.ndarray,
    sk: np.ndarray, sd: np.ndarray, volr: np.ndarray,
    price: float, rsi_os: float, rsi_ob: float,
) -> Tuple[float, float]:
    """Scoring with direct numpy array access — no dict/Series overhead."""
    buy = 0.0
    sell = 0.0

    # RSI
    rv = rsi[i]
    if not np.isnan(rv):
        if rv < rsi_os:      buy  += 20
        elif rv < 40:        buy  += 9
        if rv > rsi_ob:      sell += 20
        elif rv > 60:        sell += 9

    # MACD histogram crossover
    h = mhist[i]; ph = mhist[i - 1] if i > 0 else np.nan
    if not (np.isnan(h) or np.isnan(ph)):
        if h > 0 and ph <= 0:          buy  += 25
        elif h > 0 and h > ph:         buy  += 11
        if h < 0 and ph >= 0:          sell += 25
        elif h < 0 and h < ph:         sell += 11

    # Bollinger %B
    bp = bbpct[i]
    if not np.isnan(bp):
        if bp < 0.10:   buy  += 16
        elif bp < 0.25: buy  += 7
        if bp > 0.90:   sell += 16
        elif bp > 0.75: sell += 7

    # EMA alignment
    e9 = ema9[i]; e21 = ema21[i]; e50 = ema50[i]
    if not (np.isnan(e9) or np.isnan(e21) or np.isnan(e50)):
        if e9 > e21 > e50 and price > e50:  buy  += 13
        elif e9 < e21 < e50 and price < e50: sell += 13

    # Stochastic
    skv = sk[i]; sdv = sd[i]
    if not (np.isnan(skv) or np.isnan(sdv)):
        if skv < 20 and skv > sdv: buy  += 9
        if skv > 80 and skv < sdv: sell += 9

    # Volume
    vr = volr[i]
    if not np.isnan(vr) and vr > 1.5:
        if buy >= sell: buy  += 6
        else:           sell += 6

    if buy  > 100.0: buy  = 100.0
    if sell > 100.0: sell = 100.0

    return buy, sell
