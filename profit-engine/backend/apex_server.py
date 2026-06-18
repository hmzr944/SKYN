"""
SKYN v15 APEX — Dashboard Server
FastAPI server exposing backtest, scanner, and paper-portfolio endpoints.
Run: uvicorn apex_server:app --host 0.0.0.0 --port 8765 --reload
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Import v15 strategy ───────────────────────────────────────────────────────
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paper_test_v15 import (
    run_full_backtest,
    scan_live_signals,
    CONFIGS,
    SYMBOLS_YF,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent / "apex_state.json"
DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"


# ── State persistence ─────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "capital": 500.0,
        "equity": 500.0,
        "positions": {},
        "closed_trades": [],
        "last_scan": None,
        "last_backtest": None,
    }


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, default=str, indent=2))


# ── Background job tracking ───────────────────────────────────────────────────

_jobs: dict = {}   # job_id -> {status, result, error, started_at}


def _new_job(job_id: str):
    _jobs[job_id] = {
        "status": "running",
        "result": None,
        "error": None,
        "started_at": time.time(),
    }


def _finish_job(job_id: str, result: dict):
    if job_id in _jobs:
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["result"] = result


def _fail_job(job_id: str, error: str):
    if job_id in _jobs:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"] = error


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="SKYN v15 APEX Dashboard", version="15.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Static files ──────────────────────────────────────────────────────────────

if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")


@app.get("/")
async def serve_dashboard():
    html_path = DASHBOARD_DIR / "index.html"
    if html_path.exists():
        return FileResponse(str(html_path))
    return JSONResponse({"error": "Dashboard not found", "path": str(html_path)}, status_code=404)


# ── Backtest endpoints ────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    cfg_name: Optional[str] = "Optimal"
    capital: Optional[float] = 500.0


@app.post("/api/backtest/run")
async def start_backtest(req: BacktestRequest, bg: BackgroundTasks):
    job_id = f"bt_{int(time.time())}"
    _new_job(job_id)

    def _run():
        try:
            result = run_full_backtest(cfg_name=req.cfg_name)
            state = _load_state()
            state["last_backtest"] = {
                "cfg_name": req.cfg_name,
                "ran_at": datetime.now(timezone.utc).isoformat(),
                "metrics": result.get("metrics", {}),
            }
            _save_state(state)
            _finish_job(job_id, result)
        except Exception as e:
            _fail_job(job_id, str(e))
            logger.exception("Backtest failed")

    bg.add_task(_run)
    return {"job_id": job_id, "status": "running"}


@app.get("/api/backtest/status/{job_id}")
async def backtest_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "elapsed_s": round(time.time() - job["started_at"], 1),
        "result": job["result"] if job["status"] == "done" else None,
        "error": job["error"],
    }


@app.get("/api/backtest/configs")
async def get_configs():
    return {"configs": [{"name": c["name"], "score_min": c["score_min"],
                         "risk_pct": c["risk_pct"], "sq_bars": c["sq_bars"]} for c in CONFIGS]}


# ── Scanner endpoints ─────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    cfg_name: Optional[str] = "Selectif"
    capital: Optional[float] = 500.0


@app.post("/api/scan/run")
async def start_scan(req: ScanRequest, bg: BackgroundTasks):
    job_id = f"sc_{int(time.time())}"
    _new_job(job_id)

    def _run():
        try:
            result = scan_live_signals(capital=req.capital, cfg_name=req.cfg_name)
            state = _load_state()
            state["last_scan"] = result
            _save_state(state)
            _finish_job(job_id, result)
        except Exception as e:
            _fail_job(job_id, str(e))
            logger.exception("Scan failed")

    bg.add_task(_run)
    return {"job_id": job_id, "status": "running"}


@app.get("/api/scan/status/{job_id}")
async def scan_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "elapsed_s": round(time.time() - job["started_at"], 1),
        "result": job["result"] if job["status"] == "done" else None,
        "error": job["error"],
    }


@app.get("/api/scan/last")
async def last_scan():
    state = _load_state()
    return state.get("last_scan") or {"error": "No scan yet"}


# ── Portfolio endpoints ───────────────────────────────────────────────────────

@app.get("/api/portfolio")
async def get_portfolio():
    state = _load_state()
    positions = state.get("positions", {})
    closed = state.get("closed_trades", [])

    total_pnl = sum(t.get("pnl", 0) for t in closed)
    open_pnl = 0.0
    for pos in positions.values():
        open_pnl += pos.get("unrealized_pnl", 0.0)

    wins = sum(1 for t in closed if t.get("pnl", 0) > 0)
    total_closed = len(closed)

    return {
        "capital_start": state.get("capital", 500.0),
        "equity": state.get("equity", 500.0),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / state.get("capital", 500.0) * 100, 2),
        "open_pnl": round(open_pnl, 2),
        "positions_count": len(positions),
        "closed_trades": total_closed,
        "win_rate": round(wins / total_closed * 100, 1) if total_closed > 0 else 0,
        "positions": positions,
        "recent_trades": sorted(closed, key=lambda t: t.get("closed_at", ""), reverse=True)[:20],
    }


class OpenPositionRequest(BaseModel):
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


@app.post("/api/position/open")
async def open_position(req: OpenPositionRequest):
    state = _load_state()
    positions = state.get("positions", {})

    if req.symbol in positions:
        raise HTTPException(400, f"Position already open for {req.symbol}")

    if len(positions) >= 5:
        raise HTTPException(400, "Max 5 positions simultanées")

    tp_pct = abs(req.tp - req.entry) / req.entry
    sl_pct_actual = abs(req.sl - req.entry) / req.entry
    partial_tp1 = req.entry * (1 + tp_pct * 0.40) if req.action == "BUY" else req.entry * (1 - tp_pct * 0.40)
    partial_tp2 = req.entry * (1 + tp_pct * 0.70) if req.action == "BUY" else req.entry * (1 - tp_pct * 0.70)

    positions[req.symbol] = {
        "symbol": req.symbol,
        "action": req.action,
        "entry": req.entry,
        "current_price": req.entry,
        "sl": req.sl,
        "sl_orig": req.sl,
        "tp": req.tp,
        "partial_tp1": round(partial_tp1, 6),
        "partial_tp2": round(partial_tp2, 6),
        "partial1_taken": False,
        "partial2_taken": False,
        "risk_eur": req.risk_eur,
        "score": req.score,
        "filters": req.filters,
        "leverage": req.leverage,
        "adx": req.adx,
        "adx_boosted": req.adx_boosted,
        "unrealized_pnl": 0.0,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }

    state["positions"] = positions
    _save_state(state)
    return {"status": "opened", "position": positions[req.symbol]}


class ClosePositionRequest(BaseModel):
    symbol: str
    exit_price: float
    reason: str = "manual"


@app.post("/api/position/close")
async def close_position(req: ClosePositionRequest):
    state = _load_state()
    positions = state.get("positions", {})

    if req.symbol not in positions:
        raise HTTPException(404, f"No open position for {req.symbol}")

    pos = positions.pop(req.symbol)
    entry = pos["entry"]
    side  = "long" if pos["action"] == "BUY" else "short"
    risk  = pos["risk_eur"]

    if side == "long":
        pnl_pct = (req.exit_price - entry) / entry
    else:
        pnl_pct = (entry - req.exit_price) / entry

    sl_pct_actual = abs(pos["sl_orig"] - entry) / entry
    pnl_eur = risk * (pnl_pct / sl_pct_actual) if sl_pct_actual > 0 else 0.0

    trade = {
        **pos,
        "exit_price": req.exit_price,
        "pnl": round(pnl_eur, 2),
        "pnl_pct": round(pnl_pct * 100, 2),
        "reason": req.reason,
        "closed_at": datetime.now(timezone.utc).isoformat(),
    }

    state["positions"] = positions
    state["closed_trades"] = state.get("closed_trades", []) + [trade]
    state["equity"] = round(state.get("equity", 500.0) + pnl_eur, 2)
    _save_state(state)

    return {"status": "closed", "trade": trade}


@app.delete("/api/portfolio/reset")
async def reset_portfolio():
    state = {
        "capital": 500.0,
        "equity": 500.0,
        "positions": {},
        "closed_trades": [],
        "last_scan": None,
        "last_backtest": None,
    }
    _save_state(state)
    return {"status": "reset"}


# ── System ────────────────────────────────────────────────────────────────────

@app.get("/api/symbols")
async def get_symbols():
    return {"symbols": SYMBOLS_YF}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "v15-APEX",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_jobs": sum(1 for j in _jobs.values() if j["status"] == "running"),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("apex_server:app", host="0.0.0.0", port=8765, reload=True)
