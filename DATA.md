# DATA.md — Corridor Specification & Simulation Methodology (SIH26028)

> **Honesty Notice:** All datasets, schedules, and disruption events documented herein are generated via mechanistic simulation. While they accurately reflect operating principles, timetables, and operational disturbances of Indian Railways trunk routes, they are synthetic and should not be represented as actual historical NTES telemetry.

---

## 1. Corridor Geography & Infrastructure

The simulated corridor models the high-density double-track electrified trunk route connecting the Northern Railway (NR), North Central Railway (NCR), and East Central Railway (ECR) zones, representing the **New Delhi to Mokama via Kanpur, Prayagraj, and Patna** mainline.

### 1.1 Stations (Small Preset: 15 Stations)

| Code | Station Name | Zone | Latitude | Longitude | Cumulative Km | Classification |
|---|---|---|---|---|---|---|
| `NDLS` | New Delhi | NR | 28.6415 | 77.2194 | 0.0 | Major Terminal Junction |
| `GZB` | Ghaziabad Jn | NR | 28.6679 | 77.4332 | 26.0 | Major Junction |
| `ALJN` | Aligarh Jn | NCR | 27.8974 | 78.0880 | 131.0 | Junction |
| `TDL` | Tundla Jn | NCR | 27.2058 | 78.2415 | 209.0 | Junction |
| `ETW` | Etawah | NCR | 26.7855 | 79.0255 | 300.0 | Intermediate Station |
| `CNB` | Kanpur Central | NCR | 26.4539 | 80.3507 | 440.0 | Major Terminal Junction |
| `FTP` | Fatehpur | NCR | 25.9286 | 80.8129 | 518.0 | Intermediate Station |
| `PRYJ` | Prayagraj Jn | NCR | 25.4484 | 81.8340 | 634.0 | Major Terminal Junction |
| `MZP` | Mirzapur | NCR | 25.1464 | 82.5694 | 723.0 | Intermediate Station |
| `DDU` | Pt. DD Upadhyaya Jn | ECR | 25.2798 | 83.1189 | 787.0 | Major Freight Yard & Junction |
| `BXR` | Buxar | ECR | 25.5647 | 83.9774 | 881.0 | Intermediate Station |
| `ARA` | Ara Jn | ECR | 25.5562 | 84.6603 | 950.0 | Junction |
| `PNBE` | Patna Jn | ECR | 25.6022 | 85.1376 | 999.0 | Major Terminal Junction |
| `BKP` | Bakhtiyarpur Jn | ECR | 25.4578 | 85.5255 | 1045.0 | Junction |
| `MKA` | Mokama Jn | ECR | 25.3942 | 85.9189 | 1088.0 | Terminal Junction |

### 1.2 Sections & Track Geometry
- **Double Track**: 14 directional sections in DOWN direction (`NDLS` $\rightarrow$ `MKA`) and 14 directional sections in UP direction (`MKA` $\rightarrow$ `NDLS`), totaling 28 mainline sections.
- **Maximum Permissible Speed (MPS)**:
  - Open route: $130\text{ km/h}$.
  - Approaches to major terminal junctions (`NDLS`, `CNB`, `PRYJ`, `DDU`, `PNBE`): $100\text{ km/h}$.
- **Scheduled Section Runtime**:
  $$\text{Scheduled Runtime (min)} = \left(\frac{\text{Distance (km)}}{\text{Line Speed (km/h)}} \times 60\right) + 2.0\text{ min buffer}$$

---

## 2. Train Fleet & Priority Hierarchy

The simulator runs 10 daily coaching trains (5 DOWN, 5 UP) across 4 distinct operational priority classes:

