"""Canonical deployment sites and sensor stations.

Five flood-prone Lagos locations with deliberately different drainage
characteristics, so the analytics illustrate the site-specific coefficient
alpha (report Figure 3.5): the same rainfall yields very different water-level
trajectories at a blocked earth channel vs. a clean concrete drain.
"""
from __future__ import annotations

from .models import SiteThresholds

SITES = [
    {
        "site_id": "ajegunle",
        "name": "Ajegunle Canal",
        "area": "Ajegunle, Ajeromi-Ifelodun LGA, Lagos",
        "lat": 6.4549, "lng": 3.3293,
        "channel_depth": 1.2,
        "channel_width": 1.5,
        "channel_type": "earth-banked",
        "catchment_area": 42000,
        "drainage_quality": "poor",
        "alpha": 0.030,
        "baseline_drainage": 0.30,
        "thresholds": SiteThresholds().model_dump(),
    },
    {
        "site_id": "lekki",
        "name": "Lekki Phase 1 Drain",
        "area": "Lekki Phase 1, Eti-Osa LGA, Lagos",
        "lat": 6.4413, "lng": 3.4710,
        "channel_depth": 1.5,
        "channel_width": 2.0,
        "channel_type": "concrete-lined",
        "catchment_area": 38000,
        "drainage_quality": "good",
        "alpha": 0.014,
        "baseline_drainage": 0.62,
        "thresholds": SiteThresholds().model_dump(),
    },
    {
        "site_id": "mushin",
        "name": "Mushin Collector Drain",
        "area": "Mushin LGA, Lagos",
        "lat": 6.5274, "lng": 3.3490,
        "channel_depth": 1.0,
        "channel_width": 1.2,
        "channel_type": "concrete (undersized)",
        "catchment_area": 51000,
        "drainage_quality": "poor",
        "alpha": 0.028,
        "baseline_drainage": 0.34,
        "thresholds": SiteThresholds().model_dump(),
    },
    {
        "site_id": "oshodi",
        "name": "Oshodi Channel",
        "area": "Oshodi-Isolo LGA, Lagos",
        "lat": 6.5557, "lng": 3.3486,
        "channel_depth": 1.1,
        "channel_width": 1.4,
        "channel_type": "concrete (partially blocked)",
        "catchment_area": 47000,
        "drainage_quality": "moderate",
        "alpha": 0.022,
        "baseline_drainage": 0.45,
        "thresholds": SiteThresholds().model_dump(),
    },
    {
        "site_id": "surulere",
        "name": "Ojuelegba Underbridge Drain",
        "area": "Surulere LGA, Lagos",
        "lat": 6.5095, "lng": 3.3620,
        "channel_depth": 1.3,
        "channel_width": 1.8,
        "channel_type": "concrete-lined",
        "catchment_area": 44000,
        "drainage_quality": "moderate",
        "alpha": 0.020,
        "baseline_drainage": 0.50,
        "thresholds": SiteThresholds().model_dump(),
    },
]

# One co-located sensor node per site, plus one node in maintenance to show
# the station-health states in the UI.
STATIONS = [
    {
        "station_id": "FWS-AJG-01", "name": "Ajegunle Node 1", "site_id": "ajegunle",
        "location": "Canal footbridge, Ajegunle", "lat": 6.4549, "lng": 3.3293,
        "firmware": "fw-1.2.0",
    },
    {
        "station_id": "FWS-LEK-01", "name": "Lekki Node 1", "site_id": "lekki",
        "location": "Admiralty Way culvert", "lat": 6.4413, "lng": 3.4710,
        "firmware": "fw-1.2.0",
    },
    {
        "station_id": "FWS-MSN-01", "name": "Mushin Node 1", "site_id": "mushin",
        "location": "Idi-Oro collector", "lat": 6.5274, "lng": 3.3490,
        "firmware": "fw-1.1.0",
    },
    {
        "station_id": "FWS-OSH-01", "name": "Oshodi Node 1", "site_id": "oshodi",
        "location": "Oshodi overpass channel", "lat": 6.5557, "lng": 3.3486,
        "firmware": "fw-1.2.0",
    },
    {
        "station_id": "FWS-SUR-01", "name": "Surulere Node 1", "site_id": "surulere",
        "location": "Ojuelegba underbridge", "lat": 6.5095, "lng": 3.3620,
        "firmware": "fw-1.2.0",
    },
    {
        "station_id": "FWS-SUR-02", "name": "Surulere Node 2", "site_id": "surulere",
        "location": "Lawanson secondary drain", "lat": 6.5121, "lng": 3.3552,
        "firmware": "fw-1.0.0", "status": "maintenance",
    },
]


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
