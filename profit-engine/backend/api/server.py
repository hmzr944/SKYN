import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config
from engine.core import ProfitEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_clients: Set[WebSocket] = set()
_engine: ProfitEngine | None = None
_task = None


async def _broadcast(payload: dict):
    dead = set()
    msg = json.dumps(payload, default=str)
    for ws in _clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _clients -= dead


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine, _task
    _engine = ProfitEngine(config, broadcast_fn=_broadcast)
    _task = asyncio.create_task(_engine.run_loop(interval=60))
    yield
    if _engine:
        _engine.stop()
    if _task:
        _task.cancel()
    if _engine:
        await _engine.close()


app = FastAPI(title="Profit Engine", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/state")
async def state():
    return _engine.get_state() if _engine else {}


@app.get("/api/portfolio")
async def portfolio():
    return _engine.portfolio.to_dict() if _engine else {}


@app.post("/api/bot/start")
async def bot_start():
    global _task
    if _engine and not _engine.running:
        _task = asyncio.create_task(_engine.run_loop(interval=60))
    return {"status": "running"}


@app.post("/api/bot/stop")
async def bot_stop():
    if _engine:
        _engine.stop()
    return {"status": "stopped"}


class TradeReq(BaseModel):
    symbol: str
    action: str


@app.post("/api/trade")
async def manual_trade(req: TradeReq):
    if not _engine:
        return {"error": "Engine not running"}
    if req.action == "close" and req.symbol in _engine.portfolio.positions:
        pos = _engine.portfolio.positions[req.symbol]
        if pos.asset_type == "crypto":
            df = await _engine.crypto.fetch_ohlcv(req.symbol)
        else:
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, _engine.etf.fetch_ohlcv, req.symbol)
        if df is not None:
            price = float(df["close"].iloc[-1])
            trade = await _engine.orders.close_position(req.symbol, price, "manual")
            return trade.__dict__ if trade else {"error": "close failed"}
    return {"error": "invalid request"}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    try:
        if _engine:
            await ws.send_text(json.dumps({"type": "init", "data": _engine.get_state()}, default=str))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)


if __name__ == "__main__":
    uvicorn.run("server:app", host=config.api_host, port=config.api_port, reload=False)
