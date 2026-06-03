"""Alert log endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..models import AckRequest
from ..realtime import manager
from ..serialize import jsonify

router = APIRouter()


@router.get("")
async def list_alerts(
    site_id: str | None = None,
    level: str | None = None,
    acknowledged: bool | None = None,
    limit: int = Query(default=100, le=1000),
):
    query: dict = {}
    if site_id:
        query["site_id"] = site_id
    if level:
        query["level"] = level
    if acknowledged is not None:
        query["acknowledged"] = acknowledged
    docs = await db.alerts().find(query).sort("ts", -1).limit(limit).to_list(length=limit)
    return jsonify(docs)


@router.get("/{alert_id}")
async def get_alert(alert_id: str):
    doc = await db.alerts().find_one({"alert_id": alert_id})
    if not doc:
        raise HTTPException(404, "Alert not found")
    return jsonify(doc)


@router.post("/{alert_id}/ack")
async def acknowledge(alert_id: str, req: AckRequest):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    res = await db.alerts().update_one(
        {"alert_id": alert_id},
        {"$set": {
            "acknowledged": True,
            "acknowledged_at": now,
            "acknowledged_by": req.acknowledged_by,
        }},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Alert not found")
    doc = await db.alerts().find_one({"alert_id": alert_id})
    await manager.broadcast({"type": "alert_ack", "data": jsonify(doc)})
    return jsonify(doc)
