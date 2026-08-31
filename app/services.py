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

import logging
import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from . import db, engine
from .fixtures import DEMO_SITE
from .models import Classification, DeviceReadingPacket, IngestPacket, SiteThresholds
from .realtime import manager
from .serialize import jsonify

logger = logging.getLogger("floodwatch.ingest")

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


# --- Hardware device ingestion (POST /api/v1/readings) ---------------------
#
# The physical ESP32 node speaks a different wire format than the RF/simulator
# pipeline above (backend-api-spec.md): raw ultrasonic/climate/rain/float
# fields, a device-generated MAC-derived `device_id`, no wall clock, and no
# pre-existing station/site record. `process_device_reading` adapts that
# payload into the same flood engine and alerting path used everywhere else.
# See the "Implementation decisions" section appended to backend-api-spec.md
# for the reasoning behind the choices below (auto-registration, shared-secret
# auth, rain proxy, etc).
#
# This deployment has exactly one real site (fixtures.DEMO_SITE) — the device
# auto-registers directly under it on its first reading. There is nowhere
# else to reassign it to, by design (see [[frontend-single-site]] in the
# project README).

_DEMO_SITE_ID = DEMO_SITE["site_id"]


async def _ensure_demo_site() -> dict:
    """Idempotently ensure the single demo site exists, and return it."""
    site = await db.sites().find_one({"site_id": _DEMO_SITE_ID})
    if site is not None:
        return site
    await db.sites().update_one(
        {"site_id": _DEMO_SITE_ID},
        {"$setOnInsert": dict(DEMO_SITE)},
        upsert=True,
    )
    return await db.sites().find_one({"site_id": _DEMO_SITE_ID})


async def _ensure_station(device_id: str, location: str, ts: datetime) -> dict:
    """Auto-register a station the first time a device_id is seen.

    Zero-touch provisioning: the device registers itself under the single
    demo site on its very first POST. No admin reassignment step exists in
    this deployment because there is only one site to assign to.
    """
    station = await db.stations().find_one({"station_id": device_id})
    if station is not None:
        return station
    await _ensure_demo_site()
    doc = {
        "station_id": device_id,
        "name": device_id,
        "site_id": _DEMO_SITE_ID,
        "location": location,
        "lat": DEMO_SITE["lat"],
        "lng": DEMO_SITE["lng"],
        "status": "online",
        "rssi": -70.0,
        "firmware": "hardware",
        "sensors": {"rain_gauge": True, "ultrasonic": True, "climate": True, "float_switch": True},
        "installed_at": ts,
        "last_seen": ts,
    }
    try:
        await db.stations().insert_one(doc)
        logger.info("New device auto-registered: %s -> site '%s'", device_id, _DEMO_SITE_ID)
    except DuplicateKeyError:
        pass  # concurrent request from the same device won the race
    return await db.stations().find_one({"station_id": device_id})


def _format_reading_log(packet: DeviceReadingPacket, reading: dict, alert: dict | None) -> str:
    """One human-readable block per POST — this is what shows up in
    `render logs --tail` (or the Render dashboard) so the sensor data is
    directly readable without digging through raw JSON.
    """
    fs = ", ".join(
        f"{s.name}={'TRIGGERED' if s.triggered else 'open'}" for s in packet.float_switches
    ) or "none"
    lines = [
        f"┌─ FloodWatch reading ── {packet.device_id} "
        f"(seq {packet.sequence}, up {packet.uptime_ms / 1000:.1f}s) "
        + "─" * max(1, 40 - len(packet.device_id)),
        f"│ Water level   {reading['water_level']:.2f} m  →  "
        f"{reading['capacity_pct']:.0f}% of Hmax        [{reading['classification'].upper()}]",
        f"│ Rain          {reading['rainfall_rate']:.1f}% wetness "
        f"(raw ADC {packet.rain.raw_adc}, sensor {packet.rain.status})",
        f"│ Climate       {reading['temperature']:.1f}°C · {reading['humidity']:.0f}% RH "
        f"(DHT11 {packet.climate.status})",
        f"│ Ultrasonic    {packet.ultrasonic.status}"
        + (f" ({packet.ultrasonic.distance_cm:.1f} cm)" if packet.ultrasonic.distance_cm is not None else ""),
        f"│ Float sw      {fs}",
        f"│ WiFi          {reading['rssi']} dBm",
    ]
    if reading.get("device_rebooted"):
        lines.append("│ ⚠ device reboot detected (uptime_ms reset)")
    if alert is not None:
        lines.append(f"│ → ALERT fired: {alert['previous_level']} -> {alert['level']}")
    lines.append("└" + "─" * 60)
    return "\n".join(lines)


def _accumulate_rain(prev: dict | None, rainfall_rate: float, ts: datetime) -> float:
    """Running rain total for the day, integrated from successive readings.

    The device has no rain gauge accumulator — only an instantaneous pad
    wetness reading — so the server integrates it over time, resetting at UTC
    day rollover the same way the simulator's cumulative_rain behaves.
    """
    if prev is None:
        return 0.0
    prev_ts = prev["ts"]
    if prev_ts.date() != ts.date():
        return 0.0
    dt_hours = max(0.0, (ts - prev_ts).total_seconds() / 3600.0)
    return float(prev.get("cumulative_rain", 0.0)) + rainfall_rate * dt_hours


