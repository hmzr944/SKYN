"""
SKYN v15 APEX — Dashboard Server
Run: uvicorn apex_server:app --host 0.0.0.0 --port 8765
"""

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apex_bot import ApexBot, load_state, save_state, STATE_FILE
from paper_test_v16 import run_full_backtest, CONFIGS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"

# ── Globals ───────────────────────────────────────────────────────────────────

_clients: Set[WebSocket] = set()
_bot: Optional[ApexBot]  = None
_jobs: dict              = {}   # job_id → {status, result, error, started_at}


# ── WebSocket broadcast ────────────────────────────────────────────────────────

async def _broadcast(payload: dict):
    dead = set()
    msg  = json.dumps(payload, default=str)
    for ws in list(_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _clients -= dead


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot
    _bot = ApexBot(capital=500.0, cfg_name="Premium", broadcast_fn=_broadcast)
    logger.info("APEX server started — bot ready (use /api/bot/start to activate)")
    yield
    if _bot:
        _bot.stop()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="SKYN v15 APEX", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

if DASHBOARD_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(DASHBOARD_DIR)), name="assets")


# ── Static / dashboard ────────────────────────────────────────────────────────

@app.get("/")
async def root():
    html = DASHBOARD_DIR / "index.html"
    if html.exists():
        return FileResponse(str(html))
    return JSONResponse({"error": "Dashboard not found. Run from profit-engine/backend/"}, 404)


# ── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    try:
        if _bot:
            await ws.send_text(json.dumps(
                {"type": "init", "data": _bot.get_state()}, default=str
            ))
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                # Handle ping
                if msg == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "heartbeat"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _clients.discard(ws)


# ── Bot control ───────────────────────────────────────────────────────────────

@app.post("/api/bot/start")
async def bot_start():
    if _bot and not _bot.running:
        await _bot.start()
    return {"status": "running", "state": _bot.get_state() if _bot else {}}


@app.post("/api/bot/stop")
async def bot_stop():
    if _bot:
        _bot.stop()
    return {"status": "stopped"}


@app.get("/api/bot/status")
async def bot_status():
    if not _bot:
        return {"error": "Bot not initialized"}
    return _bot.get_state()


# ── State / Portfolio ─────────────────────────────────────────────────────────

@app.get("/api/state")
async def get_state():
    return _bot.get_state() if _bot else {}


@app.get("/api/portfolio")
async def get_portfolio():
    if not _bot:
        return {}
    s = _bot.get_state()
    return {
        "capital_start":   _bot.capital,
        "equity":          s["equity"],
        "total_pnl":       s["total_pnl"],
        "total_pnl_pct":   s["total_pnl_pct"],
        "open_pnl":        s["open_pnl"],
        "positions_count": s["positions_count"],
        "closed_trades":   s["closed_trades"],
        "win_rate":        s["win_rate"],
        "positions":       s["positions"],
        "recent_trades":   s["recent_trades"],
    }


@app.delete("/api/portfolio/reset")
async def reset_portfolio():
    if not _bot:
        return {"error": "Bot not initialized"}
    _bot.stop()
    import time as _t; _t.sleep(0.5)
    from apex_bot import _default_state
    _bot.state = _default_state(_bot.capital)
    save_state(_bot.state)
    return {"status": "reset", "equity": _bot.capital}


# ── Manual position ────────────────────────────────────────────────────────────

class OpenPositionReq(BaseModel):
    symbol: str
    action: str
    entry: float
    sl: float
    tp: float
    risk_eur: float
    score: int
    filters: int
    leverage: int = 10
    adx: float = 0.0
    adx_boosted: bool = False
    sym_key: Optional[str] = None


class ClosePositionReq(BaseModel):
    symbol: str
    exit_price: float
    reason: str = "manual"


