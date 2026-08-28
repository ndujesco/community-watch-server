"""Pydantic models for requests, responses, and domain entities."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Classification(str, Enum):
    """Four-level flood classification (report Section 3.3.4)."""

    safe = "safe"
    watch = "watch"
    warning = "warning"
    emergency = "emergency"


class StationStatus(str, Enum):
    online = "online"
    offline = "offline"
    maintenance = "maintenance"


# --- Sites -----------------------------------------------------------------
class SiteThresholds(BaseModel):
    """Site-specific, calibratable thresholds (report Section 3.3.4)."""

    watch_fraction: float = 0.5          # H >= 0.5*Hmax -> at least Watch
    warning_fraction: float = 0.8        # H >= 0.8*Hmax -> at least Warning
    tflood_minutes: float = 30.0         # T_flood below this (with rain) -> Warning
    critical_rainfall: float = 30.0      # mm/h considered a critical rate
    dhdt_negligible: float = 0.002       # m/min below which dH/dt is "negligible"
    dhdt_moderate: float = 0.01          # m/min above which rise is non-trivial


class Site(BaseModel):
    site_id: str
    name: str
    area: str
    lat: float
    lng: float
    channel_depth: float                 # H_max — total depth of channel (m)
    channel_width: float | None = None   # m
    channel_type: str = "concrete-lined"
    catchment_area: float | None = None  # m^2 / hectares (descriptive)
    drainage_quality: str = "moderate"   # good | moderate | poor
    alpha: float = 0.02                  # learned rainfall->level coefficient
    baseline_drainage: float = 0.4       # baseline drainage rate (m/h)
    thresholds: SiteThresholds = Field(default_factory=SiteThresholds)


class SiteUpdate(BaseModel):
    name: str | None = None
    area: str | None = None
    channel_depth: float | None = None
    channel_type: str | None = None
    drainage_quality: str | None = None
    thresholds: SiteThresholds | None = None


# --- Stations --------------------------------------------------------------
class SensorHealth(BaseModel):
    rain_gauge: bool = True
    ultrasonic: bool = True
    bmp280: bool = True
    float_switch: bool = True


class Station(BaseModel):
    station_id: str
    name: str
    site_id: str
    location: str
    lat: float
    lng: float
    status: StationStatus = StationStatus.online
    battery: float = 100.0          # %
    solar_voltage: float = 5.0      # V
    rssi: float = -70.0             # dBm (433 MHz link quality)
    firmware: str = "fw-1.0.0"
    sensors: SensorHealth = Field(default_factory=SensorHealth)
    installed_at: datetime | None = None
    last_seen: datetime | None = None


class StationUpdate(BaseModel):
    """Admin provisioning: name a station, move it to a real site, etc.

    Primarily used to assign a real ``site_id`` (with its calibrated
    ``channel_depth``/thresholds) to a station that was auto-registered under
    the fallback "unassigned" site on its first hardware reading.
    """

    name: str | None = None
    site_id: str | None = None
    location: str | None = None
    lat: float | None = None
    lng: float | None = None
    status: StationStatus | None = None


# --- Readings --------------------------------------------------------------
class IngestPacket(BaseModel):
    """Decoded RF packet forwarded by the RTL-SDR receiver (report 3.5.2).

    Raw sensor values only; the backend computes dH/dt, T_flood and the
    classification via the flood engine.
    """

    station_id: str
    water_level: float | None = None     # H(t) in metres (if precomputed)
    distance: float | None = None        # d(t) ultrasonic distance in metres
    rainfall_rate: float                 # R(t) mm/h
    cumulative_rain: float = 0.0         # mm
    temperature: float = 27.0            # C
    pressure: float = 1013.0             # hPa
    humidity: float = 75.0               # %
    float_triggered: bool = False
    rssi: float | None = None
    crc_valid: bool = True
    ts: datetime | None = None


# --- Device (hardware) ingestion --------------------------------------------
# Field-for-field mirror of the ESP32 firmware payload described in
# backend-api-spec.md (POST /api/v1/readings). No flood-detection logic
# lives here — see services.process_device_reading for the translation into
# the flood engine's inputs.
class DeviceNetwork(BaseModel):
    wifi_connected: bool = True
    rssi_dbm: int = -70


class DeviceUltrasonic(BaseModel):
    distance_cm: float | None = None
    status: str = "ok"           # "ok" | "out_of_range"


class DeviceClimate(BaseModel):
    temperature_c: float | None = None
    humidity_pct: float | None = None
    status: str = "ok"           # "ok" | "unavailable"


class DeviceRain(BaseModel):
    raw_adc: int
    wetness_pct: float           # 0 = dry, 100 = fully wet/submerged
    status: str = "ok"


class DeviceFloatSwitch(BaseModel):
    name: str
    pin: int
    triggered: bool


class DeviceReadingPacket(BaseModel):
    device_id: str
    location: str = "site_unassigned"
    sequence: int
    uptime_ms: int
    network: DeviceNetwork
    ultrasonic: DeviceUltrasonic
    climate: DeviceClimate
    rain: DeviceRain
    float_switches: list[DeviceFloatSwitch] = Field(default_factory=list)


class Reading(BaseModel):
    station_id: str
    site_id: str
    ts: datetime
    water_level: float
    distance: float
    rainfall_rate: float
    cumulative_rain: float
    temperature: float
    pressure: float
    humidity: float
    dhdt: float                          # m/min
    tflood: float | None                 # minutes (None if not rising)
    capacity_pct: float                  # H / Hmax * 100
    classification: Classification
    float_triggered: bool
    crc_valid: bool
    rssi: float


# --- Alerts ----------------------------------------------------------------
class CAPInfo(BaseModel):
    """Common Alerting Protocol fields (report Section 2.8 / 3.6.5)."""

    identifier: str
    sender: str
    sent: datetime
    status: str = "Actual"
    msg_type: str = "Alert"
    scope: str = "Public"
    category: str = "Met"
    event: str
    urgency: str
    severity: str
    certainty: str
    area_desc: str
    instruction: str


class Alert(BaseModel):
    alert_id: str
    ts: datetime
    station_id: str
    site_id: str
    site_name: str
    area: str
    level: Classification
    previous_level: Classification | None = None
    message: str
    tflood: float | None = None
    water_level: float
    rainfall_rate: float
    capacity_pct: float
    cap: CAPInfo
    channels: list[str] = Field(default_factory=lambda: ["dashboard"])
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None


class AckRequest(BaseModel):
    acknowledged_by: str = "operator"


# --- Subscribers -----------------------------------------------------------
class Subscriber(BaseModel):
    name: str
    phone: str
    site_id: str | None = None           # None => all sites
    min_level: Classification = Classification.warning
    active: bool = True


class SubscriberOut(Subscriber):
    subscriber_id: str
    created_at: datetime
