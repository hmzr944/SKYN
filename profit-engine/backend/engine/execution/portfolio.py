from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class Position:
    symbol: str
    side: str
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    entry_time: str
    trailing_stop: Optional[float] = None
    asset_type: str = "crypto"


@dataclass
class Trade:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    entry_time: str
    exit_time: str
    exit_reason: str


class Portfolio:
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.closed_trades: List[Trade] = []
        self._peak = initial_capital

    @property
    def equity(self) -> float:
        positions_value = sum(p.entry_price * p.quantity for p in self.positions.values())
        return self.cash + positions_value

    @property
    def total_pnl(self) -> float:
        return self.equity - self.initial_capital

    @property
    def total_pnl_pct(self) -> float:
        return self.total_pnl / self.initial_capital * 100

    @property
    def win_rate(self) -> float:
        if not self.closed_trades:
            return 0.0
        return sum(1 for t in self.closed_trades if t.pnl > 0) / len(self.closed_trades) * 100

    @property
    def drawdown(self) -> float:
        eq = self.equity
        self._peak = max(self._peak, eq)
        return (self._peak - eq) / self._peak

    def open_position(self, symbol: str, side: str, price: float,
                      quantity: float, sl: float, tp: float,
                      asset_type: str = "crypto") -> bool:
        if symbol in self.positions:
            return False
        cost = price * quantity
        if cost > self.cash:
            return False
        self.cash -= cost
        self.positions[symbol] = Position(
            symbol=symbol, side=side, entry_price=price,
            quantity=quantity, stop_loss=sl, take_profit=tp,
            entry_time=datetime.utcnow().isoformat(),
            asset_type=asset_type,
        )
        return True

    def close_position(self, symbol: str, price: float, reason: str) -> Optional[Trade]:
        pos = self.positions.pop(symbol, None)
        if not pos:
            return None
        self.cash += price * pos.quantity
        pnl = (price - pos.entry_price) * pos.quantity if pos.side == "long" \
              else (pos.entry_price - price) * pos.quantity
        pnl_pct = pnl / (pos.entry_price * pos.quantity) * 100
        trade = Trade(
            symbol=symbol, side=pos.side,
            entry_price=pos.entry_price, exit_price=price,
            quantity=pos.quantity, pnl=round(pnl, 4),
            pnl_pct=round(pnl_pct, 2),
            entry_time=pos.entry_time,
            exit_time=datetime.utcnow().isoformat(),
            exit_reason=reason,
        )
        self.closed_trades.append(trade)
        return trade

    def update_trailing_stop(self, symbol: str, price: float, atr_val: float, mult: float):
        pos = self.positions.get(symbol)
        if not pos:
            return
        if pos.side == "long":
            level = price - atr_val * mult
            if pos.trailing_stop is None or level > pos.trailing_stop:
                pos.trailing_stop = level
        else:
            level = price + atr_val * mult
            if pos.trailing_stop is None or level < pos.trailing_stop:
                pos.trailing_stop = level

    def check_exits(self, symbol: str, price: float) -> Optional[str]:
        pos = self.positions.get(symbol)
        if not pos:
            return None
        if pos.side == "long":
            if price <= pos.stop_loss:
                return "stop_loss"
            if pos.trailing_stop and price <= pos.trailing_stop:
                return "trailing_stop"
            if price >= pos.take_profit:
                return "take_profit"
        else:
            if price >= pos.stop_loss:
                return "stop_loss"
            if pos.trailing_stop and price >= pos.trailing_stop:
                return "trailing_stop"
            if price <= pos.take_profit:
                return "take_profit"
        return None

    def to_dict(self) -> dict:
        return {
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "initial_capital": self.initial_capital,
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(self.total_pnl_pct, 2),
            "drawdown_pct": round(self.drawdown * 100, 2),
            "win_rate": round(self.win_rate, 2),
            "open_positions": len(self.positions),
            "closed_trades": len(self.closed_trades),
        }
