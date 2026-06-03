"""Physical storm + drainage simulation.

Generates realistic, *co-located* rainfall and water-level behaviour so the
system has meaningful data to classify. The same model is used to seed history
and to drive the live simulator, which keeps the two continuous.

The water level evolves by the inflow/outflow balance from report 3.3.2:

    dH/dt (m/h) = alpha * R(t) - D(H)

where ``alpha`` is the site rainfall->level coefficient and ``D(H)`` is a
drainage term that grows mildly with depth. Each site has different parameters,
so identical rainfall produces different trajectories (report Figure 3.5).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class SiteParams:
    site_id: str
    hmax: float
    alpha: float            # m/h per mm/h
    baseline_drainage: float  # m/h at full channel
    storm_chance: float = 0.012  # probability a storm starts on a given step
    baseline_fraction: float = 0.09  # normal standing-water level as frac of hmax


@dataclass
class SimState:
    water_level: float
    cumulative_rain: float = 0.0
    rainfall: float = 0.0
    temperature: float = 27.0
    pressure: float = 1013.0
    humidity: float = 78.0
    storm_remaining: float = 0.0   # minutes left in the current storm
    storm_peak: float = 0.0        # peak rainfall rate of current storm (mm/h)
    storm_age: float = 0.0         # minutes since storm start
    storm_len: float = 0.0         # total storm length (minutes)
    minute_of_day: float = 0.0
    _day_rain_anchor: float = 0.0  # cumulative at start of current day


def initial_state(params: SiteParams, rng: random.Random) -> SimState:
    return SimState(
        water_level=round(params.hmax * rng.uniform(0.12, 0.28), 3),
        temperature=round(rng.uniform(25, 29), 2),
        pressure=round(rng.uniform(1010, 1015), 2),
        humidity=round(rng.uniform(70, 82), 1),
    )


def step(state: SimState, params: SiteParams, dt_min: float, rng: random.Random,
         minute_of_day: float) -> None:
    """Advance the state in place by ``dt_min`` minutes."""
    state.minute_of_day = minute_of_day

    # Reset cumulative rain at local midnight rollover.
    if minute_of_day < dt_min:
        state._day_rain_anchor = state.cumulative_rain

    # --- Rainfall process ---------------------------------------------------
    if state.storm_remaining <= 0:
        # Light intermittent drizzle between storms.
        base = max(0.0, rng.gauss(0.4, 0.6))
        state.rainfall = round(base, 2)
        # Chance to spawn a storm; afternoon convective peak (13:00-19:00).
        hour = minute_of_day / 60.0
        diurnal = 1.0 + (1.4 if 13 <= hour <= 19 else 0.0)
        if rng.random() < params.storm_chance * diurnal:
            state.storm_len = rng.uniform(40, 160)
            state.storm_remaining = state.storm_len
            state.storm_age = 0.0
            state.storm_peak = rng.uniform(18, 75)
    else:
        # Storm in progress: rainfall follows a smooth rise-and-decay envelope.
        state.storm_age += dt_min
        state.storm_remaining -= dt_min
        frac = min(1.0, max(0.0, state.storm_age / max(state.storm_len, 1.0)))
        envelope = math.sin(math.pi * frac)  # 0 -> 1 -> 0
        noise = rng.uniform(0.85, 1.15)
        state.rainfall = round(max(0.0, state.storm_peak * envelope * noise), 2)

    state.cumulative_rain = round(
        state._day_rain_anchor
        + max(0.0, state.cumulative_rain - state._day_rain_anchor)
        + state.rainfall * (dt_min / 60.0),
        2,
    )

    # --- Water-level balance: dH/dt = alpha*R - D(H) -----------------------
    # Channels carry a normal standing-water baseline; drainage acts on the
    # head above that baseline and grows with depth (more head -> faster
    # outflow). This keeps well-drained sites near baseline and lets poorly
    # drained sites accumulate during storms.
    h_base = params.baseline_fraction * params.hmax
    span = max(params.hmax - h_base, 0.05)
    # Drainage D(H): zero at baseline, rises linearly to D_max at full channel.
    d_max = params.baseline_drainage * 2.0
    drainage = d_max * max(0.0, (state.water_level - h_base) / span)
    dhdt_h = params.alpha * state.rainfall - drainage
    new_level = state.water_level + dhdt_h * (dt_min / 60.0)
    state.water_level = round(
        max(h_base, min(params.hmax * 1.08, new_level)), 4
    )

    # --- Atmosphere ---------------------------------------------------------
    hour = minute_of_day / 60.0
    diurnal_temp = 27 + 4 * math.sin((hour - 9) / 24 * 2 * math.pi)
    storm_cool = -2.5 if state.storm_remaining > 0 else 0.0
    state.temperature = round(diurnal_temp + storm_cool + rng.uniform(-0.4, 0.4), 2)

    storm_factor = state.rainfall / 50.0
    state.pressure = round(1013 - 7 * min(1.0, storm_factor) + rng.uniform(-0.6, 0.6), 2)
    target_hum = 72 + 22 * min(1.0, storm_factor)
    state.humidity = round(
        min(99.0, max(55.0, 0.85 * state.humidity + 0.15 * target_hum + rng.uniform(-1.5, 1.5))),
        1,
    )
