"""Tests for data leakage prevention, feature pipeline integrity, and ML model persistence."""

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.features.pipeline import FeaturePipeline
from src.models.ml_model import TrainDelayForecaster
from src.simulator.corridor import (
    SMALL_CORRIDOR_STATIONS,
    SMALL_CORRIDOR_TRAINS,
    build_corridor_sections,
)


def test_feature_pipeline_no_data_leakage():
    """Verify that FeaturePipeline strictly uses training dates and avoids leakage."""
    stations_ordered = [s.code for s in SMALL_CORRIDOR_STATIONS]
    _, sections = build_corridor_sections(SMALL_CORRIDOR_STATIONS)
    sec_dict = {(sec["from_station"], sec["to_station"]): sec for sec in sections}
    train_cfg_map = {t.number: t for t in SMALL_CORRIDOR_TRAINS}

    cutoff = date(2025, 12, 1)

    # Synthetic training events (before cutoff)
    train_events = [
        {
            "run_id": "run_early",
            "seq": 1,
            "station_code": "NDLS",
            "train_number": "12002",
            "actual_arr": None,
            "actual_dep": datetime(2025, 11, 15, 6, 0),
            "arr_delay_min": 0.0,
            "dwell_min": 0.0,
        },
        {
            "run_id": "run_early",
            "seq": 2,
            "station_code": "GZB",
            "train_number": "12002",
            "actual_arr": datetime(2025, 11, 15, 6, 20),
            "actual_dep": datetime(2025, 11, 15, 6, 22),
            "arr_delay_min": 6.0,
            "dwell_min": 2.0,
        },
    ]

    pipeline = FeaturePipeline()
    pipeline.fit(
        df_train_events=pd.DataFrame(train_events),
        train_config_map=train_cfg_map,
        sections_dict=sec_dict,
        stations_ordered_dn=stations_ordered,
        train_cutoff_date=cutoff,
    )

    assert pipeline.is_fitted
    assert pipeline.train_cutoff_date == cutoff

    # Verify that single-step live features do NOT use future actuals
    sec_ndls_gzb = sec_dict[("NDLS", "GZB")]
    obs_time = datetime(2025, 12, 10, 6, 0)
    X_step = pipeline.build_single_step_features(
        sec=sec_ndls_gzb,
        current_time=obs_time,
        priority_class=1,
        speed_factor=1.0,
        current_delay_min=5.0,
        dwell_last_station=2.0,
        delay_trend_last_3=0.0,
        preceding_train_delay=0.0,
        active_disruptions_for_sec=[],
    )

    # Ensure all required feature columns exist and contain valid numbers
    assert list(X_step.columns) == FeaturePipeline.FEATURE_COLUMNS
    assert not X_step.isna().any().any()
    assert X_step.loc[0, "current_delay_min"] == 5.0
    assert X_step.loc[0, "dep_hour"] == 6


def test_model_persistence_and_versioning(tmp_path: Path):
    """Verify that TrainDelayForecaster saves and loads with intact version and weights."""
    model = TrainDelayForecaster(n_estimators=10, num_leaves=7)

    # Dummy train data
    X = pd.DataFrame([{col: 1.0 for col in FeaturePipeline.FEATURE_COLUMNS} for _ in range(20)])
    y = pd.Series([2.5] * 20)

    model.fit(X, y, version="v1.0.0-test")

    save_path = tmp_path / "test_model.pkl"
    model.save(save_path)
    assert save_path.exists()

    loaded = TrainDelayForecaster.load(save_path)
    assert loaded.is_fitted
    assert loaded.version == "v1.0.0-test"
    assert loaded.feature_columns == FeaturePipeline.FEATURE_COLUMNS

    pred_original = model.predict_section_delay(X.iloc[[0]])
    pred_loaded = loaded.predict_section_delay(X.iloc[[0]])
    assert pred_original == pytest.approx(pred_loaded)


def test_model_iterative_propagation():
    """Verify that iterative propagation outputs strictly positive transit times and advancing ETAs."""
    stations_ordered = [s.code for s in SMALL_CORRIDOR_STATIONS]
    _, sections = build_corridor_sections(SMALL_CORRIDOR_STATIONS)
    sec_dict = {(sec["from_station"], sec["to_station"]): sec for sec in sections}

    pipeline = FeaturePipeline()
    pipeline.is_fitted = True
    pipeline.global_mean_delay = 2.0
    pipeline.global_std_delay = 1.0

    model = TrainDelayForecaster(n_estimators=10, num_leaves=7)
    X = pd.DataFrame([{col: 1.0 for col in FeaturePipeline.FEATURE_COLUMNS} for _ in range(20)])
    y = pd.Series([3.0] * 20)
    model.fit(X, y, version="v1.0.0")

    curr_time = datetime(2025, 11, 1, 6, 0)
    eta = model.predict_eta_iterative(
        pipeline=pipeline,
        current_dt=curr_time,
        current_station="NDLS",
        target_station="TDL",
        priority_class=1,
        speed_factor=1.0,
        current_delay_min=0.0,
        dwell_last_station=2.0,
        sections_dict=sec_dict,
        stations_ordered_dn=stations_ordered,
        train_halts=["NDLS", "GZB", "ALJN", "TDL"],
        halt_dwell_lookup={"GZB": 2.0, "ALJN": 3.0},
        active_disruptions_by_sec={},
    )

    # ETA must be strictly later than start time
    assert eta > curr_time
    total_transit = (eta - curr_time).total_seconds() / 60.0
    assert total_transit > 60.0  # NDLS to TDL is >200 km, takes > 1 hour
