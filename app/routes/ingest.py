"""Sensor data ingestion endpoint.

This is the entry point used by the RTL-SDR receiver's forwarding script
(report Section 3.5.2): decoded 433 MHz packets are POSTed here as JSON.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models import IngestPacket
from ..serialize import jsonify
from ..services import process_packet

router = APIRouter()


@router.post("/ingest", status_code=201)
async def ingest(packet: IngestPacket):
    try:
        reading = await process_packet(packet)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return jsonify(reading)
