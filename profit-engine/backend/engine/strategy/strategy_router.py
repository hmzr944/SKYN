"""
Adaptive strategy router.

Based on the detected market regime, adjusts:
  - Signal scoring (boost/penalize BUY or SELL)
  - Stop-loss multiplier
  - Take-profit R:R ratio
  - Max leverage cap
  - Minimum score threshold

Strategy mapping:
  BULL_TREND  → Momentum long: ride the trend, wide TP, moderate stops
  BEAR_TREND  → Short breakdown: inverse momentum, conservative leverage
  RANGING     → Mean reversion: RSI/BB bounces, tight stops, small TP
  BREAKOUT    → Momentum burst: volume-confirmed, aggressive TP
  HIGH_VOL    → Defensive: reduce size, no new entries above ATR threshold
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .regime_detector import Regime, RegimeResult, detect_regime
from ..analysis.signals import Signal, score_signal


@dataclass
class RouteResult:
    signal: Signal
    regime: RegimeResult
    sl_mult: float          # override stop_loss_atr_mult
    tp_rr: float            # override take_profit_rr
    max_leverage: int       # hard cap for this regime
    skip: bool = False      # HIGH_VOL may block entry entirely
    strategy_name: str = "" # for display


# ---------------------------------------------------------------------------
# Per-regime parameter tables
# ---------------------------------------------------------------------------

_PARAMS = {
    Regime.BULL_TREND: dict(
        sl_mult=1.8, tp_rr=3.5, max_leverage=5,
        buy_bonus=18, sell_penalty=30,
        min_score=65, name="Momentum Haussier",
    ),
    Regime.BEAR_TREND: dict(
        sl_mult=1.8, tp_rr=3.0, max_leverage=3,
        buy_penalty=30, sell_bonus=18,
        min_score=65, name="Momentum Baissier",
    ),
    Regime.RANGING: dict(
        # Wide stops for mean reversion — noise level is high in sideways markets.
        # Tight TP: price rarely runs far in a ranging band.
        sl_mult=2.5, tp_rr=1.2, max_leverage=2,
        buy_bonus=0, sell_bonus=0,
        min_score=75, name="Mean Reversion",
    ),
    Regime.BREAKOUT: dict(
        # Breakouts need room to breathe — first attempt often fails.
        sl_mult=2.0, tp_rr=2.5, max_leverage=4,
        buy_bonus=10, sell_bonus=10,
        min_score=75, name="Breakout",
    ),
    Regime.HIGH_VOL: dict(
        sl_mult=2.5, tp_rr=2.0, max_leverage=1,
        buy_bonus=0, sell_bonus=0,
        min_score=85, name="Défensif",
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class StrategyRouter:
    """
    Wraps score_signal() with regime-based score adjustments.
    Call route() instead of score_signal() directly.
    """

    def route(self, df: pd.DataFrame, symbol: str, cfg) -> RouteResult:
        regime_result = detect_regime(df)
        p = _PARAMS[regime_result.regime]

        # Base signal from existing multi-factor scorer
        base_signal = score_signal(df, symbol, cfg)

        # Extract last-bar context for regime-specific gating
        last = df.iloc[-1]
        bb_pct = float(last.get("bb_pct", 0.5) or 0.5)

        # Adjust scores based on regime
        adj_score, adj_action, adj_reasons = self._adjust(
            base_signal, regime_result, p, bb_pct
        )

        # Rebuild signal with adjusted values
        adjusted = Signal(
            symbol=base_signal.symbol,
            action=adj_action,
            score=round(adj_score, 1),
            confidence=_confidence(adj_score),
            reasons=adj_reasons,
            price=base_signal.price,
            suggested_sl=base_signal.suggested_sl,
            suggested_tp=base_signal.suggested_tp,
            timestamp=base_signal.timestamp,
            categories=base_signal.categories,
        )

        skip = (
            regime_result.regime == Regime.HIGH_VOL
            and regime_result.atr_pct > 5.0   # truly extreme — sit out
        )

        return RouteResult(
            signal=adjusted,
            regime=regime_result,
            sl_mult=p["sl_mult"],
            tp_rr=p["tp_rr"],
            max_leverage=p["max_leverage"],
            skip=skip,
            strategy_name=p["name"],
        )

    # ------------------------------------------------------------------

    def _adjust(self, sig: Signal, regime: RegimeResult, p: dict, bb_pct: float = 0.5):
        buy_score  = sig.score if sig.action == "BUY"  else 0.0
        sell_score = sig.score if sig.action == "SELL" else 0.0
        if sig.action == "HOLD":
            buy_score  = sig.score * 0.5
            sell_score = sig.score * 0.5

        reasons = list(sig.reasons)

        # Apply regime bonuses/penalties
        if regime.regime == Regime.BULL_TREND:
            buy_score  = min(buy_score  + p.get("buy_bonus",    0), 100)
            sell_score = max(sell_score - p.get("sell_penalty", 0), 0)
            reasons.append(f"[{p['name']}] +{p.get('buy_bonus', 0)}pts long")

        elif regime.regime == Regime.BEAR_TREND:
            sell_score = min(sell_score + p.get("sell_bonus",   0), 100)
            buy_score  = max(buy_score  - p.get("buy_penalty",  0), 0)
            reasons.append(f"[{p['name']}] +{p.get('sell_bonus', 0)}pts short")

        elif regime.regime == Regime.BREAKOUT:
            # Only boost if actual volume surge is confirmed
            if not regime.vol_surge:
                buy_score  = max(buy_score  - 25, 0)
                sell_score = max(sell_score - 25, 0)
                reasons.append(f"[{p['name']}] Volume insuffisant — pénalité -25")
            elif regime.trend_direction == "up":
                buy_score  = min(buy_score  + p.get("buy_bonus", 0), 100)
                reasons.append(f"[{p['name']}] Volume breakout haussier +{p.get('buy_bonus', 0)}")
            else:
                sell_score = min(sell_score + p.get("sell_bonus", 0), 100)
                reasons.append(f"[{p['name']}] Volume breakout baissier +{p.get('sell_bonus', 0)}")

        elif regime.regime == Regime.RANGING:
            # Mean reversion ONLY works at BB extremes — gate aggressively
            at_lower_band = bb_pct < 0.15
            at_upper_band = bb_pct > 0.85
            if sig.action == "BUY" and not at_lower_band:
                buy_score = max(buy_score - 35, 0)  # heavy penalty — not oversold enough
                reasons.append(f"[{p['name']}] BB={bb_pct:.2f} — pas à l'extrême bas (-35)")
            elif sig.action == "SELL" and not at_upper_band:
                sell_score = max(sell_score - 35, 0)
                reasons.append(f"[{p['name']}] BB={bb_pct:.2f} — pas à l'extrême haut (-35)")
            else:
                reasons.append(f"[{p['name']}] ADX={regime.adx:.0f} BB={bb_pct:.2f} — oscillation extrême")

        elif regime.regime == Regime.HIGH_VOL:
            # Suppress everything — threshold is very high
            buy_score  *= 0.5
            sell_score *= 0.5
            reasons.append(f"[{p['name']}] ATR={regime.atr_pct:.1f}% — réduction risque")

        min_score = p["min_score"]

        if buy_score >= min_score and buy_score > sell_score:
            return buy_score, "BUY", reasons
        elif sell_score >= min_score and sell_score > buy_score:
            return sell_score, "SELL", reasons
        else:
            return max(buy_score, sell_score), "HOLD", reasons


def _confidence(score: float) -> str:
    if score >= 80:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    return "LOW"
