"""Sensor station endpoints (with each station's latest reading attached)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from .. import db
from ..models import StationUpdate
from ..serialize import jsonify

router = APIRouter()


async def _attach_latest(station: dict) -> dict:
    latest = await (
        db.readings()
        .find({"station_id": station["station_id"]})
        .sort("ts", -1)
        .limit(1)
        .to_list(length=1)
    )
    station = dict(station)
    station["latest"] = latest[0] if latest else None
    # Derive an effective online/offline from last_seen recency.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    last_seen = station.get("last_seen")
    if last_seen is not None and last_seen >= now - timedelta(minutes=15):
        station["status"] = "online"
    elif station.get("status") != "maintenance":
        station["status"] = "offline"
    return station


@router.get("")
async def list_stations(site_id: str | None = None):
    query = {"site_id": site_id} if site_id else {}
    docs = await db.stations().find(query).sort("station_id", 1).to_list(length=None)
    docs = [await _attach_latest(d) for d in docs]
    return jsonify(docs)


@router.get("/{station_id}")
async def get_station(station_id: str):
    doc = await db.stations().find_one({"station_id": station_id})
    if not doc:
        raise HTTPException(404, "Station not found")
    return jsonify(await _attach_latest(doc))


@router.patch("/{station_id}")
async def update_station(station_id: str, update: StationUpdate):
    """Admin provisioning — rename a station, mark it under maintenance, etc."""
    patch = update.model_dump(exclude_none=True)
    if "status" in patch:
        patch["status"] = update.status.value  # type: ignore[union-attr]
    if not patch:
        raise HTTPException(400, "No fields to update")
    if "site_id" in patch:
        site = await db.sites().find_one({"site_id": patch["site_id"]})
        if not site:
            raise HTTPException(404, f"Site not found: {patch['site_id']}")
    res = await db.stations().update_one({"station_id": station_id}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "Station not found")
    doc = await db.stations().find_one({"station_id": station_id})
    return jsonify(await _attach_latest(doc))
