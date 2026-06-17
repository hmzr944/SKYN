"""
Grid-search optimizer with walk-forward validation.
Tests all combinations of key parameters and scores them
using a composite metric (Sharpe + profit factor + win rate - drawdown penalty).
Walk-forward validation splits data into N windows to detect overfitting.
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
import yfinance as yf

from .engine import Backtester, BacktestResult

logger = logging.getLogger(__name__)

# Parameter search space — 5×4×4×3×3×3 = 2160 combinations
# min_score_buy lowered: 55-70 generated < 8 trades on 2y data (signals too rare at those thresholds)
PARAM_SPACE = {
    "min_score_buy":       [35, 40, 45, 48, 50],
    "stop_loss_atr_mult":  [1.5, 2.0, 2.5, 3.0],
    "take_profit_rr":      [1.5, 2.0, 2.5, 3.0],
    "rsi_oversold":        [25, 30, 35],
    "rsi_overbought":      [65, 70, 75],
    "bb_std":              [1.8, 2.0, 2.2],
}

TOTAL_COMBOS = 1
for v in PARAM_SPACE.values():
    TOTAL_COMBOS *= len(v)


@dataclass
class WFWindow:
    period: int
    total_return_pct: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    profitable: bool


@dataclass
class OptResult:
    best_params: dict
    best_score: float
    best_metrics: BacktestResult
    top_results: List[Tuple[dict, BacktestResult]]
    total_combinations: int
    symbols_tested: List[str]
    wf_windows: List[WFWindow]
    wf_consistency: float  # % of windows that are profitable


def _apply_params(base_cfg, params: dict):
    cfg = copy.deepcopy(base_cfg)
    s = cfg.strategy
    r = cfg.risk
    if "min_score_buy" in params:
        s.min_score_buy = float(params["min_score_buy"])
        s.min_score_sell = float(params["min_score_buy"])
    if "stop_loss_atr_mult" in params:
        r.stop_loss_atr_mult = float(params["stop_loss_atr_mult"])
    if "take_profit_rr" in params:
        r.take_profit_rr = float(params["take_profit_rr"])
    if "rsi_oversold" in params:
        s.rsi_oversold = float(params["rsi_oversold"])
    if "rsi_overbought" in params:
        s.rsi_overbought = float(params["rsi_overbought"])
    if "bb_std" in params:
        s.bb_std = float(params["bb_std"])
    return cfg


def fetch_data(symbol: str, period: str = "2y", interval: str = "1h") -> pd.DataFrame:
    """Download OHLCV from Yahoo Finance (supports BTC-USD, ETH-USD, SPY, etc.)"""
    yf_sym = symbol.replace("/USDT", "-USD").replace("/USD", "-USD")
    try:
        df = yf.Ticker(yf_sym).history(period=period, interval=interval)
        if df.empty:
            return pd.DataFrame()
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        df.index.name = "timestamp"
        return df
    except Exception as exc:
        logger.error("fetch_data %s: %s", yf_sym, exc)
        return pd.DataFrame()


class Optimizer:
    def __init__(self, base_cfg, commission: float = 0.001, slippage: float = 0.0005):
        self.base_cfg = base_cfg
        self.bt = Backtester(commission, slippage)

    def all_combos(self) -> List[dict]:
        keys = list(PARAM_SPACE.keys())
        return [dict(zip(keys, c)) for c in itertools.product(*PARAM_SPACE.values())]

    def run(
        self,
        symbols: List[str],
        data_map: Dict[str, pd.DataFrame],
        progress_fn: Optional[Callable] = None,
    ) -> OptResult:
        combos = self.all_combos()
        scored: List[Tuple[dict, float, BacktestResult]] = []

        for i, params in enumerate(combos):
            cfg = _apply_params(self.base_cfg, params)
            per_sym_scores = []
            per_sym_results = []

            for sym in symbols:
                df = data_map.get(sym)
                if df is None or df.empty:
                    continue
                res = self.bt.run(df, cfg, symbol=sym)
                per_sym_scores.append(res.composite_score)
                per_sym_results.append(res)

            # Ignore -999 symbols (too few trades / high DD) — don't let ETF data scarcity kill crypto scores
            valid_scores = [s for s in per_sym_scores if s > -900]
            avg_score = float(np.mean(valid_scores)) if valid_scores else -999.0
            # Representative result = first symbol (or best-scoring)
            best_sym = max(per_sym_results, key=lambda r: r.composite_score) if per_sym_results else None
            if best_sym:
                best_sym.composite_score = avg_score
                best_sym.params = dict(params)

            scored.append((params, avg_score, best_sym))

            if progress_fn:
                progress_fn(i + 1, len(combos), params, avg_score)

        scored.sort(key=lambda x: x[1], reverse=True)

        best_params, best_score, best_result = scored[0]
        top_results = [(p, r) for p, _, r in scored[:50] if r is not None]

        # Walk-forward validation on best params (4 windows)
        wf_windows, wf_consistency = self._walk_forward(
            symbols[0], data_map.get(symbols[0], pd.DataFrame()), best_params, n=4
        )

        return OptResult(
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
    ) -> Tuple[List[WFWindow], float]:
        if df is None or len(df) < n * 60:
            return [], 0.0
        split = len(df) // n
        windows: List[WFWindow] = []
        for i in range(n):
            window_df = df.iloc[i * split: (i + 1) * split]
            cfg = _apply_params(self.base_cfg, params)
            res = self.bt.run(window_df, cfg, symbol=symbol)
            windows.append(WFWindow(
                period=i + 1,
                total_return_pct=res.total_return_pct,
                sharpe_ratio=res.sharpe_ratio,
                win_rate=res.win_rate,
                total_trades=res.total_trades,
                profitable=res.total_return_pct > 0,
            ))
        consistency = sum(w.profitable for w in windows) / n * 100
        return windows, consistency
