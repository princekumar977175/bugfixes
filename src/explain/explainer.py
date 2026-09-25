"""High-level ETA Explainability Engine integrating SHAP drivers, text generation, and change logging."""

from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Disruption, Run, RunEvent, Section, Train
from src.explain.drivers import extract_shap_drivers
from src.explain.templates import format_explanation
from src.explain.tracker import record_eta_change
from src.features.pipeline import FeaturePipeline
from src.models.propagation import predict_eta
from src.models.quantiles import QuantileForecaster


class ETAExplainer:
    """Unified explainability engine providing SHAP driver attribution and natural language reasoning."""

    def __init__(
        self,
        model: Any,
        pipeline: FeaturePipeline,
        quantile_model: QuantileForecaster | None = None,
    ):
        self.model = model
        self.pipeline = pipeline
        self.quantile_model = quantile_model

    def explain(
        self,
        X_features: pd.DataFrame,
        section_contexts: list[dict] | None = None,
        delta_min: float = 0.0,
        target_station: str | None = None,
        prefix_style: str = "delta",
    ) -> tuple[str, list[dict[str, Any]]]:
        """Explain an ETA prediction by extracting top-3 SHAP drivers and formatting plain-language text."""
        drivers = extract_shap_drivers(
            model=self.model,
            X_features=X_features,
            section_contexts=section_contexts,
            top_k=3,
        )

        reason_text = format_explanation(
            delta_min=delta_min,
            top_drivers=drivers,
            target_station=target_station,
            prefix_style=prefix_style,
        )

        return reason_text, drivers

    def predict_and_explain(
        self,
        run_id: str,
        timestamp: datetime,
        db_session: Session,
        log_changes: bool = False,
    ) -> list[dict[str, Any]]:
        """Run downstream ETA propagation, generate explanations for every downstream station, and optionally log changes."""
        if self.quantile_model is None:
            raise ValueError("Quantile model must be provided to run predict_and_explain.")

        # 1. Compute downstream ETA predictions
        predictions = predict_eta(
            run_id=run_id,
            timestamp=timestamp,
            db_session=db_session,
            pipeline=self.pipeline,
            quantile_model=self.quantile_model,
        )

        if not predictions:
            return []

        # 2. Query corridor metadata for authentic route-level feature extraction
        run = db_session.execute(select(Run).where(Run.run_id == run_id)).scalar_one_or_none()
        train = db_session.execute(select(Train).where(Train.number == run.train_number)).scalar_one_or_none() if run else None
        sections = db_session.execute(select(Section)).scalars().all()
        sec_dict = {(s.from_station, s.to_station): s for s in sections}
        disruptions = db_session.execute(select(Disruption)).scalars().all()
        from src.simulator.corridor import SMALL_CORRIDOR_STATIONS
        stations_ordered_dn = [s.code for s in SMALL_CORRIDOR_STATIONS]

        # Determine current position along route at timestamp
        events = db_session.execute(
            select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
        ).scalars().all()
        past_events = [e for e in events if (e.actual_dep and e.actual_dep <= timestamp) or (e.actual_arr and e.actual_arr <= timestamp)]
        current_station = past_events[-1].station_code if past_events else (events[0].station_code if events else "NDLS")

        # 3. Enrich each downstream prediction with explanations
        enriched_predictions = []
        for p in predictions:
            st_code = p["station_code"]
            st_name = p["station_name"]
            eta_median_dt = datetime.fromisoformat(p["eta_median"])
            sched_arr_dt = datetime.fromisoformat(p["sched_arr"])

            # Compute delta from scheduled arrival
            delta_min = p.get("predicted_median_delay_min", (eta_median_dt - sched_arr_dt).total_seconds() / 60.0)

            # Reconstruct downstream route sections towards target station
            step_features = []
            section_contexts = []

            if train and train.source == "NDLS" and st_code in stations_ordered_dn and current_station in stations_ordered_dn:
                # Down direction
                i_u = stations_ordered_dn.index(current_station)
                i_v = stations_ordered_dn.index(st_code)
                route_pairs = [(stations_ordered_dn[i], stations_ordered_dn[i + 1]) for i in range(i_u, i_v)]
            elif train and st_code in stations_ordered_dn and current_station in stations_ordered_dn:
                # Up direction
                i_u = stations_ordered_dn.index(current_station)
                i_v = stations_ordered_dn.index(st_code)
                route_pairs = [(stations_ordered_dn[i], stations_ordered_dn[i - 1]) for i in range(i_u, i_v, -1)]
            else:
                route_pairs = []

            for u, v in route_pairs:
                sec_obj = sec_dict.get((u, v))
                if not sec_obj:
                    continue
                sec_info = {
                    "id": sec_obj.id,
                    "from_station": u,
                    "to_station": v,
                    "distance_km": sec_obj.distance_km,
                    "line_speed_kmph": sec_obj.line_speed_kmph,
                    "scheduled_runtime_min": sec_obj.scheduled_runtime_min,
                }
                active_d = [
                    {"id": d.id, "type": d.type, "start_time": d.start_time, "end_time": d.end_time, "severity": d.severity}
                    for d in disruptions if d.section_id == sec_obj.id
                ]

                has_tsr = any(d["type"] == "TSR" for d in active_d)
                has_cong = any(d["type"] == "congestion" for d in active_d) or (v in {"NDLS", "CNB", "PRYJ", "DDU", "PNBE", "GZB"})
                has_weather = any(d["type"] == "weather" for d in active_d)

                section_contexts.append({
                    "id": sec_obj.id,
                    "from_station": u,
                    "to_station": v,
                    "has_tsr": has_tsr,
                    "has_congestion": has_cong,
                    "has_weather": has_weather,
                    "is_junction": v in {"NDLS", "CNB", "PRYJ", "DDU", "PNBE", "GZB"},
                })

                X_step = self.pipeline.build_single_step_features(
                    sec=sec_info,
                    current_time=timestamp,
                    priority_class=train.priority_class if train else 2,
                    speed_factor=1.0,
                    current_delay_min=max(0.0, delta_min),
                    dwell_last_station=2.0,
                    delay_trend_last_3=0.0,
                    preceding_train_delay=0.0,
                    active_disruptions_for_sec=active_d,
                )
                step_features.append(X_step)

            if step_features:
                df_feat = pd.concat(step_features, ignore_index=True)
            else:
                # Fallback to single row feature vector
                feat_dict = {col: 0.0 for col in FeaturePipeline.FEATURE_COLUMNS}
                feat_dict["current_delay_min"] = max(0.0, delta_min)
                feat_dict["line_speed_kmph"] = 110.0
                feat_dict["distance_km"] = 40.0 * p["stations_ahead"]
                df_feat = pd.DataFrame([feat_dict])
                section_contexts = [{"id": f"{st_code}-SEC", "from_station": st_code, "to_station": st_code}]

            reason_text, top_drivers = self.explain(
                X_features=df_feat,
                section_contexts=section_contexts,
                delta_min=delta_min,
                target_station=st_name,
                prefix_style="delta",
            )

            p["reasons"] = reason_text
            p["top_drivers"] = top_drivers
            p["delta_min"] = round(delta_min, 1)

            # 4. Optionally log change to database
            if log_changes:
                record_eta_change(
                    run_id=run_id,
                    station_code=st_code,
                    new_eta=eta_median_dt,
                    timestamp=timestamp,
                    reasons=reason_text,
                    db_session=db_session,
                    drivers=top_drivers,
                    old_eta=sched_arr_dt,
                )

            enriched_predictions.append(p)

        return enriched_predictions
