"""Baseline models for train Expected Time of Arrival (ETA) forecasting.

Baseline A: Static Schedule + Current Delay.
Baseline B: Section-wise Kinematic + Historical Mean Added Delay (fit on training data).
"""

from datetime import datetime, timedelta

import pandas as pd


class BaselineA:
    """Baseline A: ETA = scheduled_arrival + current_delay."""

    def predict(
        self,
        sched_arr_dt: datetime,
        current_delay_min: float,
    ) -> datetime:
        """Predict ETA by adding current delay to static scheduled arrival."""
        return sched_arr_dt + timedelta(minutes=current_delay_min)


class BaselineB:
    """Baseline B: Section-wise kinematic runtime + historical mean added delay."""

    def __init__(self):
        # lookup: (section_id, hour) -> mean added delay in minutes
        self.section_hour_delays: dict[tuple[str, int], float] = {}
        # fallback lookup: section_id -> mean added delay
        self.section_delays: dict[str, float] = {}
        self.global_mean_delay: float = 0.0
        self.is_fitted: bool = False

    def fit(
        self,
        df_train_events: pd.DataFrame,
        sections_dict: dict[tuple[str, str], dict],
        stations_ordered_dn: list[str],
    ) -> "BaselineB":
        """Fit historical section delay aggregates strictly on training data."""
        # Calculate section transit delays from train events
        df_sorted = df_train_events.sort_values(by=["run_id", "seq"]).copy()
        df_sorted["actual_arr"] = pd.to_datetime(df_sorted["actual_arr"])
        df_sorted["actual_dep"] = pd.to_datetime(df_sorted["actual_dep"])

        # Shift to get previous stop's departure
        df_sorted["prev_station"] = df_sorted.groupby("run_id")["station_code"].shift(1)
        df_sorted["prev_dep"] = df_sorted.groupby("run_id")["actual_dep"].shift(1)

        # Filter valid section transit hops
        hops = df_sorted[df_sorted["prev_dep"].notna() & df_sorted["actual_arr"].notna()].copy()
        hops["actual_transit_min"] = (hops["actual_arr"] - hops["prev_dep"]).dt.total_seconds() / 60.0
        hops["dep_hour"] = hops["prev_dep"].dt.hour

        # For hops between adjacent stations, match directly to section
        records = []
        for _, row in hops.iterrows():
            u = row["prev_station"]
            v = row["station_code"]

            # If adjacent stations
            if (u, v) in sections_dict:
                sec = sections_dict[(u, v)]
                sched_runtime = sec["scheduled_runtime_min"] * row.get("speed_factor", 1.0)
                added_delay = max(0.0, row["actual_transit_min"] - sched_runtime)
                records.append({
                    "section_id": sec["id"],
                    "hour": row["dep_hour"],
                    "added_delay": added_delay,
                })
            else:
                # Multi-section hop (express train skipping intermediate stations)
                # Distribute added delay proportionally across intermediate sections
                if u in stations_ordered_dn and v in stations_ordered_dn:
                    i_u = stations_ordered_dn.index(u)
                    i_v = stations_ordered_dn.index(v)
                    step = 1 if i_u < i_v else -1
                    path_secs = []
                    total_sched_runtime = 0.0
                    for idx in range(i_u, i_v, step):
                        p1 = stations_ordered_dn[idx]
                        p2 = stations_ordered_dn[idx + step]
                        if (p1, p2) in sections_dict:
                            s = sections_dict[(p1, p2)]
                            path_secs.append(s)
                            total_sched_runtime += s["scheduled_runtime_min"] * row.get("speed_factor", 1.0)

                    if path_secs and total_sched_runtime > 0:
                        total_added = max(0.0, row["actual_transit_min"] - total_sched_runtime)
                        for s in path_secs:
                            s_sched = s["scheduled_runtime_min"] * row.get("speed_factor", 1.0)
                            s_added = total_added * (s_sched / total_sched_runtime)
                            records.append({
                                "section_id": s["id"],
                                "hour": row["dep_hour"],
                                "added_delay": s_added,
                            })

        df_sec_records = pd.DataFrame(records)

        if not df_sec_records.empty:
            # Group by (section_id, hour)
            grouped_sh = df_sec_records.groupby(["section_id", "hour"])["added_delay"].mean()
            self.section_hour_delays = grouped_sh.to_dict()

            # Group by section_id
            grouped_s = df_sec_records.groupby("section_id")["added_delay"].mean()
            self.section_delays = grouped_s.to_dict()

            self.global_mean_delay = df_sec_records["added_delay"].mean()
        else:
            self.global_mean_delay = 0.0

        self.is_fitted = True
        return self

    def predict(
        self,
        current_dt: datetime,
        current_station: str,
        target_station: str,
        train_speed_factor: float,
        sections_dict: dict[tuple[str, str], dict],
        stations_ordered_dn: list[str],
        train_halts: list[str],
        halt_dwell_lookup: dict[str, float],
    ) -> datetime:
        """Predict ETA at target_station using section-by-section kinematic summation."""
        if not self.is_fitted:
            raise RuntimeError("BaselineB must be fitted before calling predict.")

        # Determine ordered path of stations from current_station to target_station
        if current_station in stations_ordered_dn and target_station in stations_ordered_dn:
            i_from = stations_ordered_dn.index(current_station)
            i_to = stations_ordered_dn.index(target_station)
            step = 1 if i_from < i_to else -1
        else:
            raise ValueError(f"Unknown stations: {current_station} or {target_station}")

        sim_time = current_dt

        # Iterate section by section
        for idx in range(i_from, i_to, step):
            u = stations_ordered_dn[idx]
            v = stations_ordered_dn[idx + step]
            sec = sections_dict[(u, v)]
            sec_id = sec["id"]

            base_runtime = sec["scheduled_runtime_min"] * train_speed_factor

            # Historical mean added delay for this section and hour
            hour = sim_time.hour
            added_delay = self.section_hour_delays.get(
                (sec_id, hour),
                self.section_delays.get(sec_id, self.global_mean_delay),
            )

            section_transit_min = max(2.0, base_runtime + added_delay)
            sim_time += timedelta(minutes=section_transit_min)

            # If v is not target_station, and train halts at v, add scheduled dwell
            if v != target_station and v in train_halts:
                dwell_min = halt_dwell_lookup.get(v, 2.0)
                sim_time += timedelta(minutes=dwell_min)

        return sim_time
