"""In-memory log buffer + fan-out, backing the live /api/logs terminal view.

A logging.Handler attached to the ingestion logger (services.py) both keeps a
bounded backlog (so a fresh page load isn't empty) and pushes new lines to
every connected SSE client in real time. Process-local by design: Render's
free tier runs a single instance, and this is a debugging convenience, not a
durable log store (Render's own log retention is that).
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque

_BUFFER_MAXLEN = 500
_buffer: deque[str] = deque(maxlen=_BUFFER_MAXLEN)
_subscribers: set[asyncio.Queue] = set()


class _BroadcastHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            return
        _buffer.append(msg)
        for q in list(_subscribers):
            q.put_nowait(msg)


def install(logger_name: str = "floodwatch.ingest") -> None:
    handler = _BroadcastHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger(logger_name).addHandler(handler)


def snapshot() -> list[str]:
    return list(_buffer)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)
