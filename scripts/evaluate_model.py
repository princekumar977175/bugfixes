"""Train LightGBM delay forecaster and evaluate against Baseline A and Baseline B.

Produces:
1. Model artifact saved to models/v1_lgbm.pkl
2. Evaluation report saved to reports/model_eval.md
3. Benchmark comparison table by stations ahead
4. Top 10 features by importance
"""

import math
import sys
from datetime import timedelta
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
from sqlalchemy import select

from src.db.models import Disruption, Run, RunEvent, Section
from src.db.session import get_engine, init_db
from src.features.pipeline import FeaturePipeline
from src.models.baselines import BaselineA, BaselineB
from src.models.ml_model import TrainDelayForecaster
from src.simulator.corridor import SMALL_CORRIDOR_STATIONS, SMALL_CORRIDOR_TRAINS


def run_pipeline_and_evaluate(
    db_url: str | None = None,
    train_ratio: float = 0.70,
    model_path: str = "models/v1_lgbm.pkl",
    reports_dir: str = "reports",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train LightGBM model and compare against baselines across stations-ahead horizons."""
    engine = get_engine(db_url)
    init_db(engine)

    # 1. Fetch runs, events, sections, disruptions
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

    # 2. Strict Time-Based Split (same as Phase 2)
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

    # Speed factor for Baseline B
    df_train_events["speed_factor"] = df_train_events["train_number"].map(
        lambda t_num: train_config_map[t_num].speed_factor if t_num in train_config_map else 1.0
    )

    # 3. Fit Feature Pipeline exclusively on training split
    pipeline = FeaturePipeline()
    pipeline.fit(
        df_train_events=df_train_events,
        train_config_map=train_config_map,
        sections_dict=sections_dict,
        stations_ordered_dn=stations_ordered_dn,
        train_cutoff_date=split_date,
    )

    # 4. Extract features & train LightGBM regressor
    X_train, y_train = pipeline.transform(
        df_events=df_train_events,
        df_disruptions=df_disruptions,
        train_config_map=train_config_map,
        sections_dict=sections_dict,
        stations_ordered_dn=stations_ordered_dn,
    )

    forecaster = TrainDelayForecaster(n_estimators=150, learning_rate=0.05, num_leaves=31)
    forecaster.fit(X_train, y_train, version="v1.0.0")
    forecaster.save(model_path)

    # Compute Feature Importances
    importances = forecaster.model.feature_importances_
    df_importance = pd.DataFrame({
        "Feature": pipeline.FEATURE_COLUMNS,
        "Importance": importances,
    }).sort_values(by="Importance", ascending=False).reset_index(drop=True)

    # 5. Fit Baselines on train set
    baseline_a = BaselineA()
    baseline_b = BaselineB()
    baseline_b.fit(df_train_events, sections_dict, stations_ordered_dn)

    active_disruptions_by_sec = {}
    for _, d_row in df_disruptions.iterrows():
        active_disruptions_by_sec.setdefault(d_row["section_id"], []).append({
            "id": d_row["id"],
            "type": d_row["type"],
            "start_time": pd.to_datetime(d_row["start_time"]),
            "end_time": pd.to_datetime(d_row["end_time"]),
            "severity": float(d_row["severity"]),
        })

    # 6. Evaluate on Test Set
    test_runs_grouped = df_test_events.groupby("run_id")
    eval_records = []

    for run_id, run_evs in test_runs_grouped:
        run_evs = run_evs.sort_values("seq").reset_index(drop=True)
        train_num = run_train_map[run_id]
        t_cfg = train_config_map.get(train_num)
        speed_factor = t_cfg.speed_factor if t_cfg else 1.0
        priority_class = t_cfg.priority_class if t_cfg else 2
        train_halts = set(run_evs["station_code"])
        halt_dwell_lookup = {
            s: (t_cfg.junction_dwell_min if s in {"NDLS", "CNB", "PRYJ", "DDU", "PNBE", "GZB"} else t_cfg.default_dwell_min)
            for s in train_halts
        } if t_cfg else {}

        n_stops = len(run_evs)

        for k in range(n_stops - 1):
            curr_stop = run_evs.iloc[k]
            curr_obs_dt = curr_stop["actual_dep"] or curr_stop["actual_arr"]
            curr_station = curr_stop["station_code"]
            current_delay = curr_stop["arr_delay_min"]
            dwell_last = curr_stop["dwell_min"]

            for m in range(k + 1, n_stops):
                target_stop = run_evs.iloc[m]
                target_station = target_stop["station_code"]
                actual_arr = target_stop["actual_arr"]
                if actual_arr is None or pd.isna(actual_arr):
                    continue

                sched_arr_dt = actual_arr - timedelta(minutes=target_stop["arr_delay_min"])
                horizon = m - k
                if horizon == 1:
                    h_group = "1 station ahead"
                elif horizon == 2:
                    h_group = "2 stations ahead"
                elif horizon == 3:
                    h_group = "3 stations ahead"
                else:
                    h_group = "4+ stations ahead"

                # Baseline A Forecast
                eta_a = baseline_a.predict(sched_arr_dt, current_delay)
                err_a = (eta_a - actual_arr).total_seconds() / 60.0

                # Baseline B Forecast
                eta_b = baseline_b.predict(
                    current_dt=curr_obs_dt,
                    current_station=curr_station,
                    target_station=target_station,
                    train_speed_factor=speed_factor,
                    sections_dict=sections_dict,
                    stations_ordered_dn=stations_ordered_dn,
                    train_halts=list(train_halts),
                    halt_dwell_lookup=halt_dwell_lookup,
                )
                err_b = (eta_b - actual_arr).total_seconds() / 60.0

                # LightGBM Forecast
                eta_ml = forecaster.predict_eta_iterative(
                    pipeline=pipeline,
                    current_dt=curr_obs_dt,
                    current_station=curr_station,
                    target_station=target_station,
                    priority_class=priority_class,
                    speed_factor=speed_factor,
                    current_delay_min=current_delay,
                    dwell_last_station=dwell_last,
                    sections_dict=sections_dict,
                    stations_ordered_dn=stations_ordered_dn,
                    train_halts=list(train_halts),
                    halt_dwell_lookup=halt_dwell_lookup,
                    active_disruptions_by_sec=active_disruptions_by_sec,
                )
                err_ml = (eta_ml - actual_arr).total_seconds() / 60.0

                eval_records.append({
                    "horizon": horizon,
                    "horizon_group": h_group,
                    "abs_err_a": abs(err_a),
                    "sq_err_a": err_a ** 2,
                    "abs_err_b": abs(err_b),
                    "sq_err_b": err_b ** 2,
                    "abs_err_ml": abs(err_ml),
                    "sq_err_ml": err_ml ** 2,
                })

    df_eval = pd.DataFrame(eval_records)

    # 7. Aggregate Metrics Table
    order = ["1 station ahead", "2 stations ahead", "3 stations ahead", "4+ stations ahead"]
    rows = []
    for grp in order:
        sub = df_eval[df_eval["horizon_group"] == grp]
        if not sub.empty:
            mae_a = sub["abs_err_a"].mean()
            rmse_a = math.sqrt(sub["sq_err_a"].mean())
            mae_b = sub["abs_err_b"].mean()
            rmse_b = math.sqrt(sub["sq_err_b"].mean())
            mae_ml = sub["abs_err_ml"].mean()
            rmse_ml = math.sqrt(sub["sq_err_ml"].mean())
            imp_vs_a = ((mae_a - mae_ml) / mae_a) * 100
            imp_vs_b = ((mae_b - mae_ml) / mae_b) * 100
            rows.append({
                "Horizon": grp,
                "Samples": len(sub),
                "Baseline A MAE": round(mae_a, 2),
                "Baseline A RMSE": round(rmse_a, 2),
                "Baseline B MAE": round(mae_b, 2),
                "Baseline B RMSE": round(rmse_b, 2),
                "LightGBM MAE": round(mae_ml, 2),
                "LightGBM RMSE": round(rmse_ml, 2),
                "ML vs Base A": f"{imp_vs_a:+.1f}%",
                "ML vs Base B": f"{imp_vs_b:+.1f}%",
            })

    # Overall Summary
    tot_mae_a = df_eval["abs_err_a"].mean()
    tot_rmse_a = math.sqrt(df_eval["sq_err_a"].mean())
    tot_mae_b = df_eval["abs_err_b"].mean()
    tot_rmse_b = math.sqrt(df_eval["sq_err_b"].mean())
    tot_mae_ml = df_eval["abs_err_ml"].mean()
    tot_rmse_ml = math.sqrt(df_eval["sq_err_ml"].mean())
    rows.append({
        "Horizon": "**Overall (All Horizons)**",
        "Samples": len(df_eval),
        "Baseline A MAE": round(tot_mae_a, 2),
        "Baseline A RMSE": round(tot_rmse_a, 2),
        "Baseline B MAE": round(tot_mae_b, 2),
        "Baseline B RMSE": round(tot_rmse_b, 2),
        "LightGBM MAE": round(tot_mae_ml, 2),
        "LightGBM RMSE": round(tot_rmse_ml, 2),
        "ML vs Base A": f"{((tot_mae_a - tot_mae_ml) / tot_mae_a) * 100:+.1f}%",
        "ML vs Base B": f"{((tot_mae_b - tot_mae_ml) / tot_mae_b) * 100:+.1f}%",
    })

    df_summary = pd.DataFrame(rows)

    # 8. Save reports/model_eval.md
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    report_file = reports_path / "model_eval.md"

    md_content = f"""# ML Model Evaluation Report (Phase 3)

Benchmark comparison between **Baseline A**, **Baseline B**, and the **LightGBM Regressor (`{model_path}`)** on the test split.

### Split Configuration:
- **Training Period**: {train_dates[0]} to {train_dates[-1]} ({len(train_dates)} days, {len(train_run_ids)} runs)
- **Testing Period**: {test_dates[0]} to {test_dates[-1]} ({len(test_dates)} days, {len(test_run_ids)} runs)
- **Total Test Predictions**: {len(df_eval):,}

---

## Benchmark Comparison Table

| Horizon | Samples | Baseline A MAE (min) | Baseline A RMSE (min) | Baseline B MAE (min) | Baseline B RMSE (min) | LightGBM MAE (min) | LightGBM RMSE (min) | ML vs Baseline A | ML vs Baseline B |
|---|---|---|---|---|---|---|---|---|---|
"""
    for _, r in df_summary.iterrows():
        md_content += f"| {r['Horizon']} | {r['Samples']:,} | {r['Baseline A MAE']:.2f} | {r['Baseline A RMSE']:.2f} | {r['Baseline B MAE']:.2f} | {r['Baseline B RMSE']:.2f} | {r['LightGBM MAE']:.2f} | {r['LightGBM RMSE']:.2f} | {r['ML vs Base A']} | {r['ML vs Base B']} |\n"

    md_content += "\n---\n\n## Top 10 Features by Importance\n\n| Rank | Feature | Importance (Split Count) |\n|---|---|---|\n"
    for rank, (_, row) in enumerate(df_importance.head(10).iterrows(), start=1):
        md_content += f"| {rank} | `{row['Feature']}` | {row['Importance']:,} |\n"

    report_file.write_text(md_content, encoding="utf-8")
    return df_summary, df_importance


def main():
    print("=" * 85)
    print("           PHASE 3 — MODEL EVALUATION & BENCHMARK COMPARISON           ")
    print("=" * 85)

    df_summary, df_importance = run_pipeline_and_evaluate(model_path="models/v1_lgbm.pkl")

    print("\n[1] MODEL VS BASELINES COMPARISON TABLE:")
    print("-" * 85)
    print(df_summary.to_string(index=False))

    print("\n[2] TOP 10 FEATURES BY IMPORTANCE (LightGBM):")
    print("-" * 85)
    top10 = df_importance.head(10).copy()
    top10["Rank"] = range(1, len(top10) + 1)
    print(top10[["Rank", "Feature", "Importance"]].to_string(index=False))
    print("=" * 85)


if __name__ == "__main__":
    main()
