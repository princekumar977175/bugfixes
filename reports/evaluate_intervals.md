# Uncertainty & Prediction Interval Evaluation (Phase 4)

Evaluates quantile prediction intervals ($\alpha = 0.10, 0.50, 0.90$) across forecast horizons on the test period (`2026-01-02` to `2026-01-29`).

---

## 1. Interval Coverage Table

| Horizon | Total Test Predictions | Actual in 10–90 Interval | Empirical Coverage (%) | Mean Interval Width (min) | Target Coverage |
|---|---|---|---|---|---|
| 1 station ahead | 2,688 | 2,407 | 89.5% | 10.1 min | ~80.0% |
| 2 stations ahead | 2,408 | 1,974 | 82.0% | 18.4 min | ~80.0% |
| 3 stations ahead | 2,128 | 1,744 | 82.0% | 26.1 min | ~80.0% |
| 4+ stations ahead | 9,184 | 7,902 | 86.0% | 52.7 min | ~80.0% |
| **Overall (All Horizons)** | 16,408 | 14,027 | 85.5% | 37.2 min | ~80.0% |

---

## 2. Concrete Prediction Examples

| # | Run ID | Station | Stations Ahead | Predicted Lower ETA | Predicted Median ETA | Predicted Upper ETA | Actual Arrival Time | In Range? |
|---|---|---|---|---|---|---|---|---|
| 1 | 12001_20260103 | New Delhi (NDLS) | 1 | 2026-01-04 01:52 | 2026-01-04 01:52 | 2026-01-04 01:59 | 2026-01-04 01:52 | **YES** |
| 2 | 12001_20260104 | Prayagraj Jn (PRYJ) | 2 | 2026-01-04 19:54 | 2026-01-04 20:01 | 2026-01-04 20:19 | 2026-01-04 20:10 | **YES** |
| 3 | 12001_20260105 | Prayagraj Jn (PRYJ) | 3 | 2026-01-05 19:52 | 2026-01-05 20:00 | 2026-01-05 20:24 | 2026-01-05 20:06 | **YES** |
| 4 | 12001_20260106 | New Delhi (NDLS) | 4 | 2026-01-07 01:36 | 2026-01-07 01:40 | 2026-01-07 02:08 | 2026-01-07 01:54 | **YES** |
| 5 | 12001_20260106 | Aligarh Jn (ALJN) | 5 | 2026-01-07 00:09 | 2026-01-07 00:19 | 2026-01-07 01:01 | 2026-01-07 00:39 | **YES** |

---

## 3. Knock-On Delay Risk Estimation
The `estimate_knock_on_risk(run_id, section_id, estimated_exit_time)` function models section safety headways:
- **Low Risk ($\le 0$ min deficit)**: Adequate separation between successive trains.
- **Medium Risk ($1\text{--}10$ min deficit)**: Trailing train encounters signal caution or brief approach hold.
- **High Risk ($> 10$ min deficit)**: Leading train creates active track contention requiring dispatch intervention.
