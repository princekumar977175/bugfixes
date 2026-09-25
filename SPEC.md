# SPEC.md — Dynamic ETA Forecast for Coaching Trains (SIH26028)

> Read this file fully before writing any code. Work one phase at a time. Do not start a phase until the previous phase's acceptance criteria pass.

## 1. Project summary

Smart India Hackathon 2026, problem statement **SIH26028**: *Dynamic Forecast of Expected Time of Arrival (ETA) for Coaching Trains* (Ministry of Railways, Software, Smart Automation).

Today, ETAs at intermediate and destination stations are mostly derived from the static schedule, the current delay and built-in recovery time. They do not reflect real conditions such as temporary speed restrictions, congestion, signal halts, unscheduled stoppages, delays of preceding trains, or historical patterns.

**Goal:** build a system that continuously recomputes the ETA for every remaining station of a running train, gives an uncertainty range, explains why the ETA changed, and shows how one train's delay affects trains behind it.

**Primary users:** control-room staff / section controllers, station staff, and passengers.

## 2. Scope

### In scope
- Synthetic-but-realistic data generator for one corridor (see Section 4)
- Baseline ETA methods and an ML forecasting model
- Section-by-section delay propagation along the remaining route
- Prediction intervals (lower / median / upper ETA)
- Human-readable explanation of ETA changes
- FastAPI backend with REST + WebSocket live updates
- React dashboard with a control-room view and a passenger view
- Evaluation report comparing the model to baselines
- Replay simulator that streams historical runs as if they were live

### Out of scope
- Real NTES / live railway feeds (not available; do not fake them)
- User accounts, payments, ticketing
- Mobile apps

### Honesty rule
All data is **simulated or replayed** unless a real dataset is explicitly added later. The UI and README must label it as such. Never present synthetic results as real Indian Railways performance.

## 3. Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+, TypeScript |
| Backend | FastAPI, Uvicorn, WebSockets |
| Database | SQLite for dev; PostgreSQL-compatible SQL (SQLAlchemy) |
| ML | pandas, scikit-learn, LightGBM (or XGBoost), SHAP |
| Frontend | React + Vite + TypeScript, Leaflet for the map, a small charting lib (Recharts) |
| Tests | pytest, httpx for API tests |
| Packaging | `requirements.txt`, `.env.example`, optional Docker Compose |

## 4. Data design

### Entities
- `stations(code, name, lat, lon, zone)`
- `sections(id, from_station, to_station, distance_km, line_speed_kmph, scheduled_runtime_min)`
- `trains(number, name, type, priority_class, source, destination)`
- `schedules(train_number, station_code, seq, sched_arr, sched_dep)`
- `runs(run_id, train_number, run_date)`
- `run_events(run_id, station_code, seq, actual_arr, actual_dep, arr_delay_min, dwell_min)`
- `disruptions(id, section_id, type, start_time, end_time, severity)` — types: `TSR`, `signal_halt`, `congestion`, `weather`, `maintenance_block`
- `live_status(run_id, ts, current_station, next_station, current_section, current_delay_min, speed_kmph, lat, lon)`

### Simulator requirements
- One corridor of roughly 30–40 stations with ~150+ block sections, both directions.
- 25–40 trains across priority classes (e.g., premium, superfast, express, mail, slow).
- 6–12 months of daily runs.
- Delay causes must be modeled, not random noise: seasonal fog, TSRs on specific sections, junction congestion at peak hours, headway effects from a delayed preceding train, dwell overruns, recovery slack.
- Seedable (`--seed`) so results are reproducible.
- Write assumptions to `DATA.md` so judges can see how the data was made.

## 5. ML design

### Targets
- Primary: **extra delay added in each remaining section** (minutes), from which station ETAs are built by cumulative sum.

### Features (only what is known at prediction time)
Section id and length, line speed, scheduled runtime, time of day, day of week, month/season, train class, current delay, delay trend over the last N sections, dwell at last station, delay of preceding train on the same section, active disruption flags and severity, historical mean/std delay for that section and hour.

### Rules
- **Split by time** (train on earlier dates, validate and test on later dates). Never random-split.
- No leakage: no feature may use information from after the prediction moment (for example, the actual arrival at the station being predicted).
- Historical aggregates must be computed on the training period only.
- Quantile models for the 10th, 50th and 90th percentiles; report interval coverage.

### Propagation
For a train at section *k*, predict delays for sections *k+1 … n* iteratively, updating the running delay after each section. Optionally estimate the knock-on delay to following trains on the same section.

### Explainability
Use SHAP (or a rule-based fallback) to produce the top 3 drivers per ETA change, then convert them to text such as: `ETA moved +12 min: speed restriction in section X, congestion at junction Y`. Store an ETA change log per train.

## 6. API design

