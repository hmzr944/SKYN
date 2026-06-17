"""
Leveraged backtesting engine for Binance Futures simulation.

Key differences from the base Backtester:
- Dynamic leverage via LeverageManager (score → leverage)
- Position sizing: risk 2% of equity, leverage amplifies notional
- Liquidation check: price crosses liq_price → full margin lost
- Commission: 0.04% (Binance futures taker fee)
- Slippage:   0.05%
- Daily loss tracking: >=10% daily loss → no new entries until next calendar day
- Short positions: profit when price falls
- Tracks avg_leverage, liquidations, daily_loss_stops
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from engine.analysis.indicators import compute_all
from engine.execution.leverage_manager import LeverageManager
# Re-use the fast scoring function and metrics helper from the base engine
from backtester.engine import _score_fast, _metrics, _get_col, composite_score


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LBTrade:
    symbol: str
    side: str                # "long" | "short"
    entry_idx: int
    exit_idx: int
    entry_price: float
    exit_price: float
    quantity: float
    margin_used: float
    leverage_used: int
    pnl: float
    pnl_pct: float           # % of margin
    exit_reason: str         # "stop_loss" | "take_profit" | "trailing_stop"
                             # | "liquidation" | "end_of_data"
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
    trades: List[LBTrade]
    params: dict
    composite_score: float = 0.0
    # Leverage-specific fields
    avg_leverage: float = 0.0
    liquidations: int = 0
    daily_loss_stops: int = 0
    leveraged_return_pct: float = 0.0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class LeveragedBacktester:
    """
    Futures backtester with dynamic leverage, liquidation simulation, and
    daily loss circuit-breaker.
    """

    def __init__(
        self,
        commission: float = 0.0004,   # Binance futures taker: 0.04%
        slippage: float = 0.0005,     # 0.05%
        leverage_manager: Optional[LeverageManager] = None,
    ) -> None:
        self.commission = commission
        self.slippage = slippage
        self.lm = leverage_manager or LeverageManager()

    # ------------------------------------------------------------------

    def run(self, df: pd.DataFrame, cfg, symbol: str = "SYM") -> BacktestResult:
        if df is None or len(df) < 60:
            return self._empty(symbol, cfg)

        df_ind = compute_all(df, cfg.strategy)
        s = cfg.strategy
        r = cfg.risk
        initial = float(cfg.initial_capital)
        n = len(df_ind)

        # Pre-extract numpy arrays — eliminates slow per-row pandas access
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

        # Date index for daily tracking
        dates = df_ind.index

        # Strategy / risk params (local vars = faster lookups)
        min_score   = float(s.min_score_buy)
        rsi_os      = float(s.rsi_oversold)
        rsi_ob      = float(s.rsi_overbought)
        sl_mult     = float(r.stop_loss_atr_mult)
        tp_rr       = float(r.take_profit_rr)
        trail_mult  = float(r.trailing_stop_atr_mult)
        risk_pct    = float(r.risk_per_trade_pct)
        commission  = self.commission
        slippage    = self.slippage

        daily_loss_limit = getattr(
            getattr(cfg, "leverage", None), "daily_loss_limit_pct", 0.10
        )

        # Account state
        cash = initial
        equity_curve: List[float] = [cash]
        trades: List[LBTrade] = []
        liquidations = 0
        daily_loss_stops = 0
        leverage_log: List[int] = []

        # Position state
        in_pos        = False
        pos_side      = 0        # 1=long, -1=short
        pos_entry     = 0.0
        pos_qty       = 0.0
        pos_margin    = 0.0      # margin locked for this position
        pos_lev       = 1
        pos_liq       = 0.0      # liquidation price
        pos_sl        = 0.0
        pos_tp        = 0.0
        pos_trail     = np.nan
        pos_idx       = 0
        pos_score     = 0.0

        # Daily loss tracking
        day_start_equity  = initial
        current_day       = _date_key(dates[0]) if n > 0 else None
        trading_halted    = False   # True when daily loss limit hit

        warmup = max(getattr(s, "ema_trend", 200), getattr(s, "bb_period", 20), 50)

        for i in range(warmup, n):
            price   = close[i]
            atr_v   = atr[i] if not np.isnan(atr[i]) else price * 0.02

            # ---- Day rollover ----------------------------------------
            day_key = _date_key(dates[i])
            if day_key != current_day:
                current_equity = cash + (_position_value(pos_side, pos_entry, pos_qty, price) if in_pos else 0.0)
                day_start_equity = current_equity
                current_day = day_key
                trading_halted = False   # reset circuit-breaker each day

            # ---- Check daily loss limit ------------------------------
            if not trading_halted and in_pos is False:
                current_equity = cash
                daily_loss = (day_start_equity - current_equity) / day_start_equity
                if daily_loss >= daily_loss_limit:
                    trading_halted = True
                    daily_loss_stops += 1

            # ---- Update trailing stop --------------------------------
            if in_pos and not np.isnan(pos_trail):
                if pos_side == 1:
                    new_t = price - atr_v * trail_mult
                    if new_t > pos_trail:
                        pos_trail = new_t
                else:
                    new_t = price + atr_v * trail_mult
                    if new_t < pos_trail:
                        pos_trail = new_t

            # ---- Check exits ----------------------------------------
            if in_pos:
                reason = None

                # Liquidation check (takes priority)
                if pos_side == 1 and price <= pos_liq:
                    reason = "liquidation"
                elif pos_side == -1 and price >= pos_liq:
                    reason = "liquidation"
                elif pos_side == 1:
                    if price <= pos_sl:
                        reason = "stop_loss"
                    elif not np.isnan(pos_trail) and price <= pos_trail:
                        reason = "trailing_stop"
                    elif price >= pos_tp:
                        reason = "take_profit"
                else:  # short
                    if price >= pos_sl:
                        reason = "stop_loss"
                    elif not np.isnan(pos_trail) and price >= pos_trail:
                        reason = "trailing_stop"
                    elif price <= pos_tp:
                        reason = "take_profit"

                if reason:
                    if reason == "liquidation":
                        # Full margin lost
                        pnl = -pos_margin
                        cash -= 0.0   # margin was already deducted at entry
                        # (cash was reduced by margin at entry; on liquidation
                        #  we don't add anything back)
                        exit_p = pos_liq
                        liquidations += 1
                    else:
                        slip = (1 - slippage) if pos_side == 1 else (1 + slippage)
                        exit_p = price * slip
                        pnl, cash = _close_position(
                            pos_side, pos_entry, exit_p, pos_qty, pos_margin,
                            commission, cash
                        )

                    pnl_pct = pnl / pos_margin * 100 if pos_margin > 0 else 0.0
                    trades.append(LBTrade(
                        symbol=symbol,
                        side="long" if pos_side == 1 else "short",
                        entry_idx=pos_idx,
                        exit_idx=i,
                        entry_price=pos_entry,
                        exit_price=exit_p,
                        quantity=pos_qty,
                        margin_used=round(pos_margin, 4),
                        leverage_used=pos_lev,
                        pnl=round(pnl, 4),
                        pnl_pct=round(pnl_pct, 3),
                        exit_reason=reason,
                        entry_score=pos_score,
                        candles_held=i - pos_idx,
                    ))
                    in_pos = False

            # ---- Check entry ----------------------------------------
            if not in_pos and cash > 0 and not trading_halted:
                buy_s, sell_s = _score_fast(
                    i, rsi, mhist, bbpct, ema9, ema21, ema50, sk, sd_arr, volr,
                    price, rsi_os, rsi_ob
                )

                action = 0
                score  = 0.0
                if buy_s >= min_score and buy_s > sell_s:
                    action = 1;  score = buy_s
                elif sell_s >= min_score and sell_s > buy_s:
                    action = -1; score = sell_s

                if action != 0:
                    lev = self.lm.get_leverage(score, "HIGH")
                    sl_dist = atr_v * sl_mult
                    tp_dist = sl_dist * tp_rr

                    if action == 1:
                        entry_p  = price * (1.0 + slippage)
                        sl       = entry_p - sl_dist
                        tp       = entry_p + tp_dist
                        liq_p    = self.lm.liquidation_price(entry_p, lev, "long")
                        # Guard: sl must be above liq price
                        sl = max(sl, liq_p * 1.001)
                    else:
                        entry_p  = price * (1.0 - slippage)
                        sl       = entry_p + sl_dist
                        tp       = entry_p - tp_dist
                        liq_p    = self.lm.liquidation_price(entry_p, lev, "short")
                        # Guard: sl must be below liq price
                        sl = min(sl, liq_p * 0.999)

                    # Position sizing: risk_pct of equity on the stop distance
                    sl_distance = abs(entry_p - sl) or entry_p * 0.02
                    risk_amount = cash * risk_pct
                    # qty so that sl_distance * qty = risk_amount (unlevered units)
                    # With leverage L: margin = qty * entry_p / L
                    # We want risk ≤ risk_amount regardless of leverage
                    qty    = (risk_amount / sl_distance)
                    margin = qty * entry_p / lev

                    # Hard cap: margin ≤ 95% of cash
                    if margin > cash * 0.95:
                        margin = cash * 0.95
                        qty    = margin * lev / entry_p

                    cost = margin * (1.0 + commission)  # entry commission on notional expressed as % of margin * lev / margin → commission on notional
                    # More precisely: entry commission = qty * entry_p * commission
                    entry_commission = qty * entry_p * commission
                    total_cost = margin + entry_commission

                    if qty > 1e-10 and total_cost <= cash:
                        cash     -= total_cost
                        in_pos    = True
                        pos_side  = action
                        pos_entry = entry_p
                        pos_qty   = qty
                        pos_margin = margin
                        pos_lev   = lev
                        pos_liq   = liq_p
                        pos_sl    = sl
                        pos_tp    = tp
                        pos_trail = np.nan
                        pos_idx   = i
                        pos_score = score
                        leverage_log.append(lev)

            # Mark-to-market equity (unrealised P&L added)
            if in_pos:
                unreal = _unrealised_pnl(pos_side, pos_entry, price, pos_qty, pos_margin, pos_lev)
                equity_curve.append(cash + pos_margin + unreal)
            else:
                equity_curve.append(cash)

        # ---- Close open position at end of data ----------------------
        if in_pos:
            final_p = close[-1]
            slip = (1 - slippage) if pos_side == 1 else (1 + slippage)
            exit_p = final_p * slip
            pnl, cash = _close_position(
                pos_side, pos_entry, exit_p, pos_qty, pos_margin, commission, cash
            )
            pnl_pct = pnl / pos_margin * 100 if pos_margin > 0 else 0.0
            trades.append(LBTrade(
                symbol=symbol,
                side="long" if pos_side == 1 else "short",
                entry_idx=pos_idx,
                exit_idx=n - 1,
                entry_price=pos_entry,
                exit_price=exit_p,
                quantity=pos_qty,
                margin_used=round(pos_margin, 4),
                leverage_used=pos_lev,
                pnl=round(pnl, 4),
                pnl_pct=round(pnl_pct, 3),
                exit_reason="end_of_data",
                entry_score=pos_score,
                candles_held=n - 1 - pos_idx,
            ))

        # ---- Metrics -------------------------------------------------
        # Convert LBTrades to BTrade-like objects for _metrics (uses .pnl / .pnl_pct)
        m = _metrics(equity_curve, _as_btrades(trades), initial)
        cs = composite_score(m, len(trades))

        avg_lev = float(np.mean(leverage_log)) if leverage_log else 0.0
        leveraged_ret = m["total_return_pct"]  # already includes leverage effect

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
            avg_leverage=round(avg_lev, 2),
            liquidations=liquidations,
            daily_loss_stops=daily_loss_stops,
            leveraged_return_pct=round(leveraged_ret, 3),
        )

    # ------------------------------------------------------------------

    def _empty(self, symbol: str, cfg) -> BacktestResult:
        return BacktestResult(
            symbol=symbol, total_trades=0, win_rate=0.0, total_return_pct=0.0,
            max_drawdown_pct=0.0, sharpe_ratio=0.0, sortino_ratio=0.0,
            profit_factor=0.0, avg_win_pct=0.0, avg_loss_pct=0.0,
            avg_trade_pct=0.0, avg_candles_held=0.0,
            equity_curve=[], trades=[], params={}, composite_score=-999.0,
            avg_leverage=0.0, liquidations=0, daily_loss_stops=0,
            leveraged_return_pct=0.0,
        )


# ---------------------------------------------------------------------------
# Helpers (module-level, no class overhead)
# ---------------------------------------------------------------------------

def _date_key(ts) -> str:
    """Return YYYY-MM-DD string for a pandas Timestamp or datetime-like."""
    try:
        return ts.strftime("%Y-%m-%d")
    except AttributeError:
        return str(ts)[:10]


def _position_value(side: int, entry: float, qty: float, price: float) -> float:
    """Rough mark-to-market value change vs. entry, for daily tracking."""
    if side == 1:
        return (price - entry) * qty
    return (entry - price) * qty


def _unrealised_pnl(
    side: int, entry: float, price: float, qty: float,
    margin: float, lev: int
) -> float:
    """Unrealised P&L in quote currency."""
    if side == 1:
        return (price - entry) * qty
    return (entry - price) * qty


def _close_position(
    side: int, entry: float, exit_p: float, qty: float,
    margin: float, commission: float, cash: float
) -> Tuple[float, float]:
    """
    Close a position and return (pnl, new_cash).

    margin is already deducted from cash at entry.
    On close we return margin + P&L back to cash.
    """
    if side == 1:
        raw_pnl = (exit_p - entry) * qty
    else:
        raw_pnl = (entry - exit_p) * qty

    # Commission on both legs: entry commission already paid; exit commission here
    exit_commission = qty * exit_p * commission
    pnl = raw_pnl - exit_commission

    # Return margin + pnl to cash
    new_cash = cash + margin + pnl
    return pnl, new_cash


class _BTradeLike:
    """Minimal duck-type wrapper so _metrics() can consume LBTrade lists."""
    __slots__ = ("pnl", "pnl_pct", "candles_held")

    def __init__(self, t: LBTrade):
        self.pnl = t.pnl
        self.pnl_pct = t.pnl_pct
        self.candles_held = t.candles_held


def _as_btrades(trades: List[LBTrade]) -> list:
    return [_BTradeLike(t) for t in trades]


# Fix the type hint import that's only needed at runtime
from typing import Tuple  # noqa: E402 — already imported transitively but be explicit
