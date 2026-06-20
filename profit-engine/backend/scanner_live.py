#!/usr/bin/env python3
"""
PRISM v20 — Scanner Live | EMA Pullback 1H
==========================================
Tourne toutes les heures (via cron ou boucle).
Scanne Pattern A sur 17 symboles OKX.
Affiche les signaux actifs avec taille de position.

Usage :
  python3 scanner_live.py              # scan unique
  python3 scanner_live.py --loop       # boucle infinie toutes les 60min
  python3 scanner_live.py --capital 1000 --config Equilibre

Cron (scan à chaque heure pile) :
  0 * * * * cd /home/user/profit-engine/backend && python3 scanner_live.py >> /tmp/prism_signals.log 2>&1
"""

import argparse, math, time, warnings
from datetime import datetime, timezone
from typing import Optional

import requests
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich import box

warnings.filterwarnings("ignore")
console = Console()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SYMBOLS = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "AVAX-USDT",
    "ADA-USDT", "LINK-USDT", "XRP-USDT", "DOT-USDT", "ATOM-USDT",
    "LTC-USDT", "DOGE-USDT", "NEAR-USDT", "TRX-USDT", "ALGO-USDT",
    "FIL-USDT", "INJ-USDT", "OP-USDT",
]

CONFIGS = {
    "Conservateur": {"risk_pct": 0.040, "max_pos": 3, "score_min": 68},
    "Equilibre":    {"risk_pct": 0.055, "max_pos": 4, "score_min": 65},
    "Agressif":     {"risk_pct": 0.065, "max_pos": 5, "score_min": 63},
}

SL_PCT       = 0.020
TP_PCT       = 0.080
ADX_MIN      = 22
EMA21_NEAR   = 0.015
PRIOR_MIN    = 0.015
BASE_LEV     = 4
HIGH_LEV     = 6

OKX_URL      = "https://www.okx.com/api/v5/market/history-candles"
WARMUP       = 250      # barres 1H nécessaires avant de scanner
LOOKBACK     = 280      # barres à télécharger (WARMUP + marge)


# ---------------------------------------------------------------------------
# Données : 280 barres 1H (≈ 11.7 jours)
# ---------------------------------------------------------------------------

def fetch_recent(inst_id: str, bars: int = LOOKBACK) -> Optional[pd.DataFrame]:
    """Télécharge les N dernières barres 1H depuis OKX (pas de cache — données fraîches)."""
    all_rows, after, pages_needed = [], None, math.ceil(bars / 100)

    for _ in range(pages_needed + 2):
        params = {"instId": inst_id, "bar": "1H", "limit": 100}
        if after:
            params["after"] = after
        try:
            r    = requests.get(OKX_URL, params=params, timeout=10)
            data = r.json()
        except Exception:
            return None
        if data.get("code") != "0" or not data.get("data"):
            break
        batch = data["data"]
        all_rows.extend(batch)
        if len(all_rows) >= bars:
            break
        after = batch[-1][0]
        time.sleep(0.06)

    if len(all_rows) < WARMUP:
        return None

    df = pd.DataFrame(all_rows[:bars], columns=[
        "timestamp","open","high","low","close","volume",
        "vol_ccy","vol_quote","confirm"
    ])
    df = df[["timestamp","open","high","low","close","volume"]]
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_datetime(
        df["timestamp"].astype(int), unit="ms", utc=True
    ).dt.tz_localize(None)
    df = df.set_index("timestamp").sort_index()
    df = df.dropna(subset=["close","open","high","low","volume"])
    return df


