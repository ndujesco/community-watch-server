"""System status & cross-site overview endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from .. import db
from ..models import Classification
from ..realtime import manager
from ..serialize import jsonify

router = APIRouter()

_RANK = {"safe": 0, "watch": 1, "warning": 2, "emergency": 3}


@router.get("/health")
async def health():
    await db.get_database().command("ping")
    return {"status": "ok", "service": "floodwatch-api", "ws_clients": manager.count}


@router.get("/overview")
async def overview():
    """Headline numbers for the dashboard top bar and summary cards."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    online_window = now - timedelta(minutes=15)

    total_stations = await db.stations().count_documents({})
    online_stations = await db.stations().count_documents(
        {"last_seen": {"$gte": online_window}}
    )
    total_sites = await db.sites().count_documents({})
    active_alerts = await db.alerts().count_documents(
        {"acknowledged": False, "level": {"$in": ["warning", "emergency"]}}
    )

    # Worst current classification across all sites' latest readings.
    sites = await db.sites().find({}).to_list(length=None)
    worst = Classification.safe.value
    site_states = []
    for site in sites:
        latest = await (
            db.readings()
            .find({"site_id": site["site_id"]})
            .sort("ts", -1)
            .limit(1)
            .to_list(length=1)
        )
        if latest:
            r = latest[0]
            level = r["classification"]
            if _RANK[level] > _RANK[worst]:
                worst = level
            site_states.append({
                "site_id": site["site_id"],
                "name": site["name"],
                "area": site["area"],
                "lat": site["lat"],
                "lng": site["lng"],
                "classification": level,
                "water_level": r["water_level"],
                "capacity_pct": r["capacity_pct"],
                "tflood": r["tflood"],
                "rainfall_rate": r["rainfall_rate"],
                "dhdt": r["dhdt"],
                "ts": r["ts"],
            })

    return jsonify({
        "now": now,
        "overall_classification": worst,
        "total_sites": total_sites,
        "total_stations": total_stations,
        "online_stations": online_stations,
        "active_alerts": active_alerts,
        "ws_clients": manager.count,
        "sites": site_states,
    })
