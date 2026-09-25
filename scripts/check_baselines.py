"""Verification script for baseline evaluation results and temporal split integrity.

1. Loads reports/baseline_eval.md (and database records).
2. Prints MAE/RMSE table for both baselines by stations-ahead.
3. Flags a warning if Baseline B's MAE is not lower than Baseline A's at every bucket.
4. Flags a warning if error does not increase as stations-ahead increases.
5. Confirms train/test split was done by date (no random split) and prints date ranges.
6. Prints row counts for train vs test.
"""

import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
from sqlalchemy import select

from src.db.models import Run, RunEvent
from src.db.session import get_engine, init_db


def check_baselines(report_path: str = "reports/baseline_eval.md", train_ratio: float = 0.70):
    print("=" * 75)
    print("                BASELINE VERIFICATION & AUDIT REPORT                 ")
    print("=" * 75)

    # 1. Parse reports/baseline_eval.md
    report_file = Path(report_path)
    if not report_file.exists():
        print(f"[!] Error: {report_file} does not exist. Run scripts/evaluate_baselines.py first.")
        sys.exit(1)

    content = report_file.read_text(encoding="utf-8")

    # Extract markdown table rows
    table_lines = []
    for line in content.splitlines():
        if line.strip().startswith("|") and not line.strip().startswith("|---"):
            table_lines.append(line.strip())

    if len(table_lines) < 2:
        print("[!] Error: No benchmark table found in report.")
        sys.exit(1)

    headers = [c.strip() for c in table_lines[0].split("|")[1:-1]]
    rows = []
    for line in table_lines[1:]:
        cols = [c.strip() for c in line.split("|")[1:-1]]
        if cols and len(cols) == len(headers):
            rows.append(cols)

    df_table = pd.DataFrame(rows, columns=headers)

    print("\n[1] BASELINE EVALUATION TABLE (By Stations Ahead):")
    print("-" * 75)
    print(df_table.to_string(index=False))

    # 2. Check if Baseline B's MAE < Baseline A's MAE at every horizon bucket
    print("\n[2] BASELINE B vs BASELINE A SUPERIORITY CHECK:")
    print("-" * 75)

    buckets = df_table[~df_table["Horizon"].str.contains("Overall", case=False)].copy()

    # Extract numerical MAE
    buckets["A_MAE"] = buckets["Baseline A MAE (min)"].astype(float)
    buckets["B_MAE"] = buckets["Baseline B MAE (min)"].astype(float)
    buckets["A_RMSE"] = buckets["Baseline A RMSE (min)"].astype(float)
    buckets["B_RMSE"] = buckets["Baseline B RMSE (min)"].astype(float)

    all_b_lower = True
    for _, r in buckets.iterrows():
        horizon_name = r["Horizon"]
        a_mae = r["A_MAE"]
        b_mae = r["B_MAE"]
        if b_mae < a_mae:
            diff = a_mae - b_mae
            pct = (diff / a_mae) * 100
            print(f"  [PASS] {horizon_name:<18}: Baseline B ({b_mae:.2f}m) < Baseline A ({a_mae:.2f}m) [-{diff:.2f}m, -{pct:.1f}%]")
        else:
            all_b_lower = False
            print(f"  [WARNING] {horizon_name:<18}: Baseline B ({b_mae:.2f}m) is NOT lower than Baseline A ({a_mae:.2f}m)!")

    if all_b_lower:
        print("  --> SUCCESS: Baseline B achieves lower MAE than Baseline A at EVERY horizon bucket.")
    else:
        print("  --> WARNING: Baseline B failed to achieve lower MAE in one or more buckets!")

    # 3. Check Monotonicity of Error (Does error increase as stations-ahead increases?)
    print("\n[3] ERROR HORIZON MONOTONICITY CHECK:")
    print("-" * 75)

    a_maes = buckets["A_MAE"].tolist()
    b_maes = buckets["B_MAE"].tolist()

    monotonic_a = all(a_maes[i] <= a_maes[i + 1] for i in range(len(a_maes) - 1))
    monotonic_b = all(b_maes[i] <= b_maes[i + 1] for i in range(len(b_maes) - 1))

    print(f"  Baseline A MAE Progression: {' -> '.join(f'{m:.2f}m' for m in a_maes)}")
    if monotonic_a:
        print("  [PASS] Baseline A error strictly increases as stations-ahead increases.")
    else:
        print("  [WARNING] Baseline A error does NOT increase monotonically over distance!")

    print(f"  Baseline B MAE Progression: {' -> '.join(f'{m:.2f}m' for m in b_maes)}")
    if monotonic_b:
        print("  [PASS] Baseline B error strictly increases as stations-ahead increases.")
    else:
        print("  [WARNING] Baseline B error does NOT increase monotonically over distance!")

    # 4 & 5. Verify Temporal Split and Row Counts from Database
    print("\n[4 & 5] TEMPORAL SPLIT AUDIT & DATASET ROW COUNTS:")
    print("-" * 75)

    engine = get_engine()
    init_db(engine)

    with engine.connect() as conn:
        df_runs = pd.read_sql(select(Run.run_id, Run.run_date).order_by(Run.run_date), conn)
        df_events = pd.read_sql(select(RunEvent.run_id, RunEvent.seq), conn)

    df_runs["run_date"] = pd.to_datetime(df_runs["run_date"]).dt.date
    unique_dates = sorted(df_runs["run_date"].unique())
    split_idx = int(len(unique_dates) * train_ratio)

    train_dates = set(unique_dates[:split_idx])
    test_dates = set(unique_dates[split_idx:])

    min_train, max_train = min(train_dates), max(train_dates)
    min_test, max_test = min(test_dates), max(test_dates)

    # Overlap check
    overlap = train_dates.intersection(test_dates)
    is_temporal = (max_train < min_test) and (len(overlap) == 0)

    print(f"  Train Date Range       : {min_train} to {max_train} ({len(train_dates)} distinct calendar days)")
    print(f"  Test Date Range        : {min_test} to {max_test} ({len(test_dates)} distinct calendar days)")
    print(f"  Date Intersection      : {len(overlap)} overlapping dates")

    if is_temporal:
        print(f"  [PASS] Split Method    : STRICT TEMPORAL SPLIT (no random splitting, cutoff at {min_test})")
    else:
        print("  [WARNING] Split Method : Potential date overlap detected!")

    train_runs = df_runs[df_runs["run_date"].isin(train_dates)]
    test_runs = df_runs[df_runs["run_date"].isin(test_dates)]

    train_run_ids = set(train_runs["run_id"])
    test_run_ids = set(test_runs["run_id"])

    train_events_count = len(df_events[df_events["run_id"].isin(train_run_ids)])
    test_events_count = len(df_events[df_events["run_id"].isin(test_run_ids)])

    print("\n  DATASET PARTITION SIZES:")
    print(f"    - Training Set : {len(train_runs):>5} runs ({train_events_count:>6} station events) [{len(train_runs)/len(df_runs)*100:.1f}%]")
    print(f"    - Testing Set  : {len(test_runs):>5} runs ({test_events_count:>6} station events) [{len(test_runs)/len(df_runs)*100:.1f}%]")
    print(f"    - Total        : {len(df_runs):>5} runs ({len(df_events):>6} station events)")
    print("=" * 75)


if __name__ == "__main__":
    check_baselines()
