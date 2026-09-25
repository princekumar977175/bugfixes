# ML Model Evaluation Report (Phase 3)

Benchmark comparison between **Baseline A**, **Baseline B**, and the **LightGBM Regressor (`models/v1_lgbm.pkl`)** on the test split.

### Split Configuration:
- **Training Period**: 2025-11-01 to 2026-01-01 (62 days, 620 runs)
- **Testing Period**: 2026-01-02 to 2026-01-29 (28 days, 280 runs)
- **Total Test Predictions**: 16,408

---

## Benchmark Comparison Table

| Horizon | Samples | Baseline A MAE (min) | Baseline A RMSE (min) | Baseline B MAE (min) | Baseline B RMSE (min) | LightGBM MAE (min) | LightGBM RMSE (min) | ML vs Baseline A | ML vs Baseline B |
|---|---|---|---|---|---|---|---|---|---|
| 1 station ahead | 2,688 | 6.17 | 10.58 | 3.77 | 7.22 | 1.47 | 2.90 | +76.2% | +61.1% |
| 2 stations ahead | 2,408 | 11.45 | 17.26 | 8.45 | 13.48 | 4.90 | 7.82 | +57.2% | +42.0% |
| 3 stations ahead | 2,128 | 16.34 | 22.73 | 12.50 | 18.34 | 8.06 | 11.76 | +50.7% | +35.5% |
| 4+ stations ahead | 9,184 | 35.36 | 44.63 | 27.02 | 35.96 | 23.77 | 31.93 | +32.8% | +12.0% |
| **Overall (All Horizons)** | 16,408 | 24.60 | 35.27 | 18.60 | 28.33 | 15.31 | 24.47 | +37.8% | +17.7% |

---

## Top 10 Features by Importance

| Rank | Feature | Importance (Split Count) |
|---|---|---|
| 1 | `hist_mean_delay` | 734 |
| 2 | `dep_hour` | 587 |
| 3 | `hist_std_delay` | 486 |
| 4 | `dwell_last_station` | 435 |
| 5 | `priority_class` | 415 |
| 6 | `current_delay_min` | 413 |
| 7 | `section_code` | 362 |
| 8 | `delay_trend_last_3` | 261 |
| 9 | `distance_km` | 244 |
| 10 | `scheduled_runtime_min` | 142 |
