import pandas as pd
from ..analysis.indicators import compute_all
from ..analysis.signals import Signal
from .risk_manager import RiskManager
from .strategy_router import StrategyRouter, RouteResult


class MultiFactorStrategy:
    def __init__(self, cfg):
        self.cfg = cfg
        self.risk = RiskManager(cfg)
        self._router = StrategyRouter()
        self._last_route: dict[str, RouteResult] = {}

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        df = compute_all(df, self.cfg.strategy)
        route = self._router.route(df, symbol, self.cfg)
        self._last_route[symbol] = route
        return route.signal

    def get_route(self, symbol: str) -> RouteResult | None:
        return self._last_route.get(symbol)

    def should_open(self, signal: Signal, portfolio) -> bool:
        return (
            signal.action in ("BUY", "SELL")
            and signal.symbol not in portfolio.positions
            and self.risk.can_open(portfolio)
            and not self._is_skipped(signal.symbol)
        )

    def _is_skipped(self, symbol: str) -> bool:
        route = self._last_route.get(symbol)
        return route is not None and route.skip

    def should_close(self, symbol: str, current_price: float, portfolio):
        return portfolio.check_exits(symbol, current_price)
