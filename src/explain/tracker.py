"""ETA Change Tracker for persisting and querying ETA revisions with explanations per run."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import ETAChangeLog, RunEvent


def record_eta_change(
    run_id: str,
    station_code: str,
    new_eta: datetime,
    timestamp: datetime,
    reasons: str,
    db_session: Session,
    drivers: list[dict[str, Any]] | None = None,
    old_eta: datetime | None = None,
) -> ETAChangeLog:
    """Record an ETA change log entry into the database.

    If old_eta is not explicitly provided, fetches the previous ETA change log for this
    run and station. If none exists, looks up the scheduled arrival time.
    """
    if old_eta is None:
        # Check previous log entry for this run and station
        prev_entry = db_session.execute(
            select(ETAChangeLog)
            .where(
                ETAChangeLog.run_id == run_id,
                ETAChangeLog.station_code == station_code,
            )
            .order_by(ETAChangeLog.timestamp.desc(), ETAChangeLog.id.desc())
        ).scalars().first()

        if prev_entry:
            old_eta = prev_entry.new_eta
        else:
            # Fallback to scheduled arrival time from RunEvent or Schedule
            ev = db_session.execute(
                select(RunEvent).where(
                    RunEvent.run_id == run_id,
                    RunEvent.station_code == station_code,
                )
            ).scalar_one_or_none()

            if ev and ev.actual_arr:
                # True scheduled time
                from datetime import timedelta
                old_eta = ev.actual_arr - timedelta(minutes=ev.arr_delay_min)
            else:
                old_eta = new_eta

    delta_min = (new_eta - old_eta).total_seconds() / 60.0 if old_eta else 0.0

    drivers_json = None
    if drivers:
        # Serialize driver details
        drivers_json = json.dumps([
            {
                "feature": d.get("feature"),
                "label": d.get("label"),
                "importance": round(d.get("importance", 0.0), 3),
                "shap_value": round(d.get("shap_value", 0.0), 3),
                "feature_val": round(d.get("feature_val", 0.0), 2) if isinstance(d.get("feature_val"), (int, float)) else str(d.get("feature_val")),
                "category": d.get("category"),
            }
            for d in drivers
        ])

    log_entry = ETAChangeLog(
        run_id=run_id,
        station_code=station_code,
        timestamp=timestamp,
        old_eta=old_eta,
        new_eta=new_eta,
        delta_min=round(delta_min, 1),
        reasons=reasons,
        drivers_json=drivers_json,
    )

    db_session.add(log_entry)
    db_session.commit()
    db_session.refresh(log_entry)
    return log_entry


def get_eta_change_history(
    run_id: str,
    db_session: Session,
    station_code: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve full chronological ETA revision history with reasons for a train run."""
    stmt = select(ETAChangeLog).where(ETAChangeLog.run_id == run_id)
    if station_code:
        stmt = stmt.where(ETAChangeLog.station_code == station_code)
    stmt = stmt.order_by(ETAChangeLog.timestamp.asc(), ETAChangeLog.id.asc())

    logs = db_session.execute(stmt).scalars().all()
    results = []

    for log in logs:
        drivers = []
        if log.drivers_json:
            try:
                drivers = json.loads(log.drivers_json)
            except Exception:
                drivers = []

        results.append({
            "id": log.id,
            "run_id": log.run_id,
            "station_code": log.station_code,
            "timestamp": log.timestamp.isoformat(),
            "old_eta": log.old_eta.isoformat() if log.old_eta else None,
            "new_eta": log.new_eta.isoformat(),
            "delta_min": log.delta_min,
            "reasons": log.reasons,
            "drivers": drivers,
        })

    return results
