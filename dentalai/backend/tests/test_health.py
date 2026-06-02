"""Smoke tests — ensure the app starts and health endpoint responds."""

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_patients_requires_auth() -> None:
    response = client.get("/api/v1/patients")
    assert response.status_code == 403  # no Bearer header → forbidden
