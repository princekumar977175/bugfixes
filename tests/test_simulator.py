"""Validation tests for the corridor dataset simulator."""

import statistics
from datetime import date

from src.simulator.generator import CorridorSimulator


def test_seed_reproducibility():
    """Verify that identical seeds produce bit-for-bit identical simulated events."""
    start_date = date(2025, 11, 1)
    num_days = 15

    sim1 = CorridorSimulator(seed=12345)
    runs1, events1, disruptions1, _ = sim1.simulate(start_date=start_date, num_days=num_days)

    sim2 = CorridorSimulator(seed=12345)
    runs2, events2, disruptions2, _ = sim2.simulate(start_date=start_date, num_days=num_days)

    assert len(runs1) == len(runs2)
    assert len(events1) == len(events2)
    assert len(disruptions1) == len(disruptions2)

    for e1, e2 in zip(events1, events2, strict=True):
        assert e1["run_id"] == e2["run_id"]
        assert e1["station_code"] == e2["station_code"]
        assert e1["seq"] == e2["seq"]
        assert e1["actual_arr"] == e2["actual_arr"]
        assert e1["actual_dep"] == e2["actual_dep"]
        assert e1["arr_delay_min"] == e2["arr_delay_min"]
        assert e1["dwell_min"] == e2["dwell_min"]


def test_physical_validity_and_no_negative_runtimes():
    """Verify that runtimes are strictly positive, dwells are non-negative, and times advance monotonically."""
    start_date = date(2025, 11, 1)
    num_days = 30

    sim = CorridorSimulator(seed=42)
    _, events, _, _ = sim.simulate(start_date=start_date, num_days=num_days)

    # Group events by run_id
    runs_events: dict[str, list[dict]] = {}
    for ev in events:
        runs_events.setdefault(ev["run_id"], []).append(ev)

    for run_id, ev_list in runs_events.items():
        ev_list.sort(key=lambda x: x["seq"])
        for i, ev in enumerate(ev_list):
            # Origin station
            if i == 0:
                assert ev["actual_arr"] is None, f"Origin arrival should be None for {run_id}"
                assert ev["actual_dep"] is not None, f"Origin departure cannot be None for {run_id}"
                assert ev["dwell_min"] == 0.0
            # Destination station
            elif i == len(ev_list) - 1:
                assert ev["actual_arr"] is not None, f"Destination arrival cannot be None for {run_id}"
                assert ev["actual_dep"] is None, f"Destination departure should be None for {run_id}"
                prev = ev_list[i - 1]
                assert prev["actual_dep"] is not None
                transit_time = (ev["actual_arr"] - prev["actual_dep"]).total_seconds() / 60.0
                assert transit_time > 0, f"Section transit time must be strictly positive: {transit_time} min"
            # Intermediate station
            else:
                assert ev["actual_arr"] is not None
                assert ev["actual_dep"] is not None
                assert ev["actual_dep"] >= ev["actual_arr"], (
                    f"Departure must be >= arrival at station {ev['station_code']} for {run_id}"
                )
                assert ev["dwell_min"] >= 0.0

                prev = ev_list[i - 1]
                assert prev["actual_dep"] is not None
                transit_time = (ev["actual_arr"] - prev["actual_dep"]).total_seconds() / 60.0
                assert transit_time > 0, (
                    f"Negative or zero section transit time ({transit_time} min) between "
                    f"{prev['station_code']} and {ev['station_code']} for {run_id}"
                )


def test_seasonal_fog_delays_exceed_baseline():
    """Verify that winter fog period (Dec 15 - Jan 20) exhibits significantly higher average delays than clear November."""
    start_date = date(2025, 11, 1)
    num_days = 90  # Nov 1 to Jan 29

    sim = CorridorSimulator(seed=42)
    _, events, _, _ = sim.simulate(start_date=start_date, num_days=num_days)

    nov_delays = []
    fog_delays = []

    fog_start = date(2025, 12, 15)
    fog_end = date(2026, 1, 20)

    for ev in events:
        if ev["actual_arr"] is None:
            continue
        arr_date = ev["actual_arr"].date()
        if arr_date.month == 11:
            nov_delays.append(ev["arr_delay_min"])
        elif fog_start <= arr_date <= fog_end:
            fog_delays.append(ev["arr_delay_min"])

    assert len(nov_delays) > 100
    assert len(fog_delays) > 100

    mean_nov = statistics.mean(nov_delays)
    mean_fog = statistics.mean(fog_delays)

    # Winter fog period must show substantial delay increase over clear November
    assert mean_fog > mean_nov + 5.0, (
        f"Fog mean delay ({mean_fog:.2f} min) should substantially exceed Nov delay ({mean_nov:.2f} min)"
    )


def test_peak_hour_junction_congestion():
    """Verify that peak-hour arrivals at major junctions experience elevated delays compared to off-peak hours."""
    start_date = date(2025, 11, 1)
    num_days = 45

    sim = CorridorSimulator(seed=42)
    _, events, _, _ = sim.simulate(start_date=start_date, num_days=num_days)

    junction_codes = {"NDLS", "CNB", "PRYJ", "DDU", "PNBE"}

    peak_delays = []
    offpeak_delays = []

    for ev in events:
        if ev["actual_arr"] is None or ev["station_code"] not in junction_codes:
            continue
        arr_hour = ev["actual_arr"].hour
        if (7 <= arr_hour <= 10) or (17 <= arr_hour <= 21):
            peak_delays.append(ev["arr_delay_min"])
        elif 11 <= arr_hour <= 15:
            offpeak_delays.append(ev["arr_delay_min"])

    assert len(peak_delays) > 50
    assert len(offpeak_delays) > 50

    mean_peak = statistics.mean(peak_delays)
    mean_offpeak = statistics.mean(offpeak_delays)

    assert mean_peak > mean_offpeak, (
        f"Peak mean delay ({mean_peak:.2f} min) should exceed off-peak ({mean_offpeak:.2f} min)"
    )
