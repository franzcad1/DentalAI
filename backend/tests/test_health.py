"""Smoke tests — ensure the app starts and health endpoint responds."""

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_patients_lists_without_auth() -> None:
    # Auth is not implemented yet (planned for a later milestone).
    # Endpoint returns 200 with no Bearer token.
    response = client.get("/api/v1/patients")
    assert response.status_code == 200
