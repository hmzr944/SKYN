"""
Dynamic leverage manager for Binance Futures.
Calculates leverage multiplier based on signal score/confidence and
computes position sizing with risk-based margin allocation.
"""
from __future__ import annotations

from typing import Dict


class LeverageManager:
    """
    Maps signal score → leverage multiplier and handles position sizing
    for leveraged futures trades.

    Score thresholds (inclusive lower bound):
        90+ → 8x
        80+ → 5x
        70+ → 3x
        60+ → 2x
        <60 → 1x  (no leverage)
    """

    # Sorted descending so the first matching threshold wins
    _SCORE_LADDER: list[tuple[float, int]] = [
        (90, 8),
        (80, 5),
        (70, 3),
        (60, 2),
    ]

    def __init__(
        self,
        score_to_leverage: Dict[int, int] | None = None,
        max_leverage: int = 10,
        risk_per_trade_pct: float = 0.02,
    ) -> None:
        """
        Args:
            score_to_leverage: Optional override mapping score → leverage.
                               Keys are integer lower-bound thresholds.
            max_leverage:      Hard cap on leverage returned.
            risk_per_trade_pct: Fraction of equity risked per trade (default 2%).
        """
        self.max_leverage = max_leverage
        self.risk_per_trade_pct = risk_per_trade_pct

        if score_to_leverage:
            # Build sorted ladder from caller-supplied mapping
            self._ladder: list[tuple[float, int]] = sorted(
                score_to_leverage.items(), key=lambda kv: kv[0], reverse=True
            )
        else:
            self._ladder = list(self._SCORE_LADDER)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_leverage(self, score: float, confidence: str = "MEDIUM") -> int:
        """
        Return leverage multiplier based on signal score.

        Args:
            score:      Composite signal score (0–100).
            confidence: Signal confidence label (e.g. "HIGH", "MEDIUM", "LOW").
                        Currently used for future extension; does not alter
                        the score-based lookup but could apply a multiplier.

        Returns:
            Integer leverage in range [1, max_leverage].
        """
        for threshold, lev in self._ladder:
            if score >= threshold:
                return min(lev, self.max_leverage)
        return 1  # no leverage below lowest threshold

    def calculate_position(
        self,
        equity: float,
        entry_price: float,
        stop_loss: float,
        leverage: int,
    ) -> dict:
        """
        Calculate position size for a leveraged futures trade.

        Sizing rule: risk exactly ``risk_per_trade_pct`` of equity on the
        stop-loss distance; leverage then amplifies how much notional
        exposure that margin buys.

        Args:
            equity:       Current account equity in quote currency.
            entry_price:  Expected fill price.
            stop_loss:    Stop-loss price.
            leverage:     Leverage multiplier to apply.

        Returns:
            dict with keys:
                quantity        — number of base-asset units
                margin_required — quote currency locked as margin
                position_value  — notional value (margin × leverage)
                liquidation_price — approximate liq price (long assumed)
        """
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance < 1e-12:
            sl_distance = entry_price * 0.02  # fallback: 2% of price

        # Dollar risk budget
        risk_amount = equity * self.risk_per_trade_pct

        # With leverage the effective sl distance per unit of notional is the same,
        # but we only put up margin = notional / leverage.
        # Units: risk_amount / sl_distance gives the raw qty as if leverage=1.
        # At leverage L, the same margin buys L× more notional, so qty scales by L.
        quantity = (risk_amount / sl_distance) * leverage

        # Margin required = notional / leverage
        position_value = quantity * entry_price
        margin_required = position_value / leverage

        # Cap: margin cannot exceed full equity
        if margin_required > equity:
            margin_required = equity
            position_value = margin_required * leverage
            quantity = position_value / entry_price

        liq = self.liquidation_price(entry_price, leverage, "long")

        return {
            "quantity": round(quantity, 8),
            "margin_required": round(margin_required, 4),
            "position_value": round(position_value, 4),
            "liquidation_price": round(liq, 4),
        }

    def liquidation_price(self, entry: float, leverage: int, side: str) -> float:
        """
        Approximate liquidation price (simplified, ignores funding/fees).

        Formula:
            Long:  entry * (1 - 0.9 / leverage)
            Short: entry * (1 + 0.9 / leverage)

        The 0.9 factor leaves a small buffer before the 100% margin loss point.

        Args:
            entry:    Entry (fill) price.
            leverage: Leverage multiplier.
            side:     "long" or "short".

        Returns:
            Approximate liquidation price as a float.
        """
        lev = max(leverage, 1)
        if side.lower() == "long":
            return entry * (1.0 - 0.9 / lev)
        else:
            return entry * (1.0 + 0.9 / lev)
