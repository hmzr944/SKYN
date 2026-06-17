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
                cls = getattr(ccxt, cfg.exchange.name)
                self._exchange = cls({"apiKey": cfg.exchange.api_key,
                                      "secret": cfg.exchange.api_secret,
                                      "enableRateLimit": True})
            except Exception as exc:
                logger.error("Exchange init failed: %s", exc)

    async def open_long(self, symbol: str, price: float, sl: float, tp: float,
                        pos: PositionSize, asset_type: str = "crypto") -> bool:
        if self.paper:
            ok = self.portfolio.open_position(symbol, "long", price, pos.quantity, sl, tp, asset_type)
            if ok:
                logger.info("[PAPER] BUY %.6f %s @ %.4f | SL=%.4f TP=%.4f",
                            pos.quantity, symbol, price, sl, tp)
            return ok
        try:
            order = await self._exchange.create_market_buy_order(symbol, pos.quantity)
            fill = order.get("average", price)
            return self.portfolio.open_position(symbol, "long", fill, pos.quantity, sl, tp, asset_type)
        except Exception as exc:
            logger.error("[LIVE] buy %s failed: %s", symbol, exc)
            return False

    async def close_position(self, symbol: str, price: float, reason: str) -> Optional[Trade]:
        pos = self.portfolio.positions.get(symbol)
        if not pos:
            return None
        if not self.paper and self._exchange:
            try:
                await self._exchange.create_market_sell_order(symbol, pos.quantity)
            except Exception as exc:
                logger.error("[LIVE] sell %s failed: %s", symbol, exc)
        trade = self.portfolio.close_position(symbol, price, reason)
        if trade:
            tag = "PAPER" if self.paper else "LIVE"
            icon = "✅" if trade.pnl > 0 else "❌"
            logger.info("[%s] %s CLOSE %s @ %.4f | PnL %.2f (%.2f%%) [%s]",
                        tag, icon, symbol, price, trade.pnl, trade.pnl_pct, reason)
        return trade

    async def close(self):
        if self._exchange:
            await self._exchange.close()
