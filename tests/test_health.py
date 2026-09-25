"""Smoke tests for FastAPI application and health endpoint."""

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_health_check_returns_ok():
    """Verify that /health returns HTTP 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "sih26028-eta"
    assert "timestamp" in data
    assert "environment" in data


def test_root_endpoint():
    """Verify that root / returns app metadata and honesty notice."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "sih26028-eta"
    assert "honesty_notice" in data
