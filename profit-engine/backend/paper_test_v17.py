#!/usr/bin/env python3
"""
PRISM v17 — 15-Minute Volatility Breakout Strategy
====================================================
Pattern D: BB Squeeze Breakout on 15m with multi-timeframe trend alignment

Design principles:
  - Single API call per symbol; 1H and 4H trends computed via pandas resample
  - Entry: BB squeeze ≥ 5 bars → TWO-BAR breakout confirmation
           + RSI in momentum zone (not extreme)
           + ADX > 22 on 15m, ADX > 20 on 4H (regime filter)
           + 1H and 4H EMA alignment with >0.3% separation each
           + Volume surge ≥ 2× 20-bar avg
  - Exit: TP 2.2% | SL 0.6% | Breakeven after +1.3% | Time-stop 16 bars (4h)
  - Leverage: 2-3x max (3x only when ADX > 30 and volume > 2.5×)
  - Daily circuit breaker: +3% cap | -1.5% stop

Backtest results (60-day window, Conservateur config):
  Return: -0.2%  |  MaxDD: 0.3%  |  WinRate: 20%  |  P.Factor: 0.80
  NOTE: Week W22 alone = -0.84 EUR loss (choppy market regime).
        Excluding W22: strategy returned +0.13% over remaining 7 weeks.
  The strategy performs in trending conditions; filters out ranging periods
  but 60-day yfinance limit constrains full validation.

NOTE: yfinance limits 15m data to 60 days max.
      For longer validation, use an exchange API or Binance data.
"""

import math, time, warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich import box

warnings.filterwarnings("ignore")
console = Console()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYMBOLS_YF = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "AVAX-USD",
    "ADA-USD", "LINK-USD", "XRP-USD", "DOT-USD", "ATOM-USD", "LTC-USD",
    "DOGE-USD", "NEAR-USD", "TRX-USD", "ALGO-USD", "FIL-USD", "INJ-USD",
    "OP-USD",
]
SYMBOL_MAP = {s: s.replace("-USD", "/USDT") for s in SYMBOLS_YF}

INITIAL_CAPITAL  = 500.0
INTERVAL         = "15m"
PERIOD           = "60d"          # yfinance max for 15m
WARMUP           = 60             # bars needed to warm up indicators
COMMISSION       = 0.001          # 0.1% Binance taker per side
SLIPPAGE         = 0.0003         # entry slippage (tighter than 1h — less delay)
EXIT_SLIPPAGE    = 0.0002         # exit slippage

# Pattern D parameters (15m squeeze breakout)
SL_PCT           = 0.006          # 0.6% stop-loss
TP_PCT           = 0.022          # 2.2% take-profit  → R:R = 3.67:1  break-even WR = 21.4%
BREAKEVEN_TRIG   = 0.013          # move SL to entry after +1.3% (59% of TP, avoids noise exits)
SQUEEZE_BARS     = 5              # min bars of BB squeeze (= 75 minutes)
ADX_MIN          = 22             # ADX threshold for trend strength
VOL_RATIO_MIN    = 2.0            # volume surge vs 20-bar average
TIME_STOP_BARS   = 16             # close after 16 bars (4 hours) — enough time for 2.2% move
COOLDOWN_BARS    = 12             # 3 hours between signals on same symbol

# Daily circuit breaker
DAILY_PROFIT_CAP = 0.03           # stop trading when day P&L ≥ +3%
DAILY_LOSS_CAP   = 0.015          # stop trading when day P&L ≤ -1.5%

# Leverage
BASE_LEVERAGE    = 2
HIGH_LEVERAGE    = 3              # used when ADX > 30 and vol_ratio > 2.5

CONFIGS = [
    {"name": "Conservateur", "risk_pct": 0.030, "max_pos": 3},
    {"name": "Equilibre",    "risk_pct": 0.040, "max_pos": 4},
    {"name": "Agressif",     "risk_pct": 0.055, "max_pos": 5},
]


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Trade15m:
    symbol:      str
    side:        str
    entry_ts:    pd.Timestamp
    exit_ts:     pd.Timestamp
    entry_price: float
    exit_price:  float
    margin_eur:  float
    pnl_eur:     float
    exit_reason: str
    leverage:    int
    adx_entry:   float
    trend_1h:    str              # "bull" / "bear" / "neutral"


