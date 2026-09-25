"""Machine Learning train delay forecasting model with iterative propagation."""

from datetime import datetime, timedelta
from pathlib import Path

import joblib
import lightgbm as lgb
import pandas as pd

from src.features.pipeline import FeaturePipeline


class TrainDelayForecaster:
    """LightGBM-based section delay forecaster with iterative downstream propagation."""

    def __init__(
        self,
        n_estimators: int = 150,
        learning_rate: float = 0.05,
        num_leaves: int = 31,
        random_state: int = 42,
    ):
        self.model = lgb.LGBMRegressor(
            objective="regression_l1",  # MAE optimization
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            num_leaves=num_leaves,
            random_state=random_state,
            verbosity=-1,
        )
        self.feature_columns: list[str] = FeaturePipeline.FEATURE_COLUMNS
        self.version: str = "v1.0.0"
        self.is_fitted: bool = False
        self.metadata: dict = {}

    def fit(self, X: pd.DataFrame, y: pd.Series, version: str = "v1.0.0") -> "TrainDelayForecaster":
        """Fit the LightGBM model on extracted training features."""
        self.version = version
        self.model.fit(X[self.feature_columns], y)
        self.is_fitted = True
        self.metadata = {
            "version": version,
            "trained_at": datetime.now().isoformat(),
            "n_samples": len(X),
            "features": self.feature_columns,
        }
        return self

    def predict_section_delay(self, X_step: pd.DataFrame) -> float:
        """Predict added delay for a single section traversal."""
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before predict_section_delay.")
        pred = float(self.model.predict(X_step[self.feature_columns])[0])
        return max(0.0, pred)

    def predict_eta_iterative(
        self,
        pipeline: FeaturePipeline,
        current_dt: datetime,
        current_station: str,
        target_station: str,
        priority_class: int,
        speed_factor: float,
        current_delay_min: float,
        dwell_last_station: float,
        sections_dict: dict[tuple[str, str], dict],
        stations_ordered_dn: list[str],
        train_halts: list[str],
        halt_dwell_lookup: dict[str, float],
        active_disruptions_by_sec: dict[str, list[dict]],
    ) -> datetime:
        """Iteratively propagate ETA section by section updating current delay and time."""
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before predict_eta_iterative.")

        if current_station in stations_ordered_dn and target_station in stations_ordered_dn:
            i_from = stations_ordered_dn.index(current_station)
            i_to = stations_ordered_dn.index(target_station)
            step = 1 if i_from < i_to else -1
        else:
            raise ValueError(f"Unknown stations: {current_station} -> {target_station}")

        sim_time = current_dt
        running_delay = current_delay_min
        prev_dwell = dwell_last_station
        prev_added_delay = 0.0

        for idx in range(i_from, i_to, step):
            u = stations_ordered_dn[idx]
            v = stations_ordered_dn[idx + step]
            sec = sections_dict[(u, v)]
            sec_id = sec["id"]

            active_dis = active_disruptions_by_sec.get(sec_id, [])

            # Construct dynamic feature row at simulation moment
            X_step = pipeline.build_single_step_features(
                sec=sec,
                current_time=sim_time,
                priority_class=priority_class,
                speed_factor=speed_factor,
                current_delay_min=running_delay,
                dwell_last_station=prev_dwell,
                delay_trend_last_3=prev_added_delay,
                preceding_train_delay=0.0,
                active_disruptions_for_sec=active_dis,
            )

            predicted_added_delay = self.predict_section_delay(X_step)

            # High priority recovery slack on clear sections
            recovery_slack = 0.0
            if priority_class <= 2 and predicted_added_delay < 1.0 and running_delay > 0:
                recovery_slack = min(running_delay, sec["scheduled_runtime_min"] * speed_factor * 0.05)

            base_runtime = sec["scheduled_runtime_min"] * speed_factor
            effective_transit_min = max(2.0, base_runtime + predicted_added_delay - recovery_slack)

            sim_time += timedelta(minutes=effective_transit_min)
            running_delay = max(0.0, running_delay + predicted_added_delay - recovery_slack)
            prev_added_delay = predicted_added_delay

            # Dwell at intermediate station
            if v != target_station and v in train_halts:
                dwell_min = halt_dwell_lookup.get(v, 2.0)
                sim_time += timedelta(minutes=dwell_min)
                prev_dwell = dwell_min

        return sim_time

    def save(self, model_path: str | Path) -> None:
        """Persist model and metadata to disk."""
        path = Path(model_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "model": self.model,
            "version": self.version,
            "metadata": self.metadata,
            "feature_columns": self.feature_columns,
        }, path)

    @classmethod
    def load(cls, model_path: str | Path) -> "TrainDelayForecaster":
        """Load persisted model artifact from disk."""
        data = joblib.load(model_path)
        forecaster = cls()
        forecaster.model = data["model"]
        forecaster.version = data["version"]
        forecaster.metadata = data.get("metadata", {})
        forecaster.feature_columns = data.get("feature_columns", FeaturePipeline.FEATURE_COLUMNS)
        forecaster.is_fitted = True
        return forecaster
