import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List
import pandas as pd

from .data_feeds.crypto_feed import CryptoFeed
from .data_feeds.etf_feed import ETFFeed
from .strategy.multi_factor import MultiFactorStrategy
from .execution.portfolio import Portfolio
from .execution.order_manager import OrderManager
from .analysis.signals import Signal

logger = logging.getLogger(__name__)


class ProfitEngine:
    def __init__(self, cfg, broadcast_fn=None):
        self.cfg = cfg
        self._broadcast = broadcast_fn
        self.portfolio = Portfolio(cfg.initial_capital)
        self.strategy = MultiFactorStrategy(cfg)
        self.orders = OrderManager(cfg, self.portfolio)
        self.crypto = CryptoFeed(cfg)
        self.etf = ETFFeed(cfg)
        self.signals: List[Signal] = []
        self.running = False
        self._candles: Dict[str, pd.DataFrame] = {}

    async def _emit(self, event_type: str, data: Any):
        payload = {"type": event_type, "data": data, "ts": datetime.utcnow().isoformat()}
        if self._broadcast is None:
            return
        if asyncio.iscoroutinefunction(self._broadcast):
            await self._broadcast(payload)
        else:
            self._broadcast(payload)

    async def _process(self, symbol: str, asset_type: str):
        try:
            if asset_type == "crypto":
                df = await self.crypto.fetch_ohlcv(symbol)
            else:
                loop = asyncio.get_event_loop()
                df = await loop.run_in_executor(None, self.etf.fetch_ohlcv, symbol)

            if df is None or len(df) < 50:
                logger.warning("Insufficient data for %s", symbol)
                return

            self._candles[symbol] = df
            signal = self.strategy.analyze(df, symbol)
            self.signals = [s for s in self.signals if s.symbol != symbol]
            self.signals.insert(0, signal)
            self.signals = self.signals[:50]

            price = signal.price
            atr_val = float(df["atr"].iloc[-1]) if "atr" in df.columns and not pd.isna(df["atr"].iloc[-1]) else price * 0.02

            # Update trailing stop for open positions
            if symbol in self.portfolio.positions:
                self.portfolio.update_trailing_stop(symbol, price, atr_val, self.cfg.risk.trailing_stop_atr_mult)

            # Check exits first
            exit_reason = self.strategy.should_close(symbol, price, self.portfolio)
            if exit_reason:
                trade = await self.orders.close_position(symbol, price, exit_reason)
                if trade:
                    await self._emit("trade_closed", {**trade.__dict__, "portfolio": self.portfolio.to_dict()})
                return

            # Check new entry
            if self.strategy.should_open(signal, self.portfolio):
                sl, tp = self.strategy.risk.calculate_stops(price, atr_val,
                                                             "long" if signal.action == "BUY" else "short")
                pos_size = self.strategy.risk.calculate_position(self.portfolio.equity, price, sl)
                if pos_size.quantity > 0:
                    ok = await self.orders.open_long(symbol, price, sl, tp, pos_size, asset_type)
                    if ok:
                        await self._emit("position_opened", {
                            "symbol": symbol, "price": price,
                            "sl": sl, "tp": tp, "quantity": pos_size.quantity,
                            "portfolio": self.portfolio.to_dict(),
                        })

            await self._emit("signal", {**signal.__dict__, "portfolio": self.portfolio.to_dict()})

        except Exception as exc:
            logger.error("Error processing %s: %s", symbol, exc, exc_info=True)

    async def run_once(self):
        tasks = (
            [self._process(s, "crypto") for s in self.cfg.crypto_symbols] +
            [self._process(s, "etf") for s in self.cfg.etf_symbols]
        )
        await asyncio.gather(*tasks)

    async def run_loop(self, interval: int = 60):
        self.running = True
        logger.info("ProfitEngine started — paper=%s", self.cfg.exchange.paper_trading)
        while self.running:
            try:
                await self.run_once()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Loop error: %s", exc, exc_info=True)
                await asyncio.sleep(10)

    def stop(self):
        self.running = False

    async def close(self):
        self.stop()
        await self.crypto.close()
        await self.orders.close()

    def get_state(self) -> dict:
        return {
            "running": self.running,
            "portfolio": self.portfolio.to_dict(),
            "signals": [s.__dict__ for s in self.signals[:20]],
            "positions": {
                k: {
                    "symbol": v.symbol, "side": v.side,
                    "entry_price": v.entry_price, "quantity": v.quantity,
                    "sl": v.stop_loss, "tp": v.take_profit,
                    "asset_type": v.asset_type, "entry_time": v.entry_time,
                } for k, v in self.portfolio.positions.items()
            },
            "closed_trades": [t.__dict__ for t in self.portfolio.closed_trades[-20:]],
        }
