import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from .data_feeds.crypto_feed import CryptoFeed
from .data_feeds.etf_feed import ETFFeed
from .data_feeds.derivatives_feed import DerivativesFeed
from .strategy.multi_factor import MultiFactorStrategy
from .strategy.signal_filter import SignalFilter
from .execution.portfolio import Portfolio
from .execution.order_manager import OrderManager
from .execution.leverage_manager import LeverageManager
from .strategy.risk_manager import PositionSize
from .analysis.signals import Signal

logger = logging.getLogger(__name__)

DAILY_LOSS_LIMIT = -10.0  # percent — hard stop for the day
_4H_REFRESH_SECONDS = 4 * 3600  # re-fetch 4h candles no more often than every 4 hours


class ProfitEngine:
    def __init__(self, cfg, broadcast_fn=None):
        self.cfg = cfg
        self._broadcast = broadcast_fn
        self.portfolio = Portfolio(cfg.initial_capital)
        self.strategy = MultiFactorStrategy(cfg)
        self.orders = OrderManager(cfg, self.portfolio)
        self.lev_mgr = LeverageManager()
        self.crypto = CryptoFeed(cfg)
        self.etf = ETFFeed(cfg)
        self.derivatives = DerivativesFeed()
        self.signal_filter = SignalFilter()
        self.signals: List[Signal] = []
        self.running = False
        self._candles: Dict[str, pd.DataFrame] = {}
        # 4h candle cache: symbol → (DataFrame, last_fetch_timestamp)
        self._df4h: Dict[str, Tuple[pd.DataFrame, float]] = {}

    async def _emit(self, event_type: str, data: Any):
        if self._broadcast is None:
            return
        payload = {"type": event_type, "data": data, "ts": datetime.utcnow().isoformat()}
        if asyncio.iscoroutinefunction(self._broadcast):
            await self._broadcast(payload)
        else:
            self._broadcast(payload)

    async def _get_4h_df(self, symbol: str) -> Optional[pd.DataFrame]:
        """Return cached 4h DataFrame, refreshing if older than 4 hours."""
        import time
        now = time.time()
        cached = self._df4h.get(symbol)
        if cached is not None:
            df_cached, fetched_at = cached
            if now - fetched_at < _4H_REFRESH_SECONDS:
                return df_cached
        # Fetch fresh 4h data via the ccxt exchange instance from CryptoFeed
        df_fresh = await self.signal_filter.fetch_4h(symbol, self.crypto.exchange)
        if df_fresh is not None and len(df_fresh) >= 10:
            self._df4h[symbol] = (df_fresh, now)
            return df_fresh
        # Keep stale cache rather than returning None if fetch failed
        if cached is not None:
            return cached[0]
        return None

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

            if symbol in self.portfolio.positions:
                # Deduct Binance funding rate (~0.01%/8h) for futures positions
                if asset_type == "crypto":
                    self.portfolio.deduct_funding(symbol)

                self.portfolio.update_trailing_stop(symbol, price, atr_val, self.cfg.risk.trailing_stop_atr_mult)

                # Force-close if price reaches liquidation level
                pos = self.portfolio.positions[symbol]
                if pos.liquidation_price > 0:
                    triggered = (pos.side == "long" and price <= pos.liquidation_price) or \
                                (pos.side == "short" and price >= pos.liquidation_price)
                    if triggered:
                        trade = await self.orders.close_position(symbol, price, "liquidation")
                        if trade:
                            await self._emit("trade_closed", {**trade.__dict__, "portfolio": self.portfolio.to_dict()})
                        return

            exit_reason = self.strategy.should_close(symbol, price, self.portfolio)
            if exit_reason:
                if exit_reason == "partial_tp":
                    # Take 50% profit — don't fully close the position
                    partial_trade = self.portfolio.partial_close(symbol, price)
                    if partial_trade:
                        logger.info("[PAPER] Partial TP %s @ %.4f | PnL %.2f (%.2f%%)",
                                    symbol, price, partial_trade.pnl, partial_trade.pnl_pct)
                        await self._emit("trade_closed", {
                            **partial_trade.__dict__,
                            "portfolio": self.portfolio.to_dict(),
                        })
                    return  # don't fully close; let the remaining half ride
                else:
                    trade = await self.orders.close_position(symbol, price, exit_reason)
                    if trade:
                        await self._emit("trade_closed", {**trade.__dict__, "portfolio": self.portfolio.to_dict()})
                    return

            # Daily loss circuit breaker — no new positions if down >10% today
            if self.portfolio.daily_pnl_pct <= DAILY_LOSS_LIMIT:
                logger.warning("Daily loss limit hit (%.2f%%) — skipping new entries", self.portfolio.daily_pnl_pct)
                await self._emit("signal", {**signal.__dict__, "portfolio": self.portfolio.to_dict()})
                return

            if self.strategy.should_open(signal, self.portfolio):
                # ----------------------------------------------------------
                # Fetch derivatives + 4h data for signal filter (crypto only)
                # ----------------------------------------------------------
                deriv = None
                df_4h = None
                if asset_type == "crypto":
                    try:
                        deriv, df_4h = await asyncio.gather(
                            self.derivatives.fetch(symbol),
                            self._get_4h_df(symbol),
                            return_exceptions=False,
                        )
                    except Exception as exc:
                        logger.warning("Pre-filter data fetch %s: %s", symbol, exc)

                # Run signal filter
                filt = await self.signal_filter.evaluate(signal, df, df_4h, deriv)

                # Apply score boost and append filter reasons
                signal.score = round(min(max(signal.score + filt.score_boost, 0), 100), 1)
                signal.reasons = signal.reasons + filt.reasons
                # Recalculate action if score boost changes the decision
                if filt.score_boost != 0.0 and signal.score < 50:
                    signal.action = "HOLD"

                if not filt.passes:
                    logger.info("SignalFilter blocked %s: %s", symbol, "; ".join(filt.reasons))
                    route = self.strategy.get_route(signal.symbol)
                    regime_info = {
                        "regime": route.regime.regime.value if route else "unknown",
                        "strategy": route.strategy_name if route else "",
                        "adx": round(route.regime.adx, 1) if route else 0,
                        "atr_pct": round(route.regime.atr_pct, 2) if route else 0,
                    }
                    await self._emit("signal", {
                        **signal.__dict__,
                        **regime_info,
                        "portfolio": self.portfolio.to_dict(),
                        "filter_blocked": True,
                        "filter_reasons": filt.reasons,
                    })
                    return

                # Re-check should_open after score adjustment
                if not self.strategy.should_open(signal, self.portfolio):
                    route = self.strategy.get_route(signal.symbol)
                    regime_info = {
                        "regime": route.regime.regime.value if route else "unknown",
                        "strategy": route.strategy_name if route else "",
                    }
                    await self._emit("signal", {**signal.__dict__, **regime_info, "portfolio": self.portfolio.to_dict()})
                    return

                side = "long" if signal.action == "BUY" else "short"

                # Use regime-adapted stop/TP parameters
                route = self.strategy.get_route(signal.symbol)
                sl_mult = route.sl_mult if route else self.cfg.risk.stop_loss_atr_mult
                tp_rr   = route.tp_rr   if route else self.cfg.risk.take_profit_rr
                max_lev = route.max_leverage if route else 10

                sl_dist = atr_val * sl_mult
                tp_dist = sl_dist * tp_rr
                if side == "long":
                    sl, tp = price - sl_dist, price + tp_dist
                    partial_tp = price + (tp - price) * 0.5   # halfway to TP
                else:
                    sl, tp = price + sl_dist, price - tp_dist
                    partial_tp = price - (price - tp) * 0.5   # halfway to TP

                # Dynamic leverage based on signal score, capped by regime
                leverage = min(self.lev_mgr.get_leverage(signal.score, signal.confidence), max_lev)
                lev_pos = self.lev_mgr.calculate_position(self.portfolio.equity, price, sl, leverage)

                pos_size = PositionSize(
                    quantity=lev_pos["quantity"],
                    risk_amount=self.portfolio.equity * self.cfg.risk.risk_per_trade_pct,
                    position_value=lev_pos["position_value"],
                )

                if pos_size.quantity > 0:
                    kwargs = dict(
                        leverage=leverage,
                        margin_required=lev_pos["margin_required"],
                        liq_price=lev_pos["liquidation_price"],
                        partial_tp=partial_tp,
                    )
                    if signal.action == "BUY":
                        ok = await self.orders.open_long(symbol, price, sl, tp, pos_size, asset_type, **kwargs)
                    else:
                        ok = await self.orders.open_short(symbol, price, sl, tp, pos_size, asset_type, **kwargs)

                    if ok:
                        route_name = route.strategy_name if route else ""
                        regime_name = route.regime.regime.value if route else ""
                        await self._emit("position_opened", {
                            "symbol": symbol, "price": price, "side": side,
                            "leverage": leverage, "sl": sl, "tp": tp,
                            "partial_tp": partial_tp,
                            "quantity": pos_size.quantity,
                            "margin_required": lev_pos["margin_required"],
                            "liquidation_price": lev_pos["liquidation_price"],
                            "strategy": route_name,
                            "regime": regime_name,
                            "filter_score_boost": filt.score_boost,
                            "filter_reasons": filt.reasons,
                            "mtf_aligned": filt.mtf_aligned,
                            "portfolio": self.portfolio.to_dict(),
                        })

            route = self.strategy.get_route(signal.symbol)
            regime_info = {
                "regime": route.regime.regime.value if route else "unknown",
                "strategy": route.strategy_name if route else "",
                "adx": round(route.regime.adx, 1) if route else 0,
                "atr_pct": round(route.regime.atr_pct, 2) if route else 0,
            }
            await self._emit("signal", {
                **signal.__dict__,
                **regime_info,
                "portfolio": self.portfolio.to_dict(),
            })

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
        regimes = {}
        for sym in list(self.cfg.crypto_symbols) + list(self.cfg.etf_symbols):
            route = self.strategy.get_route(sym)
            if route:
                regimes[sym] = {
                    "regime": route.regime.regime.value,
                    "strategy": route.strategy_name,
                    "adx": round(route.regime.adx, 1),
                    "atr_pct": round(route.regime.atr_pct, 2),
                    "trend": route.regime.trend_direction,
                    "vol_surge": route.regime.vol_surge,
                }
        return {
            "running": self.running,
            "portfolio": self.portfolio.to_dict(),
            "signals": [s.__dict__ for s in self.signals[:20]],
            "regimes": regimes,
            "positions": {
                k: {
                    "symbol": v.symbol, "side": v.side,
                    "entry_price": v.entry_price, "quantity": v.quantity,
                    "sl": v.stop_loss, "tp": v.take_profit,
                    "asset_type": v.asset_type, "entry_time": v.entry_time,
                    "leverage": v.leverage,
                    "margin_required": v.margin_required,
                    "liquidation_price": v.liquidation_price,
                } for k, v in self.portfolio.positions.items()
            },
            "closed_trades": [t.__dict__ for t in self.portfolio.closed_trades[-20:]],
        }