# ---------------------------------------------------------------------------
# Indicateurs
# ---------------------------------------------------------------------------

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    df["ema9"]  = close.ewm(span=9,  adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    ml    = ema12 - ema26
    ms    = ml.ewm(span=9, adjust=False).mean()
    df["macd_hist"]  = ml - ms
    df["macd_slope"] = (ml - ms).diff()

    delta  = close.diff()
    gain   = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss   = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df["rsi14"] = 100 - 100 / (1 + gain / (loss + 1e-10))

    df["vol_ratio"] = volume / (volume.rolling(20).mean() + 1e-10)

    # VWAP 24-bar
    tp = (high + low + close) / 3
    df["vwap"] = (tp * volume).rolling(24).sum() / (volume.rolling(24).sum() + 1e-10)

    # Stochastic (14, 3)
    low14   = low.rolling(14).min()
    high14  = high.rolling(14).max()
    stoch_k = 100 * (close - low14) / (high14 - low14 + 1e-10)
    df["stoch_k"] = stoch_k
    df["stoch_d"] = stoch_k.rolling(3).mean()

    # ADX
    tr   = pd.concat([high - low,
                      (high - close.shift()).abs(),
                      (low  - close.shift()).abs()], axis=1).max(axis=1)
    dm_p = (high - high.shift()).clip(lower=0)
    dm_m = (low.shift() - low).clip(lower=0)
    dm_p = dm_p.where(dm_p > dm_m, 0)
    dm_m = dm_m.where(dm_m > dm_p, 0)
    atr14 = tr.ewm(com=13, adjust=False).mean()
    dip   = 100 * dm_p.ewm(com=13, adjust=False).mean() / (atr14 + 1e-10)
    dim   = 100 * dm_m.ewm(com=13, adjust=False).mean() / (atr14 + 1e-10)
    dx    = 100 * (dip - dim).abs() / (dip + dim + 1e-10)
    df["adx"] = dx.ewm(com=13, adjust=False).mean()

    # 4H resampled
    df_4h    = df[["close"]].resample("4h").last().dropna()
    ema20_4h = df_4h["close"].ewm(span=20, adjust=False).mean()
    ema50_4h = df_4h["close"].ewm(span=50, adjust=False).mean()
    df["ema20_4h"] = ema20_4h.reindex(df.index, method="ffill")
    df["ema50_4h"] = ema50_4h.reindex(df.index, method="ffill")

    # Daily EMA 50, 200
    df_1d   = df[["close"]].resample("1D").last().dropna()
    ema50d  = df_1d["close"].ewm(span=50,  adjust=False).mean()
    ema200d = df_1d["close"].ewm(span=200, adjust=False).mean()
    df["ema50d"]  = ema50d.reindex(df.index,  method="ffill")
    df["ema200d"] = ema200d.reindex(df.index, method="ffill")

    return df


# ---------------------------------------------------------------------------
# Score (identique v20 — 100 pts)
# ---------------------------------------------------------------------------

def compute_score(row, prev_row) -> tuple[int, int]:
    """Retourne (buy_score, sell_score) pour la barre courante."""
    bs = ss = 0

    e9, e21, e50 = row["ema9"], row["ema21"], row["ema50"]
    if not any(math.isnan(v) for v in [e9, e21, e50]):
        if e9 > e21: bs += 12
        elif e9 < e21: ss += 12
        if e21 > e50: bs += 13
        elif e21 < e50: ss += 13

    r = row["rsi14"]
    if not math.isnan(r):
        if 40 <= r <= 65:   bs += 15
        elif 35 <= r < 40:  bs += 8
        elif 65 < r <= 70:  bs += 5
        if 35 <= r <= 60:   ss += 15
        elif 60 < r <= 65:  ss += 8
        elif 30 <= r < 35:  ss += 5

    mh, mhs = row["macd_hist"], row["macd_slope"]
    if not any(math.isnan(v) for v in [mh, mhs]):
        if mh > 0: bs += 12
        elif mh < 0: ss += 12
        if mhs > 0: bs += 8
        elif mhs < 0: ss += 8

    vr = row["vol_ratio"]
    if not math.isnan(vr):
        pts = 10 if vr >= 1.5 else 6 if vr >= 1.0 else 3 if vr >= 0.7 else 0
        bs += pts; ss += pts

    adx = row["adx"]
    if not math.isnan(adx):
        pts = 10 if adx >= 25 else 6 if adx >= 18 else 0
        bs += pts; ss += pts

    cl, vwap = row["close"], row["vwap"]
    if not any(math.isnan(v) for v in [cl, vwap]):
        if cl > vwap: bs += 10
        elif cl < vwap: ss += 10

    sk, sd_ = row["stoch_k"], row["stoch_d"]
    if not any(math.isnan(v) for v in [sk, sd_]):
        if sk > sd_ and sk < 75: bs += 10
        if sk < sd_ and sk > 25: ss += 10

    return min(bs, 100), min(ss, 100)


# ---------------------------------------------------------------------------
# Pattern A check (dernière barre)
# ---------------------------------------------------------------------------

def check_signal(df: pd.DataFrame) -> Optional[dict]:
    """
    Vérifie Pattern A sur la DERNIÈRE barre complète (bar -2, car bar -1 peut être en cours).
    Retourne un dict de signal ou None.
    """
    if len(df) < WARMUP:
        return None

    # On analyse l'avant-dernière barre (la dernière est peut-être incomplète)
    bar_idx = len(df) - 2

    try:
        row      = df.iloc[bar_idx]
        prev_row = df.iloc[bar_idx - 1]

        close    = row["close"]
        ema9     = row["ema9"]
        ema21    = row["ema21"]
        ema50    = row["ema50"]
        rsi      = row["rsi14"]
        mh_cur   = row["macd_hist"]
        mh_prev  = prev_row["macd_hist"]
        vol_r    = row["vol_ratio"]
        adx      = row["adx"]
        ema20_4h = row["ema20_4h"]
        ema50_4h = row["ema50_4h"]
        ema50d   = row["ema50d"]
        ema200d  = row["ema200d"]

        vals = [close, ema9, ema21, ema50, rsi, mh_cur, mh_prev,
                vol_r, adx, ema20_4h, ema50_4h, ema50d, ema200d]
        if any(math.isnan(v) for v in vals):
            return None

        if adx < ADX_MIN:
            return None

        # Max distance EMA21 sur 5 barres précédentes
        prev5_dists = [
            abs(df.iloc[bar_idx - i]["close"] - df.iloc[bar_idx - i]["ema21"])
            / max(df.iloc[bar_idx - i]["ema21"], 1e-10)
            for i in range(1, 6)
        ]
        max_dist = max(prev5_dists)

        daily_ratio = ema50d / max(ema200d, 1e-10)
        bull_4h = ema20_4h > ema50_4h
        bear_4h = ema20_4h < ema50_4h

        buy_sc, sell_sc = compute_score(row, prev_row)

        # ── LONG ──────────────────────────────────────────────────────────
        if (ema9 > ema21 and ema21 > ema50
                and daily_ratio > 0.98
                and bull_4h
                and abs(close - ema21) / ema21 < EMA21_NEAR
                and max_dist > PRIOR_MIN
                and 43 <= rsi <= 62
                and mh_cur > mh_prev and mh_cur > 0
                and vol_r >= 1.0
                and adx >= ADX_MIN):
            return {
                "side":      "LONG",
                "score":     buy_sc,
                "close":     close,
                "ema21":     ema21,
                "rsi":       rsi,
                "adx":       adx,
                "vol_ratio": vol_r,
                "trend_4h":  "bull",
                "bar_ts":    df.index[bar_idx],
            }

        # ── SHORT ─────────────────────────────────────────────────────────
        if (ema9 < ema21 and ema21 < ema50
                and daily_ratio < 1.02
                and bear_4h
                and abs(close - ema21) / ema21 < EMA21_NEAR
                and max_dist > PRIOR_MIN
                and 38 <= rsi <= 57
                and mh_cur < mh_prev and mh_cur < 0
                and vol_r >= 1.0
                and adx >= ADX_MIN):
            return {
                "side":      "SHORT",
                "score":     sell_sc,
                "close":     close,
                "ema21":     ema21,
                "rsi":       rsi,
                "adx":       adx,
                "vol_ratio": vol_r,
                "trend_4h":  "bear",
                "bar_ts":    df.index[bar_idx],
            }

    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Scanner principal
# ---------------------------------------------------------------------------

def run_scan(capital: float, cfg_name: str) -> list[dict]:
    cfg      = CONFIGS.get(cfg_name, CONFIGS["Equilibre"])
    score_min = cfg["score_min"]
    risk_pct  = cfg["risk_pct"]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    console.print(f"\n[bold yellow]═══ PRISM v20 Scanner | {now} ═══[/bold yellow]")
    console.print(
        f"  Config: [cyan]{cfg_name}[/cyan]  |  "
        f"Capital: €{capital:.0f}  |  "
        f"Score min: {score_min}  |  "
        f"Risk/trade: {risk_pct:.1%}\n"
    )

    # BTC 4H direction (macro filter)
    btc_4h_bull = None
    try:
        btc_df = fetch_recent("BTC-USDT")
        if btc_df is not None:
            btc_df  = add_indicators(btc_df)
            last    = btc_df.iloc[-2]
            b20, b50 = last["ema20_4h"], last["ema50_4h"]
            if not (math.isnan(float(b20)) or math.isnan(float(b50))):
                btc_4h_bull = bool(b20 > b50)
    except Exception:
        pass

    btc_macro_str = "BTC 4H: " + (
        "[green]BULL ↑[/green]" if btc_4h_bull is True
        else "[red]BEAR ↓[/red]" if btc_4h_bull is False
        else "[dim]?[/dim]"
    )
    console.print(f"  {btc_macro_str}\n")

    signals = []
    no_signal_syms = []

    for sym in [s for s in SYMBOLS if s != "BTC-USDT"]:
        try:
            df = fetch_recent(sym)
            if df is None:
                continue
            df = add_indicators(df)
            sig = check_signal(df)

            if sig is None:
                no_signal_syms.append(sym)
                continue

            # BTC macro filter
            if btc_4h_bull is not None:
                if sig["side"] == "LONG"  and not btc_4h_bull:
                    no_signal_syms.append(sym)
                    continue
                if sig["side"] == "SHORT" and btc_4h_bull:
                    no_signal_syms.append(sym)
                    continue

            if sig["score"] < score_min:
                no_signal_syms.append(sym)
                continue

            # Position sizing
            leverage   = HIGH_LEV if (sig["adx"] > 30 and sig["score"] >= 75) else BASE_LEV
            margin     = capital * risk_pct
            notional   = margin * leverage
            sl_price   = (sig["close"] * (1 - SL_PCT) if sig["side"] == "LONG"
                          else sig["close"] * (1 + SL_PCT))
            tp_price   = (sig["close"] * (1 + TP_PCT) if sig["side"] == "LONG"
                          else sig["close"] * (1 - TP_PCT))
            risk_eur   = margin * leverage * SL_PCT
            reward_eur = margin * leverage * TP_PCT

            sig["sym"]         = sym
            sig["leverage"]    = leverage
            sig["margin"]      = margin
            sig["notional"]    = notional
            sig["sl_price"]    = sl_price
            sig["tp_price"]    = tp_price
            sig["risk_eur"]    = risk_eur
            sig["reward_eur"]  = reward_eur
            signals.append(sig)

        except Exception:
            pass

    # Affichage
    if signals:
        tbl = Table(
            title=f"🔔  {len(signals)} signal(s) actif(s)",
            box=box.ROUNDED, border_style="green"
        )
        tbl.add_column("Symbole",  style="bold cyan")
        tbl.add_column("Side",     justify="center")
        tbl.add_column("Score",    justify="right")
        tbl.add_column("Prix",     justify="right")
        tbl.add_column("SL",       justify="right", style="red")
        tbl.add_column("TP",       justify="right", style="green")
        tbl.add_column("Margin",   justify="right")
        tbl.add_column("Levier",   justify="right")
        tbl.add_column("Risque",   justify="right", style="red")
        tbl.add_column("Reward",   justify="right", style="green")
        tbl.add_column("RSI",      justify="right")
        tbl.add_column("ADX",      justify="right")

        for s in sorted(signals, key=lambda x: x["score"], reverse=True):
            side_col = "[green]LONG ▲[/green]" if s["side"] == "LONG" else "[red]SHORT ▼[/red]"
            tbl.add_row(
                s["sym"],
                side_col,
                str(s["score"]),
                f"{s['close']:.4f}",
                f"{s['sl_price']:.4f}",
                f"{s['tp_price']:.4f}",
                f"€{s['margin']:.1f}",
                f"{s['leverage']}×",
                f"-€{s['risk_eur']:.1f}",
                f"+€{s['reward_eur']:.1f}",
                f"{s['rsi']:.0f}",
                f"{s['adx']:.0f}",
            )
        console.print(tbl)
        console.print(
            f"\n  [bold]Instructions :[/bold] "
            f"Entre au prochain open (barre 1H) | "
            f"SL fixe {SL_PCT:.0%} | TP fixe {TP_PCT:.0%} | "
            f"Time-stop 72h\n"
        )
    else:
        console.print(
            "  [dim]Aucun signal Pattern A en ce moment.[/dim]\n"
            f"  [dim]{len(no_signal_syms)} symboles scannés — conditions non réunies.[/dim]\n"
        )

    # Résumé discret des rejets
    if no_signal_syms:
        console.print(
            f"  [dim]Pas de signal sur : {', '.join(no_signal_syms)}[/dim]"
        )

    return signals


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="PRISM v20 — Scanner Live 1H")
    parser.add_argument("--capital", type=float, default=1000.0,
                        help="Capital total en euros (défaut: 1000)")
    parser.add_argument("--config",  type=str,  default="Equilibre",
                        choices=list(CONFIGS.keys()),
                        help="Config risk (défaut: Equilibre)")
    parser.add_argument("--loop",    action="store_true",
                        help="Boucle infinie — scan toutes les 60 min")
    args = parser.parse_args()

    if args.loop:
        console.print("[bold]Mode boucle — scan toutes les 60 minutes. Ctrl+C pour arrêter.[/bold]")
        while True:
            run_scan(capital=args.capital, cfg_name=args.config)
            console.print(f"  [dim]Prochain scan dans 60 min...[/dim]")
            time.sleep(3600)
    else:
        run_scan(capital=args.capital, cfg_name=args.config)


if __name__ == "__main__":
    main()
