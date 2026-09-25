"""Corridor infrastructure, fleet definitions, and timetable schedule generators."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass(frozen=True)
class StationDef:
    code: str
    name: str
    lat: float
    lon: float
    zone: str
    is_junction: bool
    km: float


# 15 Station Small Corridor Definition (NDLS -> MKA)
SMALL_CORRIDOR_STATIONS: list[StationDef] = [
    StationDef("NDLS", "New Delhi", 28.6415, 77.2194, "NR", True, 0.0),
    StationDef("GZB", "Ghaziabad Jn", 28.6679, 77.4332, "NR", True, 26.0),
    StationDef("ALJN", "Aligarh Jn", 27.8974, 78.0880, "NCR", True, 131.0),
    StationDef("TDL", "Tundla Jn", 27.2058, 78.2415, "NCR", True, 209.0),
    StationDef("ETW", "Etawah", 26.7855, 79.0255, "NCR", False, 300.0),
    StationDef("CNB", "Kanpur Central", 26.4539, 80.3507, "NCR", True, 440.0),
    StationDef("FTP", "Fatehpur", 25.9286, 80.8129, "NCR", False, 518.0),
    StationDef("PRYJ", "Prayagraj Jn", 25.4484, 81.8340, "NCR", True, 634.0),
    StationDef("MZP", "Mirzapur", 25.1464, 82.5694, "NCR", False, 723.0),
    StationDef("DDU", "Pt. DD Upadhyaya Jn", 25.2798, 83.1189, "ECR", True, 787.0),
    StationDef("BXR", "Buxar", 25.5647, 83.9774, "ECR", False, 881.0),
    StationDef("ARA", "Ara Jn", 25.5562, 84.6603, "ECR", True, 950.0),
    StationDef("PNBE", "Patna Jn", 25.6022, 85.1376, "ECR", True, 999.0),
    StationDef("BKP", "Bakhtiyarpur Jn", 25.4578, 85.5255, "ECR", True, 1045.0),
    StationDef("MKA", "Mokama Jn", 25.3942, 85.9189, "ECR", True, 1088.0),
]


@dataclass(frozen=True)
class TrainConfig:
    number: str
    name: str
    type: str
    priority_class: int
    source: str
    destination: str
    direction: str  # "DN" (NDLS->MKA) or "UP" (MKA->NDLS)
    origin_dep_time: time
    stops: list[str]  # Station codes where train scheduled to halt
    speed_factor: float  # Runtime multiplier relative to 130 km/h baseline
    default_dwell_min: float
    junction_dwell_min: float


SMALL_CORRIDOR_TRAINS: list[TrainConfig] = [
    # DOWN TRAINS (NDLS -> MKA/PNBE)
    TrainConfig(
        number="12002",
        name="Vande Bharat Express",
        type="Vande Bharat",
        priority_class=1,
        source="NDLS",
        destination="MKA",
        direction="DN",
        origin_dep_time=time(6, 0),
        stops=["NDLS", "GZB", "ALJN", "CNB", "PRYJ", "DDU", "PNBE", "MKA"],
        speed_factor=1.0,
        default_dwell_min=2.0,
        junction_dwell_min=5.0,
    ),
    TrainConfig(
        number="12302",
        name="Rajdhani Express",
        type="Rajdhani",
        priority_class=1,
        source="NDLS",
        destination="PNBE",
        direction="DN",
        origin_dep_time=time(16, 55),
        stops=["NDLS", "CNB", "PRYJ", "DDU", "PNBE"],
        speed_factor=1.0,
        default_dwell_min=5.0,
        junction_dwell_min=8.0,
    ),
    TrainConfig(
        number="12394",
        name="Sampark Kranti Superfast",
        type="Superfast",
        priority_class=2,
        source="NDLS",
        destination="MKA",
        direction="DN",
        origin_dep_time=time(17, 30),
        stops=["NDLS", "ALJN", "TDL", "CNB", "PRYJ", "MZP", "DDU", "ARA", "PNBE", "MKA"],
        speed_factor=1.08,
        default_dwell_min=3.0,
        junction_dwell_min=6.0,
    ),
    TrainConfig(
        number="13008",
        name="Toofan Express",
        type="Mail/Express",
        priority_class=3,
        source="NDLS",
        destination="MKA",
        direction="DN",
        origin_dep_time=time(7, 15),
        stops=[s.code for s in SMALL_CORRIDOR_STATIONS],  # All stops
        speed_factor=1.22,
        default_dwell_min=4.0,
        junction_dwell_min=8.0,
    ),
    TrainConfig(
        number="54302",
        name="Mahananda Passenger",
        type="Passenger",
        priority_class=4,
        source="NDLS",
        destination="MKA",
        direction="DN",
        origin_dep_time=time(5, 30),
        stops=[s.code for s in SMALL_CORRIDOR_STATIONS],  # All stops
        speed_factor=1.45,
        default_dwell_min=5.0,
        junction_dwell_min=10.0,
    ),
    # UP TRAINS (MKA/PNBE -> NDLS)
    TrainConfig(
        number="12001",
        name="Vande Bharat Express (Up)",
        type="Vande Bharat",
        priority_class=1,
        source="MKA",
        destination="NDLS",
        direction="UP",
        origin_dep_time=time(15, 30),
        stops=["MKA", "PNBE", "DDU", "PRYJ", "CNB", "ALJN", "GZB", "NDLS"],
        speed_factor=1.0,
        default_dwell_min=2.0,
        junction_dwell_min=5.0,
    ),
    TrainConfig(
        number="12301",
        name="Rajdhani Express (Up)",
        type="Rajdhani",
        priority_class=1,
        source="PNBE",
        destination="NDLS",
        direction="UP",
        origin_dep_time=time(19, 0),
        stops=["PNBE", "DDU", "PRYJ", "CNB", "NDLS"],
        speed_factor=1.0,
        default_dwell_min=5.0,
        junction_dwell_min=8.0,
    ),
    TrainConfig(
        number="12393",
        name="Sampark Kranti Superfast (Up)",
        type="Superfast",
        priority_class=2,
        source="MKA",
        destination="NDLS",
        direction="UP",
        origin_dep_time=time(8, 0),
        stops=["MKA", "PNBE", "ARA", "DDU", "MZP", "PRYJ", "CNB", "TDL", "ALJN", "NDLS"],
        speed_factor=1.08,
        default_dwell_min=3.0,
        junction_dwell_min=6.0,
    ),
    TrainConfig(
        number="13007",
        name="Toofan Express (Up)",
        type="Mail/Express",
        priority_class=3,
        source="MKA",
        destination="NDLS",
        direction="UP",
        origin_dep_time=time(6, 30),
        stops=list(reversed([s.code for s in SMALL_CORRIDOR_STATIONS])),  # All stops UP
        speed_factor=1.22,
        default_dwell_min=4.0,
        junction_dwell_min=8.0,
    ),
    TrainConfig(
        number="54301",
        name="Mahananda Passenger (Up)",
        type="Passenger",
        priority_class=4,
        source="MKA",
        destination="NDLS",
        direction="UP",
        origin_dep_time=time(9, 30),
        stops=list(reversed([s.code for s in SMALL_CORRIDOR_STATIONS])),  # All stops UP
        speed_factor=1.45,
        default_dwell_min=5.0,
        junction_dwell_min=10.0,
    ),
]


def build_corridor_sections(
    stations: list[StationDef],
) -> tuple[dict[str, float], list[dict]]:
    sections = []
    section_distance_lookup = {}

    # Build DOWN sections (S_i -> S_{i+1})
    for i in range(len(stations) - 1):
        s_from = stations[i]
        s_to = stations[i + 1]
        dist = round(s_to.km - s_from.km, 1)
        sec_id = f"{s_from.code}-{s_to.code}-DN"

        # Terminal and junction approaches have 100-110 kmph max line speed
        line_speed = 100.0 if (s_to.is_junction and s_to.code in {"NDLS", "CNB", "PRYJ", "DDU", "PNBE"}) else 130.0
        scheduled_runtime = round((dist / line_speed) * 60.0 + 2.0, 1)  # include 2 min signaling buffer

        sections.append({
            "id": sec_id,
            "from_station": s_from.code,
            "to_station": s_to.code,
            "distance_km": dist,
            "line_speed_kmph": line_speed,
            "scheduled_runtime_min": scheduled_runtime,
            "direction": "DN",
        })
        section_distance_lookup[(s_from.code, s_to.code)] = dist

    # Build UP sections (S_{i+1} -> S_i)
    for i in range(len(stations) - 1, 0, -1):
        s_from = stations[i]
        s_to = stations[i - 1]
        dist = round(s_from.km - s_to.km, 1)
        sec_id = f"{s_from.code}-{s_to.code}-UP"

        line_speed = 100.0 if (s_to.is_junction and s_to.code in {"NDLS", "CNB", "PRYJ", "DDU", "PNBE"}) else 130.0
        scheduled_runtime = round((dist / line_speed) * 60.0 + 2.0, 1)

        sections.append({
            "id": sec_id,
            "from_station": s_from.code,
            "to_station": s_to.code,
            "distance_km": dist,
            "line_speed_kmph": line_speed,
            "scheduled_runtime_min": scheduled_runtime,
            "direction": "UP",
        })
        section_distance_lookup[(s_from.code, s_to.code)] = dist

    return section_distance_lookup, sections


def build_train_schedules(
    trains: list[TrainConfig],
    stations: list[StationDef],
    sections_list: list[dict],
) -> list[dict]:
    """Generate static timetable schedules for each train along its halting stations."""
    station_lookup = {s.code: s for s in stations}
    section_map = {(sec["from_station"], sec["to_station"]): sec for sec in sections_list}

    all_schedules = []

    for train in trains:
        # Determine sequence of stations along train route
        route_stops = train.stops
        curr_time = datetime(2025, 1, 1, train.origin_dep_time.hour, train.origin_dep_time.minute)

        for seq_idx, st_code in enumerate(route_stops):
            st = station_lookup[st_code]
            if seq_idx == 0:
                # Origin
                sched_arr_str = None
                sched_dep_str = curr_time.strftime("%H:%M:%S")
            else:
                # Calculate scheduled runtime from previous halt
                prev_code = route_stops[seq_idx - 1]

                # Find all intermediate sections between prev_code and st_code
                if train.direction == "DN":
                    st_codes_ordered = [s.code for s in stations]
                    i_from = st_codes_ordered.index(prev_code)
                    i_to = st_codes_ordered.index(st_code)
                    step = 1
                else:
                    st_codes_ordered = list(reversed([s.code for s in stations]))
                    i_from = st_codes_ordered.index(prev_code)
                    i_to = st_codes_ordered.index(st_code)
                    step = 1

                runtime_min = 0.0
                for idx in range(i_from, i_to, step):
                    u = st_codes_ordered[idx]
                    v = st_codes_ordered[idx + 1]
                    sec = section_map[(u, v)]
                    runtime_min += sec["scheduled_runtime_min"] * train.speed_factor

                curr_time += timedelta(minutes=round(runtime_min))
                sched_arr_str = curr_time.strftime("%H:%M:%S")

                if seq_idx == len(route_stops) - 1:
                    # Destination
                    sched_dep_str = None
                else:
                    dwell = train.junction_dwell_min if st.is_junction else train.default_dwell_min
                    curr_time += timedelta(minutes=round(dwell))
                    sched_dep_str = curr_time.strftime("%H:%M:%S")

            all_schedules.append({
                "train_number": train.number,
                "station_code": st_code,
                "seq": seq_idx + 1,
                "sched_arr": sched_arr_str,
                "sched_dep": sched_dep_str,
            })

    return all_schedules
