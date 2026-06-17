from dataclasses import dataclass


@dataclass
class PositionSize:
    quantity: float
    risk_amount: float
    position_value: float


class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg

    def calculate_stops(self, price: float, atr_val: float, side: str = "long"):
        sl_dist = atr_val * self.cfg.risk.stop_loss_atr_mult
        tp_dist = sl_dist * self.cfg.risk.take_profit_rr
        if side == "long":
            return price - sl_dist, price + tp_dist
        return price + sl_dist, price - tp_dist

    def calculate_position(self, equity: float, price: float, stop_loss: float) -> PositionSize:
        sl_dist = abs(price - stop_loss) or price * 0.02
        risk_amount = equity * self.cfg.risk.risk_per_trade_pct
        quantity = risk_amount / sl_dist
        max_qty = (equity * 0.20) / price
        quantity = min(quantity, max_qty)
        return PositionSize(
            quantity=quantity,
            risk_amount=risk_amount,
            position_value=quantity * price,
        )

    def can_open(self, portfolio) -> bool:
        if len(portfolio.positions) >= self.cfg.risk.max_open_positions:
            return False
        dd = (portfolio.initial_capital - portfolio.equity) / portfolio.initial_capital
        return dd < self.cfg.risk.max_drawdown_pct
