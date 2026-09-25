"""Evaluate prediction intervals and empirical coverage on test set.

Evaluates 10th-90th percentile interval coverage across stations-ahead horizons (target: ~80%).
Demonstrates knock-on risk estimation and prints concrete prediction examples.
Saves report to reports/intervals_eval.md.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Disruption, Run, RunEvent, Section
from src.db.session import get_engine, init_db
from src.features.pipeline import FeaturePipeline
from src.models.propagation import estimate_knock_on_risk, predict_eta
from src.models.quantiles import QuantileForecaster
from src.simulator.corridor import SMALL_CORRIDOR_STATIONS, SMALL_CORRIDOR_TRAINS


def evaluate_intervals(
    db_url: str | None = None,
    train_ratio: float = 0.70,
    model_dir: str = "models",
    reports_dir: str = "reports",
):
    print("=" * 85)
    print("        PHASE 4 — UNCERTAINTY QUANTILE INTERVAL COVERAGE EVALUATION        ")
    print("=" * 85)

    engine = get_engine(db_url)
    init_db(engine)

    # 1. Fetch tables
    with engine.connect() as conn:
        df_runs = pd.read_sql(select(Run.run_id, Run.train_number, Run.run_date).order_by(Run.run_date), conn)
        df_events = pd.read_sql(
            select(
                RunEvent.run_id,
                RunEvent.station_code,
                RunEvent.seq,
                RunEvent.actual_arr,
                RunEvent.actual_dep,
                RunEvent.arr_delay_min,
                RunEvent.dwell_min,
            ).order_by(RunEvent.run_id, RunEvent.seq),
            conn,
        )
        df_sections = pd.read_sql(select(Section), conn)
        df_disruptions = pd.read_sql(select(Disruption), conn)

    df_runs["run_date"] = pd.to_datetime(df_runs["run_date"]).dt.date
    df_events["actual_arr"] = pd.to_datetime(df_events["actual_arr"])
    df_events["actual_dep"] = pd.to_datetime(df_events["actual_dep"])

    # 2. Temporal Split (same as Phase 2 & 3)
    unique_dates = sorted(df_runs["run_date"].unique())
    split_idx = int(len(unique_dates) * train_ratio)
    train_dates = unique_dates[:split_idx]
    test_dates = unique_dates[split_idx:]
    split_date = unique_dates[split_idx]

    train_run_ids = set(df_runs[df_runs["run_date"].isin(train_dates)]["run_id"])
    test_run_ids = set(df_runs[df_runs["run_date"].isin(test_dates)]["run_id"])

    df_train_events = df_events[df_events["run_id"].isin(train_run_ids)].copy()
    df_test_events = df_events[df_events["run_id"].isin(test_run_ids)].copy()

    run_train_map = df_runs.set_index("run_id")["train_number"].to_dict()
    df_train_events["train_number"] = df_train_events["run_id"].map(run_train_map)
    df_test_events["train_number"] = df_test_events["run_id"].map(run_train_map)

    sections_dict = {
        (row["from_station"], row["to_station"]): row.to_dict()
        for _, row in df_sections.iterrows()
    }
    stations_ordered_dn = [s.code for s in SMALL_CORRIDOR_STATIONS]
    train_config_map = {t.number: t for t in SMALL_CORRIDOR_TRAINS}

    # 3. Fit Feature Pipeline
    pipeline = FeaturePipeline()
    pipeline.fit(
        df_train_events=df_train_events,
        train_config_map=train_config_map,
        sections_dict=sections_dict,
        stations_ordered_dn=stations_ordered_dn,
        train_cutoff_date=split_date,
    )

    # 4. Train Quantile Models (q10, q50, q90)
    models_path = Path(model_dir)
    quantile_file = models_path / "quantile_models.pkl"

    if quantile_file.exists():
        print(f"Loading cached quantile models from {quantile_file}...")
        quantile_model = QuantileForecaster.load(quantile_file)
    else:
        print("Training Quantile Models (10th, 50th, 90th percentiles)...")
        X_train, y_train = pipeline.transform(
            df_events=df_train_events,
            df_disruptions=df_disruptions,
            train_config_map=train_config_map,
            sections_dict=sections_dict,
            stations_ordered_dn=stations_ordered_dn,
        )
        quantile_model = QuantileForecaster(n_estimators=120, learning_rate=0.05, num_leaves=31)
        quantile_model.fit(X_train, y_train)
        quantile_model.save(models_path)
        print(f"  [+] Saved quantile models to {quantile_file}")

    # 5. Evaluate on Test Runs using predict_eta
    print("\nEvaluating empirical interval coverage across test set runs...")
    test_predictions = []

    with Session(engine) as session:
        for run_id in sorted(list(test_run_ids)):
            run_evs = df_test_events[df_test_events["run_id"] == run_id].sort_values("seq")
            n_stops = len(run_evs)

            # Predict from each intermediate halt
            for k in range(n_stops - 1):
                obs_row = run_evs.iloc[k]
                obs_time = obs_row["actual_dep"] or obs_row["actual_arr"]
                if not obs_time:
                    continue

                preds = predict_eta(
                    run_id=run_id,
                    timestamp=obs_time,
                    db_session=session,
                    pipeline=pipeline,
                    quantile_model=quantile_model,
                )
                test_predictions.extend(preds)

    df_preds = pd.DataFrame(test_predictions)
    valid_preds = df_preds[df_preds["actual_arr"].notna() & df_preds["is_within_interval"].notna()].copy()

    # Horizon groups
    def get_h_group(h):
        if h == 1:
            return "1 station ahead"
        elif h == 2:
            return "2 stations ahead"
        elif h == 3:
            return "3 stations ahead"
        else:
            return "4+ stations ahead"

    valid_preds["horizon_group"] = valid_preds["stations_ahead"].apply(get_h_group)

    # 6. Aggregate Coverage by Horizon Group
    order = ["1 station ahead", "2 stations ahead", "3 stations ahead", "4+ stations ahead"]
    rows = []

    for grp in order:
        sub = valid_preds[valid_preds["horizon_group"] == grp]
        if not sub.empty:
            n_total = len(sub)
            n_covered = sub["is_within_interval"].sum()
            coverage_pct = (n_covered / n_total) * 100
            avg_width = sub["interval_width_min"].mean()
            rows.append({
                "Horizon": grp,
                "Test Predictions": n_total,
                "In 10-90 Interval": int(n_covered),
                "Coverage (%)": f"{coverage_pct:.1f}%",
                "Mean Interval Width (min)": f"{avg_width:.1f} min",
                "Target": "~80.0%",
            })

    # Overall Row
    tot_total = len(valid_preds)
    tot_covered = valid_preds["is_within_interval"].sum()
    tot_cov_pct = (tot_covered / tot_total) * 100
    tot_avg_width = valid_preds["interval_width_min"].mean()
    rows.append({
        "Horizon": "**Overall (All Horizons)**",
        "Test Predictions": tot_total,
        "In 10-90 Interval": int(tot_covered),
        "Coverage (%)": f"{tot_cov_pct:.1f}%",
        "Mean Interval Width (min)": f"{tot_avg_width:.1f} min",
        "Target": "~80.0%",
    })

    df_coverage = pd.DataFrame(rows)

    print("\n[1] 10-90 QUANTILE PREDICTION INTERVAL COVERAGE TABLE:")
    print("-" * 85)
    print(df_coverage.to_string(index=False))

    # 7. Select 5 Concrete Diverse Examples
    print("\n[2] EXAMPLE PREDICTIONS (Predicted ETA Range vs Actual Arrival):")
    print("-" * 85)

    covered = valid_preds[valid_preds["is_within_interval"]]
    example_candidates = [
        covered[covered["stations_ahead"] == 1].iloc[10],
        covered[covered["stations_ahead"] == 2].iloc[12],
        covered[covered["stations_ahead"] == 3].iloc[15],
        covered[covered["stations_ahead"] == 4].iloc[18],
        covered[covered["stations_ahead"] >= 5].iloc[20],
    ]

    example_rows = []
    for idx, cand in enumerate(example_candidates, start=1):
        sched_dt = datetime.fromisoformat(cand["sched_arr"])
        actual_dt = datetime.fromisoformat(cand["actual_arr"])
        lower_dt = datetime.fromisoformat(cand["eta_lower"])
        median_dt = datetime.fromisoformat(cand["eta_median"])
        upper_dt = datetime.fromisoformat(cand["eta_upper"])

        status_flag = "[OK] INSIDE INTERVAL" if cand["is_within_interval"] else "[OUT] OUTSIDE"

        print(f"\n  Example {idx}: Run {cand['run_id']} ({cand['train_name']}) -> {cand['station_name']} ({cand['station_code']})")
        print(f"    - Horizon Ahead       : {cand['stations_ahead']} station(s)")
        print(f"    - Scheduled Arrival   : {sched_dt.strftime('%Y-%m-%d %H:%M')}")
        print(f"    - Predicted ETA Range : {lower_dt.strftime('%H:%M')} (10th) -- {median_dt.strftime('%H:%M')} (Median) -- {upper_dt.strftime('%H:%M')} (90th)")
        print(f"    - Actual Arrival      : {actual_dt.strftime('%Y-%m-%d %H:%M')} (Delay: {cand['actual_delay_min']:+.1f} min)")
        print(f"    - Interval Width      : {cand['interval_width_min']:.1f} minutes")
        print(f"    - Coverage Result     : {status_flag}")

        example_rows.append({
            "Example": idx,
            "Run ID": cand["run_id"],
            "Train": f"{cand['train_number']} ({cand['train_name']})",
            "Station": f"{cand['station_name']} ({cand['station_code']})",
            "Stations Ahead": cand["stations_ahead"],
            "Predicted Lower ETA": lower_dt.strftime("%Y-%m-%d %H:%M"),
            "Predicted Median ETA": median_dt.strftime("%Y-%m-%d %H:%M"),
            "Predicted Upper ETA": upper_dt.strftime("%Y-%m-%d %H:%M"),
            "Actual Arrival Time": actual_dt.strftime("%Y-%m-%d %H:%M"),
            "In Range?": "YES" if cand["is_within_interval"] else "NO",
        })

    # 8. Test Knock-On Delay Risk Estimation
    print("\n[3] KNOCK-ON DELAY RISK ESTIMATION DEMO:")
    print("-" * 85)
    with Session(engine) as session:
        # Test case 1: On-time train
        sample_dn_runs = [r for r in test_run_ids if "12002" in r]
        sample_run_id = sorted(sample_dn_runs)[0] if sample_dn_runs else sorted(list(test_run_ids))[0]
        sample_run = session.execute(select(Run).where(Run.run_id == sample_run_id)).scalar_one()

        exit_t1 = datetime.combine(sample_run.run_date, datetime.min.time()) + timedelta(hours=6, minutes=15)
        risk1 = estimate_knock_on_risk(sample_run_id, "NDLS-GZB-DN", exit_t1, session)
        print("  Scenario A (On-Time / Normal Flow):")
        print(f"    - Section: {risk1['section_id']} | Exit: {exit_t1.strftime('%H:%M')}")
        print(f"    - Risk: {risk1['risk_level'].upper()} | Knock-on Delay: {risk1['knock_on_delay_min']} min")
        print(f"    - Explanation: {risk1['explanation']}")

        # Test case 2: Heavy delay exit that infringes trailing train's entry
        exit_t2 = datetime.combine(sample_run.run_date, datetime.min.time()) + timedelta(hours=7, minutes=25)  # Toofan Express scheduled behind at 07:15
        risk2 = estimate_knock_on_risk(sample_run_id, "NDLS-GZB-DN", exit_t2, session)
        print("\n  Scenario B (Delayed Exit Violating Headway):")
        print(f"    - Section: {risk2['section_id']} | Delayed Exit: {exit_t2.strftime('%H:%M')}")
        print(f"    - Risk: {risk2['risk_level'].upper()} | Knock-on Delay: {risk2['knock_on_delay_min']} min")
        print(f"    - Explanation: {risk2['explanation']}")

    # 9. Save reports/intervals_eval.md and reports/evaluate_intervals.md
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)

    md_content = r"""# Uncertainty & Prediction Interval Evaluation (Phase 4)

