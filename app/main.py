"""FloodWatch FastAPI application entry point (report Section 3.6.1)."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, db, logstream, simulator
from .config import get_settings
from .realtime import manager
from .routes import api_router

# Plain "%(message)s" — the reading-log blocks in services.py already carry
# their own structure, so a logger-name/timestamp prefix would just clutter
# `render logs --tail`.
logging.basicConfig(level=logging.INFO, format="%(message)s")

# Also fan the same ingestion-log messages out to GET /api/logs (a live,
# terminal-styled view of them in the browser) in addition to stdout.
logstream.install("floodwatch.ingest", channel="readings")
logstream.install("floodwatch.raw", channel="raw")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await simulator.start()
    try:
        yield
    finally:
        await simulator.stop()
        await db.disconnect()


app = FastAPI(
    title="FloodWatch API",
    description="IoT-Based Flood Early-Warning System — backend service.",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
async def root():
    return {
        "service": "FloodWatch API",
        "version": __version__,
        "docs": "/docs",
        "websocket": "/ws",
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "connected", "data": {"clients": manager.count}})
        while True:
            # Keep the socket alive; clients may send pings we simply echo.
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if msg == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)
