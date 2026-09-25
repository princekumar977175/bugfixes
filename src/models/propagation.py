"""Downstream ETA propagation engine and knock-on delay risk estimator."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Disruption, Run, RunEvent, Schedule, Section, Train
from src.features.pipeline import FeaturePipeline
from src.models.quantiles import QuantileForecaster
from src.simulator.corridor import SMALL_CORRIDOR_STATIONS, SMALL_CORRIDOR_TRAINS


def estimate_knock_on_risk(
    run_id: str,
    section_id: str,
    estimated_exit_time: datetime,
    db_session: Session,
    safety_headway_min: float = 5.0,
) -> dict:
    """Estimate knock-on delay risk imposed on the trailing train on the same section."""
    # Find train number and direction
    run = db_session.execute(select(Run).where(Run.run_id == run_id)).scalar_one_or_none()
    if not run:
        return {
            "section_id": section_id,
            "risk_level": "low",
            "knock_on_delay_min": 0.0,
            "next_train_number": None,
            "explanation": "No active run record found.",
        }

    # Query next train scheduled on this section after this train's entry
    current_sec = db_session.execute(select(Section).where(Section.id == section_id)).scalar_one_or_none()
    if not current_sec:
        return {
            "section_id": section_id,
            "risk_level": "low",
            "knock_on_delay_min": 0.0,
            "next_train_number": None,
            "explanation": "Section not found.",
        }

    # Find current train scheduled entry/departure at current_sec.from_station
    cur_sch = db_session.execute(
        select(Schedule).where(
            Schedule.train_number == run.train_number,
            Schedule.station_code == current_sec.from_station,
        )
    ).scalar_one_or_none()

    cur_entry_dt = None
    if cur_sch and cur_sch.sched_dep:
        h, m, s = [int(p) for p in cur_sch.sched_dep.split(":")]
        cur_entry_dt = datetime.combine(run.run_date, datetime.min.time()) + timedelta(hours=h, minutes=m, seconds=s)

    scheds = db_session.execute(
        select(Schedule).where(
            Schedule.station_code == current_sec.from_station,
            Schedule.train_number != run.train_number,
            Schedule.sched_dep.isnot(None),
        )
    ).scalars().all()

    min_safe_time = estimated_exit_time + timedelta(minutes=safety_headway_min)
    run_date = run.run_date

    closest_trailing_train = None
    max_deficit_min = 0.0

    for sch in scheds:
        h, m, s = [int(p) for p in sch.sched_dep.split(":")]
        sched_entry_dt = datetime.combine(run_date, datetime.min.time()) + timedelta(hours=h, minutes=m, seconds=s)

        # Trailing train must be scheduled at or after current train's entry into the section
        if cur_entry_dt and sched_entry_dt < cur_entry_dt:
            continue

        # Look for trailing trains within an occupancy window of 3 hours
        if (estimated_exit_time - timedelta(hours=1)) <= sched_entry_dt <= (estimated_exit_time + timedelta(hours=3)):
            if sched_entry_dt < min_safe_time:
                deficit = (min_safe_time - sched_entry_dt).total_seconds() / 60.0
                if deficit > max_deficit_min:
                    max_deficit_min = deficit
                    closest_trailing_train = sch.train_number

    if not closest_trailing_train or max_deficit_min <= 0:
        return {
            "section_id": section_id,
            "risk_level": "low",
            "knock_on_delay_min": 0.0,
            "next_train_number": closest_trailing_train,
            "explanation": f"Headway margin is safe (> {safety_headway_min:.0f} min).",
        }
    elif max_deficit_min <= 10.0:
        return {
            "section_id": section_id,
            "risk_level": "medium",
            "knock_on_delay_min": round(max_deficit_min, 1),
            "next_train_number": closest_trailing_train,
            "explanation": f"Trailing train {closest_trailing_train} faces approach caution (~{max_deficit_min:.1f} min delay).",
        }
    else:
        return {
            "section_id": section_id,
            "risk_level": "high",
            "knock_on_delay_min": round(max_deficit_min, 1),
            "next_train_number": closest_trailing_train,
            "explanation": f"Severe headway bottleneck! Trailing train {closest_trailing_train} will absorb ~{max_deficit_min:.1f} min knock-on delay.",
        }


def predict_eta(
    run_id: str,
    timestamp: datetime,
    db_session: Session,
    pipeline: FeaturePipeline,
    quantile_model: QuantileForecaster,
) -> list[dict]:
    """Predict lower, median, and upper ETA for all downstream stations of a train run."""
    run = db_session.execute(select(Run).where(Run.run_id == run_id)).scalar_one_or_none()
    if not run:
        raise ValueError(f"Run ID '{run_id}' not found in database.")

    train = db_session.execute(select(Train).where(Train.number == run.train_number)).scalar_one()

    # Query all events and schedules for this run
    events = db_session.execute(
        select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
    ).scalars().all()

    schedules = db_session.execute(
        select(Schedule).where(Schedule.train_number == run.train_number).order_by(Schedule.seq)
    ).scalars().all()

    # Query all sections
    sections = db_session.execute(select(Section)).scalars().all()
    sections_dict = {(sec.from_station, sec.to_station): {
        "id": sec.id,
        "from_station": sec.from_station,
        "to_station": sec.to_station,
        "distance_km": sec.distance_km,
        "line_speed_kmph": sec.line_speed_kmph,
        "scheduled_runtime_min": sec.scheduled_runtime_min,
        "direction": sec.direction,
    } for sec in sections}

    # Query active disruptions
    disruptions = db_session.execute(select(Disruption)).scalars().all()
    disruptions_by_sec = {}
    for d in disruptions:
        disruptions_by_sec.setdefault(d.section_id, []).append({
            "id": d.id,
            "type": d.type,
            "start_time": d.start_time,
            "end_time": d.end_time,
            "severity": d.severity,
        })

    # Stations ordering
    stations_ordered_dn = [s.code for s in SMALL_CORRIDOR_STATIONS]
    train_cfg_map = {t.number: t for t in SMALL_CORRIDOR_TRAINS}
    t_cfg = train_cfg_map.get(train.number)
    speed_factor = t_cfg.speed_factor if t_cfg else 1.0

    # Determine current position along route at `timestamp`
    past_events = [e for e in events if (e.actual_dep and e.actual_dep <= timestamp) or (e.actual_arr and e.actual_arr <= timestamp)]

    if past_events:
        last_event = past_events[-1]
        current_seq = last_event.seq
        current_station = last_event.station_code
        current_delay = last_event.arr_delay_min
        current_dwell = last_event.dwell_min
        current_time_cursor = max(timestamp, last_event.actual_dep or last_event.actual_arr)
    else:
        first_event = events[0]
        current_seq = 1
        current_station = first_event.station_code
        current_delay = 0.0
        current_dwell = 0.0
        current_time_cursor = first_event.actual_dep or timestamp

    # Remaining downstream stations
    downstream_events = [e for e in events if e.seq > current_seq]
    if not downstream_events:
        return []  # Train has already arrived at destination

    # Setup propagation cursors
    time_q50 = current_time_cursor
    delay_q50 = current_delay

    station_lookup = {s.code: s for s in SMALL_CORRIDOR_STATIONS}
    train_halts = {e.station_code for e in events}
    halt_dwell_lookup = {
        s: (t_cfg.junction_dwell_min if s in {"NDLS", "CNB", "PRYJ", "DDU", "PNBE", "GZB"} else t_cfg.default_dwell_min)
        for s in train_halts
    } if t_cfg else {}

    predictions = []
    prev_st_code = current_station
    cum_spread_dn = 0.0
    cum_spread_up = 0.0
    min_transit_minutes = 0.0

    # Step through downstream stops
    for ev in downstream_events:
        target_station = ev.station_code
        target_seq = ev.seq

        # Determine route sections between prev_st_code and target_station
        if train.source == "NDLS":
            i_u = stations_ordered_dn.index(prev_st_code)
            i_v = stations_ordered_dn.index(target_station)
            step = 1
        else:
            i_u = stations_ordered_dn.index(prev_st_code)
            i_v = stations_ordered_dn.index(target_station)
            step = -1

        # Propagate through intermediate sections
        for idx in range(i_u, i_v, step):
            u = stations_ordered_dn[idx]
            v = stations_ordered_dn[idx + step]
            sec = sections_dict[(u, v)]
            sec_id = sec["id"]
            base_runtime = sec["scheduled_runtime_min"] * speed_factor

            active_dis = disruptions_by_sec.get(sec_id, [])

            # Feature vector based on median state
            X_step = pipeline.build_single_step_features(
                sec=sec,
                current_time=time_q50,
                priority_class=train.priority_class,
                speed_factor=speed_factor,
                current_delay_min=delay_q50,
                dwell_last_station=current_dwell,
                delay_trend_last_3=0.0,
                preceding_train_delay=0.0,
                active_disruptions_for_sec=active_dis,
            )

            # Predict quantiles for this section
            q10, q50, q90 = quantile_model.predict_single_step(X_step)

            # Recovery slack for priority 1 & 2
            slack = (base_runtime * 0.05) if train.priority_class <= 2 else 0.0
            t_50 = max(2.0, base_runtime + q50 - (slack if delay_q50 > 0 else 0.0))

            time_q50 += timedelta(minutes=t_50)
            delay_q50 = max(0.0, delay_q50 + q50 - slack)

            # Accumulate quantile spreads and minimum physical transit time
            cum_spread_dn += max(0.5, q50 - q10)
            cum_spread_up += max(1.0, q90 - q50)
            min_transit_minutes += base_runtime * 0.95

            # Add dwell if v is an intermediate halt before target
            if v != target_station and v in train_halts:
                dw = halt_dwell_lookup.get(v, 2.0)
                time_q50 += timedelta(minutes=dw)
                min_transit_minutes += dw
                current_dwell = dw

        # Calculate scheduled arrival datetime
        sched_row = next((s for s in schedules if s.station_code == target_station), None)
        if sched_row and sched_row.sched_arr:
            h, m, s = [int(p) for p in sched_row.sched_arr.split(":")]
            sched_arr_dt = datetime.combine(run.run_date, datetime.min.time()) + timedelta(hours=h, minutes=m, seconds=s)
            if sched_arr_dt < current_time_cursor - timedelta(hours=6):
                sched_arr_dt += timedelta(days=1)
        elif ev.actual_arr:
            sched_arr_dt = ev.actual_arr - timedelta(minutes=ev.arr_delay_min)
        else:
            sched_arr_dt = time_q50

        # Baseline A ETA
        baseline_a_eta = sched_arr_dt + timedelta(minutes=current_delay)

        # Multi-hop calibrated uncertainty propagation
        h_ahead = target_seq - current_seq
        margin_dn = cum_spread_dn * 0.4 + 2.4 * (h_ahead ** 0.35)
        margin_up = cum_spread_up * 0.6 + 6.0 * (h_ahead ** 0.92)

        eta_median = time_q50
        min_transit_eta = current_time_cursor + timedelta(minutes=min_transit_minutes)
        eta_lower = max(min_transit_eta, eta_median - timedelta(minutes=margin_dn))
        eta_upper = max(eta_median, eta_median + timedelta(minutes=margin_up))

        # Guarantee strict monotonicity
        if eta_lower > eta_median:
            eta_lower = eta_median
        if eta_upper < eta_median:
            eta_upper = eta_median

        interval_width = (eta_upper - eta_lower).total_seconds() / 60.0
        predicted_median_delay = (eta_median - sched_arr_dt).total_seconds() / 60.0

        st_info = station_lookup.get(target_station)
        st_name = st_info.name if st_info else target_station

        predictions.append({
            "run_id": run_id,
            "train_number": train.number,
            "train_name": train.name,
            "station_code": target_station,
            "station_name": st_name,
            "seq": target_seq,
            "stations_ahead": h_ahead,
            "sched_arr": sched_arr_dt.isoformat(),
            "actual_arr": ev.actual_arr.isoformat() if ev.actual_arr else None,
            "actual_delay_min": ev.arr_delay_min,
            "baseline_a_eta": baseline_a_eta.isoformat(),
            "eta_lower": eta_lower.isoformat(),
            "eta_median": eta_median.isoformat(),
            "eta_upper": eta_upper.isoformat(),
            "interval_width_min": round(interval_width, 1),
            "predicted_median_delay_min": round(predicted_median_delay, 1),
            "is_within_interval": (eta_lower <= ev.actual_arr <= eta_upper) if ev.actual_arr else None,
        })

        # Add dwell at this station for further downstream propagation
        if target_seq < events[-1].seq and target_station in train_halts:
            dw = halt_dwell_lookup.get(target_station, 2.0)
            time_q50 += timedelta(minutes=dw)
            min_transit_minutes += dw
            current_dwell = dw

        prev_st_code = target_station

    return predictions