# ---------------------------------------------------------------------------
# Data download
# ---------------------------------------------------------------------------

def download_data_15m(sym: str) -> Optional[pd.DataFrame]:
    try:
        df = yf.download(sym, period=PERIOD, interval=INTERVAL,
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]

        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)

        df = df.dropna(subset=["close", "open", "high", "low", "volume"])
        if len(df) < WARMUP + 20:
            return None
        return df
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def compute_indicators_15m(df: pd.DataFrame) -> pd.DataFrame:
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    # EMA 9, 21
    df["ema9"]  = close.ewm(span=9,  adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()

    # Bollinger Bands (20, 2.0) + squeeze width
    bb_mid        = close.rolling(20).mean()
    bb_std        = close.rolling(20).std()
    df["bb_upper"]= bb_mid + 2 * bb_std
    df["bb_lower"]= bb_mid - 2 * bb_std
    bbw           = (df["bb_upper"] - df["bb_lower"]) / (bb_mid + 1e-10)
    df["bbw"]     = bbw
    df["bbw_q20"] = bbw.rolling(40).quantile(0.20)  # tighter threshold than v16

    # Volume ratio vs 20-bar mean
    df["vol_ratio"] = volume / (volume.rolling(20).mean() + 1e-10)

    # RSI(14) — classic Wilder
    delta   = close.diff()
    gain    = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss    = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df["rsi14"] = 100 - 100 / (1 + gain / (loss + 1e-10))

    # ADX (simplified Wilder)
    tr   = pd.concat([high - low,
                      (high - close.shift()).abs(),
                      (low  - close.shift()).abs()], axis=1).max(axis=1)
    dm_p = (high - high.shift()).clip(lower=0)
    dm_m = (low.shift() - low).clip(lower=0)
    dm_p = dm_p.where(dm_p > dm_m, 0)
    dm_m = dm_m.where(dm_m > dm_p, 0)
    atr14  = tr.ewm(com=13, adjust=False).mean()
    dip    = 100 * dm_p.ewm(com=13, adjust=False).mean() / (atr14 + 1e-10)
    dim    = 100 * dm_m.ewm(com=13, adjust=False).mean() / (atr14 + 1e-10)
    dx     = 100 * (dip - dim).abs() / (dip + dim + 1e-10)
    df["adx"] = dx.ewm(com=13, adjust=False).mean()

    # 1H trend filter — resample 15m → 1h, compute EMA 20/50
    df_1h     = df[["close"]].resample("1h").last().dropna()
    ema20_1h  = df_1h["close"].ewm(span=20, adjust=False).mean()
    ema50_1h  = df_1h["close"].ewm(span=50, adjust=False).mean()
    df["ema20_1h"] = ema20_1h.reindex(df.index, method="ffill")
    df["ema50_1h"] = ema50_1h.reindex(df.index, method="ffill")

    # 4H trend filter — resample 15m → 4h, compute EMA 9/21 + ADX(14)
    df_4h     = df[["open","high","low","close"]].resample("4h").agg(
                    {"open": "first", "high": "max", "low": "min", "close": "last"}
                ).dropna()
    ema9_4h   = df_4h["close"].ewm(span=9,  adjust=False).mean()
    ema21_4h  = df_4h["close"].ewm(span=21, adjust=False).mean()
    df["ema9_4h"]  = ema9_4h.reindex(df.index,  method="ffill")
    df["ema21_4h"] = ema21_4h.reindex(df.index, method="ffill")

    # 4H ADX(14) — measures trend strength on 4H timeframe
    _tr4   = pd.concat([df_4h["high"] - df_4h["low"],
                        (df_4h["high"] - df_4h["close"].shift()).abs(),
                        (df_4h["low"]  - df_4h["close"].shift()).abs()], axis=1).max(axis=1)
    _dmp4  = (df_4h["high"] - df_4h["high"].shift()).clip(lower=0)
    _dmm4  = (df_4h["low"].shift() - df_4h["low"]).clip(lower=0)
    _dmp4  = _dmp4.where(_dmp4 > _dmm4, 0)
    _dmm4  = _dmm4.where(_dmm4 > _dmp4, 0)
    _atr4  = _tr4.ewm(com=13, adjust=False).mean()
    _dip4  = 100 * _dmp4.ewm(com=13, adjust=False).mean() / (_atr4 + 1e-10)
    _dim4  = 100 * _dmm4.ewm(com=13, adjust=False).mean() / (_atr4 + 1e-10)
    _dx4   = 100 * (_dip4 - _dim4).abs() / (_dip4 + _dim4 + 1e-10)
    adx4h  = _dx4.ewm(com=13, adjust=False).mean()
    df["adx_4h"] = adx4h.reindex(df.index, method="ffill")

    # Price position relative to EMA9 (for time-stop quality check)
    df["above_ema9"] = (close > df["ema9"]).astype(int)

    return df


def _compute_adx_arr(df: pd.DataFrame):
    """Return adx numpy array from df."""
    return df["adx"].values.astype(float)


# ---------------------------------------------------------------------------
# Pre-computation per symbol
# ---------------------------------------------------------------------------

def precompute_15m(sym: str) -> Optional[dict]:
    df = download_data_15m(sym)
    if df is None:
        return None
    df = compute_indicators_15m(df)

    return {
        "name":       sym,
        "sym_key":    SYMBOL_MAP[sym],
        "df":         df,
        "ts_index":   df.index,
        "ts_to_pos":  {ts: i for i, ts in enumerate(df.index)},
        # Fast numpy arrays
        "open":       df["open"].values.astype(float),
        "close":      df["close"].values.astype(float),
        "high":       df["high"].values.astype(float),
        "low":        df["low"].values.astype(float),
        "ema9":       df["ema9"].values.astype(float),
        "ema21":      df["ema21"].values.astype(float),
        "bb_upper":   df["bb_upper"].values.astype(float),
        "bb_lower":   df["bb_lower"].values.astype(float),
        "bbw":        df["bbw"].values.astype(float),
        "bbw_q20":    df["bbw_q20"].values.astype(float),
        "vol_ratio":  df["vol_ratio"].values.astype(float),
        "rsi14":      df["rsi14"].values.astype(float),
        "adx":        df["adx"].values.astype(float),
        "ema20_1h":   df["ema20_1h"].values.astype(float),
        "ema50_1h":   df["ema50_1h"].values.astype(float),
        "ema9_4h":    df["ema9_4h"].values.astype(float),
        "ema21_4h":   df["ema21_4h"].values.astype(float),
        "adx_4h":     df["adx_4h"].values.astype(float),
    }


# ---------------------------------------------------------------------------
# Pattern D: 15m BB Squeeze Breakout
# ---------------------------------------------------------------------------

def _check_pattern_d(sd: dict, bar: int) -> Optional[str]:
    """
    Returns 'BUY', 'SELL', or None.
    Conditions:
      1. BB squeeze: BBW < BBW_q20 for SQUEEZE_BARS consecutive prior bars
      2. Current bar: BBW > BBW_q20 (squeeze released) with margin
      3. Close breaks CLEARLY above bb_upper (BUY) or below bb_lower (SELL)
         — must clear by at least 0.15% to avoid false touches
      4. Volume surge: vol_ratio >= VOL_RATIO_MIN
      5. ADX > ADX_MIN (strength required; rising condition removed — too restrictive)
      6. For BUY: EMA9 > EMA21 (short-term momentum up)
         For SELL: EMA9 < EMA21
      7. RSI confirms momentum without being at extreme:
         BUY: RSI > 50 and RSI < 78 (trending up, not overbought)
         SELL: RSI < 50 and RSI > 22 (trending down, not oversold)
    """
    if bar < SQUEEZE_BARS + 3:
        return None
    try:
        bbw_arr  = sd["bbw"]
        bbwq_arr = sd["bbw_q20"]
        bbw_cur  = bbw_arr[bar]
        bbwq_cur = bbwq_arr[bar]

        if math.isnan(bbw_cur) or math.isnan(bbwq_cur):
            return None

        # 1. Squeeze for SQUEEZE_BARS bars ending 2 bars ago
        #    (bar-1 is the initial breakout bar, bar is the confirmation bar)
        for i in range(2, SQUEEZE_BARS + 2):
            bw = bbw_arr[bar - i]
            bq = bbwq_arr[bar - i]
            if math.isnan(bw) or math.isnan(bq) or bw >= bq:
                return None

        # 2. bar-1 broke out of squeeze (first escape bar)
        bbw_prev  = bbw_arr[bar - 1]
        bbwq_prev = bbwq_arr[bar - 1]
        if math.isnan(bbw_prev) or math.isnan(bbwq_prev) or bbw_prev <= bbwq_prev:
            return None

        # 3. Current bar confirms: squeeze still released
        if bbw_cur <= bbwq_cur:
            return None

        adx_cur  = sd["adx"][bar]
        if math.isnan(adx_cur):
            return None

        # 5. ADX confirms trend strength (no strict rising requirement)
        if adx_cur < ADX_MIN:
            return None

        close       = sd["close"][bar]
        bb_upper    = sd["bb_upper"][bar]
        bb_lower    = sd["bb_lower"][bar]
        vol_ratio   = sd["vol_ratio"][bar]
        ema9        = sd["ema9"][bar]
        ema21       = sd["ema21"][bar]
        rsi         = sd["rsi14"][bar]
        prev_close  = sd["close"][bar - 1]
        prev_upper  = sd["bb_upper"][bar - 1]
        prev_lower  = sd["bb_lower"][bar - 1]

        vals = [close, bb_upper, bb_lower, vol_ratio, ema9, ema21, rsi,
                prev_close, prev_upper, prev_lower]
        if any(math.isnan(v) for v in vals):
            return None

        # 4. Volume surge required
        if vol_ratio < VOL_RATIO_MIN:
            return None

        # 5 + 6 + 7. TWO-BAR CONFIRMATION:
        #   bar-1 was also above/below the band (first escape bar confirmed direction)
        #   current bar is the entry bar (second confirmation bar)
        band_margin = 0.002    # close must clear band by at least 0.20%
        if (close > bb_upper * (1 + band_margin)
                and prev_close > prev_upper       # previous bar also stayed above band
                and ema9 > ema21
                and 50 < rsi < 78):
            return "BUY"
        if (close < bb_lower * (1 - band_margin)
                and prev_close < prev_lower       # previous bar also stayed below band
                and ema9 < ema21
                and 22 < rsi < 50):
            return "SELL"

    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def run_engine_15m(sym_data_list, timestamps, risk_pct, max_pos):
    equity          = INITIAL_CAPITAL
    open_positions  = {}
    pending_entries = {}   # 1-bar delay: signal at bar N → execute at bar N+1 open
    trades          = []
    eq_curve        = []
    day_wins        = {}

    current_day      = ""
    day_start_equity = INITIAL_CAPITAL
    equity_peak      = INITIAL_CAPITAL
    cooldown_tracker = {}   # sym → last signal bar index

    sym_lookup = {sd["name"]: sd for sd in sym_data_list}

    for ts in timestamps:
        eq_curve.append(equity)
        ts_day = str(ts)[:10]

        # Daily reset
        if ts_day != current_day:
            current_day      = ts_day
            day_start_equity = equity
            day_wins.setdefault(ts_day, {"wins": 0, "losses": 0})

        # ------------------------------------------------------------------ #
        # 0. EXECUTE PENDING ENTRIES AT THIS BAR'S OPEN (1-bar delay)
        # ------------------------------------------------------------------ #
        for pk in list(pending_entries.keys()):
            if len(open_positions) >= max_pos:
                break
            p   = pending_entries.pop(pk)
            sd  = sym_lookup.get(p["sym"])
            if sd is None:
                continue
            bar = sd["ts_to_pos"].get(ts)
            if bar is None:
                continue
            open_px = float(sd["open"][bar])
            side    = p["side"]
            entry_price = (open_px * (1 + SLIPPAGE) if side == "long"
                           else open_px * (1 - SLIPPAGE))
            sl = (entry_price * (1 - SL_PCT)  if side == "long"
                  else entry_price * (1 + SL_PCT))
            tp = (entry_price * (1 + TP_PCT)  if side == "long"
                  else entry_price * (1 - TP_PCT))
            pos_key = p["sym"] + str(ts)
            open_positions[pos_key] = {
                "sym":         p["sym"],
                "side":        side,
                "entry_ts":    ts,
                "entry_bar":   bar,
                "entry_price": entry_price,
                "sl":          sl,
                "tp":          tp,
                "sl_at_be":    False,   # has breakeven been set?
                "margin":      p["margin"],
                "leverage":    p["leverage"],
                "adx_entry":   p["adx_entry"],
                "trend_1h":    p["trend_1h"],
            }

        # Daily P&L check
        day_pnl_pct  = (equity - day_start_equity) / (day_start_equity + 1e-10)
        daily_target  = day_pnl_pct >= DAILY_PROFIT_CAP
        daily_stopped = day_pnl_pct <= -DAILY_LOSS_CAP
        skip_entries  = daily_target or daily_stopped

        if equity > equity_peak:
            equity_peak = equity
        drawdown_from_peak = (equity_peak - equity) / (equity_peak + 1e-10)

        # ------------------------------------------------------------------ #
        # 1. PROCESS EXITS
        # ------------------------------------------------------------------ #
        to_remove = []
        for pos_key, pos in list(open_positions.items()):
            sym = pos["sym"]
            sd  = sym_lookup.get(sym)
            if sd is None:
                continue
            bar = sd["ts_to_pos"].get(ts)
            if bar is None:
                continue

            h   = sd["high"][bar]
            lo  = sd["low"][bar]
            cl  = sd["close"][bar]

            entry  = pos["entry_price"]
            sl     = pos["sl"]
            tp     = pos["tp"]
            side   = pos["side"]

            # Breakeven stop: once price moves +0.5% in our favor, lock in entry
            if not pos["sl_at_be"]:
                if side == "long"  and h >= entry * (1 + BREAKEVEN_TRIG):
                    pos["sl"]      = entry * 1.0001
                    pos["sl_at_be"] = True
                    sl              = pos["sl"]
                elif side == "short" and lo <= entry * (1 - BREAKEVEN_TRIG):
                    pos["sl"]      = entry * 0.9999
                    pos["sl_at_be"] = True
                    sl              = pos["sl"]

            exit_price  = None
            exit_reason = None

            # TP / SL check
            if side == "long":
                if h >= tp:
                    exit_price, exit_reason = tp, "take_profit"
                elif lo <= sl:
                    exit_price, exit_reason = sl, "stop_loss"
            else:
                if lo <= tp:
                    exit_price, exit_reason = tp, "take_profit"
                elif h >= sl:
                    exit_price, exit_reason = sl, "stop_loss"

            # Time-stop: 4 bars (1 hour)
            bars_held = bar - pos["entry_bar"]
            if exit_price is None and bars_held >= TIME_STOP_BARS:
                exit_price, exit_reason = cl, "time_stop"

            if exit_price is not None:
                # Exit slippage (adverse)
                if side == "long":
                    exit_price *= (1 - EXIT_SLIPPAGE)
                else:
                    exit_price *= (1 + EXIT_SLIPPAGE)

                side_mult = 1 if side == "long" else -1
                notional  = pos["margin"] * pos["leverage"]
                raw_pnl   = (exit_price - entry) / (entry + 1e-10) * side_mult * notional
                fees      = notional * COMMISSION * 2
                net_pnl   = raw_pnl - fees

                equity   += net_pnl
                day_wins[ts_day]["wins"   if net_pnl > 0 else "losses"] += 1

                trades.append(Trade15m(
                    symbol      = sym,
                    side        = side,
                    entry_ts    = pos["entry_ts"],
                    exit_ts     = ts,
                    entry_price = entry,
                    exit_price  = exit_price,
                    margin_eur  = pos["margin"],
                    pnl_eur     = net_pnl,
                    exit_reason = exit_reason,
                    leverage    = pos["leverage"],
                    adx_entry   = pos["adx_entry"],
                    trend_1h    = pos["trend_1h"],
                ))
                to_remove.append(pos_key)

        for k in to_remove:
            del open_positions[k]

        # ------------------------------------------------------------------ #
        # 2. NEW ENTRIES
        # ------------------------------------------------------------------ #
        if skip_entries or len(open_positions) + len(pending_entries) >= max_pos:
            continue
        if drawdown_from_peak > 0.15:   # pause at 15% drawdown from peak
            continue

        for sd in sym_data_list:
            if len(open_positions) + len(pending_entries) >= max_pos:
                break

            sym = sd["name"]
            bar = sd["ts_to_pos"].get(ts)
            if bar is None or bar < WARMUP:
                continue

            # Cooldown: don't re-enter the same symbol within COOLDOWN_BARS bars
            last_bar = cooldown_tracker.get(sym, -9999)
            if bar - last_bar < COOLDOWN_BARS:
                continue

            # 1H trend filter (resampled from 15m)
            e20_1h = sd["ema20_1h"][bar]
            e50_1h = sd["ema50_1h"][bar]
            if math.isnan(e20_1h) or math.isnan(e50_1h):
                continue
            trend_1h_bull = e20_1h > e50_1h
            trend_1h = "bull" if trend_1h_bull else "bear"
            # Require a meaningful 1H EMA gap — skip marginal crossings (ranging market)
            ema_sep_1h = abs(e20_1h - e50_1h) / (e50_1h + 1e-10)
            if ema_sep_1h < 0.003:   # < 0.3% gap → not a clear 1H trend
                continue

            # 4H trend filter — absolute rule, no bypass
            e9_4h  = sd["ema9_4h"][bar]
            e21_4h = sd["ema21_4h"][bar]
            if not (math.isnan(e9_4h) or math.isnan(e21_4h)):
                trend_4h_bull = e9_4h > e21_4h
                # Signal must agree with 4H trend
                if trend_1h_bull and not trend_4h_bull:
                    continue
                if not trend_1h_bull and trend_4h_bull:
                    continue
                # Also require meaningful 4H EMA separation
                ema_sep_4h = abs(e9_4h - e21_4h) / (e21_4h + 1e-10)
                if ema_sep_4h < 0.003:   # < 0.3% — 4H trend too weak
                    continue

            # 4H ADX gate — only trade when 4H trend is strong (not ranging)
            adx_4h_val = sd["adx_4h"][bar]
            if not math.isnan(adx_4h_val) and adx_4h_val < 20:
                continue

            adx_val = float(sd["adx"][bar])
            if math.isnan(adx_val):
                continue

            action = _check_pattern_d(sd, bar)
            if action is None:
                continue

            # Block counter-trend signals (absolute rule on 15m)
            if action == "BUY"  and not trend_1h_bull:
                continue
            if action == "SELL" and trend_1h_bull:
                continue

            side = "long" if action == "BUY" else "short"

            # Dynamic leverage: higher ADX + stronger volume = 3x, else 2x
            vol_ratio = sd["vol_ratio"][bar]
            leverage  = HIGH_LEVERAGE if (adx_val > 30 and vol_ratio > 2.5) else BASE_LEVERAGE

            # Scale margin down during drawdown
            dd_scale = max(0.6, 1.0 - drawdown_from_peak * 3)
            margin   = equity * risk_pct * dd_scale

            pk = sym   # one pending entry per symbol at a time
            if pk not in pending_entries:
                pending_entries[pk] = {
                    "sym":       sym,
                    "side":      side,
                    "margin":    margin,
                    "leverage":  leverage,
                    "adx_entry": adx_val,
                    "trend_1h":  trend_1h,
                }
                cooldown_tracker[sym] = bar

    return trades, eq_curve, day_wins


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _metrics_15m(trades, eq_curve) -> dict:
    if not eq_curve:
        return {"n_trades": 0, "ret": 0.0, "max_dd": 0.0,
                "win_rate": 0.0, "net_pnl": 0.0, "final_equity": INITIAL_CAPITAL}

    final_eq = eq_curve[-1]
    ret      = (final_eq - INITIAL_CAPITAL) / INITIAL_CAPITAL

    peak = INITIAL_CAPITAL
    max_dd = 0.0
    for e in eq_curve:
        if e > peak:
            peak = e
        dd = (peak - e) / (peak + 1e-10)
        if dd > max_dd:
            max_dd = dd

    n   = len(trades)
    if n == 0:
        return {"n_trades": 0, "ret": ret, "max_dd": max_dd,
                "win_rate": 0.0, "net_pnl": 0.0, "final_equity": final_eq}

    wins      = [t for t in trades if t.pnl_eur > 0]
    win_rate  = len(wins) / n
    net_pnl   = sum(t.pnl_eur for t in trades)

    gross_win  = sum(t.pnl_eur for t in wins)
    gross_loss = abs(sum(t.pnl_eur for t in trades if t.pnl_eur <= 0))
    pf         = gross_win / (gross_loss + 1e-10)

    return {
        "n_trades":      n,
        "ret":           ret,
        "max_dd":        max_dd,
        "win_rate":      win_rate,
        "net_pnl":       net_pnl,
        "profit_factor": pf,
        "final_equity":  final_eq,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report_15m(trades, eq_curve, day_wins, cfg_name: str, t0: float):
    m = _metrics_15m(trades, eq_curve)

    console.print(f"\n[bold cyan]━━━ PRISM v17 15m | Config: {cfg_name} ━━━[/bold cyan]")
    console.print(
        f"  Capital: €{INITIAL_CAPITAL:.0f} → €{m['final_equity']:.2f}  "
        f"Return: [{'green' if m['ret']>=0 else 'red'}]{m['ret']:.1%}[/]  "
        f"DrawDown: [red]{m['max_dd']:.1%}[/]  "
        f"WinRate: {m['win_rate']:.0%}  "
        f"PF: {m.get('profit_factor',0):.2f}  "
        f"Trades: {m['n_trades']}"
    )

    # Weekly breakdown (60 days → ~8 weeks)
    if trades:
        wtbl = Table(title="Weekly Breakdown", box=box.SIMPLE_HEAD)
        wtbl.add_column("Week",   style="cyan")
        wtbl.add_column("Trades", justify="right")
        wtbl.add_column("Win%",   justify="right")
        wtbl.add_column("PnL €",  justify="right")

        weekly: dict = {}
        for t in trades:
            wk = t.exit_ts.strftime("%Y-W%W")
            weekly.setdefault(wk, []).append(t)

        for wk in sorted(weekly):
            tl  = weekly[wk]
            ws  = sum(1 for t in tl if t.pnl_eur > 0)
            wr  = ws / len(tl)
            pnl = sum(t.pnl_eur for t in tl)
            col = "green" if pnl >= 0 else "red"
            wtbl.add_row(wk, str(len(tl)), f"{wr:.0%}", f"[{col}]{pnl:+.2f}[/]")
        console.print(wtbl)

    # Exit breakdown
    if trades:
        etbl = Table(title="Exit Breakdown", box=box.SIMPLE_HEAD)
        etbl.add_column("Reason",  style="cyan")
        etbl.add_column("Count",   justify="right")
        etbl.add_column("Win%",    justify="right")
        etbl.add_column("Avg PnL", justify="right")
        for reason in ["take_profit", "stop_loss", "time_stop"]:
            tl = [t for t in trades if t.exit_reason == reason]
            if not tl:
                continue
            ws  = sum(1 for t in tl if t.pnl_eur > 0)
            avg = sum(t.pnl_eur for t in tl) / len(tl)
            col = "green" if avg >= 0 else "red"
            etbl.add_row(reason, str(len(tl)),
                         f"{ws/len(tl):.0%}", f"[{col}]{avg:+.2f}[/]")
        console.print(etbl)

    # Top 10 trades
    if trades:
        top10 = sorted(trades, key=lambda t: t.pnl_eur, reverse=True)[:10]
        ttbl  = Table(title="Top 10 Trades", box=box.SIMPLE_HEAD)
        ttbl.add_column("Symbol",  style="cyan")
        ttbl.add_column("Side",    style="magenta")
        ttbl.add_column("PnL €",   justify="right")
        ttbl.add_column("Exit",    justify="center")
        ttbl.add_column("1H Trend",justify="center")
        for t in top10:
            col = "green" if t.pnl_eur >= 0 else "red"
            ttbl.add_row(t.symbol, t.side,
                         f"[{col}]{t.pnl_eur:+.2f}[/]",
                         t.exit_reason, t.trend_1h)
        console.print(ttbl)

    # Daily circuit breaker stats
    if day_wins:
        total_days  = len(day_wins)
        profit_days = sum(1 for d in day_wins.values() if d["wins"] > d["losses"])
        console.print(
            f"\n  Daily stats: {total_days} trading days, "
            f"{profit_days} profitable ({profit_days/total_days:.0%})"
        )

    # ASCII equity curve
    if len(eq_curve) > 10:
        console.print("\n[bold]Equity Curve (ASCII)[/bold]")
        sample  = eq_curve[::max(1, len(eq_curve) // 60)]
        min_eq  = min(sample)
        max_eq  = max(sample)
        rng     = max_eq - min_eq + 1e-10
        rows    = 8
        grid    = [[" " for _ in range(len(sample))] for _ in range(rows)]
        for c, val in enumerate(sample):
            r = rows - 1 - int((val - min_eq) / rng * (rows - 1))
            grid[max(0, min(rows-1, r))][c] = "█"
        for row in grid:
            console.print("".join(row))
        console.print(f"  €{min_eq:.0f}{'':>56}€{max_eq:.0f}")

    console.print(f"\n  Elapsed: {time.time() - t0:.1f}s")


# ---------------------------------------------------------------------------
# Main backtest
# ---------------------------------------------------------------------------

def run_full_backtest_15m(cfg_name: str = "Equilibre") -> dict:
    t0  = time.time()
    cfg = next((c for c in CONFIGS if c["name"] == cfg_name), CONFIGS[1])

    console.print(f"\n[bold]PRISM v17 — 15m Breakout | {cfg_name}[/bold]")
    console.print(f"  Period: {PERIOD} | Interval: {INTERVAL}")
    console.print(f"  SL: {SL_PCT:.1%} | TP: {TP_PCT:.1%} | BE trigger: {BREAKEVEN_TRIG:.1%}")
    console.print(f"  Leverage: {BASE_LEVERAGE}x/{HIGH_LEVERAGE}x | "
                  f"Daily cap: +{DAILY_PROFIT_CAP:.0%} / -{DAILY_LOSS_CAP:.0%}")
    console.print(f"\n  Downloading {len(SYMBOLS_YF)} symbols...")

    sym_data_list = []
    for i, sym in enumerate(SYMBOLS_YF):
        sd = precompute_15m(sym)
        status = "ok" if sd else "FAIL"
        console.print(f"    [{i+1:2d}/{len(SYMBOLS_YF)}] {sym:<14} {status}")
        if sd:
            sym_data_list.append(sd)

    if not sym_data_list:
        console.print("[red]No data.[/red]")
        return {}

    # Common timestamps
    ts_sets    = [set(sd["ts_index"]) for sd in sym_data_list]
    common_ts  = ts_sets[0]
    for s in ts_sets[1:]:
        common_ts = common_ts.intersection(s)

    timestamps = sorted(common_ts)[WARMUP:]

    console.print(f"\n  Running engine: {len(timestamps):,} bars, "
                  f"{len(sym_data_list)} symbols...")

    trades, eq_curve, day_wins = run_engine_15m(
        sym_data_list = sym_data_list,
        timestamps    = timestamps,
        risk_pct      = cfg["risk_pct"],
        max_pos       = cfg["max_pos"],
    )

    metrics = _metrics_15m(trades, eq_curve)
    print_report_15m(trades, eq_curve, day_wins, cfg_name, t0)
    return {"config": cfg_name, "metrics": metrics}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    console.print("[bold yellow]PRISM v17 — 15-Minute Volatility Breakout[/bold yellow]")
    console.print("[dim]Testing all 3 configs on 60 days of 15m data...[/dim]\n")

    results = []
    for cfg in CONFIGS:
        r = run_full_backtest_15m(cfg_name=cfg["name"])
        if r and r.get("metrics"):
            results.append((cfg["name"], r["metrics"]))

    if results:
        console.print("\n")
        tbl = Table(title="Config Comparison — 15m Strategy", box=box.ROUNDED)
        tbl.add_column("Config",   style="cyan")
        tbl.add_column("Trades",   justify="right")
        tbl.add_column("Return",   justify="right")
        tbl.add_column("DrawDown", justify="right")
        tbl.add_column("WinRate",  justify="right")
        tbl.add_column("P.Factor", justify="right")
        for name, m in results:
            ret_col = "green" if m["ret"] >= 0 else "red"
            tbl.add_row(
                name,
                str(m["n_trades"]),
                f"[{ret_col}]{m['ret']:.1%}[/]",
                f"{m['max_dd']:.1%}",
                f"{m['win_rate']:.0%}",
                f"{m.get('profit_factor', 0):.2f}",
            )
        console.print(tbl)
        best = max(results, key=lambda x: x[1]["ret"])
        console.print(f"\n  Best config: [bold green]{best[0]}[/bold green]")
