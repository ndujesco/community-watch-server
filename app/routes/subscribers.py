"""Email alert subscriber management (report Section 3.6.5)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pymongo.errors import DuplicateKeyError

from .. import db
from ..models import Subscriber
from ..serialize import jsonify

router = APIRouter()


@router.get("")
async def list_subscribers(site_id: str | None = None):
    query = {"site_id": site_id} if site_id else {}
    docs = await db.subscribers().find(query).sort("created_at", -1).to_list(length=None)
    return jsonify(docs)


@router.post("", status_code=201)
async def add_subscriber(sub: Subscriber):
    doc = sub.model_dump()
    doc["subscriber_id"] = f"SUB-{uuid.uuid4().hex[:8].upper()}"
    doc["created_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        await db.subscribers().insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "A subscriber with this email address already exists")
    return jsonify(doc)


@router.delete("/{subscriber_id}", status_code=204)
async def delete_subscriber(subscriber_id: str):
    res = await db.subscribers().delete_one({"subscriber_id": subscriber_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Subscriber not found")
    return None