@app.post("/api/position/open")
async def open_position(req: OpenPositionReq):
    if not _bot:
        return JSONResponse({"error": "Bot not initialized"}, 500)
    if req.symbol in _bot.state["positions"]:
        return JSONResponse({"error": f"Position déjà ouverte: {req.symbol}"}, 400)
    if len(_bot.state["positions"]) >= 5:
        return JSONResponse({"error": "Max 5 positions simultanées"}, 400)

    sig = req.model_dump()
    if not sig.get("sym_key"):
        sig["sym_key"] = req.symbol.replace("/USDT", "-USD")
    _bot._open_position(sig)
    save_state(_bot.state)
    await _broadcast({"type": "trade_open", "data": _bot.state["positions"][req.symbol]})
    await _broadcast({"type": "state", "data": _bot.get_state()})
    return {"status": "opened", "position": _bot.state["positions"][req.symbol]}


@app.post("/api/position/close")
async def close_position(req: ClosePositionReq):
    if not _bot:
        return JSONResponse({"error": "Bot not initialized"}, 500)
    if req.symbol not in _bot.state["positions"]:
        return JSONResponse({"error": f"Pas de position ouverte: {req.symbol}"}, 404)
    _bot._close_position(req.symbol, req.exit_price, req.reason)
    save_state(_bot.state)
    trade = _bot.state["closed_trades"][-1] if _bot.state["closed_trades"] else {}
    await _broadcast({"type": "trade_close", "data": trade})
    await _broadcast({"type": "state", "data": _bot.get_state()})
    return {"status": "closed", "trade": trade}


# ── Backtest jobs ─────────────────────────────────────────────────────────────

class BacktestReq(BaseModel):
    cfg_name: Optional[str] = "Selectif"


@app.post("/api/backtest/run")
async def run_backtest(req: BacktestReq, bg_tasks=None):
    job_id = f"bt_{int(time.time())}"
    _jobs[job_id] = {"status": "running", "result": None, "error": None, "started_at": time.time()}

    def _run():
        try:
            result = run_full_backtest(cfg_name=req.cfg_name)
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result
        except Exception as e:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
            logger.exception("Backtest failed")

    import threading
    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@app.get("/api/backtest/status/{job_id}")
async def backtest_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, 404)
    return {
        "job_id":    job_id,
        "status":    job["status"],
        "elapsed_s": round(time.time() - job["started_at"], 1),
        "result":    job["result"] if job["status"] == "done" else None,
        "error":     job["error"],
    }


@app.get("/api/backtest/configs")
async def get_configs():
    return {"configs": [
        {"name": c["name"], "score_min": c["score_min"],
         "risk_pct": c["risk_pct"], "sq_bars": c["sq_bars"]}
        for c in CONFIGS
    ]}


# ── Scanner (manual one-shot) ─────────────────────────────────────────────────

class ScanReq(BaseModel):
    cfg_name: Optional[str] = "Selectif"
    capital: Optional[float] = 500.0


@app.post("/api/scan/run")
async def run_scan(req: ScanReq):
    job_id = f"sc_{int(time.time())}"
    _jobs[job_id] = {"status": "running", "result": None, "error": None, "started_at": time.time()}

    def _run():
        from paper_test_v16 import scan_live_signals
        try:
            result = scan_live_signals(capital=req.capital, cfg_name=req.cfg_name)
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result
        except Exception as e:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
            logger.exception("Scan failed")

    import threading
    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@app.get("/api/scan/status/{job_id}")
async def scan_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, 404)
    return {
        "job_id":    job_id,
        "status":    job["status"],
        "elapsed_s": round(time.time() - job["started_at"], 1),
        "result":    job["result"] if job["status"] == "done" else None,
        "error":     job["error"],
    }


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    from datetime import datetime, timezone
    return {
        "status":      "ok",
        "version":     "v15-APEX",
        "bot_running": _bot.running if _bot else False,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    uvicorn.run("apex_server:app", host="0.0.0.0", port=8765, reload=False)
