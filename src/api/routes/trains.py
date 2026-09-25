"""Train routes for listing active trains, querying downstream ETAs, and explainability."""

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import (
    DriverAttribution,
    ETAChangeLogItem,
    StationETAForecast,
    TrainETAResponse,
    TrainExplainResponse,
    TrainListItem,
    TrainListResponse,
)
from src.db.models import ETAChangeLog, Run, RunEvent, Train
from src.db.session import get_db
from src.simulator.replay import replay_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trains", tags=["Trains"])


def _determine_run_state(
    run: Run, events: list[RunEvent], query_time: datetime
) -> tuple[str, str | None, str | None, float]:
    """Calculate operational status, current/next station, and delay as of query_time."""
    if not events:
        return "scheduled", None, None, 0.0

    first_dep = events[0].actual_dep
    last_arr = events[-1].actual_arr or events[-1].actual_dep

    if first_dep and query_time < first_dep:
        return "scheduled", events[0].station_code, events[1].station_code if len(events) > 1 else None, 0.0

    if last_arr and query_time >= last_arr:
        return "completed", events[-1].station_code, None, events[-1].arr_delay_min

    past_events = [e for e in events if (e.actual_dep and e.actual_dep <= query_time) or (e.actual_arr and e.actual_arr <= query_time)]
    if past_events:
        last_ev = past_events[-1]
        cur_st = last_ev.station_code
        cur_delay = last_ev.arr_delay_min
        future_events = [e for e in events if e.seq > last_ev.seq]
        next_st = future_events[0].station_code if future_events else None
        return "running", cur_st, next_st, cur_delay
    else:
        return "scheduled", events[0].station_code, events[1].station_code if len(events) > 1 else None, 0.0


@router.get("", response_model=TrainListResponse)
def list_trains(
    run_date: str | None = Query(None, alias="date", description="Operational date (YYYY-MM-DD)"),
    status: str | None = Query(None, description="Filter by status: running, scheduled, completed"),
    db: Session = Depends(get_db),
) -> TrainListResponse:
    """List running trains along the corridor with their current delay and position."""
    if run_date:
        target_date = date.fromisoformat(run_date)
    else:
        target_date = replay_engine.sim_date

    runs = db.execute(
        select(Run).where(Run.run_date == target_date).order_by(Run.train_number)
    ).scalars().all()

    # If no runs on that date, fallback to latest date in DB
    if not runs:
        latest_run = db.execute(select(Run).order_by(Run.run_date.desc())).scalars().first()
        if latest_run:
            target_date = latest_run.run_date
            runs = db.execute(
                select(Run).where(Run.run_date == target_date).order_by(Run.train_number)
            ).scalars().all()

    # Time cursor for position calculation
    if replay_engine.status == "running" or replay_engine.current_sim_time.date() == target_date:
        query_time = replay_engine.current_sim_time
    else:
        query_time = datetime.combine(target_date, datetime.min.time()) + timedelta(hours=8)

    train_items: list[TrainListItem] = []
    for r in runs:
        train = db.execute(select(Train).where(Train.number == r.train_number)).scalar_one_or_none()
        if not train:
            continue

        events = db.execute(
            select(RunEvent).where(RunEvent.run_id == r.run_id).order_by(RunEvent.seq)
        ).scalars().all()

        op_status, cur_st, next_st, cur_delay = _determine_run_state(r, events, query_time)

        if status and op_status.lower() != status.lower():
            continue

        # Evaluate downstream knock-on risk
        if cur_delay >= 25.0:
            risk = "high"
        elif cur_delay >= 10.0:
            risk = "medium"
        else:
            risk = "low"

        train_items.append(
            TrainListItem(
                run_id=r.run_id,
                train_number=train.number,
                train_name=train.name,
                train_type=train.type,
                priority_class=train.priority_class,
                source=train.source,
                destination=train.destination,
                run_date=r.run_date,
                current_station=cur_st,
                next_station=next_st,
                current_delay_min=round(cur_delay, 1),
                status=op_status,
                knock_on_risk=risk,
            )
        )

    return TrainListResponse(total=len(train_items), trains=train_items)


