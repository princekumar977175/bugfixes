"""Replay engine for corridor simulation and real-time WebSocket ETA streaming."""

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import StationETAForecast, WebSocketETAUpdate
from src.api.ws_manager import ConnectionManager, ws_manager
from src.db.models import Run, RunEvent
from src.db.session import SessionLocal
from src.explain.explainer import ETAExplainer

logger = logging.getLogger(__name__)


class ReplayEngine:
    """Manages simulated time progression, train tracking, and streaming ETA predictions over WebSockets."""

    def __init__(
        self,
        explainer: ETAExplainer | None = None,
        manager: ConnectionManager | None = None,
    ) -> None:
        self.explainer = explainer
        self.ws_manager = manager or ws_manager
        self.status: str = "stopped"  # "stopped", "running", "paused"
        self.speed: float = 1.0  # Multiplier
        self.sim_date: date = date(2026, 1, 20)
        self.current_sim_time: datetime = datetime(2026, 1, 20, 6, 0, 0)
        self.active_run_id: str | None = None
        self._loop_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def set_explainer(self, explainer: ETAExplainer) -> None:
        """Inject the ETAExplainer engine."""
        self.explainer = explainer

    def get_status(self) -> dict[str, Any]:
        """Return snapshot of the engine status."""
        return {
            "status": self.status,
            "current_sim_time": self.current_sim_time.isoformat(),
            "speed": self.speed,
            "active_run_id": self.active_run_id,
        }

    def set_speed(self, speed: float) -> None:
        """Update simulation speed factor."""
        self.speed = max(0.1, min(120.0, float(speed)))
        logger.info(f"Replay speed updated to {self.speed}x")

    def pause(self) -> None:
        """Pause simulated time progression."""
        self.status = "paused"
        logger.info(f"Replay paused at sim_time={self.current_sim_time.isoformat()}")

    def resume(self) -> None:
        """Resume execution from paused state."""
        self.status = "running"
        self._ensure_loop()
        logger.info(f"Replay resumed at sim_time={self.current_sim_time.isoformat()}")

    def start(
        self,
        sim_date: str | None = None,
        run_id: str | None = None,
        speed: float = 1.0,
    ) -> dict[str, Any]:
        """Initiate or restart simulated replay for a given date or run."""
        self.speed = max(0.1, min(120.0, float(speed)))

        with SessionLocal() as session:
            if run_id:
                run = session.execute(select(Run).where(Run.run_id == run_id)).scalar_one_or_none()
                if run:
                    self.active_run_id = run_id
                    self.sim_date = run.run_date
                    # Set sim_time to 5 minutes before train departure
                    first_ev = session.execute(
                        select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
                    ).scalars().first()
                    if first_ev and first_ev.actual_dep:
                        self.current_sim_time = first_ev.actual_dep - timedelta(minutes=5)
                    else:
                        self.current_sim_time = datetime.combine(self.sim_date, datetime.min.time()) + timedelta(hours=6)
                else:
                    self.active_run_id = run_id
            elif sim_date:
                self.sim_date = date.fromisoformat(sim_date)
                self.current_sim_time = datetime.combine(self.sim_date, datetime.min.time()) + timedelta(hours=6)
            else:
                # Default to latest date in database if available
                latest_run = session.execute(select(Run).order_by(Run.run_date.desc())).scalars().first()
                if latest_run:
                    self.sim_date = latest_run.run_date
                self.current_sim_time = datetime.combine(self.sim_date, datetime.min.time()) + timedelta(hours=6)

        self.status = "running"
        self._ensure_loop()
        logger.info(f"Replay started: sim_time={self.current_sim_time.isoformat()}, speed={self.speed}x, active_run={self.active_run_id}")
        return self.get_status()

    def stop(self) -> None:
        """Stop replay and terminate background worker."""
        self.status = "stopped"
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        self._loop_task = None
        logger.info("Replay stopped.")

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Explicitly set the event loop for the background worker."""
        self._event_loop = loop

    def _ensure_loop(self) -> None:
        """Ensure the background async ticker task is running."""
        loop = getattr(self, "_event_loop", None)
        if loop is None or loop.is_closed():
            try:
                loop = asyncio.get_running_loop()
                self._event_loop = loop
            except RuntimeError:
                return

        if self._loop_task is None or self._loop_task.done():
            self._loop_task = loop.create_task(self._ticker_loop())

    async def _ticker_loop(self) -> None:
        """Continuous ticker loop advancing simulation time and emitting updates."""
        try:
            while self.status != "stopped":
                if self.status == "running":
                    # Real-world tick interval inversely scales with speed
                    # At 1x speed: ~1.5s; at 5x speed: ~0.3s
                    tick_interval = max(0.05, min(2.0, 1.5 / max(0.1, self.speed)))
                    await asyncio.sleep(tick_interval)
                    if self.status != "running":
                        continue
                    # Simulated advance per tick
                    step_secs = 60.0 * self.speed
                    await self.step(step_secs)
                else:
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in replay ticker loop: {e}", exc_info=True)

    async def step(self, seconds: float = 300.0) -> list[dict[str, Any]]:
        """Advance simulated time by `seconds` and broadcast live updates."""
        async with self._lock:
            self.current_sim_time += timedelta(seconds=seconds)
            current_time = self.current_sim_time

            updates = []
            with SessionLocal() as session:
                target_runs = self._get_active_runs_at_time(session, current_time)

                for r_id in target_runs:
                    update_dict = self._generate_run_update(session, r_id, current_time)
                    if update_dict:
                        updates.append(update_dict)
                        # Broadcast via WebSocket manager
                        await self.ws_manager.broadcast_to_run(r_id, update_dict)

            return updates

    def _get_active_runs_at_time(self, session: Session, sim_time: datetime) -> list[str]:
        """Find runs active at simulated time."""
        if self.active_run_id:
            return [self.active_run_id]

        target_date = sim_time.date()
        runs = session.execute(select(Run).where(Run.run_date == target_date)).scalars().all()
        active_run_ids = []

        for r in runs:
            events = session.execute(
                select(RunEvent).where(RunEvent.run_id == r.run_id).order_by(RunEvent.seq)
            ).scalars().all()
            if not events:
                continue

            first_dep = events[0].actual_dep
            last_arr = events[-1].actual_arr or events[-1].actual_dep
            if first_dep and last_arr:
                # Active if train has started and not finished plus a 1-hour window
                if (first_dep - timedelta(minutes=15)) <= sim_time <= (last_arr + timedelta(minutes=30)):
                    active_run_ids.append(r.run_id)

        # Fallback if none active at that exact time: return first run on that date
        if not active_run_ids and runs:
            active_run_ids.append(runs[0].run_id)

        return active_run_ids[:5]  # Limit to 5 concurrent trains for smooth performance

    def _generate_run_update(
        self, session: Session, run_id: str, sim_time: datetime
    ) -> dict[str, Any] | None:
        """Compute live predictions and return a WebSocketETAUpdate dictionary."""
        events = session.execute(
            select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
        ).scalars().all()
        if not events:
            return None

        past_events = [e for e in events if (e.actual_dep and e.actual_dep <= sim_time) or (e.actual_arr and e.actual_arr <= sim_time)]
        if past_events:
            last_ev = past_events[-1]
            current_station = last_ev.station_code
            current_delay = last_ev.arr_delay_min
        else:
            first_ev = events[0]
            current_station = first_ev.station_code
            current_delay = 0.0

        if not self.explainer:
            from src.api.main import init_forecast_engine

            init_forecast_engine()

        if self.explainer:
            try:
                preds = self.explainer.predict_and_explain(
                    run_id=run_id,
                    timestamp=sim_time,
                    db_session=session,
                    log_changes=False,
                )
            except Exception as e:
                logger.warning(f"predict_and_explain failed for run {run_id} at {sim_time}: {e}")
                preds = []
        else:
            preds = []

        station_forecasts = []
        for p in preds:
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

        # Extract next station and latest explainability drivers
        future_events = [e for e in events if e.seq > (last_ev.seq if past_events else 1)]
        next_station = future_events[0].station_code if future_events else None

        target_pred = preds[-1] if preds else {}
        latest_explanation = target_pred.get("reasons", "Normal corridor operations.")
        delta_min = float(target_pred.get("delta_min", target_pred.get("predicted_median_delay_min", 0.0)))
        raw_drivers = target_pred.get("top_drivers", [])

        payload = WebSocketETAUpdate(
            type="eta_update",
            run_id=run_id,
            sim_time=sim_time.isoformat(),
            current_station=current_station,
            current_delay_min=round(current_delay, 1),
            predictions=station_forecasts,
        )
        payload_dict = payload.model_dump(mode="json")
        payload_dict["next_station"] = next_station
        payload_dict["latest_explanation"] = latest_explanation
        payload_dict["delta_min"] = round(delta_min, 1)
        payload_dict["top_drivers"] = [
            {
                "feature": d.get("feature", "unknown"),
                "label": d.get("label", "Delay driver"),
                "shap_value": round(float(d.get("shap_value", 0.0)), 2),
                "importance": round(float(d.get("importance", 0.0)), 2),
                "feature_val": d.get("feature_val", 0.0),
                "category": d.get("category", "infrastructure"),
            }
            for d in raw_drivers
        ]
        return payload_dict


# Global singleton instance
replay_engine = ReplayEngine()
