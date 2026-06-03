"""Site-specific flood detection & prediction engine.

Implements the mathematical model from Chapter 3.3 of the project report:

  * Rate of water-level change      dH/dt = (H(t) - H(t-dt)) / dt          (3.3.1)
  * Rainfall -> water-level balance dH/dt = alpha*R(t) - D(H)              (3.3.2)
  * Time-to-flood estimation        T_flood = (Hmax - H(t)) / (dH/dt)      (3.3.3)
  * Four-level threshold classifier  Safe / Watch / Warning / Emergency    (3.3.4)

All quantities are grounded in the *co-located* rain gauge and water-level
sensor, so the model implicitly captures the drainage characteristics of the
specific deployment site without needing to know alpha or D(H) explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import Classification


@dataclass
class EngineResult:
    dhdt: float                  # m/min  (positive => rising)
    tflood: float | None         # minutes until H reaches Hmax (None if not rising)
    capacity_pct: float          # H / Hmax * 100
    classification: Classification
    alpha_estimate: float | None  # instantaneous rainfall->level coefficient


def compute_dhdt(
    water_level: float,
    prev_level: float | None,
    ts: datetime,
    prev_ts: datetime | None,
) -> float:
    """dH/dt in metres per minute between two consecutive readings (3.3.1)."""
    if prev_level is None or prev_ts is None:
        return 0.0
    dt_min = (ts - prev_ts).total_seconds() / 60.0
    if dt_min <= 0:
        return 0.0
    return (water_level - prev_level) / dt_min


def estimate_time_to_flood(
    water_level: float, hmax: float, dhdt: float, negligible: float
) -> float | None:
    """Linear extrapolation to channel capacity (3.3.3).

    Returns minutes until H(t) reaches Hmax when the level is rising; None when
    the level is steady or falling (no imminent overflow by extrapolation).
    """
    if dhdt <= negligible:
        return None
    remaining = hmax - water_level
    if remaining <= 0:
        return 0.0
    return remaining / dhdt


def estimate_alpha(
    dhdt: float, rainfall_rate: float, baseline_drainage: float
) -> float | None:
    """Instantaneous site coefficient from the inflow/outflow balance (3.3.2).

        dH/dt = alpha*R - D(H)   =>   alpha = (dH/dt_per_hour + D) / R

    dhdt is m/min here, converted to m/h to match rainfall (mm/h scale).
    Returns None when it is not raining (alpha undefined / noisy).
    """
    if rainfall_rate <= 0.5:
        return None
    dhdt_per_hour = dhdt * 60.0
    alpha = (dhdt_per_hour + baseline_drainage) / rainfall_rate
    # alpha is in (m/h) per (mm/h); keep physically plausible, non-negative.
    return max(0.0, round(alpha, 5))


def classify(
    water_level: float,
    hmax: float,
    dhdt: float,
    rainfall_rate: float,
    tflood: float | None,
    thresholds: dict,
) -> Classification:
    """Four-level threshold classification (report Section 3.3.4).

    Emergency: H >= Hmax (flooding confirmed/imminent).
    Warning:   H >= 0.8*Hmax, OR (T_flood < tflood_minutes AND R > critical).
    Watch:     H >= 0.5*Hmax, OR R elevated, OR dH/dt positive & non-trivial.
    Safe:      otherwise.
    """
    watch_frac = thresholds["watch_fraction"]
    warning_frac = thresholds["warning_fraction"]
    tflood_min = thresholds["tflood_minutes"]
    critical_rain = thresholds["critical_rainfall"]
    dhdt_negligible = thresholds["dhdt_negligible"]
    dhdt_moderate = thresholds["dhdt_moderate"]

    capacity = water_level / hmax if hmax > 0 else 0.0

    # Emergency — channel capacity reached or exceeded.
    if capacity >= 1.0:
        return Classification.emergency

    # Warning — near capacity, or fast rise with heavy rain projected to overflow soon.
    imminent = tflood is not None and tflood < tflood_min and rainfall_rate > critical_rain
    if capacity >= warning_frac or imminent:
        return Classification.warning

    # Watch — half-full, elevated rainfall, or a meaningful rising trend.
    elevated_rain = rainfall_rate > critical_rain * 0.5
    rising = dhdt > max(dhdt_negligible, dhdt_moderate)
    if capacity >= watch_frac or elevated_rain or rising:
        return Classification.watch

    return Classification.safe


def evaluate(
    *,
    water_level: float,
    rainfall_rate: float,
    hmax: float,
    prev_level: float | None,
    ts: datetime,
    prev_ts: datetime | None,
    baseline_drainage: float,
    thresholds: dict,
) -> EngineResult:
    """Run the full engine for one reading."""
    dhdt = compute_dhdt(water_level, prev_level, ts, prev_ts)
    tflood = estimate_time_to_flood(
        water_level, hmax, dhdt, thresholds["dhdt_negligible"]
    )
    capacity_pct = (water_level / hmax * 100.0) if hmax > 0 else 0.0
    classification = classify(
        water_level, hmax, dhdt, rainfall_rate, tflood, thresholds
    )
    alpha_estimate = estimate_alpha(dhdt, rainfall_rate, baseline_drainage)
    return EngineResult(
        dhdt=round(dhdt, 5),
        tflood=round(tflood, 1) if tflood is not None else None,
        capacity_pct=round(capacity_pct, 1),
        classification=classification,
        alpha_estimate=alpha_estimate,
    )


# --- CAP / plain-language messaging ----------------------------------------
_SEVERITY = {
    Classification.safe: ("Minor", "Past", "Likely"),
    Classification.watch: ("Moderate", "Future", "Possible"),
    Classification.warning: ("Severe", "Expected", "Likely"),
    Classification.emergency: ("Extreme", "Immediate", "Observed"),
}
_EVENT = {
    Classification.safe: "Flood Conditions Normal",
    Classification.watch: "Flood Watch",
    Classification.warning: "Flood Warning",
    Classification.emergency: "Flood Emergency",
}


def cap_attributes(level: Classification) -> dict:
    severity, urgency, certainty = _SEVERITY[level]
    return {
        "event": _EVENT[level],
        "severity": severity,
        "urgency": urgency,
        "certainty": certainty,
    }


def compose_message(
    level: Classification, site_name: str, tflood: float | None
) -> str:
    """Plain-language alert text (report Section 3.6.5)."""
    if level == Classification.emergency:
        return (
            f"FLOOD EMERGENCY: Water at {site_name} has reached channel capacity. "
            f"Flooding is occurring. Move to higher ground immediately."
        )
    if level == Classification.warning:
        if tflood is not None:
            return (
                f"FLOOD WARNING: Water level at {site_name} is rising rapidly. "
                f"Expected to overflow in approximately {round(tflood)} minutes. "
                f"Move to higher ground."
            )
        return (
            f"FLOOD WARNING: Water level at {site_name} is dangerously high. "
            f"Prepare to move to higher ground."
        )
    if level == Classification.watch:
        return (
            f"FLOOD WATCH: Water level at {site_name} is rising. "
            f"Monitor conditions and prepare to act."
        )
    return f"All clear: water level at {site_name} has returned to normal."
