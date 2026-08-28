# FloodWatch API — IoT Flood Early-Warning System (Backend)

FastAPI + MongoDB backend implementing the site-specific flood detection and
prediction model from the project report (Chapter 3): rate of water-level
change (dH/dt), time-to-flood (T_flood), four-level classification
(Safe / Watch / Warning / Emergency), CAP-compliant alerts, and real-time
WebSocket streaming. A built-in simulator stands in for the physical sensor
network (hardware assembly is the next project phase).

## Architecture

```
ESP32 node (WiFi) ──HTTP POST /api/v1/readings──▶ FastAPI ──▶ Flood Engine ──▶ MongoDB
(or built-in simulator, via /api/ingest)              │           (dH/dt, T_flood,
                                                      │            classification)
                                                      └── WebSocket /ws ──▶ Dashboard
```

The node reads an ultrasonic water-level sensor, an analog rain-intensity
sensor, a climate (temp/humidity) sensor, and two float switches, then POSTs
a JSON reading directly over WiFi — see `../backend-api-spec.md` for the
exact payload. `/api/ingest` is the earlier RF/simulator-shaped path, kept
for the built-in simulator and any RF gateway forwarder.

| File | Responsibility |
|------|----------------|
| `app/engine.py` | The maths: dH/dt, T_flood, α estimation, 4-level classifier, CAP/message |
| `app/services.py` | Ingestion pipeline: store reading, learn α, raise alerts, broadcast |
| `app/simulation.py` | Storm + drainage physics (`dH/dt = α·R − D(H)`) |
| `app/simulator.py` | Background task driving live readings |
| `app/routes/` | REST endpoints (sites, stations, readings, alerts, analytics, ingest, subscribers) |
| `app/realtime.py` | WebSocket connection manager / broadcast |
| `seed.py` | Seed sites, stations, ~4 days of history + alerts |

## Run locally

```bash
cd community-watch-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .env already contains MONGO_URI
python seed.py --days 4 --step 5          # populate the database (run once)
uvicorn app.main:app --reload --port 8000 # start the API + live simulator
```

API docs: <http://localhost:8000/docs> · Health: `/api/health` · WebSocket: `/ws`

## Environment variables (`.env`)

| Var | Default | Notes |
|-----|---------|-------|
| `MONGO_URI` | — | MongoDB connection string (required) |
| `SIMULATOR_ENABLED` | `true` | Set `false` to disable the live simulator |
| `SIMULATOR_INTERVAL_SECONDS` | `5` | Seconds between simulated readings |
| `CORS_ORIGINS` | localhost dev origins | Comma-separated; `*.vercel.app` is always allowed |
| `ALERT_SENDER` | `floodwatch@unilag.edu.ng` | CAP sender identity |
| `DEVICE_API_KEYS` | *(empty)* | Comma-separated shared secret(s) checked against `X-Device-Key` on `POST /api/v1/readings`. Empty disables the check (dev only). |

## Key endpoints

- `GET  /api/overview` — network-wide status snapshot
- `GET  /api/sites` · `GET /api/sites/{id}` · `PATCH /api/sites/{id}`
- `GET  /api/stations` · `GET /api/stations/{id}`
- `GET  /api/readings` · `/api/readings/latest` · `/api/readings/timeseries`
- `GET  /api/alerts` · `POST /api/alerts/{id}/ack`
- `GET  /api/analytics/site/{id}` · `/api/analytics/summary`
- `POST /api/v1/readings` — real hardware ingestion (see
  `../backend-api-spec.md`); `X-Device-Key` header, auto-registers new
  `device_id`s under a fallback "unassigned" site
- `PATCH /api/stations/{id}` — admin provisioning, e.g. assign an
  auto-registered device to its real, calibrated site
- `POST /api/ingest` — legacy/simulator-shaped packet ingestion
- `WS   /ws` — live `reading` / `alert` broadcasts

## Deploy (Render — recommended)

This service needs a **long-running process** (WebSocket + background simulator),
so a serverless host like Vercel is **not** suitable. Render's free web service
is the right fit. See `../DEPLOYMENT.md` for full step-by-step instructions; the
included `render.yaml` blueprint automates it.
