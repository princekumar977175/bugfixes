"""Verification and audit script for prediction intervals and uncertainty bounds (Phase 4).

1. Prints interval coverage (10-90 range) by stations-ahead from reports/evaluate_intervals.md.
2. Flags a warning if overall coverage is below 70% or above 90% (target ~80%).
3. Flags a warning if coverage collapses sharply (drops below 50%) at any stations-ahead bucket.
4. Prints 5 example predictions: run_id, station, predicted lower/median/upper ETA,
   and actual arrival time, with a flag showing whether the actual fell inside the interval.
5. Prints average interval width by stations-ahead to check that it is widening but not exploding.
"""

import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd


def parse_markdown_table(table_block: list[str]) -> pd.DataFrame:
    """Parse a markdown table block into a pandas DataFrame."""
    lines = [line.strip() for line in table_block if line.strip().startswith("|") and not line.strip().startswith("|---")]
    if len(lines) < 2:
        return pd.DataFrame()
    headers = [c.strip() for c in lines[0].split("|")[1:-1]]
    rows = []
    for line in lines[1:]:
        cols = [c.strip() for c in line.split("|")[1:-1]]
        if cols and len(cols) == len(headers):
            rows.append(cols)
    return pd.DataFrame(rows, columns=headers)


def check_intervals(
    report_path: str = "reports/evaluate_intervals.md",
    fallback_report_path: str = "reports/intervals_eval.md",
) -> None:
    print("=" * 85)
    print("         PHASE 4 — UNCERTAINTY INTERVAL AUDIT & VERIFICATION REPORT         ")
    print("=" * 85)

    rep_file = Path(report_path)
    if not rep_file.exists():
        rep_file = Path(fallback_report_path)

    if not rep_file.exists():
        print(f"[!] Error: Report file '{report_path}' not found. Run scripts/evaluate_intervals.py first.")
        sys.exit(1)

    print(f"Loading interval evaluation report from: {rep_file}")
    content = rep_file.read_text(encoding="utf-8")

    # Split report into sections
    sections = content.split("## ")
    coverage_block = []
    examples_block = []

    for sec in sections:
        if "1. Interval Coverage Table" in sec:
            coverage_block = [line for line in sec.splitlines() if line.strip().startswith("|")]
        elif "2. Concrete Prediction Examples" in sec:
            examples_block = [line for line in sec.splitlines() if line.strip().startswith("|")]

    if not coverage_block:
        print("[!] Error: No Interval Coverage Table found in report.")
        sys.exit(1)

    df_coverage = parse_markdown_table(coverage_block)
    df_examples = parse_markdown_table(examples_block) if examples_block else pd.DataFrame()

    # -------------------------------------------------------------------------
    # 1. Print Interval Coverage & Average Width by Stations Ahead
    # -------------------------------------------------------------------------
    print("\n[1] INTERVAL COVERAGE (10–90 RANGE) & MEAN WIDTH BY STATIONS AHEAD:")
    print("-" * 85)
    print(df_coverage.to_string(index=False))

    # -------------------------------------------------------------------------
    # 2. Check Overall Coverage (Target 70% - 90%, centered ~80%)
    # -------------------------------------------------------------------------
    print("\n[2] OVERALL COVERAGE TARGET CHECK (Target: 70% – 90%):")
    print("-" * 85)

    overall_row = df_coverage[df_coverage["Horizon"].str.contains("Overall", case=False)]
    has_warning = False

    if overall_row.empty:
        print("  [WARNING] Overall coverage summary row not found in report table.")
        has_warning = True
    else:
        cov_str = overall_row.iloc[0]["Empirical Coverage (%)"].replace("%", "").strip()
        overall_cov = float(cov_str)
        if overall_cov < 70.0:
            print(f"  [WARNING] Overall coverage {overall_cov:.1f}% is BELOW acceptable threshold (70.0%)!")
            has_warning = True
        elif overall_cov > 90.0:
            print(f"  [WARNING] Overall coverage {overall_cov:.1f}% is ABOVE acceptable threshold (90.0%)!")
            has_warning = True
        else:
            print(f"  [PASS] Overall Empirical Coverage: {overall_cov:.1f}% (Healthy target ~80.0% within [70%, 90%])")

    # -------------------------------------------------------------------------
    # 3. Check for Sharp Coverage Collapse (< 50%) at Any Bucket
    # -------------------------------------------------------------------------
    print("\n[3] HORIZON BUCKET COVERAGE COLLAPSE CHECK (Threshold: >= 50.0%):")
    print("-" * 85)

    bucket_rows = df_coverage[~df_coverage["Horizon"].str.contains("Overall", case=False)].copy()
    any_collapsed = False

    for _, row in bucket_rows.iterrows():
        hz_name = row["Horizon"]
        cov_val = float(row["Empirical Coverage (%)"].replace("%", "").strip())
        if cov_val < 50.0:
            print(f"  [WARNING] Bucket '{hz_name}' collapsed sharply to {cov_val:.1f}% (< 50.0%)!")
            any_collapsed = True
            has_warning = True
        else:
            print(f"  [PASS] Bucket '{hz_name:<18}': {cov_val:.1f}% >= 50.0% threshold.")

    if not any_collapsed:
        print("  --> SUCCESS: No stations-ahead horizon experienced coverage collapse.")

    # -------------------------------------------------------------------------
    # 4. Print Average Interval Width by Stations Ahead (Widening but Not Exploding)
    # -------------------------------------------------------------------------
    print("\n[4] AVERAGE INTERVAL WIDTH PROGRESSION (Widening But Not Exploding):")
    print("-" * 85)

    widths = []
    horizon_names = []
    for _, row in bucket_rows.iterrows():
        w_str = row["Mean Interval Width (min)"].replace("min", "").strip()
        w_val = float(w_str)
        widths.append(w_val)
        horizon_names.append(row["Horizon"])
        print(f"  - {row['Horizon']:<18}: Mean Interval Width = {w_val:>5.1f} min")

    # Check that widths are widening
    is_widening = all(widths[i] <= widths[i + 1] for i in range(len(widths) - 1))
    max_width = max(widths) if widths else 0.0

    print("\n  Progression Summary:")
    print(f"    Width Progression : {' -> '.join(f'{w:.1f}m' for w in widths)}")
    if is_widening:
        print("    [PASS] Uncertainty expands monotonically as stations-ahead increases.")
    else:
        print("    [WARNING] Uncertainty width does not expand monotonically with distance!")
        has_warning = True

    if max_width > 120.0:
        print(f"    [WARNING] Interval width exploded (> 120 min) at terminal horizon: {max_width:.1f} min!")
        has_warning = True
    else:
        print(f"    [PASS] Interval width remains controlled and bounded: max width = {max_width:.1f} min (< 120 min).")

    # -------------------------------------------------------------------------
    # 5. Print 5 Concrete Example Predictions
    # -------------------------------------------------------------------------
    print("\n[5] 5 CONCRETE PREDICTION EXAMPLES (Predicted Range vs Actual Arrival):")
    print("-" * 85)

    if df_examples.empty:
        print("  [!] Warning: No examples table found in report.")
        has_warning = True
    else:
        # Display 5 examples
        ex_subset = df_examples.head(5).copy()
        # Clean markdown formatting like **YES**
        if "In Range?" in ex_subset.columns:
            ex_subset["In Range?"] = ex_subset["In Range?"].str.replace("*", "", regex=False).str.strip()

        print(ex_subset.to_string(index=False))

        print("\n  Individual Prediction Tracebacks:")
        for idx, (_, row) in enumerate(ex_subset.iterrows()):
            run_id = row.get("Run ID", "N/A")
            station = row.get("Station", "N/A")
            ahead = row.get("Stations Ahead", "N/A")
            lower = row.get("Predicted Lower ETA", "N/A")
            median = row.get("Predicted Median ETA", "N/A")
            upper = row.get("Predicted Upper ETA", "N/A")
            actual = row.get("Actual Arrival Time", "N/A")
            in_range = row.get("In Range?", "YES")

            flag_str = "[OK] INSIDE INTERVAL" if in_range == "YES" else "[OUT] OUTSIDE INTERVAL"
            print(f"    Example {idx + 1}: Run {run_id} -> {station} ({ahead} stations ahead)")
            print(f"      - Predicted Range : {lower} (10th) | {median} (Median) | {upper} (90th)")
            print(f"      - Actual Arrival  : {actual}")
            print(f"      - Covered?        : {flag_str}")

    print("\n" + "=" * 85)
    if has_warning:
        print("                 AUDIT COMPLETED WITH WARNINGS                      ")
    else:
        print("                 AUDIT COMPLETED SUCCESSFULLY: ALL CHECKS PASSED     ")
    print("=" * 85)


if __name__ == "__main__":
    check_intervals()
