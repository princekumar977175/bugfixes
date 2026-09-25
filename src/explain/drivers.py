"""SHAP-based and rule-based top-driver extraction for train ETA delay predictions."""

from typing import Any

import pandas as pd

from src.features.pipeline import FeaturePipeline

CATEGORY_MAP = {
    "disruption_type_tsr": "tsr",
    "is_tsr": "tsr",
    "disruption_severity": "tsr",
    "active_disruption_severity": "tsr",
    "has_disruption": "tsr",
    "is_peak_hour": "congestion",
    "is_congestion": "congestion",
    "disruption_type_weather": "weather",
    "is_weather": "weather",
    "is_winter_fog_window": "weather",
    "is_fog_season": "weather",
    "preceding_train_delay": "headway",
    "current_delay_min": "upstream_delay",
    "delay_trend_last_3": "upstream_delay",
    "dwell_last_station": "dwell",
    "line_speed_kmph": "speed_limit",
    "distance_km": "distance",
    "scheduled_runtime_min": "runtime",
    "priority_class": "priority",
    "speed_factor": "train_speed",
    "hist_mean_delay": "historical",
    "hist_std_delay": "historical",
    "dep_hour": "schedule",
    "day_of_week": "schedule",
    "month": "season",
    "section_code": "infrastructure",
}

FEATURE_LABELS = {
    "disruption_type_tsr": "Temporary Speed Restriction (TSR)",
    "is_tsr": "Temporary Speed Restriction (TSR)",
    "disruption_severity": "Disruption Severity Factor",
    "active_disruption_severity": "Track Disruption Severity",
    "has_disruption": "Track Disruption Warning",
    "is_peak_hour": "Peak-Hour Traffic Congestion",
    "is_congestion": "Junction Congestion",
    "disruption_type_weather": "Adverse Weather / Fog Regulation",
    "is_weather": "Adverse Weather",
    "is_winter_fog_window": "Winter Fog Caution Window",
    "is_fog_season": "Fog Season Caution",
    "preceding_train_delay": "Preceding Train Headway",
    "current_delay_min": "Upstream Accumulated Delay",
    "delay_trend_last_3": "Recent Delay Trend (3 Sections)",
    "dwell_last_station": "Station Dwell Overrun",
    "line_speed_kmph": "Section Line Speed Limit",
    "distance_km": "Section Route Distance",
    "priority_class": "Train Priority Dispatch",
    "scheduled_runtime_min": "Base Timetable Runtime",
    "hist_mean_delay": "Historical Section Bottleneck Delay",
    "hist_std_delay": "Historical Section Delay Variance",
    "section_code": "Track Infrastructure Geometry",
    "speed_factor": "Train Class Speed Factor",
    "dep_hour": "Departure Time-of-Day",
    "day_of_week": "Day-of-Week Dispatch Load",
    "month": "Seasonal Operating Period",
}