@router.get("/{run_id}/eta", response_model=TrainETAResponse)
def get_train_eta(
    run_id: str,
    timestamp: str | None = Query(None, description="As-of timestamp (ISO format)"),
    db: Session = Depends(get_db),
) -> TrainETAResponse:
    """Retrieve dynamic downstream ETA predictions (10th, 50th, 90th percentile) and Baseline A."""
    run = db.execute(select(Run).where(Run.run_id == run_id)).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail=f"Train run '{run_id}' not found.")

    train = db.execute(select(Train).where(Train.number == run.train_number)).scalar_one_or_none()
    if not train:
        raise HTTPException(status_code=404, detail=f"Train metadata for run '{run_id}' not found.")

    events = db.execute(
        select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
    ).scalars().all()
    if not events:
        raise HTTPException(status_code=404, detail=f"No run events found for run '{run_id}'.")

    # Determine evaluation timestamp
    if timestamp:
        try:
            as_of_dt = datetime.fromisoformat(timestamp)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=f"Invalid timestamp format: {timestamp}") from err
    elif replay_engine.status in ("running", "paused") and replay_engine.current_sim_time.date() == run.run_date:
        as_of_dt = replay_engine.current_sim_time
    else:
        # Midpoint of run or first departure
        first_dep = events[0].actual_dep or datetime.combine(run.run_date, datetime.min.time()) + timedelta(hours=6)
        as_of_dt = first_dep + timedelta(minutes=45)

    # Determine current station and delay
    past_events = [e for e in events if (e.actual_dep and e.actual_dep <= as_of_dt) or (e.actual_arr and e.actual_arr <= as_of_dt)]
    if past_events:
        current_station = past_events[-1].station_code
        current_delay = past_events[-1].arr_delay_min
    else:
        current_station = events[0].station_code
        current_delay = 0.0

    if not replay_engine.explainer:
        from src.api.main import init_forecast_engine

        init_forecast_engine()
    if not replay_engine.explainer:
        raise HTTPException(status_code=503, detail="Forecast engine is initializing.")

    # Call downstream propagation and explainability
    raw_preds = replay_engine.explainer.predict_and_explain(
        run_id=run_id,
        timestamp=as_of_dt,
        db_session=db,
        log_changes=True,
    )

    station_forecasts: list[StationETAForecast] = []
    for p in raw_preds:
        station_forecasts.append(
            StationETAForecast(
                station_code=p["station_code"],
                station_name=p["station_name"],
                seq=p["seq"],
                stations_ahead=p["stations_ahead"],
                sched_arr=p["sched_arr"],
                actual_arr=p.get("actual_arr"),
                baseline_a_eta=p["baseline_a_eta"],
                eta_lower=p["eta_lower"],
                eta_median=p["eta_median"],
                eta_upper=p["eta_upper"],
                interval_width_min=p["interval_width_min"],
                predicted_median_delay_min=p["predicted_median_delay_min"],
                reasons=p.get("reasons", "On-time operations."),
            )
        )

    return TrainETAResponse(
        run_id=run.run_id,
        train_number=train.number,
        train_name=train.name,
        as_of_timestamp=as_of_dt.isoformat(),
        current_station=current_station,
        current_delay_min=round(current_delay, 1),
        downstream_stations=station_forecasts,
    )


@router.get("/{run_id}/explain", response_model=TrainExplainResponse)
def get_train_explanation(
    run_id: str,
    timestamp: str | None = Query(None, description="As-of timestamp (ISO format)"),
    db: Session = Depends(get_db),
) -> TrainExplainResponse:
    """Retrieve plain-language delay driver explanations, SHAP feature attributions, and ETA change history."""
    run = db.execute(select(Run).where(Run.run_id == run_id)).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail=f"Train run '{run_id}' not found.")

    train = db.execute(select(Train).where(Train.number == run.train_number)).scalar_one_or_none()
    if not train:
        raise HTTPException(status_code=404, detail=f"Train metadata for run '{run_id}' not found.")

    events = db.execute(
        select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
    ).scalars().all()
    if not events:
        raise HTTPException(status_code=404, detail=f"No run events found for run '{run_id}'.")

    if timestamp:
        try:
            as_of_dt = datetime.fromisoformat(timestamp)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=f"Invalid timestamp format: {timestamp}") from err
    elif replay_engine.status in ("running", "paused") and replay_engine.current_sim_time.date() == run.run_date:
        as_of_dt = replay_engine.current_sim_time
    else:
        first_dep = events[0].actual_dep or datetime.combine(run.run_date, datetime.min.time()) + timedelta(hours=6)
        as_of_dt = first_dep + timedelta(minutes=45)

    if not replay_engine.explainer:
        from src.api.main import init_forecast_engine

        init_forecast_engine()
    if not replay_engine.explainer:
        raise HTTPException(status_code=503, detail="Forecast engine is initializing.")

    raw_preds = replay_engine.explainer.predict_and_explain(
        run_id=run_id,
        timestamp=as_of_dt,
        db_session=db,
        log_changes=False,
    )

    # Pick the most significant downstream prediction (e.g. final destination or first downstream stop)
    if raw_preds:
        target_pred = raw_preds[-1]  # Destination forecast
        latest_explanation = target_pred.get("reasons", "Normal corridor operations.")
        delta_min = float(target_pred.get("delta_min", target_pred.get("predicted_median_delay_min", 0.0)))
        raw_drivers = target_pred.get("top_drivers", [])
    else:
        latest_explanation = "Train completed its scheduled run."
        delta_min = 0.0
        raw_drivers = []

    top_drivers: list[DriverAttribution] = []
    for d in raw_drivers:
        top_drivers.append(
            DriverAttribution(
                feature=d.get("feature", "unknown"),
                label=d.get("label", "Delay driver"),
                shap_value=round(float(d.get("shap_value", 0.0)), 2),
                importance=round(float(d.get("importance", 0.0)), 2),
                feature_val=d.get("feature_val", 0.0),
                category=d.get("category", "infrastructure"),
            )
        )

    # Fetch change history from database
    logs = db.execute(
        select(ETAChangeLog)
        .where(ETAChangeLog.run_id == run_id)
        .order_by(ETAChangeLog.timestamp.desc())
        .limit(10)
    ).scalars().all()

    change_history: list[ETAChangeLogItem] = [
        ETAChangeLogItem(
            id=log.id,
            station_code=log.station_code,
            timestamp=log.timestamp.isoformat(),
            old_eta=log.old_eta.isoformat() if log.old_eta else None,
            new_eta=log.new_eta.isoformat(),
            delta_min=round(log.delta_min, 1),
            reasons=log.reasons,
        )
        for log in logs
    ]

    return TrainExplainResponse(
        run_id=run.run_id,
        train_number=train.number,
        train_name=train.name,
        as_of_timestamp=as_of_dt.isoformat(),
        latest_explanation=latest_explanation,
        delta_min=round(delta_min, 1),
        top_drivers=top_drivers,
        change_history=change_history,
    )
