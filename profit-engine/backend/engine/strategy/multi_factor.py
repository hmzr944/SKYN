import pandas as pd
from ..analysis.indicators import compute_all
from ..analysis.signals import score_signal, Signal
from .risk_manager import RiskManager


class MultiFactorStrategy:
    def __init__(self, cfg):
        self.cfg = cfg
        self.risk = RiskManager(cfg)

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        df = compute_all(df, self.cfg.strategy)
        return score_signal(df, symbol, self.cfg)

    def should_open(self, signal: Signal, portfolio) -> bool:
        return (
            signal.action in ("BUY", "SELL")
            and signal.symbol not in portfolio.positions
            and self.risk.can_open(portfolio)
        )

    def should_close(self, symbol: str, current_price: float, portfolio):
        return portfolio.check_exits(symbol, current_price)
