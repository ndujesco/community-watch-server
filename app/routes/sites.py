"""Site (deployment location) endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db
from ..models import SiteUpdate
from ..serialize import jsonify

router = APIRouter()


@router.get("")
async def list_sites():
    docs = await db.sites().find({}).sort("site_id", 1).to_list(length=None)
    return jsonify(docs)


@router.get("/{site_id}")
async def get_site(site_id: str):
    doc = await db.sites().find_one({"site_id": site_id})
    if not doc:
        raise HTTPException(404, "Site not found")
    return jsonify(doc)


@router.patch("/{site_id}")
async def update_site(site_id: str, update: SiteUpdate):
    patch = {k: v for k, v in update.model_dump(exclude_none=True).items()}
    if "thresholds" in patch and patch["thresholds"] is not None:
        patch["thresholds"] = update.thresholds.model_dump()  # type: ignore[union-attr]
    if not patch:
        raise HTTPException(400, "No fields to update")
    res = await db.sites().update_one({"site_id": site_id}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "Site not found")
    doc = await db.sites().find_one({"site_id": site_id})
    return jsonify(doc)
