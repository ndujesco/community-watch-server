"""Seed the MongoDB database with sites, stations, historical readings & alerts.

Run from the server directory:  python seed.py [--days N]

Generates physically-coherent history with the same storm/drainage model and
flood engine used at runtime, so charts, analytics, and the alert log are
populated immediately. Safe to re-run: it clears the core collections first
(subscribers are preserved).
"""
from __future__ import annotations

import argparse
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient

from app import engine
from app.fixtures import SITES, STATIONS
from app.models import Classification
from app.simulation import SiteParams, initial_state, step

_RANK = {"safe": 0, "watch": 1, "warning": 2, "emergency": 3}


def build_reading(packet, prev, site, ts):
    hmax = float(site["channel_depth"])
    water_level = float(packet["water_level"])
    distance = round(hmax - water_level, 3)
    prev_level = float(prev["water_level"]) if prev else None
    prev_ts = prev["ts"] if prev else None
    result = engine.evaluate(
        water_level=water_level,
        rainfall_rate=packet["rainfall_rate"],
        hmax=hmax,
        prev_level=prev_level,
        ts=ts,
        prev_ts=prev_ts,
        baseline_drainage=float(site["baseline_drainage"]),
        thresholds=site["thresholds"],
    )
    return {
        "station_id": packet["station_id"],
        "site_id": site["site_id"],
        "ts": ts,
        "water_level": round(water_level, 3),
        "distance": distance,
        "rainfall_rate": round(packet["rainfall_rate"], 2),
        "cumulative_rain": round(packet["cumulative_rain"], 2),
        "temperature": round(packet["temperature"], 2),
        "pressure": round(packet["pressure"], 2),
        "humidity": round(packet["humidity"], 1),
        "dhdt": result.dhdt,
        "tflood": result.tflood,
        "capacity_pct": result.capacity_pct,
        "classification": result.classification.value,
        "float_triggered": water_level >= hmax * 0.95,
        "crc_valid": packet["crc_valid"],
        "rssi": packet["rssi"],
    }, result