| Train No | Name | Class | Direction | Origin Dep | Halts | Speed Factor | Dwell Policy (min) |
|---|---|---|---|---|---|---|---|
| `12002` | Vande Bharat Express | 1 (Premium) | DN | 06:00 | 8 halts | $1.00$ | 2 min (CNB/PRYJ: 5 min) |
| `12302` | Rajdhani Express | 1 (Premium) | DN | 16:55 | 5 halts | $1.00$ | 5 min (Junctions: 8 min) |
| `12394` | Sampark Kranti SF | 2 (Superfast) | DN | 17:30 | 10 halts | $1.08$ | 3 min (Junctions: 6 min) |
| `13008` | Toofan Express | 3 (Mail/Exp) | DN | 07:15 | All 15 | $1.22$ | 4 min (Junctions: 8 min) |
| `54302` | Mahananda Passenger | 4 (Ordinary) | DN | 05:30 | All 15 | $1.45$ | 5 min (Junctions: 10 min) |
| `12001` | Vande Bharat (Up) | 1 (Premium) | UP | 15:30 | 8 halts | $1.00$ | 2 min (CNB/PRYJ: 5 min) |
| `12301` | Rajdhani Express (Up) | 1 (Premium) | UP | 19:00 | 5 halts | $1.00$ | 5 min (Junctions: 8 min) |
| `12393` | Sampark Kranti SF (Up) | 2 (Superfast) | UP | 08:00 | 10 halts | $1.08$ | 3 min (Junctions: 6 min) |
| `13007` | Toofan Express (Up) | 3 (Mail/Exp) | UP | 06:30 | All 15 | $1.22$ | 4 min (Junctions: 8 min) |
| `54301` | Mahananda Pass. (Up) | 4 (Ordinary) | UP | 09:30 | All 15 | $1.45$ | 5 min (Junctions: 10 min) |

---

## 3. Mechanistic Delay Modeling

Rather than inject white noise, delays are generated deterministically and mechanistically:

### 3.1 Seasonal Winter Fog (December 15 – January 20)
- **Time Window**: Active on ~70% of winter nights between 22:00 and 09:00 across northern gangetic sections (`NDLS` through `DDU`).
- **Impact**: Reduces speed capability by $40\%\text{–}60\%$, adding $20\%\text{–}40\%$ extra transit time to affected sections.

### 3.2 Temporary Speed Restrictions (TSR)
- **Duration**: Active maintenance and track renewal caution orders spanning 3–7 consecutive days on random sections.
- **Impact**: Speed restricted to $30\text{–}50\text{ km/h}$, imposing $4.0\text{–}10.0\text{ min}$ of section delay per passing train.
- Logged in the `disruptions` entity with `type = "TSR"` and active timestamps.

### 3.3 Peak-Hour Junction Congestion
- **Hubs**: `NDLS`, `CNB`, `PRYJ`, `DDU`, `PNBE`.
- **Peak Windows**: Morning (07:00–10:00) and Evening (17:00–21:00).
- **Impact**: Approach signaling hold and platform reoccupation delay adding $6.0\text{–}20.0\text{ min}$ upon arrival.

### 3.4 Preceding-Train Safety Headway & Knock-on Delays
- **Safety Headway**: Minimum $5\text{–}6\text{ minutes}$ between train entries on the same directional section.
- **Propagation**: If train $A$ is delayed on section $S$, trailing train $B$ must hold until the headway interval is restored, inheriting knock-on delay.

### 3.5 Dwell Time Overruns
- Modeled with a log-normal passenger boarding distribution:
  $$\text{Dwell} = \text{Base Dwell} + \max(0, \text{Lognormal}(0, 0.4) - 0.9)$$
  producing typical extensions of $1\text{–}5\text{ min}$ during passenger surges.

### 3.6 Recovery Margin / Slack Absorption
- Priority 1 and 2 trains have built-in schedule padding allowing $3\%\text{–}5\%$ recovery of runtime on clear sections with no active disruptions or headways.

---

## 4. Database Schema Entities

All entities are mapped to SQLAlchemy 2.0 models in `src/db/models.py`:

```
stations (code [PK], name, lat, lon, zone, is_junction)
    │
    ├─< sections (id [PK], from_station [FK], to_station [FK], distance_km, line_speed_kmph, scheduled_runtime_min, direction)
    │       │
    │       └─< disruptions (id [PK], section_id [FK], type, start_time, end_time, severity)
    │
    └─< schedules (train_number [PK, FK], station_code [PK, FK], seq, sched_arr, sched_dep)
            ▲
trains (number [PK], name, type, priority_class, source [FK], destination [FK])
    │
    └─< runs (run_id [PK], train_number [FK], run_date)
            │
            ├─< run_events (run_id [PK, FK], station_code [PK, FK], seq, actual_arr, actual_dep, arr_delay_min, dwell_min)
            └─< live_status (run_id [PK, FK], ts [PK], current_station, next_station, current_section, current_delay_min, speed_kmph, lat, lon)
```

---

## 5. Reproducibility & Generation

To regenerate the dataset from scratch:

```bash
# Standard 90-day simulation with seed 42
python -m src.simulator.generator --seed 42 --days 90 --corridor small --start-date 2025-11-01
```

### Row Count Verification (90-day small preset):
- `stations`: 15
- `sections`: 28
- `trains`: 10
- `schedules`: 106
- `runs`: 900
- `run_events`: 9,540
- `disruptions`: 466
- `live_status`: 900
