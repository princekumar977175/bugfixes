"""Rigorous data leakage prevention tests for feature pipeline and ML model."""

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from src.features.pipeline import FeaturePipeline
from src.simulator.corridor import (
    SMALL_CORRIDOR_STATIONS,
    SMALL_CORRIDOR_TRAINS,
    build_corridor_sections,
)


def test_no_future_information_in_prediction_features():
    """Verify that features extracted at prediction time T_pred are invariant to future data changes."""
    stations_ordered = [s.code for s in SMALL_CORRIDOR_STATIONS]
    _, sections = build_corridor_sections(SMALL_CORRIDOR_STATIONS)
    sec_dict = {(sec["from_station"], sec["to_station"]): sec for sec in sections}
    train_cfg_map = {t.number: t for t in SMALL_CORRIDOR_TRAINS}

    cutoff_date = date(2025, 12, 1)

    # Historical training events before cutoff
    train_events = [
        {
            "run_id": "train_run_1",
            "seq": 1,
            "station_code": "NDLS",
            "train_number": "12002",
            "actual_arr": None,
            "actual_dep": datetime(2025, 11, 10, 6, 0),
            "arr_delay_min": 0.0,
            "dwell_min": 0.0,
        },
        {
            "run_id": "train_run_1",
            "seq": 2,
            "station_code": "GZB",
            "train_number": "12002",
            "actual_arr": datetime(2025, 11, 10, 6, 20),
            "actual_dep": datetime(2025, 11, 10, 6, 22),
            "arr_delay_min": 4.0,
            "dwell_min": 2.0,
        },
    ]

    pipeline = FeaturePipeline()
    pipeline.fit(
        df_train_events=pd.DataFrame(train_events),
        train_config_map=train_cfg_map,
        sections_dict=sec_dict,
        stations_ordered_dn=stations_ordered,
        train_cutoff_date=cutoff_date,
    )

    sec_gzb_aljn = sec_dict[("GZB", "ALJN")]
    t_pred = datetime(2025, 12, 15, 6, 25)

    # 1. Base feature extraction at t_pred with known state up to t_pred
    active_disruptions_at_pred = [
        {
            "id": "DIS_PAST",
            "type": "TSR",
            "start_time": datetime(2025, 12, 15, 5, 0),
            "end_time": datetime(2025, 12, 15, 12, 0),
            "severity": 0.5,
        }
    ]

    feats_baseline = pipeline.build_single_step_features(
        sec=sec_gzb_aljn,
        current_time=t_pred,
        priority_class=1,
        speed_factor=1.0,
        current_delay_min=4.0,
        dwell_last_station=2.0,
        delay_trend_last_3=2.0,
        preceding_train_delay=1.0,
        active_disruptions_for_sec=active_disruptions_at_pred,
    )

    # 2. Add future events/disruptions that occur AFTER t_pred (e.g. at t_pred + 2 hours)
    future_disruptions = list(active_disruptions_at_pred) + [
        {
            "id": "DIS_FUTURE",
            "type": "weather",
            "start_time": t_pred + timedelta(hours=2),
            "end_time": t_pred + timedelta(hours=6),
            "severity": 0.9,
        }
    ]

    feats_with_future = pipeline.build_single_step_features(
        sec=sec_gzb_aljn,
        current_time=t_pred,
        priority_class=1,
        speed_factor=1.0,
        current_delay_min=4.0,
        dwell_last_station=2.0,
        delay_trend_last_3=2.0,
        preceding_train_delay=1.0,
        active_disruptions_for_sec=future_disruptions,
    )

    # Leakage Assertion: Features at t_pred MUST NOT change when future data changes
    pd.testing.assert_frame_equal(feats_baseline, feats_with_future)
    assert feats_baseline.loc[0, "has_disruption"] == 1
    assert feats_baseline.loc[0, "disruption_severity"] == 0.5  # not 0.9 from future!
    assert feats_baseline.loc[0, "disruption_type_tsr"] == 1
    assert feats_baseline.loc[0, "disruption_type_weather"] == 0  # future weather ignored!


def test_leakage_detector_fails_on_post_prediction_timestamp():
    """Verify that a deliberate leakage injection is caught and fails."""
    pipeline = FeaturePipeline()
    pipeline.is_fitted = True

    t_pred = datetime(2025, 12, 15, 6, 25)
    sec_mock = {
        "id": "NDLS-GZB-DN",
        "distance_km": 26.0,
        "line_speed_kmph": 130.0,
        "scheduled_runtime_min": 14.0,
    }

    # Simulate an invalid feature calculation that looks ahead into future actual arrival
    future_actual_arr = t_pred + timedelta(minutes=95)  # severe delay that happened in future

    # Check function that asserts prediction features do NOT equal or correlate with future actuals
    def validate_features_do_not_leak_future_arrival(feat_df: pd.DataFrame, future_arr: datetime, t_now: datetime):
        # Feature matrix cannot contain future arrival timestamp or future delay
        for col in feat_df.columns:
            val = feat_df.iloc[0][col]
            if isinstance(val, datetime) and val > t_now:
                raise ValueError(f"Leakage detected! Column {col} contains future timestamp {val} > {t_now}")

    # Valid feature set
    feats = pipeline.build_single_step_features(
        sec=sec_mock,
        current_time=t_pred,
        priority_class=1,
        speed_factor=1.0,
        current_delay_min=0.0,
        dwell_last_station=0.0,
        delay_trend_last_3=0.0,
        preceding_train_delay=0.0,
        active_disruptions_for_sec=[],
    )

    # Valid check passes
    validate_features_do_not_leak_future_arrival(feats, future_actual_arr, t_pred)

    # Intentionally corrupt features by injecting future actual timestamp to test detector
    leaked_feats = feats.copy()
    leaked_feats["future_arrival_leaked"] = future_actual_arr

    with pytest.raises(ValueError, match="Leakage detected"):
        validate_features_do_not_leak_future_arrival(leaked_feats, future_actual_arr, t_pred)
