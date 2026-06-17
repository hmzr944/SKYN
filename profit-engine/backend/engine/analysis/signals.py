from dataclasses import dataclass
from typing import List
import pandas as pd
from .patterns import detect_candlestick, detect_support_resistance


@dataclass
class Signal:
    symbol: str
    action: str
    score: float
    confidence: str
    reasons: List[str]
    price: float
    suggested_sl: float
    suggested_tp: float
    timestamp: str


def score_signal(df: pd.DataFrame, symbol: str, cfg) -> Signal:
    s = cfg.strategy
    r = cfg.risk
    last = df.iloc[-1]
    prev = df.iloc[-2]
    price = float(last["close"])
    atr_val = float(last["atr"]) if not pd.isna(last.get("atr", float("nan"))) else price * 0.02

    buy = 0.0
    sell = 0.0
    buy_r: List[str] = []
    sell_r: List[str] = []

    # RSI
    rsi_v = last.get("rsi")
    if rsi_v is not None and not pd.isna(rsi_v):
        if rsi_v < s.rsi_oversold:
            buy += 18; buy_r.append(f"RSI survendu ({rsi_v:.0f})")
        elif rsi_v < 40:
            buy += 8; buy_r.append(f"RSI bas ({rsi_v:.0f})")
        if rsi_v > s.rsi_overbought:
            sell += 18; sell_r.append(f"RSI suracheté ({rsi_v:.0f})")
        elif rsi_v > 60:
            sell += 8; sell_r.append(f"RSI haut ({rsi_v:.0f})")

    # MACD
    hist = last.get("macd_hist")
    prev_hist = prev.get("macd_hist")
    if hist is not None and prev_hist is not None and not pd.isna(hist) and not pd.isna(prev_hist):
        if hist > 0 and prev_hist <= 0:
            buy += 22; buy_r.append("Croisement MACD haussier")
        elif hist > 0 and hist > prev_hist:
            buy += 10; buy_r.append("MACD momentum+")
        if hist < 0 and prev_hist >= 0:
            sell += 22; sell_r.append("Croisement MACD baissier")
        elif hist < 0 and hist < prev_hist:
            sell += 10; sell_r.append("MACD momentum-")

    # Bollinger Bands
    bb_pct = last.get("bb_pct")
    if bb_pct is not None and not pd.isna(bb_pct):
        if bb_pct < 0.1:
            buy += 15; buy_r.append("Prix bande inf. BB")
        elif bb_pct < 0.25:
            buy += 7
        if bb_pct > 0.9:
            sell += 15; sell_r.append("Prix bande sup. BB")
        elif bb_pct > 0.75:
            sell += 7

    # EMA alignment
    e9, e21, e50 = last.get("ema9"), last.get("ema21"), last.get("ema50")
    if all(v is not None and not pd.isna(v) for v in [e9, e21, e50]):
        if e9 > e21 > e50 and price > e50:
            buy += 12; buy_r.append("Alignement EMA haussier")
        elif e9 < e21 < e50 and price < e50:
            sell += 12; sell_r.append("Alignement EMA baissier")

    # Volume
    vol_ratio = last.get("vol_ratio")
    if vol_ratio is not None and not pd.isna(vol_ratio) and vol_ratio > 1.5:
        if buy >= sell:
            buy += 8; buy_r.append(f"Volume élevé ({vol_ratio:.1f}x)")
        else:
            sell += 8; sell_r.append(f"Volume élevé ({vol_ratio:.1f}x)")

    # Stochastic
    sk, sd = last.get("stoch_k"), last.get("stoch_d")
    if sk is not None and sd is not None and not pd.isna(sk) and not pd.isna(sd):
        if sk < 20 and sk > sd:
            buy += 8; buy_r.append("Stochastique survendu + croisement")
        if sk > 80 and sk < sd:
            sell += 8; sell_r.append("Stochastique suracheté + croisement")

    # Candlestick patterns
    for p in detect_candlestick(df):
        pts = p.strength * 15
        if p.bullish:
            buy += pts; buy_r.append(f"Pattern: {p.name}")
        else:
            sell += pts; sell_r.append(f"Pattern: {p.name}")

    # Support / Resistance
    supports, resistances = detect_support_resistance(df)
    for lv in supports:
        if abs(price - lv) / price < 0.015:
            buy += 10; buy_r.append(f"Rebond support ({lv})"); break
    for lv in resistances:
        if abs(price - lv) / price < 0.015:
            sell += 10; sell_r.append(f"Rejet résistance ({lv})"); break

    buy = min(buy, 100)
    sell = min(sell, 100)

    sl_dist = atr_val * r.stop_loss_atr_mult
    tp_dist = sl_dist * r.take_profit_rr

    if buy >= s.min_score_buy and buy > sell:
        action = "BUY"
        score = buy
        reasons = buy_r
        sl = round(price - sl_dist, 6)
        tp = round(price + tp_dist, 6)
    elif sell >= s.min_score_sell and sell > buy:
        action = "SELL"
        score = sell
        reasons = sell_r
        sl = round(price + sl_dist, 6)
        tp = round(price - tp_dist, 6)
    else:
        action = "HOLD"
        score = max(buy, sell)
        reasons = buy_r if buy >= sell else sell_r
        sl = round(price - sl_dist, 6)
        tp = round(price + tp_dist, 6)

    confidence = "HIGH" if score >= 80 else "MEDIUM" if score >= 60 else "LOW"

    return Signal(
        symbol=symbol,
        action=action,
        score=round(score, 1),
        confidence=confidence,
        reasons=reasons,
        price=price,
        suggested_sl=sl,
        suggested_tp=tp,
        timestamp=str(df.index[-1]),
    )
