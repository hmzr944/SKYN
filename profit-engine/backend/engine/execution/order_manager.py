import logging
from typing import Optional
from ..strategy.risk_manager import PositionSize
from .portfolio import Portfolio, Trade

logger = logging.getLogger(__name__)


class OrderManager:
    def __init__(self, cfg, portfolio: Portfolio):
        self.cfg = cfg
        self.portfolio = portfolio
        self.paper = cfg.exchange.paper_trading
        self._exchange = None
        if not self.paper and cfg.exchange.api_key:
            try:
                import ccxt.async_support as ccxt
                # Use binanceusdm for USDT-margined perpetual futures
                self._exchange = ccxt.binanceusdm({
                    "apiKey": cfg.exchange.api_key,
                    "secret": cfg.exchange.api_secret,
                    "enableRateLimit": True,
                    "options": {"defaultType": "future"},
                })
            except Exception as exc:
                logger.error("Exchange init failed: %s", exc)

    async def open_long(self, symbol: str, price: float, sl: float, tp: float,
                        pos: PositionSize, asset_type: str = "crypto",
                        leverage: int = 1, margin_required: float = 0.0,
                        liq_price: float = 0.0, partial_tp: float = 0.0) -> bool:
        if self.paper:
            ok = self.portfolio.open_position(
                symbol, "long", price, pos.quantity, sl, tp, asset_type,
                leverage=leverage, margin_required=margin_required,
                liquidation_price=liq_price, partial_tp=partial_tp,
            )
            if ok:
                logger.info("[PAPER] LONG %.6f %s @ %.4f | SL=%.4f TP=%.4f PTP=%.4f LEV=%dx",
                            pos.quantity, symbol, price, sl, tp, partial_tp, leverage)
            return ok
        try:
            await self._exchange.set_leverage(leverage, symbol)
            order = await self._exchange.create_market_buy_order(symbol, pos.quantity)
            fill = order.get("average", price)
            return self.portfolio.open_position(
                symbol, "long", fill, pos.quantity, sl, tp, asset_type,
                leverage=leverage, margin_required=margin_required,
                liquidation_price=liq_price, partial_tp=partial_tp,
            )
        except Exception as exc:
            logger.error("[LIVE] buy %s failed: %s", symbol, exc)
            return False

    async def open_short(self, symbol: str, price: float, sl: float, tp: float,
                         pos: PositionSize, asset_type: str = "crypto",
                         leverage: int = 1, margin_required: float = 0.0,
                         liq_price: float = 0.0, partial_tp: float = 0.0) -> bool:
        if self.paper:
            ok = self.portfolio.open_position(
                symbol, "short", price, pos.quantity, sl, tp, asset_type,
                leverage=leverage, margin_required=margin_required,
                liquidation_price=liq_price, partial_tp=partial_tp,
            )
            if ok:
                logger.info("[PAPER] SHORT %.6f %s @ %.4f | SL=%.4f TP=%.4f PTP=%.4f LEV=%dx",
                            pos.quantity, symbol, price, sl, tp, partial_tp, leverage)
            return ok
        try:
            await self._exchange.set_leverage(leverage, symbol)
            order = await self._exchange.create_order(
                symbol, "market", "sell", pos.quantity,
                params={"reduceOnly": False},
            )
            fill = order.get("average", price)
            return self.portfolio.open_position(
                symbol, "short", fill, pos.quantity, sl, tp, asset_type,
                leverage=leverage, margin_required=margin_required,
                liquidation_price=liq_price, partial_tp=partial_tp,
            )
        except Exception as exc:
            logger.error("[LIVE] short %s failed: %s", symbol, exc)
            return False

    async def close_position(self, symbol: str, price: float, reason: str) -> Optional[Trade]:
        pos = self.portfolio.positions.get(symbol)
        if not pos:
            return None
        if not self.paper and self._exchange:
            try:
                if pos.side == "long":
                    await self._exchange.create_market_sell_order(
                        symbol, pos.quantity, params={"reduceOnly": True}
                    )
                else:
                    await self._exchange.create_market_buy_order(
                        symbol, pos.quantity, params={"reduceOnly": True}
                    )
            except Exception as exc:
                logger.error("[LIVE] close %s failed: %s", symbol, exc)
        trade = self.portfolio.close_position(symbol, price, reason)
        if trade:
            tag = "PAPER" if self.paper else "LIVE"
            icon = "✅" if trade.pnl > 0 else "❌"
            logger.info("[%s] %s CLOSE %s @ %.4f | PnL %.2f (%.2f%%) LEV=%dx [%s]",
                        tag, icon, symbol, price, trade.pnl, trade.pnl_pct, trade.leverage, reason)
        return trade

    async def close(self):
        if self._exchange:
            await self._exchange.close()
