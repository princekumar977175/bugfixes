"""Feature engineering pipeline for train delay forecasting per Section 5 of SPEC.md."""

from datetime import date, datetime

import pandas as pd


class FeaturePipeline:
    """Feature engineering pipeline computing features strictly at prediction moment without leakage."""

    FEATURE_COLUMNS = [
        "section_code",  # integer-encoded section
        "distance_km",
        "line_speed_kmph",
        "scheduled_runtime_min",
        "dep_hour",
        "day_of_week",
        "month",
        "is_winter_fog_window",
        "is_peak_hour",
        "priority_class",
        "speed_factor",
        "current_delay_min",
        "delay_trend_last_3",
        "dwell_last_station",
        "preceding_train_delay",
        "has_disruption",
        "disruption_severity",
        "disruption_type_tsr",
        "disruption_type_weather",
        "hist_mean_delay",
        "hist_std_delay",
    ]

    def __init__(self):
        self.section_hour_stats: dict[tuple[str, int], tuple[float, float]] = {}
        self.section_stats: dict[str, tuple[float, float]] = {}
        self.global_mean_delay: float = 0.0
        self.global_std_delay: float = 0.0
        self.section_to_code: dict[str, int] = {}
        self.is_fitted: bool = False
        self.train_cutoff_date: date | None = None

    def _extract_hops_chronological(
        self,
        df_events: pd.DataFrame,
        train_config_map: dict[str, any],
        sections_dict: dict[tuple[str, str], dict],
        stations_ordered_dn: list[str],
    ) -> pd.DataFrame:
        """Extract section traversals and compute causal delay trends and preceding-train headways."""
        df_sorted = df_events.sort_values(by=["run_id", "seq"]).copy()
        df_sorted["actual_arr"] = pd.to_datetime(df_sorted["actual_arr"])
        df_sorted["actual_dep"] = pd.to_datetime(df_sorted["actual_dep"])

        # Lag features along the train run
        df_sorted["prev_station"] = df_sorted.groupby("run_id")["station_code"].shift(1)
        df_sorted["prev_dep"] = df_sorted.groupby("run_id")["actual_dep"].shift(1)
        df_sorted["prev_arr_delay"] = df_sorted.groupby("run_id")["arr_delay_min"].shift(1)
        df_sorted["prev_dwell"] = df_sorted.groupby("run_id")["dwell_min"].shift(1)

        # Delays for last 3 stops to compute delay trend
        df_sorted["delay_lag_1"] = df_sorted["prev_arr_delay"]
        df_sorted["delay_lag_2"] = df_sorted.groupby("run_id")["arr_delay_min"].shift(2)
        df_sorted["delay_lag_3"] = df_sorted.groupby("run_id")["arr_delay_min"].shift(3)

        hops = df_sorted[df_sorted["prev_dep"].notna() & df_sorted["actual_arr"].notna()].copy()
        hops["actual_transit_min"] = (hops["actual_arr"] - hops["prev_dep"]).dt.total_seconds() / 60.0

        records = []
        for _, row in hops.iterrows():
            u = row["prev_station"]
            v = row["station_code"]
            t_num = row.get("train_number")
            t_cfg = train_config_map.get(t_num)
            speed_factor = t_cfg.speed_factor if t_cfg else 1.0
            prio_class = t_cfg.priority_class if t_cfg else 2

            curr_delay = row["prev_arr_delay"] if pd.notna(row["prev_arr_delay"]) else 0.0
            prev_dwell = row["prev_dwell"] if pd.notna(row["prev_dwell"]) else 0.0

            # Trend over last up to 3 sections
            lag1 = row["delay_lag_1"] if pd.notna(row["delay_lag_1"]) else curr_delay
            lag3 = row["delay_lag_3"] if pd.notna(row["delay_lag_3"]) else (
                row["delay_lag_2"] if pd.notna(row["delay_lag_2"]) else lag1
            )
            delay_trend_3 = curr_delay - lag3

            if (u, v) in sections_dict:
                sec = sections_dict[(u, v)]
                sched_runtime = sec["scheduled_runtime_min"] * speed_factor
                added_delay = max(0.0, row["actual_transit_min"] - sched_runtime)
                records.append({
                    "run_id": row["run_id"],
                    "section_id": sec["id"],
                    "entry_time": row["prev_dep"],
                    "exit_time": row["actual_arr"],
                    "distance_km": sec["distance_km"],
                    "line_speed_kmph": sec["line_speed_kmph"],
                    "scheduled_runtime_min": sec["scheduled_runtime_min"],
                    "dep_hour": row["prev_dep"].hour,
                    "day_of_week": row["prev_dep"].dayofweek,
                    "month": row["prev_dep"].month,
                    "priority_class": prio_class,
                    "speed_factor": speed_factor,
                    "current_delay_min": curr_delay,
                    "delay_trend_last_3": delay_trend_3,
                    "dwell_last_station": prev_dwell,
                    "actual_transit_min": row["actual_transit_min"],
                    "added_delay_min": added_delay,
                })
            else:
                # Multi-section express hop
                if u in stations_ordered_dn and v in stations_ordered_dn:
                    i_u = stations_ordered_dn.index(u)
                    i_v = stations_ordered_dn.index(v)
                    step = 1 if i_u < i_v else -1
                    path_secs = []
                    total_sched = 0.0
                    for idx in range(i_u, i_v, step):
                        p1 = stations_ordered_dn[idx]
                        p2 = stations_ordered_dn[idx + step]
                        if (p1, p2) in sections_dict:
                            s = sections_dict[(p1, p2)]
                            path_secs.append(s)
                            total_sched += s["scheduled_runtime_min"] * speed_factor

                    if path_secs and total_sched > 0:
                        total_added = max(0.0, row["actual_transit_min"] - total_sched)
                        sec_cursor = row["prev_dep"]
                        for s in path_secs:
                            s_sched = s["scheduled_runtime_min"] * speed_factor
                            s_added = total_added * (s_sched / total_sched)
                            records.append({
                                "run_id": row["run_id"],
                                "section_id": s["id"],
                                "entry_time": sec_cursor,
                                "exit_time": sec_cursor + pd.Timedelta(minutes=s_sched + s_added),
                                "distance_km": s["distance_km"],
                                "line_speed_kmph": s["line_speed_kmph"],
                                "scheduled_runtime_min": s["scheduled_runtime_min"],
                                "dep_hour": sec_cursor.hour,
                                "day_of_week": sec_cursor.dayofweek,
                                "month": sec_cursor.month,
                                "priority_class": prio_class,
                                "speed_factor": speed_factor,
                                "current_delay_min": curr_delay,
                                "delay_trend_last_3": delay_trend_3,
                                "dwell_last_station": prev_dwell,
                                "actual_transit_min": s_sched + s_added,
                                "added_delay_min": s_added,
                            })
                            sec_cursor += pd.Timedelta(minutes=s_sched + s_added)

        df_traversals = pd.DataFrame(records)
        if df_traversals.empty:
            return df_traversals

        # Compute Preceding-Train Delay on the same section
        # Sort all section traversals strictly chronologically by entry_time
        df_traversals = df_traversals.sort_values(by=["entry_time"]).reset_index(drop=True)

        # Track the last train's exit time and delay on each section
        last_exit_on_sec: dict[str, tuple[datetime, float]] = {}
        preceding_delays = []

        for _, row in df_traversals.iterrows():
            sec_id = row["section_id"]
            t_in = row["entry_time"]

            prec_delay = 0.0
            if sec_id in last_exit_on_sec:
                last_exit, last_del = last_exit_on_sec[sec_id]
                # Preceding train was ahead within a realistic 2-hour window
                if pd.Timedelta(seconds=0) <= (t_in - last_exit) <= pd.Timedelta(hours=2):
                    prec_delay = max(0.0, last_del)

            preceding_delays.append(prec_delay)
            # Update latest exit on this section
            last_exit_on_sec[sec_id] = (row["exit_time"], row["current_delay_min"])

        df_traversals["preceding_train_delay"] = preceding_delays
        return df_traversals

    def fit(
        self,
        df_train_events: pd.DataFrame,
        train_config_map: dict[str, any],
        sections_dict: dict[tuple[str, str], dict],
        stations_ordered_dn: list[str],
        train_cutoff_date: date,
    ) -> "FeaturePipeline":
        """Compute section encodings and historical statistics strictly on training data."""
        self.train_cutoff_date = train_cutoff_date

        # Build categorical integer encoding for sections
        all_section_ids = sorted(list({sec["id"] for sec in sections_dict.values()}))
        self.section_to_code = {s_id: idx for idx, s_id in enumerate(all_section_ids)}

        df_hops = self._extract_hops_chronological(
            df_train_events, train_config_map, sections_dict, stations_ordered_dn
        )

        if not df_hops.empty:
            # Group by section_id and hour
            grouped_sh = df_hops.groupby(["section_id", "dep_hour"])["added_delay_min"].agg(["mean", "std"])
            for (sec_id, hr), row in grouped_sh.iterrows():
                std_val = row["std"] if pd.notna(row["std"]) else 0.0
                self.section_hour_stats[(sec_id, hr)] = (row["mean"], std_val)

            # Group by section_id
            grouped_s = df_hops.groupby("section_id")["added_delay_min"].agg(["mean", "std"])
            for sec_id, row in grouped_s.iterrows():
                std_val = row["std"] if pd.notna(row["std"]) else 0.0
                self.section_stats[sec_id] = (row["mean"], std_val)

            self.global_mean_delay = float(df_hops["added_delay_min"].mean())
            self.global_std_delay = float(df_hops["added_delay_min"].std()) if len(df_hops) > 1 else 0.0

        self.is_fitted = True
        return self

    def transform(
        self,
        df_events: pd.DataFrame,
        df_disruptions: pd.DataFrame,
        train_config_map: dict[str, any],
        sections_dict: dict[tuple[str, str], dict],
        stations_ordered_dn: list[str],
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Transform events into feature matrix X and target y."""
        if not self.is_fitted:
            raise RuntimeError("FeaturePipeline must be fitted on training data before transforming.")

        df_hops = self._extract_hops_chronological(
            df_events, train_config_map, sections_dict, stations_ordered_dn
        )
        if df_hops.empty:
            return pd.DataFrame(columns=self.FEATURE_COLUMNS), pd.Series(dtype=float)

        df_dis = df_disruptions.copy()
        df_dis["start_time"] = pd.to_datetime(df_dis["start_time"])
        df_dis["end_time"] = pd.to_datetime(df_dis["end_time"])

        df_hops["is_peak_hour"] = df_hops["dep_hour"].apply(
            lambda h: 1 if (7 <= h <= 10 or 17 <= h <= 21) else 0
        )

        def is_fog_window(row) -> int:
            t = row["entry_time"]
            d = t.date()
            if date(2025, 12, 15) <= d <= date(2026, 1, 20):
                if t.hour >= 22 or t.hour <= 8:
                    return 1
            return 0

        df_hops["is_winter_fog_window"] = df_hops.apply(is_fog_window, axis=1)

        # Match active disruptions
        has_dis_list = []
        severity_list = []
        dis_tsr_list = []
        dis_weather_list = []

        dis_by_sec = {}
        for _, d_row in df_dis.iterrows():
            dis_by_sec.setdefault(d_row["section_id"], []).append(d_row)

        for _, row in df_hops.iterrows():
            sec_id = row["section_id"]
            t_entry = row["entry_time"]
            active_dis = [
                d for d in dis_by_sec.get(sec_id, [])
                if d["start_time"] <= t_entry <= d["end_time"]
            ]
            if active_dis:
                d = active_dis[0]
                has_dis_list.append(1)
                severity_list.append(float(d["severity"]))
                dis_tsr_list.append(1 if d["type"] == "TSR" else 0)
                dis_weather_list.append(1 if d["type"] == "weather" else 0)
            else:
                has_dis_list.append(0)
                severity_list.append(0.0)
                dis_tsr_list.append(0)
                dis_weather_list.append(0)

        df_hops["has_disruption"] = has_dis_list
        df_hops["disruption_severity"] = severity_list
        df_hops["disruption_type_tsr"] = dis_tsr_list
        df_hops["disruption_type_weather"] = dis_weather_list

        # Section categorical encoding
        df_hops["section_code"] = df_hops["section_id"].map(
            lambda s: self.section_to_code.get(s, -1)
        )

        # Historical aggregates
        hist_means = []
        hist_stds = []
        for _, row in df_hops.iterrows():
            key = (row["section_id"], row["dep_hour"])
            if key in self.section_hour_stats:
                m, s = self.section_hour_stats[key]
            elif row["section_id"] in self.section_stats:
                m, s = self.section_stats[row["section_id"]]
            else:
                m, s = self.global_mean_delay, self.global_std_delay
            hist_means.append(m)
            hist_stds.append(s)

        df_hops["hist_mean_delay"] = hist_means
        df_hops["hist_std_delay"] = hist_stds

        X = df_hops[self.FEATURE_COLUMNS].copy()
        y = df_hops["added_delay_min"].copy()
        return X, y

    def build_single_step_features(
        self,
        sec: dict,
        current_time: datetime,
        priority_class: int,
        speed_factor: float,
        current_delay_min: float,
        dwell_last_station: float,
        delay_trend_last_3: float,
        preceding_train_delay: float,
        active_disruptions_for_sec: list[dict],
    ) -> pd.DataFrame:
        """Construct feature dataframe for a single section step during live inference."""
        dep_hour = current_time.hour
        day_of_week = current_time.weekday()
        month = current_time.month
        is_peak = 1 if (7 <= dep_hour <= 10 or 17 <= dep_hour <= 21) else 0

        c_date = current_time.date()
        is_fog = 1 if (date(2025, 12, 15) <= c_date <= date(2026, 1, 20) and (dep_hour >= 22 or dep_hour <= 8)) else 0

        has_dis = 0
        severity = 0.0
        dis_tsr = 0
        dis_weather = 0

        for d in active_disruptions_for_sec:
            if d["start_time"] <= current_time <= d["end_time"]:
                has_dis = 1
                severity = float(d["severity"])
                if d["type"] == "TSR":
                    dis_tsr = 1
                elif d["type"] == "weather":
                    dis_weather = 1
                break

        sec_id = sec["id"]
        sec_code = self.section_to_code.get(sec_id, -1)
        key = (sec_id, dep_hour)
        if key in self.section_hour_stats:
            m, s = self.section_hour_stats[key]
        elif sec_id in self.section_stats:
            m, s = self.section_stats[sec_id]
        else:
            m, s = self.global_mean_delay, self.global_std_delay

        row = {
            "section_code": sec_code,
            "distance_km": sec["distance_km"],
            "line_speed_kmph": sec["line_speed_kmph"],
            "scheduled_runtime_min": sec["scheduled_runtime_min"],
            "dep_hour": dep_hour,
            "day_of_week": day_of_week,
            "month": month,
            "is_winter_fog_window": is_fog,
            "is_peak_hour": is_peak,
            "priority_class": priority_class,
            "speed_factor": speed_factor,
            "current_delay_min": current_delay_min,
            "delay_trend_last_3": delay_trend_last_3,
            "dwell_last_station": dwell_last_station,
            "preceding_train_delay": preceding_train_delay,
            "has_disruption": has_dis,
            "disruption_severity": severity,
            "disruption_type_tsr": dis_tsr,
            "disruption_type_weather": dis_weather,
            "hist_mean_delay": m,
            "hist_std_delay": s,
        }
        return pd.DataFrame([row], columns=self.FEATURE_COLUMNS)
