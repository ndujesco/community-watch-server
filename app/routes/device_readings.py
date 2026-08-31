"""Hardware device ingestion endpoint (backend-api-spec.md).

This is the real ESP32 firmware's entry point — distinct from /api/ingest,
which is the decoded-RF-packet path used by the simulator. Auth is a
shared-secret header check (see Settings.device_api_keys); when no keys are
configured the check is a no-op so local/dev deployments work unmodified.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request

from ..config import get_settings
from ..models import DeviceReadingPacket
from ..services import process_device_reading

router = APIRouter()

raw_logger = logging.getLogger("floodwatch.raw")


def _check_device_key(x_device_key: str | None) -> None:
    valid_keys = get_settings().device_api_key_set
    if not valid_keys:
        return  # auth disabled: no keys configured
    if x_device_key is None or x_device_key not in valid_keys:
        raise HTTPException(401, "Invalid or missing X-Device-Key")


@router.post("/readings", status_code=200)
async def ingest_device_reading(
    request: Request,
    packet: DeviceReadingPacket,
    x_device_key: str | None = Header(default=None, alias="X-Device-Key"),
):
    _check_device_key(x_device_key)

    # Log the literal, unprocessed bytes the device sent -- before any
    # Pydantic parsing/coercion -- so a wiring/firmware bug that produces a
    # malformed or unexpected payload is still visible verbatim, not just
    # what the model happened to successfully extract from it.
    raw_body = await request.body()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    raw_logger.info("[%s] %s", ts, raw_body.decode("utf-8", errors="replace"))

    await process_device_reading(packet)
    return {"status": "ok"}
