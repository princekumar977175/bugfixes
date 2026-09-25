# Baseline Models Evaluation Report (Phase 2)

Evaluated on the synthetic corridor test set using strict **temporal splitting** (train on earlier dates, test on later dates).

### Split Configuration:
- **Training Period**: 2025-11-01 to 2026-01-01 (62 days, 620 train runs)
- **Test Period**: 2026-01-02 to 2026-01-29 (28 days, 280 test runs)
- **Total Test Predictions**: 16,408

---

## Benchmark Comparison Table

| Horizon | Test Samples | Baseline A MAE (min) | Baseline A RMSE (min) | Baseline B MAE (min) | Baseline B RMSE (min) | Baseline B vs A Improvement |
|---|---|---|---|---|---|---|
| 1 station ahead | 2,688 | 6.17 | 10.58 | 3.77 | 7.22 | +38.9% |
| 2 stations ahead | 2,408 | 11.45 | 17.26 | 8.45 | 13.48 | +26.2% |
| 3 stations ahead | 2,128 | 16.34 | 22.73 | 12.50 | 18.34 | +23.5% |
| 4+ stations ahead | 9,184 | 35.36 | 44.63 | 27.02 | 35.96 | +23.6% |
| **Overall (All Horizons)** | 16,408 | 24.60 | 35.27 | 18.60 | 28.33 | +24.4% |

---

## Key Observations
1. **Short-horizon forecasting ($h=1$)**:
   - Baseline A (`scheduled + current_delay`) performs reasonably well ($MAE \approx 4\text{--}6\text{ min}$) over a single station hop where disruptions have little time to compound.
2. **Longer-horizon forecasting ($h \ge 3$)**:
   - Baseline A error compounds rapidly as trains encounter downstream speed restrictions, morning/evening congestion at junctions, and winter fog.
   - Baseline B incorporates physical section line speeds and training-derived historical mean delay per section and hour, significantly stabilizing multi-hop error.
3. **Foundation for ML (Phase 3)**:
   - Baseline B will serve as the benchmark for the LightGBM forecasting model in Phase 3.
