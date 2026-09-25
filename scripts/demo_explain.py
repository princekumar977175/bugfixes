"""Demonstration script for Phase 5 explainability and ETA change logging.

Prints 3 concrete real prediction explanations with top-3 SHAP drivers and verifies change log persistence.
"""

import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Run, RunEvent
from src.db.session import get_engine, init_db
from src.explain.explainer import ETAExplainer
from src.explain.tracker import get_eta_change_history
from src.features.pipeline import FeaturePipeline
from src.models.ml_model import TrainDelayForecaster
from src.models.quantiles import QuantileForecaster


def run_demo() -> None:
    print("=" * 85)
    print("         PHASE 5 — EXPLAINABILITY & ETA CHANGE LOG DEMONSTRATION           ")
    print("=" * 85)

    engine = get_engine()
    init_db(engine)

    forecaster = TrainDelayForecaster.load("models/v1_lgbm.pkl")
    quantile_model = QuantileForecaster.load("models/quantile_models.pkl")

    pipeline = FeaturePipeline()
    pipeline.is_fitted = True
    pipeline.historical_mean_delay = {}
    pipeline.historical_std_delay = {}

    explainer = ETAExplainer(forecaster, pipeline, quantile_model)

    sample_runs_specs = [
        ("12002_20260115", 2, "Vande Bharat Express (Dn)"),
        ("12302_20260120", 2, "Howrah Rajdhani Express (Dn)"),
        ("13008_20260118", 4, "Toofan Express (Dn)"),
    ]

    with Session(engine) as session:
        for idx, (run_id, obs_seq, _train_desc) in enumerate(sample_runs_specs, 1):
            run = session.execute(select(Run).where(Run.run_id == run_id)).scalar_one_or_none()
            if not run:
                # Fallback to any run
                run = session.execute(select(Run).order_by(Run.run_date.desc())).scalars().first()
                run_id = run.run_id

            events = session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
            ).scalars().all()

            obs_event = events[min(obs_seq, len(events) - 1)]
            obs_time = obs_event.actual_dep or obs_event.actual_arr

            # Run prediction with explanation and log change
            preds = explainer.predict_and_explain(
                run_id=run_id,
                timestamp=obs_time,
                db_session=session,
                log_changes=True,
            )

            # Choose an informative downstream station (e.g. 2nd or terminal downstream halt)
            target_p = next((p for p in preds if p["delta_min"] > 0), preds[-1])

            print(f"\n[Example {idx}] Train: {run.train.number} ({run.train.name}) | Run ID: {run_id}")
            print(f"  - Current Observation Point : {obs_event.station_code} at {obs_time.strftime('%Y-%m-%d %H:%M')}")
            print(f"  - Target Station Ahead      : {target_p['station_name']} ({target_p['station_code']}) [{target_p['stations_ahead']} stations ahead]")
            print(f"  - Scheduled Arrival Time    : {target_p['sched_arr']}")
            print(f"  - Predicted 10–90 ETA Range : [{target_p['eta_lower']} to {target_p['eta_upper']}]")
            print(f"  - Median Predicted ETA      : {target_p['eta_median']}")
            print(f"  - Delay Revision (Delta)    : {target_p['delta_min']:+.1f} min")
            print(f"  - Plain-Language Explanation: \"{target_p['reasons']}\"")
            print("  - Extracted Top-3 SHAP Drivers:")
            for d in target_p["top_drivers"]:
                print(f"      * {d['label']:<32} | SHAP Contrib: {d['shap_value']:+.2f} min | Importance: {d['importance']:.2f}")

        # Check recorded change logs in DB
        print("\n" + "-" * 85)
        print("DATABASE CHANGE LOG AUDIT:")
        history = get_eta_change_history(sample_runs_specs[0][0], session)
        print(f"  Total change logs recorded for Run {sample_runs_specs[0][0]}: {len(history)} entries.")
        if history:
            sample_log = history[0]
            print(f"  Sample Log Entry -> Station: {sample_log['station_code']} | Delta: {sample_log['delta_min']:+.1f}m | Timestamp: {sample_log['timestamp']}")
            print(f"                      Reasons: \"{sample_log['reasons']}\"")

    print("=" * 85)


if __name__ == "__main__":
    run_demo()
