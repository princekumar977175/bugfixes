"""Tests for explainability, SHAP driver extraction, text templates, and ETA change logs (Phase 5)."""

from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Run, RunEvent
from src.db.session import get_engine, init_db
from src.explain.drivers import extract_rule_based_drivers, extract_shap_drivers
from src.explain.explainer import ETAExplainer
from src.explain.templates import driver_to_text, format_explanation
from src.explain.tracker import get_eta_change_history
from src.features.pipeline import FeaturePipeline
from src.models.ml_model import TrainDelayForecaster
from src.models.quantiles import QuantileForecaster

FORBIDDEN_PLACEHOLDERS = [
    "todo",
    "placeholder",
    "lorem ipsum",
    "driver 1",
    "driver 2",
    "dummy",
    "unknown",
    "undefined",
    "null",
]


def test_shap_driver_extraction():
    """Verify SHAP extraction produces at most top 3 drivers with valid mathematical attributions."""
    forecaster = TrainDelayForecaster.load("models/v1_lgbm.pkl")

    # Construct sample features with active speed restriction and congestion
    feat_dict = {col: 0.0 for col in FeaturePipeline.FEATURE_COLUMNS}
    feat_dict["distance_km"] = 45.0
    feat_dict["line_speed_kmph"] = 110.0
    feat_dict["is_tsr"] = 1.0
    feat_dict["active_disruption_severity"] = 0.8
    feat_dict["is_congestion"] = 1.0
    feat_dict["is_peak_hour"] = 1.0
    feat_dict["current_delay_min"] = 12.0
    feat_dict["preceding_train_delay"] = 15.0

    df_sample = pd.DataFrame([feat_dict])
    contexts = [
        {
            "id": "NDLS-GZB-DN",
            "from_station": "NDLS",
            "to_station": "GZB",
            "has_tsr": True,
            "has_congestion": True,
            "is_junction": True,
        }
    ]

    drivers = extract_shap_drivers(forecaster, df_sample, contexts, top_k=3)

    assert 1 <= len(drivers) <= 3
    for d in drivers:
        assert "feature" in d
        assert "importance" in d
        assert "shap_value" in d
        assert "category" in d
        assert isinstance(d["importance"], float)
        assert d["importance"] >= 0.0


def test_text_template_no_placeholders_and_real_values():
    """Verify that templates generate rich plain-language explanations referencing real values without placeholders."""
    drivers = [
        {
            "feature": "is_tsr",
            "label": "Temporary Speed Restriction",
            "category": "tsr",
            "feature_val": 0.8,
            "affected_sections": ["NDLS-GZB-DN"],
            "affected_stations": ["GZB"],
        },
        {
            "feature": "is_congestion",
            "label": "Peak-Hour Congestion",
            "category": "congestion",
            "feature_val": 1.0,
            "affected_sections": ["NDLS-GZB-DN"],
            "affected_stations": ["GZB"],
        },
    ]

    text = format_explanation(delta_min=14.0, top_drivers=drivers, target_station="GZB", prefix_style="delta")
    assert text.startswith("+14 min:")
    assert "NDLS-GZB-DN" in text
    assert "GZB" in text

    # Check that forbidden placeholder terms never appear
    lower_text = text.lower()
    for ph in FORBIDDEN_PLACEHOLDERS:
        assert ph not in lower_text, f"Found forbidden placeholder '{ph}' in explanation: '{text}'"


def test_every_prediction_returns_reasons_and_stores_change_log():
    """End-to-end test verifying that every downstream prediction returns reasons and populates change logs."""
    engine = get_engine()
    init_db(engine)

    forecaster = TrainDelayForecaster.load("models/v1_lgbm.pkl")
    quantile_model = QuantileForecaster.load("models/quantile_models.pkl")

    # Dummy fitted pipeline
    pipeline = FeaturePipeline()
    pipeline.is_fitted = True
    pipeline.historical_mean_delay = {}
    pipeline.historical_std_delay = {}

    explainer = ETAExplainer(
        model=forecaster,
        pipeline=pipeline,
        quantile_model=quantile_model,
    )

    with Session(engine) as session:
        # Fetch an active test run
        run = session.execute(select(Run)).scalars().first()
        assert run is not None

        events = session.execute(
            select(RunEvent).where(RunEvent.run_id == run.run_id).order_by(RunEvent.seq)
        ).scalars().all()

        obs_time = events[0].actual_dep or datetime.combine(run.run_date, datetime.min.time().replace(hour=7))

        predictions = explainer.predict_and_explain(
            run_id=run.run_id,
            timestamp=obs_time,
            db_session=session,
            log_changes=True,
        )

        assert len(predictions) > 0, "Must return downstream predictions."

        for p in predictions:
            # 1. Every prediction returns at least one reason
            assert "reasons" in p
            assert isinstance(p["reasons"], str)
            assert len(p["reasons"].strip()) > 0

            # 2. Reasons reference real domain concepts and no placeholder text
            r_lower = p["reasons"].lower()
            for ph in FORBIDDEN_PLACEHOLDERS:
                assert ph not in r_lower, f"Placeholder '{ph}' found in reasons: '{p['reasons']}'"

            # 3. Top drivers list is populated (1 to 3 drivers)
            assert "top_drivers" in p
            assert 1 <= len(p["top_drivers"]) <= 3

        # 4. Confirm change log was stored in the database
        history = get_eta_change_history(run.run_id, session)
        assert len(history) >= len(predictions)

        first_log = history[0]
        assert first_log["run_id"] == run.run_id
        assert first_log["new_eta"] is not None
        assert first_log["reasons"] is not None
        assert len(first_log["reasons"]) > 0


def test_rule_based_fallback():
    """Verify rule-based fallback when model is not available."""
    df_feat = pd.DataFrame([{
        "is_tsr": 1.0,
        "active_disruption_severity": 0.7,
        "is_congestion": 0.0,
        "is_weather": 1.0,
        "current_delay_min": 8.0,
        "line_speed_kmph": 100.0,
        "dwell_last_station": 1.0,
    }])
    contexts = [{"id": "CNB-PRYJ-DN", "from_station": "CNB", "to_station": "PRYJ", "has_tsr": True, "has_weather": True}]

    drivers = extract_rule_based_drivers(df_feat, contexts, top_k=3)
    assert 1 <= len(drivers) <= 3
    assert any(d["category"] in {"tsr", "weather", "upstream_delay"} for d in drivers)

    clause = driver_to_text(drivers[0])
    assert len(clause) > 0
    assert "CNB-PRYJ-DN" in clause or "speed restriction" in clause
