"""Live terminal-style viewers for the ingestion logs.

GET /api/logs           -> formatted per-reading summary (water level,
                            classification, sensor status, etc.)
GET /api/logs/stream     -> the SSE feed backing the page above
GET /api/logs/raw        -> the literal, unprocessed JSON body the device
                            POSTed, exactly as received, before any parsing
GET /api/logs/raw/stream -> the SSE feed backing the raw page

No auth, no CORS concerns: meant to be opened directly against the
backend's own URL rather than embedded in the React frontend.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse

from .. import logstream

router = APIRouter()


def _page(title: str, subtitle: str, stream_path: str, empty_text: str) -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>{title}</title>
<style>
  html, body {{ height: 100%; margin: 0; background: #0d0f12; }}
  body {{
    font-family: "SF Mono", Menlo, Consolas, "Courier New", monospace;
    display: flex; flex-direction: column;
  }}
  .titlebar {{
    display: flex; align-items: center; gap: 8px;
    padding: 10px 14px; background: #1b1f24; border-bottom: 1px solid #2a2f36;
    flex-shrink: 0;
  }}
  .dot {{ width: 11px; height: 11px; border-radius: 50%; }}
  .dot.red {{ background: #ff5f57; }}
  .dot.yellow {{ background: #febc2e; }}
  .dot.green {{ background: #28c840; }}
  .titlebar span.label {{
    margin-left: 8px; color: #9aa4af; font-size: 12.5px;
  }}
  .titlebar a {{
    margin-left: 10px; color: #6b7683; font-size: 11.5px; text-decoration: none;
  }}
  .titlebar a:hover {{ color: #d7e0e8; }}
  .status {{
    margin-left: auto; font-size: 11.5px; color: #6b7683;
  }}
  .status.live {{ color: #28c840; }}
  #screen {{
    flex: 1; overflow-y: auto; padding: 14px 18px;
    color: #d7e0e8; font-size: 13px; line-height: 1.5;
    white-space: pre-wrap; word-break: break-word;
  }}
  .line {{ opacity: 0; animation: fadein 0.15s ease-out forwards; }}
  @keyframes fadein {{ to {{ opacity: 1; }} }}
  .empty {{ color: #5c6673; font-style: italic; }}
  #cursor {{
    display: inline-block; width: 8px; height: 15px;
    background: #28c840; margin-left: 2px; vertical-align: text-bottom;
    animation: blink 1s step-start infinite;
  }}
  @keyframes blink {{ 50% {{ opacity: 0; }} }}
</style>
</head>
<body>
  <div class="titlebar">
    <div class="dot red"></div>
    <div class="dot yellow"></div>
    <div class="dot green"></div>
    <span class="label">{subtitle}</span>
    <a href="/api/logs">formatted</a>
    <a href="/api/logs/raw">raw</a>
    <span class="status" id="status">connecting…</span>
  </div>
  <div id="screen"><span class="empty">{empty_text}</span><span id="cursor"></span></div>
<script>
const screen = document.getElementById('screen');
const statusEl = document.getElementById('status');
const cursor = document.getElementById('cursor');
let gotAny = false;

function appendLine(text) {{
  if (!gotAny) {{
    screen.innerHTML = '';
    gotAny = true;
  }}
  const el = document.createElement('div');
  el.className = 'line';
  el.textContent = text;
  screen.appendChild(el);
  screen.appendChild(cursor);
  screen.scrollTop = screen.scrollHeight;
}}

function connect() {{
  const es = new EventSource('{stream_path}');
  es.onopen = () => {{ statusEl.textContent = '● live'; statusEl.className = 'status live'; }};
  es.onmessage = (e) => appendLine(JSON.parse(e.data));
  es.onerror = () => {{
    statusEl.textContent = 'reconnecting…';
    statusEl.className = 'status';
    es.close();
    setTimeout(connect, 2000);
  }};
}}
connect();
</script>
</body>
</html>
"""


def _stream(channel: str) -> StreamingResponse:
    async def event_source():
        for line in logstream.snapshot(channel):
            yield f"data: {json.dumps(line)}\n\n"
        q = logstream.subscribe(channel)
        try:
            while True:
                line = await q.get()
                yield f"data: {json.dumps(line)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            logstream.unsubscribe(channel, q)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("", response_class=HTMLResponse)
async def logs_page():
    return _page(
        "FloodWatch — live log",
        "floodwatch@render — POST /api/v1/readings",
        "/api/logs/stream",
        "Waiting for the first sensor reading…",
    )


@router.get("/stream")
async def logs_stream():
    return _stream("readings")


@router.get("/raw", response_class=HTMLResponse)
async def raw_logs_page():
    return _page(
        "FloodWatch — raw log",
        "floodwatch@render — raw POST body, unprocessed",
        "/api/logs/raw/stream",
        "Waiting for the first raw request body…",
    )


@router.get("/raw/stream")
async def raw_logs_stream():
    return _stream("raw")