- `GET /health`
- `GET /trains` — list running trains with current delay
- `GET /trains/{run_id}/eta` — ETA (lower / median / upper) for all remaining stations, plus baseline ETA for comparison
- `GET /trains/{run_id}/explain` — reasons for the latest ETA change
- `GET /sections/{id}/disruptions`
- `POST /replay/start`, `POST /replay/pause`, `POST /replay/speed` — control the simulator
- `WS /ws/trains/{run_id}` — push ETA updates as replay time advances
- Add Pydantic schemas for all request/response models and OpenAPI docs.

## 7. Frontend design

**Control-room view:** map with train positions, delay heatmap by section, table of trains sorted by delay, disruption markers, downstream-impact risk (low / medium / high), replay controls.

**Passenger view:** search by train number, live ETA with range, "why did this change" panel, timeline of upcoming stations, optional "alert me before arrival" toggle.

Show a visible **"Simulated data"** badge on both views.

## 8. Repository structure

```
sih26028-eta/
├── README.md
├── SPEC.md
├── DATA.md
├── requirements.txt
├── .env.example
├── data/                # generated data (gitignored except samples)
├── src/
│   ├── simulator/       # data generator + replay engine
│   ├── db/              # models, session, migrations
│   ├── features/        # feature engineering
│   ├── models/          # baselines, training, inference, propagation
│   ├── explain/         # SHAP + text reasons
│   └── api/             # FastAPI app, routes, schemas, websockets
├── notebooks/           # optional EDA
├── reports/             # evaluation outputs (tables, plots)
├── tests/
└── frontend/            # React + Vite app
```

## 9. Build plan and acceptance criteria

### Phase 0 — Scaffold
Create the repo structure, virtualenv, `requirements.txt`, lint config, and a passing `pytest` smoke test.
**Done when:** `pytest` runs green and `uvicorn` serves `/health`.

### Phase 1 — Database and simulator
Implement the schema and the seeded data generator.
**Done when:** one command generates the dataset, row counts are printed, delays show realistic patterns (fog season, peak-hour congestion), and `DATA.md` documents the assumptions.

### Phase 2 — Baselines
Implement (a) `scheduled + current_delay`, (b) section-wise `distance/speed + mean historical delay`.
**Done when:** a script prints MAE by number of stations ahead for both baselines on the test period.

### Phase 3 — Features and model
Build the feature pipeline and train the LightGBM model with a time-based split.
**Done when:** the model beats both baselines on test MAE, a leakage-check test exists, and the model is saved to disk with a version tag.

### Phase 4 — Propagation and uncertainty
Add iterative downstream prediction and quantile models.
**Done when:** `predict_eta(run_id, timestamp)` returns lower/median/upper for every remaining station, and the 10–90 interval covers roughly 80% of actual arrivals on the test set.

### Phase 5 — Explainability
Add SHAP-based drivers and the text reason generator.
**Done when:** every ETA update returns at least one plain-language reason, and reasons are stored in a change log.

### Phase 6 — API
Implement the REST and WebSocket endpoints with schemas and tests.
**Done when:** API tests pass and a WebSocket client receives ETA updates while replay runs.

### Phase 7 — Frontend
Build the control-room and passenger views against the API.
**Done when:** starting a replay shows moving trains, live ETA changes, and explanations without a page refresh.

### Phase 8 — Evaluation report
Generate `reports/evaluation.md` with MAE/RMSE by forecast horizon and by train class, model vs baselines, interval coverage, and 2–3 case studies of a disruption.
**Done when:** the report and plots regenerate with one command.

### Phase 9 — Polish and delivery
README with setup steps, architecture diagram, screenshots, deployment (or Docker Compose), and a demo script for the video.
**Done when:** a fresh clone can be run by following the README only.

## 10. Rules for the coding agent

1. Work on one phase at a time. At the end of each phase, summarize what changed and what to check.
2. Write tests alongside code. Do not mark a phase done if tests fail.
3. Keep functions small and typed. Put config values in `.env` or a config module, never hard-code them.
4. Do not invent real-world facts (train numbers, real delay statistics). Use clearly synthetic or clearly sourced data.
5. Never use a random split or any future information for training. If unsure about leakage, stop and ask.
6. Before installing a new dependency, check if an existing one already covers the need.
7. Do not rewrite working modules without a reason. Prefer small diffs.
8. When a requirement is ambiguous, list the assumption you made in the phase summary instead of guessing silently.

## 11. Demo story (for the video)

1. A train is running on time and the passenger view shows its ETA.
2. A speed restriction or congestion event appears on a section ahead.
3. The ETA updates live, with a wider range and a plain-language reason.
4. The control room sees the knock-on risk for the trains behind.
5. Show the evaluation chart: the model's error is lower than the static-schedule method.
