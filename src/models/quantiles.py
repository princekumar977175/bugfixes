"""Quantile regression models for uncertainty estimation (10th, 50th, 90th percentiles)."""

from datetime import datetime
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from src.features.pipeline import FeaturePipeline


class QuantileForecaster:
    """LightGBM quantile forecaster estimating the 10th, 50th, and 90th delay percentiles."""

    def __init__(
        self,
        n_estimators: int = 120,
        learning_rate: float = 0.05,
        num_leaves: int = 31,
        random_state: int = 42,
    ):
        self.quantiles = [0.10, 0.50, 0.90]
        self.models: dict[float, lgb.LGBMRegressor] = {
            q: lgb.LGBMRegressor(
                objective="quantile",
                alpha=q,
                n_estimators=n_estimators,
                learning_rate=learning_rate,
                num_leaves=num_leaves,
                random_state=random_state,
                verbosity=-1,
            )
            for q in self.quantiles
        }
        self.feature_columns = FeaturePipeline.FEATURE_COLUMNS
        self.version = "v1.0.0-quantiles"
        self.is_fitted = False
        self.metadata = {}

    def fit(self, X: pd.DataFrame, y: pd.Series, version: str = "v1.0.0-quantiles") -> "QuantileForecaster":
        """Fit 10th, 50th, and 90th percentile LightGBM models on training features."""
        self.version = version
        X_mat = X[self.feature_columns]

        for q in self.quantiles:
            self.models[q].fit(X_mat, y)

        self.is_fitted = True
        self.metadata = {
            "version": version,
            "trained_at": datetime.now().isoformat(),
            "n_samples": len(X),
            "quantiles": self.quantiles,
            "features": self.feature_columns,
        }
        return self

    def predict_quantiles(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Predict (q10, q50, q90) ensuring quantile monotonicity."""
        if not self.is_fitted:
            raise RuntimeError("QuantileForecaster must be fitted before predict_quantiles.")

        X_mat = X[self.feature_columns]
        q10 = np.maximum(0.0, self.models[0.10].predict(X_mat))
        q50 = np.maximum(q10, self.models[0.50].predict(X_mat))
        q90 = np.maximum(q50, self.models[0.90].predict(X_mat))

        return q10, q50, q90

    def predict_single_step(self, X_step: pd.DataFrame) -> tuple[float, float, float]:
        """Predict scalar (q10, q50, q90) added delay for a single section traversal."""
        q10, q50, q90 = self.predict_quantiles(X_step)
        return float(q10[0]), float(q50[0]), float(q90[0])

    def save(self, model_dir: str | Path) -> None:
        """Save quantile models to disk."""
        dir_path = Path(model_dir)
        dir_path.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "models": self.models,
            "version": self.version,
            "metadata": self.metadata,
            "feature_columns": self.feature_columns,
        }, dir_path / "quantile_models.pkl")

    @classmethod
    def load(cls, model_dir: str | Path) -> "QuantileForecaster":
        """Load quantile models from disk."""
        dir_path = Path(model_dir)
        file_path = dir_path / "quantile_models.pkl" if dir_path.is_dir() else dir_path
        data = joblib.load(file_path)

        forecaster = cls()
        forecaster.models = data["models"]
        forecaster.version = data["version"]
        forecaster.metadata = data.get("metadata", {})
        forecaster.feature_columns = data.get("feature_columns", FeaturePipeline.FEATURE_COLUMNS)
        forecaster.is_fitted = True
        return forecaster