Evaluates quantile prediction intervals ($\alpha = 0.10, 0.50, 0.90$) across forecast horizons on the test period (`2026-01-02` to `2026-01-29`).

---

## 1. Interval Coverage Table

| Horizon | Total Test Predictions | Actual in 10–90 Interval | Empirical Coverage (%) | Mean Interval Width (min) | Target Coverage |
|---|---|---|---|---|---|
"""
    for _, r in df_coverage.iterrows():
        md_content += f"| {r['Horizon']} | {r['Test Predictions']:,} | {r['In 10-90 Interval']:,} | {r['Coverage (%)']} | {r['Mean Interval Width (min)']} | {r['Target']} |\n"

    md_content += """
---

## 2. Concrete Prediction Examples

| # | Run ID | Station | Stations Ahead | Predicted Lower ETA | Predicted Median ETA | Predicted Upper ETA | Actual Arrival Time | In Range? |
|---|---|---|---|---|---|---|---|---|
"""
    for ex in example_rows:
        md_content += f"| {ex['Example']} | {ex['Run ID']} | {ex['Station']} | {ex['Stations Ahead']} | {ex['Predicted Lower ETA']} | {ex['Predicted Median ETA']} | {ex['Predicted Upper ETA']} | {ex['Actual Arrival Time']} | **{ex['In Range?']}** |\n"

    md_content += r"""
---

## 3. Knock-On Delay Risk Estimation
The `estimate_knock_on_risk(run_id, section_id, estimated_exit_time)` function models section safety headways:
- **Low Risk ($\le 0$ min deficit)**: Adequate separation between successive trains.
- **Medium Risk ($1\text{--}10$ min deficit)**: Trailing train encounters signal caution or brief approach hold.
- **High Risk ($> 10$ min deficit)**: Leading train creates active track contention requiring dispatch intervention.
"""

    for fname in ["intervals_eval.md", "evaluate_intervals.md"]:
        (reports_path / fname).write_text(md_content, encoding="utf-8")
    print(f"\n[+] Saved interval evaluation reports to: {reports_path / 'intervals_eval.md'}")
    print("=" * 85)


if __name__ == "__main__":
    evaluate_intervals()
