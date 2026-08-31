"""Live terminal-style viewer for the POST /api/v1/readings log stream.

GET /api/logs         -> a self-contained HTML page styled like a terminal
GET /api/logs/stream   -> the underlying Server-Sent Events feed it consumes

No auth, no CORS concerns: this is meant to be opened directly against the
backend's own URL (e.g. https://community-watch-server.onrender.com/api/logs)
rather than embedded in the React frontend.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse

from .. import logstream

router = APIRouter()

_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>FloodWatch — live log</title>
<style>
  html, body { height: 100%; margin: 0; background: #0d0f12; }
  body {
    font-family: "SF Mono", Menlo, Consolas, "Courier New", monospace;
    display: flex; flex-direction: column;
  }
  .titlebar {
    display: flex; align-items: center; gap: 8px;
    padding: 10px 14px; background: #1b1f24; border-bottom: 1px solid #2a2f36;
    flex-shrink: 0;
  }
  .dot { width: 11px; height: 11px; border-radius: 50%; }
  .dot.red { background: #ff5f57; }
  .dot.yellow { background: #febc2e; }
  .dot.green { background: #28c840; }
  .titlebar span.label {
    margin-left: 8px; color: #9aa4af; font-size: 12.5px;
  }
  .status {
    margin-left: auto; font-size: 11.5px; color: #6b7683;
  }
  .status.live { color: #28c840; }
  #screen {
    flex: 1; overflow-y: auto; padding: 14px 18px;
    color: #d7e0e8; font-size: 13px; line-height: 1.5;
    white-space: pre-wrap; word-break: break-word;
  }
  .line { opacity: 0; animation: fadein 0.15s ease-out forwards; }
  @keyframes fadein { to { opacity: 1; } }
  .empty { color: #5c6673; font-style: italic; }
  #cursor {
    display: inline-block; width: 8px; height: 15px;
    background: #28c840; margin-left: 2px; vertical-align: text-bottom;
    animation: blink 1s step-start infinite;
  }
  @keyframes blink { 50% { opacity: 0; } }
</style>
</head>
<body>
  <div class="titlebar">
    <div class="dot red"></div>
    <div class="dot yellow"></div>
    <div class="dot green"></div>
    <span class="label">floodwatch@render — POST /api/v1/readings</span>
    <span class="status" id="status">connecting…</span>
  </div>
  <div id="screen"><span class="empty">Waiting for the first sensor reading…</span><span id="cursor"></span></div>
<script>
const screen = document.getElementById('screen');
const statusEl = document.getElementById('status');
const cursor = document.getElementById('cursor');
let gotAny = false;

function appendLine(text) {
  if (!gotAny) {
    screen.innerHTML = '';
    gotAny = true;
  }
  const el = document.createElement('div');
  el.className = 'line';
  el.textContent = text;
  screen.appendChild(el);
  screen.appendChild(cursor);
  screen.scrollTop = screen.scrollHeight;
}

function connect() {
  const es = new EventSource('/api/logs/stream');
  es.onopen = () => { statusEl.textContent = '● live'; statusEl.className = 'status live'; };
  es.onmessage = (e) => appendLine(JSON.parse(e.data));
  es.onerror = () => {
    statusEl.textContent = 'reconnecting…';
    statusEl.className = 'status';
    es.close();
    setTimeout(connect, 2000);
  };
}
connect();
</script>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse)
async def logs_page():
    return _PAGE


@router.get("/stream")
async def logs_stream():
    async def event_source():
        for line in logstream.snapshot():
            yield f"data: {json.dumps(line)}\n\n"
        q = logstream.subscribe()
        try:
            while True:
                line = await q.get()
                yield f"data: {json.dumps(line)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            logstream.unsubscribe(q)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
