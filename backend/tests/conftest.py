"""Shared pytest fixtures.

The key fixture here is `agent_db`: it spins up a fresh in-memory SQLite
database for each test and patches app.agent.agent.SessionLocal to point at it.
This prevents tests from touching or wiping the developer's dentalai.db.
"""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
import app.models.orm  # noqa: F401 — registers all ORM classes with Base.metadata
from app.models.orm import (
    AppointmentType,
    AvailableSlot,
    Location,
    Patient,
    PatientRecall,
    Provider,
)


@pytest.fixture()
def agent_db():
    """Isolated in-memory SQLite database pre-seeded with minimal fixtures.

    Patches app.agent.agent.SessionLocal for the duration of the test so that
    all agent tool functions talk to the in-memory DB, not the dev database.

    Yields a sessionmaker so individual tests can open their own sessions to
    inspect state after a tool call.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Seed minimal shared fixtures
    db = TestSession()
    try:
        provider = Provider(first_name="Alice", last_name="Smith", specialty="General")
        location = Location(name="Main Office", address="123 Main St", phone="555-0100")
        db.add_all([provider, location])
        db.flush()

        db.add_all([
            AppointmentType(name="cleaning", duration_minutes=45),
            AppointmentType(name="exam", duration_minutes=30),
        ])

        patients = [
            Patient(first_name="John", last_name="Doe", email="john@example.com"),
            Patient(first_name="Jane", last_name="Roe", email="jane@example.com"),
        ]
        db.add_all(patients)
        db.flush()

        slot_time = datetime.utcnow() + timedelta(days=3)
        db.add(AvailableSlot(
            provider_id=provider.id,
            location_id=location.id,
            start_time=slot_time,
            end_time=slot_time + timedelta(minutes=30),
            is_booked=False,
        ))

        db.add(PatientRecall(
            patient_id=patients[0].id,
            recall_type="6-month cleaning",
            due_date=date(2024, 1, 1),
            status="pending",
        ))

        db.commit()
    finally:
        db.close()

    with patch("app.agent.agent.SessionLocal", TestSession):
        yield TestSession

    Base.metadata.drop_all(bind=engine)
    engine.dispose()
