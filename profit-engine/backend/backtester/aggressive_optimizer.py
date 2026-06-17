"""
Aggressive grid-search optimizer that uses LeveragedBacktester.

Parameter space is tuned for higher-frequency crypto signals with tighter
stops and moderate-to-high leverage.  Scoring boosts configurations that
achieve higher average leverage (i.e. more confident signals).

Only crypto symbols are tested (BTC-USD, ETH-USD, SOL-USD).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import copy
import itertools
import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .leveraged_engine import LeveragedBacktester, BacktestResult
from .engine import composite_score
from .optimizer import fetch_data, _apply_params   # re-use data fetcher and param applicator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parameter search space
# 5 × 4 × 4 × 3 × 3 × 3 = 2 160 combinations
# ---------------------------------------------------------------------------

PARAM_SPACE: Dict[str, list] = {
    "min_score_buy":      [35, 40, 45, 48, 50],
    "stop_loss_atr_mult": [0.5, 0.8, 1.0, 1.5],
    "take_profit_rr":     [1.5, 2.0, 2.5, 3.0],
    "rsi_oversold":       [25, 30, 35],
    "rsi_overbought":     [65, 70, 75],
    "bb_std":             [1.8, 2.0, 2.2],
}

CRYPTO_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD"]

TOTAL_COMBOS = 1
for _v in PARAM_SPACE.values():
    TOTAL_COMBOS *= len(_v)


# ---------------------------------------------------------------------------
# Composite score with leverage bonus
# ---------------------------------------------------------------------------

def composite_score_leveraged(m: dict, n_trades: int, avg_leverage: float) -> float:
    """
    Extends the base composite_score with a leverage bonus.

    composite_score_leveraged = composite_score * (1 + avg_leverage * 0.1)

    This rewards parameter sets that generate high-confidence signals
    (which earn higher leverage), while the base score still penalises
    poor risk-adjusted returns.
    """
    base = composite_score(m, n_trades)
    if base <= -900:
        return base
    bonus = 1.0 + avg_leverage * 0.1
    return round(base * bonus, 5)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AWFWindow:
    period: int
    total_return_pct: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    avg_leverage: float
    profitable: bool


@dataclass
class AggOptResult:
    best_params: dict
    best_score: float
    best_metrics: BacktestResult
    top_results: List[Tuple[dict, BacktestResult]]
    total_combinations: int
    symbols_tested: List[str]
    wf_windows: List[AWFWindow]
    wf_consistency: float


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------

class AggressiveOptimizer:
    """
    Grid-search optimizer using LeveragedBacktester.
    Scores each parameter combination with composite_score_leveraged.
    """

    def __init__(
        self,
        base_cfg,
        commission: float = 0.0004,   # Binance futures taker
        slippage:   float = 0.0005,
    ) -> None:
        self.base_cfg = base_cfg
        self.bt = LeveragedBacktester(commission=commission, slippage=slippage)

    def all_combos(self) -> List[dict]:
        keys = list(PARAM_SPACE.keys())
        return [dict(zip(keys, c)) for c in itertools.product(*PARAM_SPACE.values())]

    def run(
        self,
        symbols: List[str],
        data_map: Dict[str, pd.DataFrame],
        progress_fn: Optional[Callable] = None,
    ) -> AggOptResult:
        combos = self.all_combos()
        scored: List[Tuple[dict, float, Optional[BacktestResult]]] = []

        for i, params in enumerate(combos):
            cfg = _apply_params(self.base_cfg, params)
            per_sym_scores: List[float] = []
            per_sym_results: List[BacktestResult] = []

            for sym in symbols:
                df = data_map.get(sym)
                if df is None or df.empty:
                    continue
                res = self.bt.run(df, cfg, symbol=sym)
                m = {
                    "total_return_pct": res.total_return_pct,
                    "max_drawdown_pct": res.max_drawdown_pct,
                    "sharpe_ratio":     res.sharpe_ratio,
                    "sortino_ratio":    res.sortino_ratio,
                    "win_rate":         res.win_rate,
                    "profit_factor":    res.profit_factor,
                }
                sym_score = composite_score_leveraged(m, res.total_trades, res.avg_leverage)
                per_sym_scores.append(sym_score)
                per_sym_results.append(res)

            valid_scores = [s for s in per_sym_scores if s > -900]
            avg_score = float(np.mean(valid_scores)) if valid_scores else -999.0

            best_res = (
                max(per_sym_results, key=lambda r: r.composite_score)
                if per_sym_results else None
            )
            if best_res is not None:
                best_res.composite_score = avg_score
                best_res.params = dict(params)

            scored.append((params, avg_score, best_res))

            if progress_fn:
                progress_fn(i + 1, len(combos), params, avg_score)

        scored.sort(key=lambda x: x[1], reverse=True)

        best_params, best_score, best_result = scored[0]
        top_results = [(p, r) for p, _, r in scored[:50] if r is not None]

        # Walk-forward on first available symbol
        wf_symbol = symbols[0] if symbols else "BTC-USD"
        wf_windows, wf_consistency = self._walk_forward(
            wf_symbol, data_map.get(wf_symbol, pd.DataFrame()), best_params, n=4
        )

        return AggOptResult(
            best_params=best_params,
            best_score=best_score,
            best_metrics=best_result,
            top_results=top_results,
            total_combinations=len(combos),
            symbols_tested=symbols,
            wf_windows=wf_windows,
            wf_consistency=wf_consistency,
        )

    def _walk_forward(
        self, symbol: str, df: pd.DataFrame, params: dict, n: int = 4
    ) -> Tuple[List[AWFWindow], float]:
        if df is None or len(df) < n * 60:
            return [], 0.0
        split = len(df) // n
        windows: List[AWFWindow] = []
        for i in range(n):
            window_df = df.iloc[i * split: (i + 1) * split]
            cfg = _apply_params(self.base_cfg, params)
            res = self.bt.run(window_df, cfg, symbol=symbol)
            windows.append(AWFWindow(
                period=i + 1,
                total_return_pct=res.total_return_pct,
                sharpe_ratio=res.sharpe_ratio,
                win_rate=res.win_rate,
                total_trades=res.total_trades,
                avg_leverage=res.avg_leverage,
                profitable=res.total_return_pct > 0,
            ))
        consistency = sum(w.profitable for w in windows) / n * 100
        return windows, consistency
