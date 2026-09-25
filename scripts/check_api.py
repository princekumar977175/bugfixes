"""Verification and audit script for Phase 6 API & WebSocket Streaming.

1. Starts the API (or connects to a running instance) and hits
   /health, /trains, /trains/{run_id}/eta, /trains/{run_id}/explain,
   /sections/{id}/disruptions — printing status code and a sample of each response.
2. Calls POST /replay/start, waits a few seconds, then opens
   WS /ws/trains/{run_id} and prints the first 3 messages received.
3. Calls POST /replay/speed with a faster multiplier and confirms
   messages arrive more often.
4. Calls POST /replay/pause and confirms no new WebSocket messages
   arrive for 5 seconds after.
5. Hits an invalid run_id and confirms a proper 404, not a 500.
Prints pass/fail for each check.
"""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import websockets

ROOT_DIR = Path(__file__).resolve().parent.parent
BASE_URL = "http://127.0.0.1:8000"
WS_BASE_URL = "ws://127.0.0.1:8000"


def ensure_server_running() -> subprocess.Popen | None:
    """Ensure the FastAPI server is running; launch a subprocess if not."""
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=1.5)
        if r.status_code == 200:
            print("Connected to existing running API server on port 8000.")
            return None
    except Exception:
        pass

    print("Launching Uvicorn API server on http://127.0.0.1:8000...")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--log-level",
            "warning",
        ],
        cwd=str(ROOT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Poll until ready
    for _ in range(40):
        try:
            r = httpx.get(f"{BASE_URL}/health", timeout=1.0)
            if r.status_code == 200:
                print("API server is ready and serving requests.")
                return proc
        except Exception:
            time.sleep(0.5)

    proc.terminate()
    raise RuntimeError("Failed to start API server within 20 seconds.")


async def run_audit():
    print("=" * 80)
    print("           PHASE 6 — FASTAPI & WEBSOCKET AUDIT AND VERIFICATION            ")
    print("=" * 80)

    server_proc = ensure_server_running()
    results: dict[str, bool] = {}
    sample_run_id = None

    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
            # -------------------------------------------------------------
            # CHECK 1: REST Endpoints
            # -------------------------------------------------------------
            print("\n" + "-" * 80)
            print("CHECK 1: Validating REST API endpoints...")
            print("-" * 80)

            # 1.1 /health
            r_health = await client.get("/health")
            print(f"GET /health -> HTTP {r_health.status_code}")
            health_json = r_health.json()
            print(f"  Sample: status={health_json.get('status')}, app={health_json.get('app')}, env={health_json.get('environment')}")
            assert r_health.status_code == 200 and health_json.get("status") == "ok"

            # 1.2 /trains
            r_trains = await client.get("/trains")
            print(f"GET /trains -> HTTP {r_trains.status_code}")
            trains_json = r_trains.json()
            total_trains = trains_json.get("total", 0)
            first_train = trains_json.get("trains", [{}])[0]
            sample_run_id = first_train.get("run_id")
            print(f"  Sample: total={total_trains}, first_train={sample_run_id} ({first_train.get('train_name')}), current_station={first_train.get('current_station')}")
            assert r_trains.status_code == 200 and total_trains > 0 and sample_run_id is not None

            # 1.3 /trains/{run_id}/eta
            r_eta = await client.get(f"/trains/{sample_run_id}/eta")
            print(f"GET /trains/{sample_run_id}/eta -> HTTP {r_eta.status_code}")
            eta_json = r_eta.json()
            downstream = eta_json.get("downstream_stations", [])
            first_stop = downstream[0] if downstream else {}
            print(f"  Sample: current_station={eta_json.get('current_station')}, downstream_stops={len(downstream)}")
            print(f"  Next Stop: {first_stop.get('station_name')} ({first_stop.get('station_code')})")
            print(f"    Scheduled: {first_stop.get('sched_arr')}")
            print(f"    Baseline A: {first_stop.get('baseline_a_eta')}")
            print(f"    Predicted 10-50-90: [{first_stop.get('eta_lower')} -> {first_stop.get('eta_median')} -> {first_stop.get('eta_upper')}]")
            print(f"    Interval Width: {first_stop.get('interval_width_min')} min")
            print(f"    Explanation: {first_stop.get('reasons')}")
            assert r_eta.status_code == 200 and len(downstream) > 0

            # 1.4 /trains/{run_id}/explain
            r_explain = await client.get(f"/trains/{sample_run_id}/explain")
            print(f"GET /trains/{sample_run_id}/explain -> HTTP {r_explain.status_code}")
            exp_json = r_explain.json()
            print(f"  Latest Explanation: {exp_json.get('latest_explanation')}")
            print(f"  Top Drivers ({len(exp_json.get('top_drivers', []))}):")
            for d in exp_json.get("top_drivers", []):
                print(f"    - {d.get('label')}: SHAP {d.get('shap_value'):+.2f} min (val: {d.get('feature_val')})")
            assert r_explain.status_code == 200 and exp_json.get("latest_explanation")

            # 1.5 /sections/{id}/disruptions
            r_disrupt = await client.get("/sections/all/disruptions")
            print(f"GET /sections/all/disruptions -> HTTP {r_disrupt.status_code}")
            disrupt_json = r_disrupt.json()
            total_disruptions = disrupt_json.get("total", 0)
            first_disrupt = disrupt_json.get("disruptions", [{}])[0]
            print(f"  Sample: total={total_disruptions}, first: section={first_disrupt.get('section_id')}, type={first_disrupt.get('type')}, severity={first_disrupt.get('severity')}")
            assert r_disrupt.status_code == 200 and total_disruptions > 0

            results["Check 1: REST Endpoints"] = True
            print("[PASS] Check 1: All REST endpoints returned HTTP 200 with valid data.")

            # -------------------------------------------------------------
            # CHECK 2: Replay Start & First 3 WebSocket Messages
            # -------------------------------------------------------------
            print("\n" + "-" * 80)
            print("CHECK 2: Starting replay and streaming first 3 WebSocket messages...")
            print("-" * 80)

            # Start replay for this train at 1x speed
            r_start = await client.post("/replay/start", json={"run_id": sample_run_id, "speed": 1.0})
            print(f"POST /replay/start -> HTTP {r_start.status_code}, status={r_start.json().get('status')}")
            assert r_start.status_code == 200

            print("Waiting 1 second before opening WebSocket connection...")
            await asyncio.sleep(1.0)

            ws_url = f"{WS_BASE_URL}/ws/trains/{sample_run_id}"
            print(f"Connecting to WebSocket: {ws_url}")

            received_messages: list[dict[str, Any]] = []
            async with websockets.connect(ws_url) as ws:
                # Receive first 3 messages
                for i in range(1, 4):
                    raw_msg = await asyncio.wait_for(ws.recv(), timeout=8.0)
                    msg_data = json.loads(raw_msg)
                    received_messages.append(msg_data)
                    print(f"  Message {i}: type={msg_data.get('type')}, sim_time={msg_data.get('sim_time')}, current_station={msg_data.get('current_station')}, delay={msg_data.get('current_delay_min')} min, stops_forecast={len(msg_data.get('predictions', []))}")

                assert len(received_messages) == 3
                results["Check 2: Replay Start & WebSocket Streaming"] = True
                print("[PASS] Check 2: First 3 WebSocket messages successfully received.")

                # ---------------------------------------------------------
                # CHECK 3: Replay Speed Adjustment & Frequency Check
                # ---------------------------------------------------------
                print("\n" + "-" * 80)
                print("CHECK 3: Increasing speed multiplier and confirming higher message frequency...")
                print("-" * 80)

                # Measure time for next message at speed = 1.0
                t0 = time.time()
                await asyncio.wait_for(ws.recv(), timeout=5.0)
                interval_1x = time.time() - t0
                print(f"  Measured interval at 1.0x speed: {interval_1x:.3f} s")

                # Boost speed to 6.0x
                r_speed = await client.post("/replay/speed", json={"speed": 6.0})
                print(f"POST /replay/speed (6.0x) -> HTTP {r_speed.status_code}, speed={r_speed.json().get('speed')}x")
                assert r_speed.status_code == 200

                # Measure interval at 6.0x speed
                t1 = time.time()
                await asyncio.wait_for(ws.recv(), timeout=3.0)
                interval_6x = time.time() - t1
                print(f"  Measured interval at 6.0x speed: {interval_6x:.3f} s")

                ratio = interval_1x / max(0.001, interval_6x)
                print(f"  Frequency speedup ratio: {ratio:.1f}x faster ({interval_1x:.2f}s vs {interval_6x:.2f}s)")
                assert interval_6x < interval_1x, f"Expected {interval_6x:.2f}s < {interval_1x:.2f}s"
                results["Check 3: Replay Speed & Message Frequency"] = True
                print("[PASS] Check 3: Messages arrived significantly faster at higher speed multiplier.")

                # ---------------------------------------------------------
                # CHECK 4: Replay Pause & WebSocket Silence Check
                # ---------------------------------------------------------
                print("\n" + "-" * 80)
                print("CHECK 4: Pausing replay and verifying zero messages for 5 seconds...")
                print("-" * 80)

                r_pause = await client.post("/replay/pause")
                print(f"POST /replay/pause -> HTTP {r_pause.status_code}, status={r_pause.json().get('status')}")
                assert r_pause.status_code == 200 and r_pause.json().get("status") == "paused"

                # Drain any immediate leftover packets in buffer
                while True:
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=0.15)
                    except TimeoutError:
                        break

                print("Monitoring WebSocket silence for 5.0 seconds...")
                silence_maintained = False
                try:
                    unexpected_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    print(f"  [FAIL] Unexpected message arrived while paused: {unexpected_msg[:80]}")
                except TimeoutError:
                    print("  Confirmed: 0 messages received during 5.0s pause window.")
                    silence_maintained = True

                assert silence_maintained, "Messages arrived while simulation was paused."
                results["Check 4: Replay Pause & WebSocket Silence"] = True
                print("[PASS] Check 4: Zero WebSocket messages arrived for 5 seconds after pause.")

            # -------------------------------------------------------------
            # CHECK 5: Error Handling (Invalid run_id returns 404, not 500)
            # -------------------------------------------------------------
            print("\n" + "-" * 80)
            print("CHECK 5: Verifying invalid run_id returns proper HTTP 404...")
            print("-" * 80)

            invalid_id = "nonexistent_train_run_9999"
            r_bad_eta = await client.get(f"/trains/{invalid_id}/eta")
            print(f"GET /trains/{invalid_id}/eta -> HTTP {r_bad_eta.status_code}")
            print(f"  Detail: {r_bad_eta.json().get('detail')}")

            r_bad_exp = await client.get(f"/trains/{invalid_id}/explain")
            print(f"GET /trains/{invalid_id}/explain -> HTTP {r_bad_exp.status_code}")
            print(f"  Detail: {r_bad_exp.json().get('detail')}")

            assert r_bad_eta.status_code == 404, f"Expected 404, got {r_bad_eta.status_code}"
            assert r_bad_exp.status_code == 404, f"Expected 404, got {r_bad_exp.status_code}"
            assert r_bad_eta.status_code != 500 and r_bad_exp.status_code != 500

            results["Check 5: Proper 404 Error Handling"] = True
            print("[PASS] Check 5: Proper 404 returned for invalid run_id without internal 500 errors.")

    finally:
        if server_proc is not None:
            print("\nStopping background Uvicorn API server...")
            server_proc.terminate()
            server_proc.wait()
            print("API server stopped.")

    # -----------------------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------------------
    print("\n" + "=" * 80)
    print("                       AUDIT SUMMARY RESULTS                        ")
    print("=" * 80)
    all_passed = True
    for check_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {check_name}")
        if not passed:
            all_passed = False

    print("=" * 80)
    if all_passed and len(results) == 5:
        print("  ALL 5 CHECKS PASSED SUCCESSFULLY (5/5)")
    else:
        print(f"  SOME CHECKS FAILED: {sum(results.values())}/5 PASSED")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(run_audit())