def extract_shap_drivers(
    model: Any,
    X_features: pd.DataFrame,
    section_contexts: list[dict] | None = None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Extract top-k delay drivers using LightGBM TreeSHAP contributions."""
    feature_cols = FeaturePipeline.FEATURE_COLUMNS
    X_mat = X_features[feature_cols]

    # Retrieve underlying LightGBM booster
    booster = None
    if hasattr(model, "model") and hasattr(model.model, "booster_"):
        booster = model.model.booster_
    elif hasattr(model, "booster_"):
        booster = model.booster_
    elif hasattr(model, "models") and 0.50 in model.models and hasattr(model.models[0.50], "booster_"):
        booster = model.models[0.50].booster_

    if booster is None:
        return extract_rule_based_drivers(X_features, section_contexts, top_k)

    try:
        # Exact TreeSHAP contributions from LightGBM C++ engine
        # Output shape: (n_samples, n_features + 1), last column is expected value
        contribs = booster.predict(X_mat, pred_contrib=True)
        shap_values = contribs[:, :-1]  # (n_samples, n_features)

        # Aggregate Shapley contributions across route sections
        total_shap = shap_values.sum(axis=0)

        # Map to feature names
        driver_items = []
        for idx, col in enumerate(feature_cols):
            shap_val = float(total_shap[idx])
            mean_feature_val = float(X_mat[col].mean())
            max_feature_val = float(X_mat[col].max())

            driver_items.append({
                "feature": col,
                "label": FEATURE_LABELS.get(col, col.replace("_", " ").title()),
                "shap_value": shap_val,
                "importance": abs(shap_val),
                "feature_val": max_feature_val if max_feature_val > 0 else mean_feature_val,
                "category": CATEGORY_MAP.get(col, "general"),
            })

        # Rank drivers: prioritize positive delay contributors, then absolute importance
        driver_items.sort(key=lambda d: (d["shap_value"] > 0, d["importance"]), reverse=True)

        # Filter out negligible contributions (< 0.05 min) unless all are zero
        active_drivers = [d for d in driver_items if d["importance"] >= 0.05]
        if not active_drivers:
            active_drivers = driver_items[:top_k]
        else:
            active_drivers = active_drivers[:top_k]

        # Attach section and station context if available
        if section_contexts:
            _enrich_driver_contexts(active_drivers, section_contexts)

        return active_drivers

    except Exception:
        return extract_rule_based_drivers(X_features, section_contexts, top_k)


def extract_rule_based_drivers(
    X_features: pd.DataFrame,
    section_contexts: list[dict] | None = None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Rule-based driver extraction fallback inspecting active disruptions and track conditions."""
    drivers = []

    # 1. Active TSR (Temporary Speed Restriction)
    if "is_tsr" in X_features.columns and (X_features["is_tsr"] > 0).any():
        max_sev = float(X_features.get("active_disruption_severity", pd.Series([1.0])).max())
        drivers.append({
            "feature": "is_tsr",
            "label": "Temporary Speed Restriction (TSR)",
            "shap_value": 8.0 * max_sev,
            "importance": 8.0 * max_sev,
            "feature_val": max_sev,
            "category": "tsr",
        })

    # 2. Congestion / Peak Hour
    is_cong = (
        ("is_congestion" in X_features.columns and (X_features["is_congestion"] > 0).any())
        or ("is_peak_hour" in X_features.columns and (X_features["is_peak_hour"] > 0).any())
    )
    if is_cong:
        drivers.append({
            "feature": "is_congestion",
            "label": "Peak-Hour Junction Congestion",
            "shap_value": 5.0,
            "importance": 5.0,
            "feature_val": 1.0,
            "category": "congestion",
        })

    # 3. Preceding Train Delay
    if "preceding_train_delay" in X_features.columns and (X_features["preceding_train_delay"] > 0).any():
        p_delay = float(X_features["preceding_train_delay"].max())
        drivers.append({
            "feature": "preceding_train_delay",
            "label": "Preceding Train Headway",
            "shap_value": min(12.0, p_delay * 0.4),
            "importance": min(12.0, p_delay * 0.4),
            "feature_val": p_delay,
            "category": "headway",
        })

    # 4. Adverse Weather / Fog Season
    is_weather = (
        ("is_weather" in X_features.columns and (X_features["is_weather"] > 0).any())
        or ("is_fog_season" in X_features.columns and (X_features["is_fog_season"] > 0).any())
    )
    if is_weather:
        drivers.append({
            "feature": "is_weather",
            "label": "Fog Season Caution",
            "shap_value": 4.5,
            "importance": 4.5,
            "feature_val": 1.0,
            "category": "weather",
        })

    # 5. Upstream Accumulated Delay
    if "current_delay_min" in X_features.columns and (X_features["current_delay_min"] > 3.0).any():
        c_delay = float(X_features["current_delay_min"].max())
        drivers.append({
            "feature": "current_delay_min",
            "label": "Upstream Inherited Delay",
            "shap_value": min(15.0, c_delay * 0.3),
            "importance": min(15.0, c_delay * 0.3),
            "feature_val": c_delay,
            "category": "upstream_delay",
        })

    # 6. Dwell Overrun
    if "dwell_last_station" in X_features.columns and (X_features["dwell_last_station"] > 2.0).any():
        dwell_val = float(X_features["dwell_last_station"].max())
        drivers.append({
            "feature": "dwell_last_station",
            "label": "Station Dwell Overrun",
            "shap_value": dwell_val - 2.0,
            "importance": dwell_val - 2.0,
            "feature_val": dwell_val,
            "category": "dwell",
        })

    # Fallback default if completely on time
    if not drivers:
        drivers.append({
            "feature": "line_speed_kmph",
            "label": "Clear Track Signal Clearance",
            "shap_value": 0.0,
            "importance": 0.0,
            "feature_val": float(X_features.get("line_speed_kmph", pd.Series([130.0])).mean()),
            "category": "clear_track",
        })

    drivers.sort(key=lambda d: d["importance"], reverse=True)
    selected = drivers[:top_k]

    if section_contexts:
        _enrich_driver_contexts(selected, section_contexts)

    return selected


def _enrich_driver_contexts(drivers: list[dict[str, Any]], section_contexts: list[dict]) -> None:
    """Enrich drivers with actual downstream section IDs and station codes."""
    for d in drivers:
        cat = d.get("category")
        matched_sections = []
        matched_stations = []

        for ctx in section_contexts:
            sec_id = ctx.get("id") or ctx.get("section_id")
            from_st = ctx.get("from_station")
            to_st = ctx.get("to_station")

            if cat == "tsr" and ctx.get("has_tsr"):
                if sec_id and sec_id not in matched_sections:
                    matched_sections.append(sec_id)
            elif cat == "congestion" and (ctx.get("has_congestion") or ctx.get("is_junction")):
                st = to_st or from_st
                if st and st not in matched_stations:
                    matched_stations.append(st)
            elif cat == "weather" and ctx.get("has_weather"):
                if sec_id and sec_id not in matched_sections:
                    matched_sections.append(sec_id)
            elif cat == "headway" and ctx.get("preceding_delay", 0) > 0:
                if sec_id and sec_id not in matched_sections:
                    matched_sections.append(sec_id)

        # Fallback to the first downstream section/station if none specifically flagged
        if not matched_sections and section_contexts:
            first_sec = section_contexts[0].get("id") or section_contexts[0].get("section_id")
            if first_sec:
                matched_sections.append(first_sec)
        if not matched_stations and section_contexts:
            first_st = section_contexts[0].get("to_station") or section_contexts[0].get("from_station")
            if first_st:
                matched_stations.append(first_st)

        d["affected_sections"] = matched_sections
        d["affected_stations"] = matched_stations
