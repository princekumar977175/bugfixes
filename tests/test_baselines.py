"""Tests for Baseline A and Baseline B forecasting models."""

from datetime import datetime

import pandas as pd
import pytest

from src.models.baselines import BaselineA, BaselineB
from src.simulator.corridor import SMALL_CORRIDOR_STATIONS, build_corridor_sections


def test_baseline_a_prediction():
    """Verify Baseline A adds current delay to scheduled arrival."""
    model = BaselineA()
    sched_arr = datetime(2025, 11, 1, 10, 0)
    current_delay = 15.5

    eta = model.predict(sched_arr, current_delay)
    assert eta == datetime(2025, 11, 1, 10, 15, 30)

    # Negative delay (early)
    eta_early = model.predict(sched_arr, -5.0)
    assert eta_early == datetime(2025, 11, 1, 9, 55)


def test_baseline_b_requires_fit():
    """Verify Baseline B raises error if predict is called before fitting."""
    model = BaselineB()
    with pytest.raises(RuntimeError, match="must be fitted"):
        model.predict(
            current_dt=datetime(2025, 11, 1, 6, 0),
            current_station="NDLS",
            target_station="GZB",
            train_speed_factor=1.0,
            sections_dict={},
            stations_ordered_dn=[],
            train_halts=[],
            halt_dwell_lookup={},
        )


def test_baseline_b_fit_and_predict():
    """Verify Baseline B learns section delay patterns and predicts monotonic future ETAs."""
    stations_ordered = [s.code for s in SMALL_CORRIDOR_STATIONS]
    _, sections = build_corridor_sections(SMALL_CORRIDOR_STATIONS)
    sec_dict = {(sec["from_station"], sec["to_station"]): sec for sec in sections}

    # Synthetic training hops
    train_data = [
        {
            "run_id": "run_1",
            "seq": 1,
            "station_code": "NDLS",
            "actual_arr": None,
            "actual_dep": datetime(2025, 11, 1, 6, 0),
            "speed_factor": 1.0,
        },
        {
            "run_id": "run_1",
            "seq": 2,
            "station_code": "GZB",
            "actual_arr": datetime(2025, 11, 1, 6, 25),  # 25 min transit (sched is 14 min -> +11 min delay)
            "actual_dep": datetime(2025, 11, 1, 6, 28),
            "speed_factor": 1.0,
        },
        {
            "run_id": "run_1",
            "seq": 3,
            "station_code": "ALJN",
            "actual_arr": datetime(2025, 11, 1, 7, 30),
            "actual_dep": datetime(2025, 11, 1, 7, 33),
            "speed_factor": 1.0,
        },
    ]
    df_train = pd.DataFrame(train_data)

    model = BaselineB()
    model.fit(df_train, sec_dict, stations_ordered)

    assert model.is_fitted
    assert len(model.section_delays) > 0

    # Predict ETA from NDLS to GZB
    cur_dt = datetime(2025, 12, 1, 6, 0)
    eta_gzb = model.predict(
        current_dt=cur_dt,
        current_station="NDLS",
        target_station="GZB",
        train_speed_factor=1.0,
        sections_dict=sec_dict,
        stations_ordered_dn=stations_ordered,
        train_halts=["NDLS", "GZB", "ALJN"],
        halt_dwell_lookup={"GZB": 3.0},
    )

    assert eta_gzb > cur_dt
    # Section runtime + learned delay should be close to 25 min
    transit_sec = (eta_gzb - cur_dt).total_seconds() / 60.0
    assert 20.0 <= transit_sec <= 30.0

    # Predict ETA from NDLS to ALJN (multi-hop)
    eta_aljn = model.predict(
        current_dt=cur_dt,
        current_station="NDLS",
        target_station="ALJN",
        train_speed_factor=1.0,
        sections_dict=sec_dict,
        stations_ordered_dn=stations_ordered,
        train_halts=["NDLS", "GZB", "ALJN"],
        halt_dwell_lookup={"GZB": 3.0},
    )
    assert eta_aljn > eta_gzb
