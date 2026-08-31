"""Reset the database to the single-site live demo shape.

Run from the server directory:  python seed.py

This project's live demo is one real ESP32 sensor node reporting to one real
site ("demo" — see app/fixtures.py). This script clears out the old
multi-site *validation* dataset (five fictitious Lagos sites/stations with
simulated storm history, originally used to demonstrate the flood engine and
analytics across varied drainage scenarios) and leaves exactly:

  - the single "demo" site document
  - zero station documents (the real device creates its own station record
    the first time it POSTs to /api/v1/readings — zero-touch provisioning)

Safe to re-run. Clears sites/stations/readings/alerts; subscribers are
preserved (they're independent of which sites exist).

If you want the old multi-site simulated dataset back for report figures or
further engine validation, see git history for the previous version of this
script and of app/fixtures.py (SITES/STATIONS) — the underlying simulator
(app/simulator.py) and storm model (app/simulation.py) are unchanged and
still support it; SIMULATOR_ENABLED just defaults to off now.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient

from app.fixtures import DEMO_SITE


def main():
    load_dotenv()
    uri = os.environ["MONGO_URI"]
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    db = client.get_default_database()
    print(f"Connected to {db.name}")

    print("Clearing collections (sites, stations, readings, alerts)...")
    db.sites.delete_many({})
    db.stations.delete_many({})
    db.readings.delete_many({})
    db.alerts.delete_many({})

    # Indexes (idempotent).
    db.sites.create_index([("site_id", ASCENDING)], unique=True)
    db.stations.create_index([("station_id", ASCENDING)], unique=True)
    db.readings.create_index([("station_id", ASCENDING), ("ts", DESCENDING)])
    db.readings.create_index([("site_id", ASCENDING), ("ts", DESCENDING)])
    db.readings.create_index([("ts", DESCENDING)])
    db.alerts.create_index([("ts", DESCENDING)])
    db.alerts.create_index([("alert_id", ASCENDING)], unique=True)
    try:
        db.subscribers.drop_index("phone_1")  # old SMS-era index, if present
    except Exception:
        pass
    try:
        db.subscribers.create_index([("email", ASCENDING)], unique=True)
    except Exception:
        pass

    db.sites.insert_one(dict(DEMO_SITE))
    print(f"Inserted 1 site: {DEMO_SITE['site_id']} ({DEMO_SITE['name']})")
    print("No stations inserted — your ESP32 will auto-register on its first POST.")
    print("Done.")
    client.close()


if __name__ == "__main__":
    main()
