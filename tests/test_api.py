"""Comprehensive integration tests for REST API endpoints and WebSocket live streaming."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.schemas import (
    HealthResponse,
    SectionDisruptionsResponse,
    TrainETAResponse,
    TrainExplainResponse,
    TrainListResponse,
    WebSocketETAUpdate,
)
from src.simulator.replay import replay_engine


@pytest.fixture(scope="module")
def client():
    """Module-scoped FastAPI test client."""
    with TestClient(app) as test_client:
        yield test_client
    replay_engine.stop()


def test_health_endpoint(client: TestClient):
    """Test GET /health returns service health status matching HealthResponse schema."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    model = HealthResponse.model_validate(data)
    assert model.status == "ok"
    assert model.app == "sih26028-eta"
    assert model.timestamp is not None


def test_root_endpoint(client: TestClient):
    """Test GET / returns app metadata and simulated data notice."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "sih26028-eta"
    assert "honesty_notice" in data


def test_list_trains_endpoint(client: TestClient):
    """Test GET /trains returns a valid list of corridor runs."""
    response = client.get("/trains")
    assert response.status_code == 200
    data = response.json()
    validated = TrainListResponse.model_validate(data)
    assert validated.total > 0
    assert len(validated.trains) == validated.total

    first_train = validated.trains[0]
    assert first_train.run_id is not None
    assert first_train.train_number is not None
    assert first_train.train_name is not None
    assert first_train.status in ("running", "scheduled", "completed")


def test_list_trains_filtered_by_date(client: TestClient):
    """Test GET /trains with date query parameter."""
    response = client.get("/trains?date=2026-01-20")
    assert response.status_code == 200
    data = response.json()
    validated = TrainListResponse.model_validate(data)
    assert validated.total > 0
    for t in validated.trains:
        assert str(t.run_date) == "2026-01-20"


def test_get_train_eta_success(client: TestClient):
    """Test GET /trains/{run_id}/eta returns downstream predictions with uncertainty bounds."""
    # Obtain a valid run_id
    trains_res = client.get("/trains")
    run_id = trains_res.json()["trains"][0]["run_id"]

    response = client.get(f"/trains/{run_id}/eta")
    assert response.status_code == 200
    data = response.json()
    validated = TrainETAResponse.model_validate(data)

    assert validated.run_id == run_id
    assert validated.train_number is not None
    assert len(validated.downstream_stations) > 0

    for st in validated.downstream_stations:
        assert st.eta_lower <= st.eta_median <= st.eta_upper
        assert st.interval_width_min >= 0.0
        assert st.baseline_a_eta is not None
        assert st.reasons != ""


def test_get_train_eta_not_found(client: TestClient):
    """Test GET /trains/{run_id}/eta with nonexistent run_id returns 404."""
    response = client.get("/trains/nonexistent_train_999/eta")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_train_explain_success(client: TestClient):
    """Test GET /trains/{run_id}/explain returns top SHAP drivers and plain-language reason."""
    trains_res = client.get("/trains")
    run_id = trains_res.json()["trains"][0]["run_id"]

    response = client.get(f"/trains/{run_id}/explain")
    assert response.status_code == 200
    data = response.json()
    validated = TrainExplainResponse.model_validate(data)

    assert validated.run_id == run_id
    assert validated.latest_explanation != ""
    assert isinstance(validated.top_drivers, list)
    assert len(validated.top_drivers) <= 3
    for driver in validated.top_drivers:
        assert driver.feature != ""
        assert driver.label != ""


def test_get_train_explain_not_found(client: TestClient):
    """Test GET /trains/{run_id}/explain with nonexistent run_id returns 404."""
    response = client.get("/trains/nonexistent_train_999/explain")
    assert response.status_code == 404


def test_get_section_disruptions_all(client: TestClient):
    """Test GET /sections/all/disruptions returns corridor-wide disruptions."""
    response = client.get("/sections/all/disruptions")
    assert response.status_code == 200
    data = response.json()
    validated = SectionDisruptionsResponse.model_validate(data)
    assert validated.section_id == "all"
    assert validated.total > 0
    assert len(validated.disruptions) == validated.total


def test_get_section_disruptions_single_section(client: TestClient):
    """Test GET /sections/{id}/disruptions for a specific corridor section."""
    all_res = client.get("/sections/all/disruptions")
    sec_id = all_res.json()["disruptions"][0]["section_id"]

    response = client.get(f"/sections/{sec_id}/disruptions")
    assert response.status_code == 200
    data = response.json()
    validated = SectionDisruptionsResponse.model_validate(data)
    assert validated.section_id == sec_id
    for d in validated.disruptions:
        assert d.section_id == sec_id


def test_get_section_disruptions_not_found(client: TestClient):
    """Test GET /sections/{id}/disruptions with nonexistent section returns 404."""
    response = client.get("/sections/NONEXISTENT_SEC_999/disruptions")
    assert response.status_code == 404


def test_replay_control_lifecycle(client: TestClient):
    """Test simulation replay start, pause, speed adjustment, and status endpoints."""
    # 1. Start replay
    start_res = client.post("/replay/start", json={"speed": 2.0, "date": "2026-01-20"})
    assert start_res.status_code == 200
    status = start_res.json()
    assert status["status"] == "running"
    assert status["speed"] == 2.0

    # 2. Check status
    stat_res = client.get("/replay/status")
    assert stat_res.status_code == 200
    assert stat_res.json()["status"] == "running"

    # 3. Pause replay
    pause_res = client.post("/replay/pause")
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "paused"

    # 4. Update speed
    speed_res = client.post("/replay/speed", json={"speed": 5.0})
    assert speed_res.status_code == 200
    assert speed_res.json()["speed"] == 5.0

    # 5. Invalid speed (Pydantic schema validation returns 422)
    bad_speed = client.post("/replay/speed", json={"speed": -1.0})
    assert bad_speed.status_code in (400, 422)


def test_websocket_eta_streaming_during_replay(client: TestClient):
    """Test WebSocket connection receives live ETA updates as simulation advances."""
    train_res = client.get("/trains")
    run_id = train_res.json()["trains"][0]["run_id"]

    # Start replay with this target run
    client.post("/replay/start", json={"run_id": run_id, "speed": 1.0})

    with client.websocket_connect(f"/ws/trains/{run_id}") as ws:
        # 1. Initial snapshot received upon connecting
        msg_initial = ws.receive_json()
        assert msg_initial is not None
        assert msg_initial.get("type") in ("eta_update", "connected")

        # 2. Advance simulation time by one step
        client.post("/replay/step?seconds=300")

        # 3. Live ETA update broadcast received over WebSocket
        msg_step = ws.receive_json()
        assert msg_step is not None
        assert msg_step["type"] == "eta_update"
        assert msg_step["run_id"] == run_id

        # Validate with Pydantic WebSocketETAUpdate schema
        validated_update = WebSocketETAUpdate.model_validate(msg_step)
        assert validated_update.run_id == run_id
        assert len(validated_update.predictions) > 0
        first_forecast = validated_update.predictions[0]
        assert first_forecast.eta_lower <= first_forecast.eta_median <= first_forecast.eta_upper
        assert first_forecast.reasons != ""


def test_websocket_ping_pong(client: TestClient):
    """Test WebSocket ping/pong keepalive communication."""
    with client.websocket_connect("/ws/trains/all") as ws:
        # Connected handshake
        _ = ws.receive_json()
        # Send ping
        ws.send_text("ping")
        pong_response = ws.receive_json()
        assert pong_response["type"] == "pong"
        assert "sim_time" in pong_response
