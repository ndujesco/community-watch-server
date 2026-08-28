"""Aggregated API router."""
from fastapi import APIRouter

from . import (
    alerts,
    analytics,
    device_readings,
    ingest,
    readings,
    sites,
    stations,
    subscribers,
    system,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router, tags=["system"])
api_router.include_router(sites.router, prefix="/sites", tags=["sites"])
api_router.include_router(stations.router, prefix="/stations", tags=["stations"])
api_router.include_router(readings.router, prefix="/readings", tags=["readings"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(subscribers.router, prefix="/subscribers", tags=["subscribers"])
api_router.include_router(ingest.router, tags=["ingest"])

# Real hardware ingestion (backend-api-spec.md): POST /api/v1/readings.
api_router.include_router(device_readings.router, prefix="/v1", tags=["device-ingest"])
