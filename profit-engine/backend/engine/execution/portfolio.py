from dataclasses import dataclass
from datetime import datetime, date
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
    leverage: int = 1
    margin_required: float = 0.0
    liquidation_price: float = 0.0
    last_funding_time: Optional[str] = None
    partial_tp: float = 0.0       # price to take 50% profit
    partial_taken: bool = False    # already took partial TP


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
    leverage: int = 1


class Portfolio:
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.closed_trades: List[Trade] = []
        self._peak = initial_capital
        self._day_start_equity = initial_capital
        self._day_date = date.today()

    @property
    def equity(self) -> float:
        locked = sum(
            (p.margin_required if p.margin_required > 0 else p.entry_price * p.quantity)
            for p in self.positions.values()
        )
        return self.cash + locked

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

    def _refresh_day(self):
        today = date.today()
        if today != self._day_date:
            self._day_start_equity = self.equity
            self._day_date = today

    @property
    def daily_pnl_pct(self) -> float:
        self._refresh_day()
        if self._day_start_equity <= 0:
            return 0.0
        return (self.equity - self._day_start_equity) / self._day_start_equity * 100

    def open_position(self, symbol: str, side: str, price: float,
                      quantity: float, sl: float, tp: float,
                      asset_type: str = "crypto",
                      leverage: int = 1,
                      margin_required: float = 0.0,
                      liquidation_price: float = 0.0,
                      partial_tp: float = 0.0) -> bool:
        if symbol in self.positions:
            return False
        if margin_required <= 0:
            margin_required = price * quantity / max(leverage, 1)
        if margin_required > self.cash:
            return False
        self.cash -= margin_required
        self.positions[symbol] = Position(
            symbol=symbol, side=side, entry_price=price,
            quantity=quantity, stop_loss=sl, take_profit=tp,
            entry_time=datetime.utcnow().isoformat(),
            asset_type=asset_type,
            leverage=leverage,
            margin_required=margin_required,
            liquidation_price=liquidation_price,
            last_funding_time=datetime.utcnow().isoformat(),
            partial_tp=partial_tp,
            partial_taken=False,
        )
        return True

    def close_position(self, symbol: str, price: float, reason: str) -> Optional[Trade]:
        pos = self.positions.pop(symbol, None)
        if not pos:
            return None
        pnl = (price - pos.entry_price) * pos.quantity if pos.side == "long" \
              else (pos.entry_price - price) * pos.quantity
        # Return margin + realized PnL (pnl is negative on loss)
        self.cash += pos.margin_required + pnl
        margin_basis = pos.margin_required if pos.margin_required > 0 else pos.entry_price * pos.quantity
        pnl_pct = pnl / margin_basis * 100
        trade = Trade(
            symbol=symbol, side=pos.side,
            entry_price=pos.entry_price, exit_price=price,
            quantity=pos.quantity, pnl=round(pnl, 4),
            pnl_pct=round(pnl_pct, 2),
            entry_time=pos.entry_time,
            exit_time=datetime.utcnow().isoformat(),
            exit_reason=reason,
            leverage=pos.leverage,
        )
        self.closed_trades.append(trade)
        return trade

    def deduct_funding(self, symbol: str) -> float:
        """Deduct ~0.01%/8h Binance funding rate for open futures positions."""
        pos = self.positions.get(symbol)
        if not pos or pos.leverage <= 1 or pos.asset_type != "crypto":
            return 0.0
        now = datetime.utcnow()
        if pos.last_funding_time:
            last = datetime.fromisoformat(pos.last_funding_time)
            if (now - last).total_seconds() < 28800:  # 8 hours
                return 0.0
        funding = pos.entry_price * pos.quantity * 0.0001
        self.cash -= funding
        pos.last_funding_time = now.isoformat()
        return funding

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

    def partial_close(self, symbol: str, price: float) -> Optional[Trade]:
        """Close 50% of position at partial TP, move stop to breakeven."""
        pos = self.positions.get(symbol)
        if not pos or pos.partial_taken:
            return None
        half_qty = pos.quantity / 2
        pnl = (price - pos.entry_price) * half_qty if pos.side == "long" \
              else (pos.entry_price - price) * half_qty
        # Return half the margin + pnl
        returned_margin = pos.margin_required / 2
        self.cash += returned_margin + pnl
        # Update position: half qty, half margin, move SL to breakeven
        pos.quantity -= half_qty
        pos.margin_required -= returned_margin
        pos.stop_loss = pos.entry_price  # breakeven stop
        pos.partial_taken = True
        margin_basis = returned_margin if returned_margin > 0 else pos.entry_price * half_qty
        pnl_pct = pnl / margin_basis * 100
        trade = Trade(
            symbol=symbol, side=pos.side,
            entry_price=pos.entry_price, exit_price=price,
            quantity=half_qty, pnl=round(pnl, 4),
            pnl_pct=round(pnl_pct, 2),
            entry_time=pos.entry_time,
            exit_time=datetime.utcnow().isoformat(),
            exit_reason="partial_tp",
            leverage=pos.leverage,
        )
        self.closed_trades.append(trade)
        return trade

    def check_exits(self, symbol: str, price: float) -> Optional[str]:
        pos = self.positions.get(symbol)
        if not pos:
            return None
        # Partial TP check — must come before full TP
        if pos.partial_tp > 0 and not pos.partial_taken:
            if (pos.side == "long" and price >= pos.partial_tp) or \
               (pos.side == "short" and price <= pos.partial_tp):
                return "partial_tp"
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
            "daily_pnl_pct": round(self.daily_pnl_pct, 2),
        }
