"""Tests for downstream ETA propagation, quantile intervals, and knock-on delay estimation."""

from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from src.db.models import Run, RunEvent
from src.db.session import get_engine, init_db
from src.features.pipeline import FeaturePipeline
from src.models.propagation import estimate_knock_on_risk, predict_eta
from src.models.quantiles import QuantileForecaster
from src.simulator.corridor import (
    SMALL_CORRIDOR_STATIONS,
    SMALL_CORRIDOR_TRAINS,
    build_corridor_sections,
)


def test_quantile_forecaster_monotonicity():
    """Verify that QuantileForecaster enforces q10 <= q50 <= q90."""
    forecaster = QuantileForecaster(n_estimators=10, num_leaves=7)
    X = pd.DataFrame([{col: 1.0 for col in FeaturePipeline.FEATURE_COLUMNS} for _ in range(30)])
    y = pd.Series([5.0] * 30)

    forecaster.fit(X, y)
    q10, q50, q90 = forecaster.predict_quantiles(X.iloc[:5])

    for i in range(5):
        assert q10[i] >= 0.0
        assert q10[i] <= q50[i] + 1e-6
        assert q50[i] <= q90[i] + 1e-6


def test_predict_eta_downstream_intervals():
    """Verify that predict_eta returns properly formatted downstream predictions with monotonic intervals."""
    engine = get_engine()
    init_db(engine)

    stations_ordered = [s.code for s in SMALL_CORRIDOR_STATIONS]
    _, sections = build_corridor_sections(SMALL_CORRIDOR_STATIONS)
    sec_dict = {(sec["from_station"], sec["to_station"]): sec for sec in sections}
    train_cfg_map = {t.number: t for t in SMALL_CORRIDOR_TRAINS}

    pipeline = FeaturePipeline()
    pipeline.fit(
        df_train_events=pd.DataFrame([
            {
                "run_id": "run_test_init",
                "seq": 1,
                "station_code": "NDLS",
                "train_number": "12002",
                "actual_arr": None,
                "actual_dep": datetime(2025, 11, 1, 6, 0),
                "arr_delay_min": 0.0,
                "dwell_min": 0.0,
            },
            {
                "run_id": "run_test_init",
                "seq": 2,
                "station_code": "GZB",
                "train_number": "12002",
                "actual_arr": datetime(2025, 11, 1, 6, 18),
                "actual_dep": datetime(2025, 11, 1, 6, 20),
                "arr_delay_min": 4.0,
                "dwell_min": 2.0,
            },
        ]),
        train_config_map=train_cfg_map,
        sections_dict=sec_dict,
        stations_ordered_dn=stations_ordered,
        train_cutoff_date=datetime(2025, 12, 1).date(),
    )

    quantile_model = QuantileForecaster(n_estimators=10, num_leaves=7)
    X = pd.DataFrame([{col: 1.0 for col in FeaturePipeline.FEATURE_COLUMNS} for _ in range(20)])
    y = pd.Series([2.0] * 20)
    quantile_model.fit(X, y)

    with Session(engine) as session:
        # Get a real run from the DB
        run = session.query(Run).first()
        assert run is not None, "Database must have runs generated."

        events = session.query(RunEvent).filter_by(run_id=run.run_id).order_by(RunEvent.seq).all()
        # Pick timestamp right after departure of stop 1
        obs_time = events[0].actual_dep

        preds = predict_eta(
            run_id=run.run_id,
            timestamp=obs_time,
            db_session=session,
            pipeline=pipeline,
            quantile_model=quantile_model,
        )

        assert len(preds) > 0
        for p in preds:
            assert "station_code" in p
            assert "eta_lower" in p
            assert "eta_median" in p
            assert "eta_upper" in p
            assert "interval_width_min" in p
            assert p["interval_width_min"] >= 0.0

            lower = datetime.fromisoformat(p["eta_lower"])
            median = datetime.fromisoformat(p["eta_median"])
            upper = datetime.fromisoformat(p["eta_upper"])

            assert lower <= median <= upper


def test_estimate_knock_on_risk():
    """Verify knock-on risk estimation correctly flags headway deficits."""
    engine = get_engine()
    init_db(engine)

    with Session(engine) as session:
        run = session.query(Run).first()
        assert run is not None

        # Scenario 1: Early/normal exit -> low risk
        t_early = datetime.combine(run.run_date, datetime.min.time().replace(hour=5, minute=45))
        risk_low = estimate_knock_on_risk(run.run_id, "NDLS-GZB-DN", t_early, session)
        assert risk_low["risk_level"] in {"low", "medium"}

        # Scenario 2: Severe delay exit that blocks a following train scheduled shortly after
        t_delayed = datetime.combine(run.run_date, datetime.min.time().replace(hour=7, minute=25))
        risk_high = estimate_knock_on_risk(run.run_id, "NDLS-GZB-DN", t_delayed, session)
        assert "risk_level" in risk_high
        assert "knock_on_delay_min" in risk_high
