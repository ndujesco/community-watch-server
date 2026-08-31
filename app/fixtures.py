"""Canonical deployment site for the live single-node demo.

This project was designed around a multi-site network (see the flood engine
in engine.py and the simulator in simulator.py, which can still animate any
number of sites for validation), but the physical hardware built for this
final-year project is a single ESP32 sensor node. So there is exactly one
real deployment site here; the device auto-registers under it on its first
reading (see services.py: _ensure_station / _ensure_demo_site).
"""
from __future__ import annotations

from .models import SiteThresholds

DEMO_SITE = {
    "site_id": "demo",
    "name": "FloodWatch Demo Site",
    "area": "Live hardware demo — single ESP32 sensor node",
    "lat": 6.5244,
    "lng": 3.3792,
    "channel_depth": 1.2,               # matches the bench rig's Hmax
    "channel_width": None,
    "channel_type": "bench/demo rig",
    "catchment_area": None,
    "drainage_quality": "moderate",
    "alpha": 0.02,
    "baseline_drainage": 0.4,
    "thresholds": SiteThresholds().model_dump(),
}

# Kept as a list for compatibility with code that iterates "all sites"
# (simulator.py, seed.py) — there is just the one entry.
SITES = [DEMO_SITE]

# No stations are pre-seeded: the real device creates its own station record
# the first time it POSTs to /api/v1/readings (zero-touch provisioning).
STATIONS: list[dict] = []


def site_params_map():
    """Return {site_id: SiteParams-compatible dict} for the simulation model."""
    return {
        s["site_id"]: {
            "hmax": s["channel_depth"],
            "alpha": s["alpha"],
            "baseline_drainage": s["baseline_drainage"],
        }
        for s in SITES
    }
