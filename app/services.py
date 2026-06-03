"""Ingestion pipeline shared by the HTTP ingest endpoint and the simulator.

Given a decoded sensor packet, this:
  1. resolves the station and its site (for H_max, thresholds, drainage),
  2. derives the water level from the ultrasonic distance when needed,
  3. runs the flood engine (dH/dt, T_flood, classification, alpha),
  4. persists the reading and refreshes the site's learned alpha,
  5. raises an alert on a classification transition (with CAP + plain text),
  6. broadcasts the reading (and any alert) to WebSocket clients.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from . import db, engine
from .models import Classification, IngestPacket
from .realtime import manager
from .serialize import jsonify

# Severity ranking for transition detection / subscriber filtering.
_RANK = {
    Classification.safe: 0,
    Classification.watch: 1,
    Classification.warning: 2,
    Classification.emergency: 3,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _latest_reading(station_id: str) -> dict | None:
    cursor = db.readings().find({"station_id": station_id}).sort("ts", -1).limit(1)
    docs = await cursor.to_list(length=1)
    return docs[0] if docs else None


async def _smooth_alpha(site_id: str, current_alpha: float, new_estimate: float) -> float:
    """Exponential moving average so the learned coefficient adapts slowly."""
    blended = round(0.95 * current_alpha + 0.05 * new_estimate, 5)
    await db.sites().update_one({"site_id": site_id}, {"$set": {"alpha": blended}})
    return blended


async def process_packet(packet: IngestPacket, *, broadcast: bool = True) -> dict:
    station = await db.stations().find_one({"station_id": packet.station_id})
    if station is None:
        raise ValueError(f"Unknown station: {packet.station_id}")
    site = await db.sites().find_one({"site_id": station["site_id"]})
    if site is None:
        raise ValueError(f"Station {packet.station_id} has no site")

    hmax = float(site["channel_depth"])
    thresholds = site["thresholds"]
    ts = packet.ts or _utcnow()

    # Resolve water level H(t) = D - d(t) when only distance is supplied (3.2.2).
    if packet.water_level is not None:
        water_level = max(0.0, float(packet.water_level))
        distance = hmax - water_level
    else:
        distance = float(packet.distance if packet.distance is not None else hmax)
        water_level = max(0.0, hmax - distance)

    prev = await _latest_reading(packet.station_id)
    prev_level = float(prev["water_level"]) if prev else None
    prev_ts = prev["ts"] if prev else None
    prev_class = Classification(prev["classification"]) if prev else Classification.safe

    result = engine.evaluate(
        water_level=water_level,
        rainfall_rate=packet.rainfall_rate,
        hmax=hmax,
        prev_level=prev_level,
        ts=ts,
        prev_ts=prev_ts,
        baseline_drainage=float(site.get("baseline_drainage", 0.4)),
        thresholds=thresholds,
    )

    reading_doc = {
        "station_id": packet.station_id,
        "site_id": station["site_id"],
        "ts": ts,
        "water_level": round(water_level, 3),
        "distance": round(distance, 3),
        "rainfall_rate": round(packet.rainfall_rate, 2),
        "cumulative_rain": round(packet.cumulative_rain, 2),
        "temperature": round(packet.temperature, 2),
        "pressure": round(packet.pressure, 2),
        "humidity": round(packet.humidity, 1),
        "dhdt": result.dhdt,
        "tflood": result.tflood,
        "capacity_pct": result.capacity_pct,
        "classification": result.classification.value,
        "float_triggered": packet.float_triggered,
        "crc_valid": packet.crc_valid,
        "rssi": packet.rssi if packet.rssi is not None else station.get("rssi", -70.0),
    }
    insert = await db.readings().insert_one(reading_doc)
    reading_doc["_id"] = insert.inserted_id

    # Refresh learned site coefficient alpha.
    if result.alpha_estimate is not None:
        await _smooth_alpha(
            station["site_id"], float(site.get("alpha", 0.02)), result.alpha_estimate
        )

    # Update station telemetry.
    await db.stations().update_one(
        {"station_id": packet.station_id},
        {"$set": {
            "last_seen": ts,
            "status": "online",
            "rssi": reading_doc["rssi"],
        }},
    )

    alert_doc = None
    # Alert on an *escalation* of severity, or on return to safe from a higher state.
    new_rank = _RANK[result.classification]
    old_rank = _RANK[prev_class]
    escalated = new_rank > old_rank and new_rank >= _RANK[Classification.watch]
    recovered = new_rank == 0 and old_rank >= _RANK[Classification.warning]
    if escalated or recovered:
        alert_doc = await _create_alert(
            station=station,
            site=site,
            reading=reading_doc,
            level=result.classification,
            previous=prev_class,
            tflood=result.tflood,
        )

    if broadcast:
        await manager.broadcast({"type": "reading", "data": jsonify(reading_doc)})
        if alert_doc is not None:
            await manager.broadcast({"type": "alert", "data": jsonify(alert_doc)})

    return reading_doc


async def _create_alert(
    *, station: dict, site: dict, reading: dict, level: Classification,
    previous: Classification, tflood: float | None,
) -> dict:
    from .config import get_settings

    ts = reading["ts"]
    alert_id = f"ALT-{uuid.uuid4().hex[:10].upper()}"
    cap_attrs = engine.cap_attributes(level)
    message = engine.compose_message(level, site["name"], tflood)

    # Which delivery channels fire for this severity.
    channels = ["dashboard"]
    if _RANK[level] >= _RANK[Classification.warning]:
        channels += ["sms", "push"]

    cap = {
        "identifier": alert_id,
        "sender": get_settings().alert_sender,
        "sent": ts,
        "status": "Actual",
        "msg_type": "Alert",
        "scope": "Public",
        "category": "Met",
        "event": cap_attrs["event"],
        "urgency": cap_attrs["urgency"],
        "severity": cap_attrs["severity"],
        "certainty": cap_attrs["certainty"],
        "area_desc": f"{site['name']}, {site['area']}",
        "instruction": message,
    }
    alert_doc = {
        "alert_id": alert_id,
        "ts": ts,
        "station_id": station["station_id"],
        "site_id": site["site_id"],
        "site_name": site["name"],
        "area": site["area"],
        "level": level.value,
        "previous_level": previous.value,
        "message": message,
        "tflood": tflood,
        "water_level": reading["water_level"],
        "rainfall_rate": reading["rainfall_rate"],
        "capacity_pct": reading["capacity_pct"],
        "cap": cap,
        "channels": channels,
        "acknowledged": False,
        "acknowledged_at": None,
        "acknowledged_by": None,
    }
    insert = await db.alerts().insert_one(alert_doc)
    alert_doc["_id"] = insert.inserted_id
    return alert_doc
