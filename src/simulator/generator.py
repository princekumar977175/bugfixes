"""Synthetic corridor dataset generator with realistic disruption and headway modeling."""

import argparse
import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.db.models import Disruption, LiveStatus, Run, RunEvent, Schedule, Section, Station, Train
from src.db.session import get_engine, init_db
from src.simulator.corridor import (
    SMALL_CORRIDOR_STATIONS,
    SMALL_CORRIDOR_TRAINS,
    StationDef,
    TrainConfig,
    build_corridor_sections,
    build_train_schedules,
)


def parse_time_str(t_str: str | None) -> time | None:
    if not t_str:
        return None
    parts = [int(p) for p in t_str.split(":")]
    return time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)


class CorridorSimulator:
    """Simulates train traffic across multi-month periods with mechanistic delay models."""

    def __init__(
        self,
        seed: int = 42,
        stations: list[StationDef] | None = None,
        trains: list[TrainConfig] | None = None,
    ):
        self.seed = seed
        self.rng = random.Random(seed)
        self.stations = stations or SMALL_CORRIDOR_STATIONS
        self.trains = trains or SMALL_CORRIDOR_TRAINS
        self.section_dist_map, self.sections = build_corridor_sections(self.stations)
        self.schedules = build_train_schedules(self.trains, self.stations, self.sections)

        self.station_map = {s.code: s for s in self.stations}
        self.section_map = {(sec["from_station"], sec["to_station"]): sec for sec in self.sections}
        self.train_map = {t.number: t for t in self.trains}

    def generate_disruptions(
        self,
        start_date: date,
        num_days: int,
    ) -> list[dict]:
        """Generate stochastic multi-day TSRs and winter weather disruption periods."""
        disruptions = []
        end_date = start_date + timedelta(days=num_days)

        # 1. Seasonal Winter Fog Window: Dec 15 to Jan 20
        fog_start = date(2025, 12, 15)
        fog_end = date(2026, 1, 20)

        # Fog disruption covers Northern/NCR sections (NDLS to DDU)
        ncr_sections = [
            sec["id"] for sec in self.sections
            if any(st in sec["id"] for st in ["NDLS", "GZB", "ALJN", "TDL", "ETW", "CNB", "FTP", "PRYJ", "DDU"])
        ]

        curr_d = start_date
        while curr_d < end_date:
            if fog_start <= curr_d <= fog_end:
                # Night/early morning fog window
                fog_window_start = datetime.combine(curr_d, time(22, 0))
                fog_window_end = datetime.combine(curr_d + timedelta(days=1), time(9, 0))
                # Fog occurs on ~70% of winter nights
                if self.rng.random() < 0.70:
                    for sec_id in ncr_sections:
                        disruptions.append({
                            "id": f"DIS_FOG_{curr_d}_{sec_id}",
                            "section_id": sec_id,
                            "type": "weather",
                            "start_time": fog_window_start,
                            "end_time": fog_window_end,
                            "severity": round(self.rng.uniform(0.40, 0.60), 2),  # drops speed by 40-60%
                        })
            curr_d += timedelta(days=1)

        # 2. Temporary Speed Restrictions (TSRs): 3-7 day track maintenance zones
        num_tsrs = max(2, num_days // 15)
        for i in range(num_tsrs):
            target_sec = self.rng.choice(self.sections)
            tsr_start_day = self.rng.randint(0, max(0, num_days - 7))
            tsr_duration = self.rng.randint(3, 7)
            t_start = datetime.combine(start_date + timedelta(days=tsr_start_day), time(6, 0))
            t_end = datetime.combine(start_date + timedelta(days=tsr_start_day + tsr_duration), time(18, 0))
            disruptions.append({
                "id": f"DIS_TSR_{i}_{target_sec['id']}",
                "section_id": target_sec["id"],
                "type": "TSR",
                "start_time": t_start,
                "end_time": t_end,
                "severity": round(self.rng.uniform(0.35, 0.55), 2),  # 30-50 km/h restriction
            })

        return disruptions

    def simulate(
        self,
        start_date: date,
        num_days: int = 90,
    ) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
        """Simulate all train runs across the specified date range."""
        disruptions = self.generate_disruptions(start_date, num_days)

        # Build index of active disruptions per section for fast lookup
        disruption_by_section: dict[str, list[dict]] = {}
        for d in disruptions:
            disruption_by_section.setdefault(d["section_id"], []).append(d)

        runs = []
        run_events = []
        live_statuses = []

        # Headway tracker: track occupancy intervals by (from_station, to_station) -> list of (entry_time, exit_time, priority)
        section_occupancies: dict[tuple[str, str], list[tuple[datetime, datetime, int]]] = {}

        for day_offset in range(num_days):
            current_date = start_date + timedelta(days=day_offset)

            # Sort trains by scheduled origin departure time so we simulate chronologically
            train_order = sorted(self.trains, key=lambda t: t.origin_dep_time)

            for train in train_order:
                run_id = f"{train.number}_{current_date.strftime('%Y%m%d')}"
                runs.append({
                    "run_id": run_id,
                    "train_number": train.number,
                    "run_date": current_date,
                })

                train_scheds = [
                    s for s in self.schedules if s["train_number"] == train.number
                ]
                train_scheds.sort(key=lambda s: s["seq"])

                # Determine origin departure
                origin_sched_dep_str = train_scheds[0]["sched_dep"]
                origin_time = parse_time_str(origin_sched_dep_str)
                origin_dt = datetime.combine(current_date, origin_time)

                # Origin punctuality: small random initial dispatch variation (-1 to +4 min)
                initial_delay = self.rng.choice([0, 0, 0, 1, 2])
                current_actual_dep = origin_dt + timedelta(minutes=initial_delay)

                # Record origin event
                run_events.append({
                    "run_id": run_id,
                    "station_code": train_scheds[0]["station_code"],
                    "seq": 1,
                    "actual_arr": None,
                    "actual_dep": current_actual_dep,
                    "arr_delay_min": 0.0,
                    "dwell_min": 0.0,
                })

                prev_actual_dep = current_actual_dep
                sched_dt_cursor = origin_dt

                # Simulate progress through consecutive route halts
                for s_idx in range(1, len(train_scheds)):
                    prev_stop_code = train_scheds[s_idx - 1]["station_code"]
                    curr_stop_code = train_scheds[s_idx]["station_code"]
                    seq_num = train_scheds[s_idx]["seq"]

                    # 1. Calculate scheduled arrival datetime
                    sched_arr_str = train_scheds[s_idx]["sched_arr"]
                    sched_arr_time = parse_time_str(sched_arr_str)

                    # Handle day rollover in static schedule
                    sched_arr_dt = datetime.combine(sched_dt_cursor.date(), sched_arr_time)
                    if sched_arr_dt < sched_dt_cursor:
                        sched_arr_dt += timedelta(days=1)
                    sched_dt_cursor = sched_arr_dt

                    # 2. Determine section path between consecutive halts
                    if train.direction == "DN":
                        st_codes_ordered = [s.code for s in self.stations]
                        i_from = st_codes_ordered.index(prev_stop_code)
                        i_to = st_codes_ordered.index(curr_stop_code)
                        step = 1
                    else:
                        st_codes_ordered = list(reversed([s.code for s in self.stations]))
                        i_from = st_codes_ordered.index(prev_stop_code)
                        i_to = st_codes_ordered.index(curr_stop_code)
                        step = 1

                    sec_entry_time = prev_actual_dep

                    for idx in range(i_from, i_to, step):
                        u = st_codes_ordered[idx]
                        v = st_codes_ordered[idx + 1]
                        sec = self.section_map[(u, v)]
                        sec_id = sec["id"]
                        base_sec_runtime = sec["scheduled_runtime_min"] * train.speed_factor

                        # Check Headway: section is occupied if another train entered before sec_entry_time
                        # and has not yet cleared plus 5-minute safety headway
                        sec_key = (u, v)
                        existing_occupancies = section_occupancies.get(sec_key, [])
                        headway_delay_min = 0.0

                        for occ_in, occ_out, occ_prio in existing_occupancies:
                            # Conflict only if other train entered before or at sec_entry_time
                            # and is still in section or clearing headway
                            if occ_in <= sec_entry_time < (occ_out + timedelta(minutes=5)):
                                # Precedence: if current train has lower or equal priority (numerically >=)
                                if train.priority_class >= occ_prio:
                                    min_free_time = occ_out + timedelta(minutes=5)
                                    wait_min = (min_free_time - sec_entry_time).total_seconds() / 60.0
                                    headway_delay_min = max(headway_delay_min, wait_min)
                                    sec_entry_time = min_free_time

                        # Check Disruptions on this section (Fog, TSR)
                        disruption_delay_min = 0.0
                        active_disruptions = disruption_by_section.get(sec_id, [])
                        for dis in active_disruptions:
                            if dis["start_time"] <= sec_entry_time <= dis["end_time"]:
                                if dis["type"] == "weather":  # Fog
                                    disruption_delay_min += base_sec_runtime * self.rng.uniform(0.20, 0.40)
                                elif dis["type"] == "TSR":
                                    disruption_delay_min += self.rng.uniform(4.0, 10.0)

                        # Recovery margin: priority 1 & 2 trains can absorb minor delays on clear sections
                        recovery_min = 0.0
                        if train.priority_class <= 2 and disruption_delay_min == 0.0 and headway_delay_min == 0.0:
                            recovery_min = base_sec_runtime * 0.05

                        effective_sec_runtime = max(2.0, base_sec_runtime + disruption_delay_min - recovery_min)
                        sec_exit_time = sec_entry_time + timedelta(minutes=effective_sec_runtime)

                        # Record this train's occupancy interval
                        section_occupancies.setdefault(sec_key, []).append((sec_entry_time, sec_exit_time, train.priority_class))
                        # Prune past occupancies older than 12 hours
                        cutoff = sec_entry_time - timedelta(hours=12)
                        section_occupancies[sec_key] = [
                            occ for occ in section_occupancies[sec_key] if occ[1] >= cutoff
                        ]

                        sec_entry_time = sec_exit_time

                    actual_arr_dt = sec_exit_time

                    # 3. Peak-hour junction congestion delay on approach to major hubs
                    curr_station = self.station_map[curr_stop_code]
                    congestion_delay_min = 0.0
                    if curr_station.is_junction and curr_station.code in {"NDLS", "CNB", "PRYJ", "DDU", "PNBE"}:
                        arr_hour = actual_arr_dt.hour
                        if (7 <= arr_hour <= 10) or (17 <= arr_hour <= 21):
                            # Peak hour platform/approach congestion
                            congestion_delay_min = self.rng.uniform(6.0, 18.0)
                            actual_arr_dt += timedelta(minutes=congestion_delay_min)

                    # Calculate arrival delay relative to scheduled arrival datetime
                    arr_delay_min = round((actual_arr_dt - sched_arr_dt).total_seconds() / 60.0, 1)

                    # 4. Station Dwell Time & Departure
                    is_destination = (s_idx == len(train_scheds) - 1)
                    if is_destination:
                        actual_dep_dt = None
                        dwell_min = 0.0
                    else:
                        base_dwell = train.junction_dwell_min if curr_station.is_junction else train.default_dwell_min
                        # Lognormal passenger surge dwell overrun
                        dwell_overrun = self.rng.lognormvariate(0.0, 0.4) - 0.9
                        actual_dwell = max(base_dwell, round(base_dwell + max(0.0, dwell_overrun), 1))

                        # Scheduled departure datetime
                        sched_dep_str = train_scheds[s_idx]["sched_dep"]
                        sched_dep_time = parse_time_str(sched_dep_str)
                        sched_dep_dt = datetime.combine(sched_arr_dt.date(), sched_dep_time)
                        if sched_dep_dt < sched_arr_dt:
                            sched_dep_dt += timedelta(days=1)

                        # Lower-priority trains (class 3 & 4) held on loop lines at junction stations
                        # when a higher-priority train is operating on the route behind them
                        loop_delay = 0.0
                        if train.priority_class >= 3 and curr_station.is_junction:
                            # 20% chance of being looped for 10-20 min for precedence clearance
                            if self.rng.random() < 0.25:
                                loop_delay = self.rng.uniform(10.0, 22.0)

                        min_dep_dt = actual_arr_dt + timedelta(minutes=actual_dwell + loop_delay)

                        # Punctuality Rule: Train NEVER departs before scheduled departure time
                        actual_dep_dt = max(min_dep_dt, sched_dep_dt)
                        dwell_min = round((actual_dep_dt - actual_arr_dt).total_seconds() / 60.0, 1)

                        sched_dt_cursor = sched_dep_dt
                        prev_actual_dep = actual_dep_dt

                    run_events.append({
                        "run_id": run_id,
                        "station_code": curr_stop_code,
                        "seq": seq_num,
                        "actual_arr": actual_arr_dt,
                        "actual_dep": actual_dep_dt,
                        "arr_delay_min": arr_delay_min,
                        "dwell_min": dwell_min,
                    })

                # Snapshot final checkpoint for live_status
                last_event = run_events[-1]
                last_st = self.station_map[last_event["station_code"]]
                live_statuses.append({
                    "run_id": run_id,
                    "ts": last_event["actual_arr"] or last_event["actual_dep"],
                    "current_station": last_event["station_code"],
                    "next_station": None,
                    "current_section": None,
                    "current_delay_min": last_event["arr_delay_min"],
                    "speed_kmph": 0.0,
                    "lat": last_st.lat,
                    "lon": last_st.lon,
                })

        return runs, run_events, disruptions, live_statuses


def populate_database(
    db_session: Session,
    simulator: CorridorSimulator,
    start_date: date,
    num_days: int = 90,
) -> dict[str, int]:
    """Populate database tables with infrastructure, schedules, disruptions, and simulated runs."""
    # 1. Clear existing records to ensure fresh seeded run
    db_session.execute(delete(LiveStatus))
    db_session.execute(delete(RunEvent))
    db_session.execute(delete(Run))
    db_session.execute(delete(Disruption))
    db_session.execute(delete(Schedule))
    db_session.execute(delete(Train))
    db_session.execute(delete(Section))
    db_session.execute(delete(Station))
    db_session.flush()

    # 2. Insert Stations
    stations_to_add = [
        Station(
            code=s.code,
            name=s.name,
            lat=s.lat,
            lon=s.lon,
            zone=s.zone,
            is_junction=s.is_junction,
        )
        for s in simulator.stations
    ]
    db_session.add_all(stations_to_add)
    db_session.flush()

    # 3. Insert Sections
    sections_to_add = [
        Section(
            id=sec["id"],
            from_station=sec["from_station"],
            to_station=sec["to_station"],
            distance_km=sec["distance_km"],
            line_speed_kmph=sec["line_speed_kmph"],
            scheduled_runtime_min=sec["scheduled_runtime_min"],
            direction=sec["direction"],
        )
        for sec in simulator.sections
    ]
    db_session.add_all(sections_to_add)
    db_session.flush()

    # 4. Insert Trains
    trains_to_add = [
        Train(
            number=t.number,
            name=t.name,
            type=t.type,
            priority_class=t.priority_class,
            source=t.source,
            destination=t.destination,
        )
        for t in simulator.trains
    ]
    db_session.add_all(trains_to_add)
    db_session.flush()

    # 5. Insert Schedules
    schedules_to_add = [
        Schedule(
            train_number=sch["train_number"],
            station_code=sch["station_code"],
            seq=sch["seq"],
            sched_arr=sch["sched_arr"],
            sched_dep=sch["sched_dep"],
        )
        for sch in simulator.schedules
    ]
    db_session.add_all(schedules_to_add)
    db_session.flush()

    # 6. Simulate operational runs and disruptions
    runs_data, events_data, disruptions_data, live_data = simulator.simulate(start_date, num_days)

    db_session.add_all([
        Disruption(
            id=d["id"],
            section_id=d["section_id"],
            type=d["type"],
            start_time=d["start_time"],
            end_time=d["end_time"],
            severity=d["severity"],
        )
        for d in disruptions_data
    ])

    db_session.add_all([
        Run(
            run_id=r["run_id"],
            train_number=r["train_number"],
            run_date=r["run_date"],
        )
        for r in runs_data
    ])
    db_session.flush()

    # Batch insert run_events
    BATCH_SIZE = 5000
    for i in range(0, len(events_data), BATCH_SIZE):
        batch = events_data[i : i + BATCH_SIZE]
        db_session.add_all([
            RunEvent(
                run_id=e["run_id"],
                station_code=e["station_code"],
                seq=e["seq"],
                actual_arr=e["actual_arr"],
                actual_dep=e["actual_dep"],
                arr_delay_min=e["arr_delay_min"],
                dwell_min=e["dwell_min"],
            )
            for e in batch
        ])
        db_session.flush()

    db_session.add_all([
        LiveStatus(
            run_id=ls["run_id"],
            ts=ls["ts"],
            current_station=ls["current_station"],
            next_station=ls["next_station"],
            current_section=ls["current_section"],
            current_delay_min=ls["current_delay_min"],
            speed_kmph=ls["speed_kmph"],
            lat=ls["lat"],
            lon=ls["lon"],
        )
        for ls in live_data
    ])

    db_session.commit()

    # Return counts
    counts = {
        "stations": db_session.scalar(select(func.count(Station.code))),
        "sections": db_session.scalar(select(func.count(Section.id))),
        "trains": db_session.scalar(select(func.count(Train.number))),
        "schedules": db_session.scalar(select(func.count(Schedule.train_number))),
        "runs": db_session.scalar(select(func.count(Run.run_id))),
        "run_events": db_session.scalar(select(func.count(RunEvent.run_id))),
        "disruptions": db_session.scalar(select(func.count(Disruption.id))),
        "live_status": db_session.scalar(select(func.count(LiveStatus.run_id))),
    }
    return counts


def main():
    parser = argparse.ArgumentParser(description="Corridor synthetic dataset generator.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    parser.add_argument("--days", type=int, default=90, help="Number of operational days to simulate.")
    parser.add_argument("--start-date", type=str, default="2025-11-01", help="Start date (YYYY-MM-DD).")
    parser.add_argument("--corridor", type=str, default="small", choices=["small", "full"], help="Corridor preset size.")
    parser.add_argument("--db-url", type=str, default=None, help="Database connection URL.")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start_date)
    print(f"Initializing Corridor Simulator (seed={args.seed}, days={args.days}, start={start_date}, preset={args.corridor})...")

    sim = CorridorSimulator(seed=args.seed)

    engine = get_engine(args.db_url)
    init_db(engine)

    with Session(engine) as session:
        counts = populate_database(session, sim, start_date=start_date, num_days=args.days)

    print("\nGeneration Complete! Database Table Row Counts:")
    print("-" * 40)
    for table, count in counts.items():
        print(f"  {table:<15}: {count:>8} rows")
    print("-" * 40)


if __name__ == "__main__":
    main()
