"""
SKYN v15 APEX — Autonomous Paper-Trading Bot
Scans every hour for signals, monitors positions every 5 min.
All trades are paper (simulated) — no real exchange connection.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Optional

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent / "apex_state.json"

DAILY_LOSS_LIMIT = 0.12   # -12% equity in one day → halt trading
MAX_POSITIONS    = 5
PARTIAL_TP_LOCK  = 0.30   # fraction of initial risk locked at stage-2

SCAN_INTERVAL_S    = 3600   # 1 hour
MONITOR_INTERVAL_S = 300    # 5 minutes


# ── State helpers ─────────────────────────────────────────────────────────────

def _default_state(capital: float = 500.0) -> dict:
    return {
        "capital":     capital,
        "equity":      capital,
        "positions":   {},
        "closed_trades": [],
        "last_scan":   None,
        "bot_running": False,
        "daily_equity_start": capital,
        "daily_date":  str(datetime.now(timezone.utc).date()),
        "scan_count":  0,
        "last_scan_ts": None,
        "next_scan_ts": None,
        "log":         [],        # last 50 log entries
    }


def load_state(capital: float = 500.0) -> dict:
    if STATE_FILE.exists():
        try:
            s = json.loads(STATE_FILE.read_text())
            # Reset daily circuit breaker if new day
            today = str(datetime.now(timezone.utc).date())
            if s.get("daily_date") != today:
                s["daily_date"] = today
                s["daily_equity_start"] = s.get("equity", capital)
            return s
        except Exception:
            pass
    return _default_state(capital)


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, default=str, indent=2))


# ── Price fetching ────────────────────────────────────────────────────────────

def fetch_price(yf_sym: str) -> Optional[float]:
    """Fetch the latest price for a symbol via yfinance (5m bars)."""
    try:
        hist = yf.Ticker(yf_sym).history(period="1d", interval="5m")
        if len(hist) > 0:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"fetch_price({yf_sym}): {e}")
    return None


def fetch_prices_batch(symbols: list[str]) -> dict:
    """Fetch latest prices for multiple symbols at once."""
    if not symbols:
        return {}
    try:
        data = yf.download(
            symbols, period="1d", interval="5m",
            progress=False, auto_adjust=True, group_by="ticker"
        )
        prices = {}
        for sym in symbols:
            try:
                if len(symbols) == 1:
                    col = data["Close"]
                else:
                    col = data[sym]["Close"]
                if len(col) > 0:
                    prices[sym] = float(col.iloc[-1])
            except Exception:
                pass
        return prices
    except Exception as e:
        logger.warning(f"fetch_prices_batch error: {e}")
        # Fallback: fetch individually
        prices = {}
        for sym in symbols:
            p = fetch_price(sym)
            if p:
                prices[sym] = p
        return prices


# ── Bot ───────────────────────────────────────────────────────────────────────

class ApexBot:
    def __init__(
        self,
        capital: float = 500.0,
        cfg_name: str = "Selectif",
        broadcast_fn: Optional[Callable] = None,
    ):
        self.capital   = capital
        self.cfg_name  = cfg_name
        self._broadcast = broadcast_fn
        self.running   = False
        self.state     = load_state(capital)
        self.state["bot_running"] = False
        self._scan_task    = None
        self._monitor_task = None

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def _bcast(self, msg: dict):
        if self._broadcast:
            try:
                await self._broadcast(msg)
            except Exception:
                pass

    def _log(self, msg: str, level: str = "info"):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = {"ts": ts, "msg": msg, "level": level}
        self.state.setdefault("log", []).append(entry)
        if len(self.state["log"]) > 100:
            self.state["log"] = self.state["log"][-100:]
        getattr(logger, level, logger.info)(msg)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self):
        if self.running:
            return
        self.running = True
        self.state["bot_running"] = True
        self._log("Bot démarré — scan toutes les 60 min, monitoring toutes les 5 min")
        save_state(self.state)
        await self._bcast({"type": "bot_started"})

        self._scan_task    = asyncio.create_task(self._scan_loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    def stop(self):
        self.running = False
        self.state["bot_running"] = False
        self._log("Bot arrêté")
        save_state(self.state)
        if self._scan_task:
            self._scan_task.cancel()
        if self._monitor_task:
            self._monitor_task.cancel()

    # ── Scan loop ─────────────────────────────────────────────────────────────

    async def _scan_loop(self):
        """Run signal scan immediately then every hour."""
        await asyncio.sleep(2)   # small delay to let server finish startup
        while self.running:
            try:
                await self._do_scan()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log(f"Erreur scan: {e}", "error")

            # Schedule next scan on the next full hour
            now = datetime.now(timezone.utc)
            next_h = (now + timedelta(hours=1)).replace(minute=2, second=0, microsecond=0)
            wait_s = (next_h - now).total_seconds()
            self.state["next_scan_ts"] = next_h.isoformat()
            save_state(self.state)
            self._log(f"Prochain scan dans {int(wait_s//60)}min")
            await self._bcast({"type": "state", "data": self._public_state()})
            try:
                await asyncio.sleep(wait_s)
            except asyncio.CancelledError:
                break

    async def _do_scan(self):
        from paper_test_v15 import scan_live_signals

        self._log(f"Scan #{self.state.get('scan_count', 0) + 1} — téléchargement données…")
        now_ts = datetime.now(timezone.utc).isoformat()
        self.state["last_scan_ts"] = now_ts

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, scan_live_signals, self.state["equity"], self.cfg_name
        )

        if "error" in result:
            self._log(f"Scan erreur: {result['error']}", "error")
            return

        self.state["last_scan"] = result
        self.state["scan_count"] = self.state.get("scan_count", 0) + 1

        macro     = result.get("macro", "neutral")
        btc_price = result.get("btc_price", 0)
        btc_rsi   = result.get("btc_rsi", 50)
        signals   = result.get("signals", [])

        self._log(
            f"Scan OK — macro={macro} BTC=${btc_price:,.0f} RSI={btc_rsi:.0f} "
            f"— {len(signals)} signal(s)"
        )

        await self._bcast({"type": "scan_done", "data": result})

        # Process new signals
        for sig in signals:
            sym = sig["symbol"]

            # Already have a position
            if sym in self.state["positions"]:
                continue

            # Max positions reached
            if len(self.state["positions"]) >= MAX_POSITIONS:
                self._log(f"Max positions atteint ({MAX_POSITIONS}) — skip {sym}")
                break

            # Daily loss circuit breaker
            if self._daily_loss_hit():
                self._log(
                    f"Circuit breaker déclenché (−{DAILY_LOSS_LIMIT*100:.0f}% jour) — "
                    "pas de nouvelles entrées", "warning"
                )
                break

            self._open_position(sig)
            await self._bcast({"type": "trade_open", "data": self.state["positions"][sym]})

        save_state(self.state)
        await self._bcast({"type": "state", "data": self._public_state()})

    # ── Monitor loop ──────────────────────────────────────────────────────────

    async def _monitor_loop(self):
        await asyncio.sleep(30)   # wait 30s before first monitor
        while self.running:
            try:
                await asyncio.sleep(MONITOR_INTERVAL_S)
                if self.state["positions"]:
                    await self._monitor_positions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log(f"Erreur monitoring: {e}", "error")

    async def _monitor_positions(self):
        positions = self.state["positions"]
        if not positions:
            return

        # Fetch prices for all open positions
        yf_syms = list({
            p.get("sym_key", p["symbol"].replace("/USDT", "-USD"))
            for p in positions.values()
        })

        loop = asyncio.get_event_loop()
        prices = await loop.run_in_executor(None, fetch_prices_batch, yf_syms)

        if not prices:
            self._log("Monitoring: impossible de récupérer les prix", "warning")
            return

        changed = False
        for sym, pos in list(positions.items()):
            yf_sym = pos.get("sym_key", sym.replace("/USDT", "-USD"))
            price  = prices.get(yf_sym)
            if not price:
                continue

            pos["current_price"] = round(price, 6)
            action = pos["action"]
            side   = "long" if action == "BUY" else "short"
            entry  = pos["entry"]

            # Unrealized P&L
            sl_dist = abs(pos["sl_orig"] - entry)
            if sl_dist > 0:
                pnl_raw = (price - entry) if side == "long" else (entry - price)
                pos["unrealized_pnl"] = round(pos["risk_eur"] * pnl_raw / sl_dist, 2)

            reason     = None
            exit_price = price

            # ── SL hit ────────────────────────────────────────────────────────
            if side == "long"  and price <= pos["sl"]:
                reason = "stop_loss"; exit_price = pos["sl"]
            elif side == "short" and price >= pos["sl"]:
                reason = "stop_loss"; exit_price = pos["sl"]

            # ── TP hit ────────────────────────────────────────────────────────
            elif side == "long"  and price >= pos["tp"]:
                reason = "take_profit"; exit_price = pos["tp"]
            elif side == "short" and price <= pos["tp"]:
                reason = "take_profit"; exit_price = pos["tp"]

            # ── Partial TP stage 1 (40%): SL → breakeven ──────────────────
            if reason is None and not pos.get("partial1_taken"):
                if side == "long"  and price >= pos["partial_tp1"]:
                    pos["partial1_taken"] = True
                    pos["sl"] = entry
                    changed = True
                    self._log(f"{sym}: PartialTP1 touché → SL breakeven")
                elif side == "short" and price <= pos["partial_tp1"]:
                    pos["partial1_taken"] = True
                    pos["sl"] = entry
                    changed = True
                    self._log(f"{sym}: PartialTP1 touché → SL breakeven")

            # ── Partial TP stage 2 (70%): SL → lock profit ────────────────
            if reason is None and pos.get("partial1_taken") and not pos.get("partial2_taken"):
                lock = PARTIAL_TP_LOCK * abs(pos["sl_orig"] - entry)
                if side == "long"  and price >= pos["partial_tp2"]:
                    pos["partial2_taken"] = True
                    pos["sl"] = round(entry + lock, 6)
                    changed = True
                    self._log(f"{sym}: PartialTP2 touché → profit verrouillé")
                elif side == "short" and price <= pos["partial_tp2"]:
                    pos["partial2_taken"] = True
                    pos["sl"] = round(entry - lock, 6)
                    changed = True
                    self._log(f"{sym}: PartialTP2 touché → profit verrouillé")

            if reason:
                self._close_position(sym, exit_price, reason)
                changed = True
                await self._bcast({
                    "type": "trade_close",
                    "data": self.state["closed_trades"][-1] if self.state["closed_trades"] else {}
                })

        if changed:
            save_state(self.state)
        else:
            save_state(self.state)   # always save price updates

        await self._bcast({"type": "state", "data": self._public_state()})

    # ── Position management ────────────────────────────────────────────────────

    def _open_position(self, sig: dict):
        sym   = sig["symbol"]
        entry = sig["entry"]
        tp    = sig["tp"]
        sl    = sig["sl"]
        action = sig["action"]
        side   = "long" if action == "BUY" else "short"

        tp_pct = abs(tp - entry) / entry
        partial_tp1_price = (
            entry * (1 + tp_pct * 0.40) if side == "long"
            else entry * (1 - tp_pct * 0.40)
        )
        partial_tp2_price = (
            entry * (1 + tp_pct * 0.70) if side == "long"
            else entry * (1 - tp_pct * 0.70)
        )

        pos = {
            "symbol":        sym,
            "sym_key":       sig.get("sym_key", sym.replace("/USDT", "-USD")),
            "action":        action,
            "entry":         entry,
            "current_price": entry,
            "sl":            sl,
            "sl_orig":       sl,
            "tp":            tp,
            "partial_tp1":   round(partial_tp1_price, 6),
            "partial_tp2":   round(partial_tp2_price, 6),
            "partial1_taken": False,
            "partial2_taken": False,
            "risk_eur":      sig["risk_eur"],
            "score":         sig["score"],
            "filters":       sig["filters"],
            "leverage":      sig["leverage"],
            "adx":           sig["adx"],
            "adx_boosted":   sig.get("adx_boosted", False),
            "unrealized_pnl": 0.0,
            "opened_at":     datetime.now(timezone.utc).isoformat(),
        }
        self.state["positions"][sym] = pos
        self._log(
            f"ENTRÉE {action} {sym} @ {entry:.4f} — "
            f"SL {sl:.4f} | TP {tp:.4f} | "
            f"Risque {sig['risk_eur']:.1f}€ | Score {sig['score']}"
        )

    def _close_position(self, sym: str, exit_price: float, reason: str):
        pos = self.state["positions"].pop(sym, None)
        if pos is None:
            return

        side   = "long" if pos["action"] == "BUY" else "short"
        entry  = pos["entry"]
        sl_dist = abs(pos["sl_orig"] - entry)

        if sl_dist > 0:
            raw_pnl  = (exit_price - entry) if side == "long" else (entry - exit_price)
            pnl_eur  = round(pos["risk_eur"] * raw_pnl / sl_dist, 2)
            pnl_pct  = round(raw_pnl / entry * 100, 2)
        else:
            pnl_eur = 0.0
            pnl_pct = 0.0

        old_equity = self.state["equity"]
        self.state["equity"] = round(old_equity + pnl_eur, 2)

        trade = {
            **pos,
            "exit_price": exit_price,
            "pnl":        pnl_eur,
            "pnl_pct":    pnl_pct,
            "reason":     reason,
            "closed_at":  datetime.now(timezone.utc).isoformat(),
        }
        self.state["closed_trades"].append(trade)

        emoji = "✅" if pnl_eur > 0 else "❌"
        self._log(
            f"{emoji} SORTIE {pos['action']} {sym} @ {exit_price:.4f} "
            f"({reason}) → {'+' if pnl_eur >= 0 else ''}{pnl_eur:.2f}€ "
            f"({'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%) | "
            f"Equity: {old_equity:.0f}€ → {self.state['equity']:.0f}€",
            "info" if pnl_eur > 0 else "warning"
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _daily_loss_hit(self) -> bool:
        today = str(datetime.now(timezone.utc).date())
        if self.state.get("daily_date") != today:
            self.state["daily_date"] = today
            self.state["daily_equity_start"] = self.state["equity"]
        start = self.state.get("daily_equity_start", self.capital)
        if start <= 0:
            return False
        return (self.state["equity"] - start) / start < -DAILY_LOSS_LIMIT

    def _public_state(self) -> dict:
        """Lightweight state dict for WebSocket broadcast."""
        trades = self.state.get("closed_trades", [])
        equity = self.state.get("equity", self.capital)
        total_pnl = equity - self.capital
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        open_pnl = sum(
            p.get("unrealized_pnl", 0) for p in self.state["positions"].values()
        )
        return {
            "bot_running":   self.running,
            "equity":        round(equity, 2),
            "capital":       self.capital,
            "total_pnl":     round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / self.capital * 100, 2) if self.capital else 0,
            "open_pnl":      round(open_pnl, 2),
            "positions":     self.state["positions"],
            "positions_count": len(self.state["positions"]),
            "closed_trades": len(trades),
            "win_rate":      round(wins / len(trades) * 100, 1) if trades else 0,
            "recent_trades": sorted(trades, key=lambda t: t.get("closed_at", ""), reverse=True)[:15],
            "last_scan":     self.state.get("last_scan"),
            "scan_count":    self.state.get("scan_count", 0),
            "last_scan_ts":  self.state.get("last_scan_ts"),
            "next_scan_ts":  self.state.get("next_scan_ts"),
            "log":           self.state.get("log", [])[-30:],
            "daily_loss_hit": self._daily_loss_hit(),
        }

    def get_state(self) -> dict:
        return self._public_state()
