"""Smoke tests — ensure the app starts and health endpoint responds."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import create_app
import app.models.orm  # noqa: F401

# Build a throwaway in-memory DB shared across all threads in this test module.
# StaticPool is required: TestClient uses a background thread, and SQLite's
# default per-thread connection isolation would give that thread an empty DB.
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=_engine)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


_app = create_app()
_app.dependency_overrides[get_db] = _override_get_db
client = TestClient(_app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_patients_lists_without_auth() -> None:
    # Auth is not implemented yet (planned for a later milestone).
    # Endpoint returns 200 with no Bearer token.
    response = client.get("/api/v1/patients")
    assert response.status_code == 200
