"""In-memory log buffers + fan-out, backing the live /api/logs terminal
views. Supports multiple independent named channels (e.g. "readings" for
the formatted per-reading summary, "raw" for the literal unprocessed
request body) so they can be viewed and streamed separately.

A logging.Handler attached to a given logger both keeps a bounded backlog
per channel (so a fresh page load isn't empty) and pushes new lines to
every connected SSE client on that channel in real time. Process-local by
design: Render's free tier runs a single instance, and this is a debugging
convenience, not a durable log store (Render's own log retention is that).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque

_BUFFER_MAXLEN = 500
_buffers: dict[str, deque] = defaultdict(lambda: deque(maxlen=_BUFFER_MAXLEN))
_subscribers: dict[str, set] = defaultdict(set)


class _BroadcastHandler(logging.Handler):
    def __init__(self, channel: str) -> None:
        super().__init__()
        self.channel = channel

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            return
        _buffers[self.channel].append(msg)
        for q in list(_subscribers[self.channel]):
            q.put_nowait(msg)


def install(logger_name: str, channel: str | None = None) -> None:
    handler = _BroadcastHandler(channel or logger_name)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger(logger_name).addHandler(handler)


def snapshot(channel: str) -> list[str]:
    return list(_buffers[channel])


def subscribe(channel: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers[channel].add(q)
    return q


def unsubscribe(channel: str, q: asyncio.Queue) -> None:
    _subscribers[channel].discard(q)