def build_alert(station, site, reading, level, previous, tflood, sender):
    alert_id = f"ALT-{uuid.uuid4().hex[:10].upper()}"
    cap_attrs = engine.cap_attributes(level)
    message = engine.compose_message(level, site["name"], tflood)
    channels = ["dashboard"]
    if _RANK[level.value] >= _RANK["warning"]:
        channels += ["sms", "push"]
    return {
        "alert_id": alert_id,
        "ts": reading["ts"],
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
        "cap": {
            "identifier": alert_id,
            "sender": sender,
            "sent": reading["ts"],
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
        },
        "channels": channels,
        "acknowledged": False,
        "acknowledged_at": None,
        "acknowledged_by": None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=4)
    parser.add_argument("--step", type=int, default=5, help="minutes between readings")
    args = parser.parse_args()

    load_dotenv()
    uri = os.environ["MONGO_URI"]
    sender = os.environ.get("ALERT_SENDER", "floodwatch@unilag.edu.ng")
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    db = client.get_default_database()
    print(f"Connected to {db.name}")

    print("Clearing collections (sites, stations, readings, alerts)...")
    db.sites.delete_many({})
    db.stations.delete_many({})
    db.readings.delete_many({})
    db.alerts.delete_many({})

    # Indexes
    db.sites.create_index([("site_id", ASCENDING)], unique=True)
    db.stations.create_index([("station_id", ASCENDING)], unique=True)
    db.readings.create_index([("station_id", ASCENDING), ("ts", DESCENDING)])
    db.readings.create_index([("site_id", ASCENDING), ("ts", DESCENDING)])
    db.readings.create_index([("ts", DESCENDING)])
    db.alerts.create_index([("ts", DESCENDING)])
    db.alerts.create_index([("alert_id", ASCENDING)], unique=True)
    try:
        db.subscribers.create_index([("phone", ASCENDING)], unique=True)
    except Exception:
        pass

    site_by_id = {s["site_id"]: s for s in SITES}
    db.sites.insert_many([dict(s) for s in SITES])
    print(f"Inserted {len(SITES)} sites")

    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    start = now - timedelta(days=args.days)
    dt = args.step

    total_readings = 0
    total_alerts = 0
    station_docs = []

    for st in STATIONS:
        station_doc = {
            "station_id": st["station_id"],
            "name": st["name"],
            "site_id": st["site_id"],
            "location": st["location"],
            "lat": st["lat"],
            "lng": st["lng"],
            "status": st.get("status", "online"),
            "firmware": st.get("firmware", "fw-1.0.0"),
            "sensors": {"rain_gauge": True, "ultrasonic": True,
                        "bmp280": True, "float_switch": True},
            "installed_at": now - timedelta(days=30),
            "solar_voltage": round(random.uniform(4.6, 5.4), 2),
        }

        if st.get("status") == "maintenance":
            station_doc["battery"] = round(random.uniform(8, 20), 1)
            station_doc["rssi"] = -95.0
            station_doc["last_seen"] = now - timedelta(hours=6)
            station_doc["sensors"]["ultrasonic"] = False
            station_docs.append(station_doc)
            print(f"  {st['station_id']}: maintenance (no readings)")
            continue

        site = site_by_id[st["site_id"]]
        params = SiteParams(
            site_id=site["site_id"], hmax=site["channel_depth"],
            alpha=site["alpha"], baseline_drainage=site["baseline_drainage"],
        )
        rng = random.Random(hash(st["station_id"]) & 0xFFFFFFFF)
        state = initial_state(params, rng)

        prev = None
        prev_class = Classification.safe
        readings_batch = []
        alerts_batch = []
        t = start
        while t <= now:
            minute_of_day = t.hour * 60 + t.minute + t.second / 60.0
            step(state, params, dt, rng, minute_of_day)
            packet = {
                "station_id": st["station_id"],
                "water_level": state.water_level,
                "rainfall_rate": state.rainfall,
                "cumulative_rain": state.cumulative_rain,
                "temperature": state.temperature,
                "pressure": state.pressure,
                "humidity": state.humidity,
                "crc_valid": rng.random() > 0.01,
                "rssi": round(-65 + rng.uniform(-15, 6), 1),
            }
            reading, result = build_reading(packet, prev, site, t)
            readings_batch.append(reading)

            new_rank = _RANK[result.classification.value]
            old_rank = _RANK[prev_class.value]
            escalated = new_rank > old_rank and new_rank >= _RANK["watch"]
            recovered = new_rank == 0 and old_rank >= _RANK["warning"]
            if escalated or recovered:
                alerts_batch.append(build_alert(
                    st, site, reading, result.classification,
                    prev_class, result.tflood, sender,
                ))
            prev = reading
            prev_class = result.classification
            t += timedelta(minutes=dt)

        if readings_batch:
            db.readings.insert_many(readings_batch)
        if alerts_batch:
            db.alerts.insert_many(alerts_batch)
        total_readings += len(readings_batch)
        total_alerts += len(alerts_batch)

        # Empirical alpha for this site -> store as learned coefficient.
        num = sum(r["rainfall_rate"] * (r["dhdt"] * 60.0)
                  for r in readings_batch if r["rainfall_rate"] > 0.5)
        den = sum(r["rainfall_rate"] ** 2
                  for r in readings_batch if r["rainfall_rate"] > 0.5)
        if den > 0:
            db.sites.update_one({"site_id": site["site_id"]},
                                {"$set": {"alpha": round(num / den, 5)}})

        station_doc["battery"] = round(random.uniform(58, 98), 1)
        station_doc["rssi"] = readings_batch[-1]["rssi"] if readings_batch else -70.0
        station_doc["last_seen"] = readings_batch[-1]["ts"] if readings_batch else now
        station_docs.append(station_doc)
        print(f"  {st['station_id']}: {len(readings_batch)} readings, "
              f"{len(alerts_batch)} alerts")

    db.stations.insert_many(station_docs)
    print(f"Inserted {len(station_docs)} stations")

    # Demo subscribers (idempotent).
    subs = [
        {"name": "Community Warden — Ajegunle", "phone": "+2348030000001",
         "site_id": "ajegunle", "min_level": "warning", "active": True},
        {"name": "LASEMA Operations", "phone": "+2348030000002",
         "site_id": None, "min_level": "warning", "active": True},
        {"name": "Resident — Mushin", "phone": "+2348030000003",
         "site_id": "mushin", "min_level": "emergency", "active": True},
    ]
    for s in subs:
        s["subscriber_id"] = f"SUB-{uuid.uuid4().hex[:8].upper()}"
        s["created_at"] = now
        db.subscribers.update_one({"phone": s["phone"]}, {"$setOnInsert": s}, upsert=True)

    print(f"\nDone. {total_readings} readings, {total_alerts} alerts across "
          f"{len(SITES)} sites.")
    client.close()


if __name__ == "__main__":
    main()
