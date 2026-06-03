"""Reading query endpoints: latest snapshot, history, and chart series."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from .. import db
from ..serialize import jsonify

router = APIRouter()


def _parse_range(hours: int | None, frm: str | None, to: str | None):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    end = datetime.fromisoformat(to.replace("Z", "")) if to else now
    if frm:
        start = datetime.fromisoformat(frm.replace("Z", ""))
    else:
        start = end - timedelta(hours=hours or 24)
    return start, end


@router.get("/latest")
async def latest(station_id: str | None = None, site_id: str | None = None):
    """Latest reading per station (optionally filtered)."""
    match: dict = {}
    if station_id:
        match["station_id"] = station_id
    if site_id:
        match["site_id"] = site_id
    station_ids = await db.readings().distinct("station_id", match)
    out = []
    for sid in station_ids:
        doc = await (
            db.readings().find({"station_id": sid}).sort("ts", -1).limit(1).to_list(length=1)
        )
        if doc:
            out.append(doc[0])
    out.sort(key=lambda d: d["station_id"])
    return jsonify(out)


@router.get("")
async def history(
    station_id: str | None = None,
    site_id: str | None = None,
    hours: int | None = None,
    frm: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    limit: int = Query(default=500, le=5000),
):
    start, end = _parse_range(hours, frm, to)
    query: dict = {"ts": {"$gte": start, "$lte": end}}
    if station_id:
        query["station_id"] = station_id
    if site_id:
        query["site_id"] = site_id
    docs = await (
        db.readings().find(query).sort("ts", -1).limit(limit).to_list(length=limit)
    )
    docs.reverse()
    return jsonify(docs)


@router.get("/timeseries")
async def timeseries(
    station_id: str | None = None,
    site_id: str | None = None,
    hours: int = 24,
    points: int = Query(default=120, le=500),
):
    """Down-sampled series for charts: evenly spaced buckets, averaged."""
    start, end = _parse_range(hours, None, None)
    query: dict = {"ts": {"$gte": start, "$lte": end}}
    if station_id:
        query["station_id"] = station_id
    if site_id:
        query["site_id"] = site_id

    span = max((end - start).total_seconds(), 1)
    bucket = span / points

    pipeline = [
        {"$match": query},
        {"$addFields": {
            "_bucket": {
                "$floor": {
                    "$divide": [
                        {"$subtract": ["$ts", start]},
                        bucket * 1000,
                    ]
                }
            }
        }},
        {"$group": {
            "_id": "$_bucket",
            "ts": {"$first": "$ts"},
            "water_level": {"$avg": "$water_level"},
            "rainfall_rate": {"$avg": "$rainfall_rate"},
            "cumulative_rain": {"$max": "$cumulative_rain"},
            "dhdt": {"$avg": "$dhdt"},
            "tflood": {"$avg": "$tflood"},
            "temperature": {"$avg": "$temperature"},
            "pressure": {"$avg": "$pressure"},
            "humidity": {"$avg": "$humidity"},
            "capacity_pct": {"$avg": "$capacity_pct"},
        }},
        {"$sort": {"_id": 1}},
    ]
    cursor = await db.readings().aggregate(pipeline)
    docs = await cursor.to_list(length=None)
    for d in docs:
        d.pop("_id", None)
        for k in ("water_level", "rainfall_rate", "dhdt", "temperature",
                  "pressure", "humidity", "capacity_pct"):
            if d.get(k) is not None:
                d[k] = round(d[k], 3)
    return jsonify(docs)
