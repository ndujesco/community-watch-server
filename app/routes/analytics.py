"""Analytics endpoints — the rainfall->water-level relationship and site profile.

These power the Analytics page, which visualises the site-specific drainage
behaviour described in report Sections 3.3.2 and 3.3.5.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from .. import db
from ..serialize import jsonify

router = APIRouter()


@router.get("/site/{site_id}")
async def site_analytics(site_id: str, hours: int = 72):
    site = await db.sites().find_one({"site_id": site_id})
    if not site:
        raise HTTPException(404, "Site not found")

    start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    docs = await (
        db.readings()
        .find({"site_id": site_id, "ts": {"$gte": start}})
        .sort("ts", 1)
        .to_list(length=None)
    )

    # Rainfall vs dH/dt scatter (the empirical site response, report 3.3.2).
    scatter = [
        {"rainfall_rate": d["rainfall_rate"], "dhdt": d["dhdt"], "ts": d["ts"]}
        for d in docs if d["rainfall_rate"] > 0.5
    ]

    # Classification distribution.
    dist = {"safe": 0, "watch": 0, "warning": 0, "emergency": 0}
    for d in docs:
        dist[d["classification"]] = dist.get(d["classification"], 0) + 1

    # Peak/summary stats.
    levels = [d["water_level"] for d in docs] or [0]
    rains = [d["rainfall_rate"] for d in docs] or [0]
    rising = [d["dhdt"] for d in docs if d["dhdt"] > 0]

    # Empirical alpha = slope of dH/dt(per hour) vs R via least squares through origin.
    num = sum(d["rainfall_rate"] * (d["dhdt"] * 60.0) for d in docs if d["rainfall_rate"] > 0.5)
    den = sum(d["rainfall_rate"] ** 2 for d in docs if d["rainfall_rate"] > 0.5)
    empirical_alpha = round(num / den, 5) if den > 0 else None

    summary = {
        "samples": len(docs),
        "peak_water_level": round(max(levels), 3),
        "mean_water_level": round(sum(levels) / len(levels), 3),
        "peak_rainfall": round(max(rains), 2),
        "max_dhdt": round(max(rising), 4) if rising else 0.0,
        "channel_depth": site["channel_depth"],
        "stored_alpha": site.get("alpha"),
        "empirical_alpha": empirical_alpha,
        "drainage_quality": site.get("drainage_quality"),
        "baseline_drainage": site.get("baseline_drainage"),
    }

    return jsonify({
        "site": site,
        "scatter": scatter,
        "distribution": dist,
        "summary": summary,
    })


@router.get("/summary")
async def overall_summary(hours: int = 72):
    """Cross-site comparison used to illustrate report Figure 3.5."""
    start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    sites = await db.sites().find({}).sort("site_id", 1).to_list(length=None)
    rows = []
    for site in sites:
        docs = await (
            db.readings()
            .find({"site_id": site["site_id"], "ts": {"$gte": start}})
            .to_list(length=None)
        )
        if not docs:
            continue
        num = sum(d["rainfall_rate"] * (d["dhdt"] * 60.0) for d in docs if d["rainfall_rate"] > 0.5)
        den = sum(d["rainfall_rate"] ** 2 for d in docs if d["rainfall_rate"] > 0.5)
        rows.append({
            "site_id": site["site_id"],
            "name": site["name"],
            "area": site["area"],
            "drainage_quality": site.get("drainage_quality"),
            "channel_depth": site["channel_depth"],
            "alpha": site.get("alpha"),
            "empirical_alpha": round(num / den, 5) if den > 0 else None,
            "peak_water_level": round(max(d["water_level"] for d in docs), 3),
            "peak_rainfall": round(max(d["rainfall_rate"] for d in docs), 2),
            "samples": len(docs),
        })
    return jsonify({"sites": rows, "hours": hours})