async def process_device_reading(packet: DeviceReadingPacket, *, broadcast: bool = True) -> dict:
    # The device has no clock sync (backend-api-spec.md) — server receipt
    # time is the only authoritative timestamp; uptime_ms is boot-relative.
    ts = _utcnow()

    station = await _ensure_station(packet.device_id, packet.location, ts)
    if packet.location and station.get("location") != packet.location:
        await db.stations().update_one(
            {"station_id": packet.device_id}, {"$set": {"location": packet.location}}
        )
        station = dict(station)
        station["location"] = packet.location

    site = await db.sites().find_one({"site_id": station["site_id"]})
    if site is None:
        site = await _ensure_demo_site()
    hmax = float(site["channel_depth"])
    thresholds = site["thresholds"]

    prev = await _latest_reading(packet.device_id)
    prev_level = float(prev["water_level"]) if prev else None
    prev_ts = prev["ts"] if prev else None
    prev_class = Classification(prev["classification"]) if prev else Classification.safe

    # Ultrasonic -> water level: smaller distance = higher water (device is
    # mounted looking down at the surface). null/out_of_range is "unknown,"
    # not "safe" — carry the last known level forward instead of guessing.
    ultrasonic_ok = packet.ultrasonic.status == "ok" and packet.ultrasonic.distance_cm is not None
    if ultrasonic_ok:
        distance = packet.ultrasonic.distance_cm / 100.0  # cm -> m
        water_level = max(0.0, hmax - distance)
    elif prev_level is not None:
        water_level = prev_level
        distance = max(0.0, hmax - prev_level)
    else:
        water_level = 0.0
        distance = hmax

    # Float switches are fallback ground-truth: a tripped switch must not be
    # masked by a missing/faulty ultrasonic reading.
    float_triggered = any(fs.triggered for fs in packet.float_switches)
    if float_triggered and not ultrasonic_ok:
        water_level = max(water_level, hmax)

    # rain.wetness_pct is pad wetness intensity (0-100), not calibrated mm/h —
    # used directly as a directional proxy for rainfall_rate so the existing
    # rain-aware classification/alpha-learning still applies.
    rainfall_rate = max(0.0, float(packet.rain.wetness_pct))
    cumulative_rain = _accumulate_rain(prev, rainfall_rate, ts)

    climate_ok = packet.climate.status == "ok"
    temperature = (
        packet.climate.temperature_c
        if climate_ok and packet.climate.temperature_c is not None
        else (float(prev["temperature"]) if prev else 27.0)
    )
    humidity = (
        packet.climate.humidity_pct
        if climate_ok and packet.climate.humidity_pct is not None
        else (float(prev["humidity"]) if prev else 75.0)
    )
    pressure = float(prev["pressure"]) if prev else 1013.0  # not measured by this hardware rev

    result = engine.evaluate(
        water_level=water_level,
        rainfall_rate=rainfall_rate,
        hmax=hmax,
        prev_level=prev_level,
        ts=ts,
        prev_ts=prev_ts,
        baseline_drainage=float(site.get("baseline_drainage", 0.4)),
        thresholds=thresholds,
    )

    # Reboot detection: sequence/uptime both reset to a small number on a
    # power cycle (spec's guidance for detecting reboots, not ordering).
    prev_uptime = station.get("last_uptime_ms")
    rebooted = prev_uptime is not None and packet.uptime_ms < prev_uptime

    reading_doc = {
        "station_id": packet.device_id,
        "site_id": station["site_id"],
        "ts": ts,
        "water_level": round(water_level, 3),
        "distance": round(distance, 3),
        "rainfall_rate": round(rainfall_rate, 2),
        "cumulative_rain": round(cumulative_rain, 2),
        "temperature": round(temperature, 2),
        "pressure": round(pressure, 2),
        "humidity": round(humidity, 1),
        "dhdt": result.dhdt,
        "tflood": result.tflood,
        "capacity_pct": result.capacity_pct,
        "classification": result.classification.value,
        "float_triggered": float_triggered,
        "crc_valid": True,  # HTTP/TCP guarantees integrity; no RF CRC on this path
        "rssi": packet.network.rssi_dbm,
        # Raw device provenance, kept alongside the derived fields above so a
        # sensor fault or a reboot can be diagnosed after the fact.
        "device_sequence": packet.sequence,
        "device_uptime_ms": packet.uptime_ms,
        "device_rebooted": rebooted,
        "ultrasonic_status": packet.ultrasonic.status,
        "climate_status": packet.climate.status,
        "rain_raw_adc": packet.rain.raw_adc,
        "float_switches": [fs.model_dump() for fs in packet.float_switches],
    }
    insert = await db.readings().insert_one(reading_doc)
    reading_doc["_id"] = insert.inserted_id

    if result.alpha_estimate is not None:
        await _smooth_alpha(
            station["site_id"], float(site.get("alpha", 0.02)), result.alpha_estimate
        )

    await db.stations().update_one(
        {"station_id": packet.device_id},
        {"$set": {
            "last_seen": ts,
            "status": "online",
            "rssi": reading_doc["rssi"],
            "last_sequence": packet.sequence,
            "last_uptime_ms": packet.uptime_ms,
            "sensors.ultrasonic": packet.ultrasonic.status == "ok",
            "sensors.climate": climate_ok,
            "sensors.rain_gauge": packet.rain.status == "ok",
            "sensors.float_switch": True,
        }},
    )

    alert_doc = None
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

    logger.info(_format_reading_log(packet, reading_doc, alert_doc))

    if broadcast:
        await manager.broadcast({"type": "reading", "data": jsonify(reading_doc)})
        if alert_doc is not None:
            await manager.broadcast({"type": "alert", "data": jsonify(alert_doc)})

    return reading_doc
