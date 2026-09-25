"""Natural language text templates converting delay drivers into plain language.

Generates human-readable explanations such as:
"+12 min: speed restriction on section NDLS-GZB-DN, congestion at junction GZB"
"""

from typing import Any


def driver_to_text(driver: dict[str, Any]) -> str:
    """Convert an individual driver dictionary into a concise plain-language clause."""
    cat = driver.get("category", "general")
    feat = driver.get("feature", "")
    val = driver.get("feature_val", 0.0)
    sections = driver.get("affected_sections", [])
    stations = driver.get("affected_stations", [])

    sec_str = sections[0] if sections else "section ahead"
    st_str = stations[0] if stations else "junction ahead"

    if cat == "tsr" or feat in {"disruption_type_tsr", "disruption_severity", "has_disruption", "is_tsr", "active_disruption_severity"}:
        return f"speed restriction in section {sec_str}"

    elif cat == "congestion" or feat in {"is_congestion", "is_peak_hour"}:
        return f"congestion at junction {st_str}"

    elif cat == "weather" or feat in {"disruption_type_weather", "is_winter_fog_window", "is_weather", "is_fog_season"}:
        return f"fog visibility regulation on section {sec_str}"

    elif cat == "headway" or feat == "preceding_train_delay":
        if isinstance(val, (int, float)) and val > 0:
            return f"headway regulation behind preceding train ({val:.0f}m delay ahead)"
        return f"headway regulation behind preceding train on section {sec_str}"

    elif cat == "upstream_delay" or feat in {"current_delay_min", "delay_trend_last_3"}:
        if isinstance(val, (int, float)) and val > 0:
            return f"inherited upstream delay ({val:.0f} min)"
        return "accumulated upstream delay from prior sections"

    elif cat == "dwell" or feat == "dwell_last_station":
        if isinstance(val, (int, float)) and val > 2.0:
            return f"extended dwell overrun at {st_str} ({val:.0f} min)"
        return f"station dwell overrun at {st_str}"

    elif cat == "historical" or feat in {"hist_mean_delay", "hist_std_delay"}:
        return f"historical section bottleneck on section {sec_str}"

    elif cat == "priority" or feat == "priority_class":
        return "priority traffic dispatch regulation"

    elif cat == "speed_limit" or feat == "line_speed_kmph":
        return f"line speed restriction on section {sec_str}"

    elif cat == "clear_track":
        return "clear signals and normal line speed"

    # Default fallback using human-readable label
    lbl = driver.get("label", feat.replace("_", " ").title())
    return f"{lbl.lower()} on section {sec_str}"


def format_explanation(
    delta_min: float,
    top_drivers: list[dict[str, Any]],
    target_station: str | None = None,
    prefix_style: str = "delta",
) -> str:
    """Format delay delta and top drivers into a clean, operational plain-language explanation.

    Args:
        delta_min: Delay revision or absolute delay in minutes.
        top_drivers: List of extracted top driver dictionaries.
        target_station: Target station code or name (optional).
        prefix_style: 'delta' -> "+12 min: ...", 'eta_moved' -> "ETA moved +12 min: ..."
    """
    clauses: list[str] = []
    seen: set[str] = set()

    for d in top_drivers:
        clause = driver_to_text(d)
        if clause and clause not in seen:
            clauses.append(clause)
            seen.add(clause)

    # Ensure every prediction has at least one valid reason
    if not clauses:
        if delta_min > 0:
            clauses.append(f"operational track caution towards {target_station or 'downstream stations'}")
        elif delta_min < 0:
            clauses.append("recovering time under priority dispatch with clear section signals")
        else:
            clauses.append("on-time running with clear signals and high priority clearance")

    # Limit to top 3 clauses
    selected_clauses = clauses[:3]
    body = ", ".join(selected_clauses)

    sign = "+" if delta_min >= 0 else ""
    delta_display = f"{sign}{delta_min:.0f} min"

    if prefix_style == "eta_moved":
        return f"ETA moved {delta_display}: {body}"
    else:
        return f"{delta_display}: {body}"
