"""Background live simulator.

Stands in for the physical sensor network (report Chapter 4: hardware not yet
assembled). It continuously advances the storm/drainage model for each active
station and pushes the resulting packets through the same ingestion pipeline
the RTL-SDR receiver would use, so the dashboard updates in real time.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

from . import db
from .config import get_settings
from .fixtures import SITES
from .models import IngestPacket
from .services import process_packet
from .simulation import SimState, SiteParams, initial_state, step

_task: asyncio.Task | None = None


async def _load_states() -> dict[str, tuple[SimState, SiteParams, str]]:
    """Build per-station sim state, resuming from the last stored reading."""
    site_by_id = {s["site_id"]: s for s in SITES}
    states: dict[str, tuple[SimState, SiteParams, str]] = {}
    stations = await db.stations().find(
        {"status": {"$ne": "maintenance"}}
    ).to_list(length=None)
    for st in stations:
        site = site_by_id.get(st["site_id"])
        if not site:
            continue
        params = SiteParams(
            site_id=site["site_id"],
            hmax=site["channel_depth"],
            alpha=site["alpha"],
            baseline_drainage=site["baseline_drainage"],
        )
        rng = random.Random(hash(st["station_id"]) & 0xFFFFFFFF)
        last = await (
            db.readings().find({"station_id": st["station_id"]})
            .sort("ts", -1).limit(1).to_list(length=1)
        )
        if last:
            r = last[0]
            state = initial_state(params, rng)
            state.water_level = r["water_level"]
            state.cumulative_rain = r["cumulative_rain"]
            state.rainfall = r["rainfall_rate"]
            state.temperature = r["temperature"]
            state.pressure = r["pressure"]
            state.humidity = r["humidity"]
        else:
            state = initial_state(params, rng)
        states[st["station_id"]] = (state, params, st["site_id"])
    return states


async def _run() -> None:
    settings = get_settings()
    interval = settings.simulator_interval_seconds
    # One real tick represents a few simulated minutes so trends move visibly.
    sim_minutes_per_tick = 3.0

    states = await _load_states()
    rng = random.Random()
    try:
        while True:
            await asyncio.sleep(interval)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            minute_of_day = now.hour * 60 + now.minute + now.second / 60.0
            for station_id, (state, params, _site_id) in states.items():
                step(state, params, sim_minutes_per_tick, rng, minute_of_day)
                packet = IngestPacket(
                    station_id=station_id,
                    water_level=state.water_level,
                    rainfall_rate=state.rainfall,
                    cumulative_rain=state.cumulative_rain,
                    temperature=state.temperature,
                    pressure=state.pressure,
                    humidity=state.humidity,
                    float_triggered=state.water_level >= params.hmax * 0.95,
                    rssi=round(-65 + rng.uniform(-12, 6), 1),
                    crc_valid=rng.random() > 0.01,
                    ts=now,
                )
                try:
                    await process_packet(packet)
                except Exception as exc:  # never let one station kill the loop
                    print(f"[simulator] {station_id} error: {exc}")
    except asyncio.CancelledError:
        pass


async def start() -> None:
    global _task
    if not get_settings().simulator_enabled:
        return
    if _task is None or _task.done():
        _task = asyncio.create_task(_run())


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
