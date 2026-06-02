"""Faker-powered seed script.

Run from the backend/ directory:
    python -m app.db.seed

Idempotent: drops and recreates all tables on each run so you get a
clean, reproducible dataset every time.
"""

import random
from datetime import date, datetime, timedelta, timezone

from faker import Faker

from app.db.session import Base, SessionLocal, engine
from app.models.orm import (
    Appointment,
    AppointmentType,
    AvailableSlot,
    Location,
    Patient,
    PatientRecall,
    Provider,
)

fake = Faker()
rng = random.Random(42)  # fixed seed for reproducibility

APPOINTMENT_STATUSES_HISTORY = ["completed", "cancelled", "no_show"]
SPECIALTIES = ["General Dentistry", "Orthodontics", "Periodontics", "Endodontics", "Oral Surgery"]
RECALL_TYPES = ["6-month cleaning", "annual exam", "periodontal maintenance", "post-treatment check"]

APPOINTMENT_TYPE_DEFS = [
    ("cleaning", 45),
    ("exam", 30),
    ("filling", 60),
    ("crown", 90),
    ("extraction", 60),
]


def _random_business_time(base_date: date) -> datetime:
    """Return a random datetime between 8am and 5pm on base_date."""
    hour = rng.randint(8, 16)
    minute = rng.choice([0, 15, 30, 45])
    return datetime(base_date.year, base_date.month, base_date.day, hour, minute, tzinfo=timezone.utc)


def run_seed() -> None:
    print("Dropping and recreating schema…")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # ------------------------------------------------------------------
        # Providers (3)
        # ------------------------------------------------------------------
        providers: list[Provider] = []
        for _ in range(3):
            p = Provider(
                first_name=fake.first_name(),
                last_name=fake.last_name(),
                specialty=rng.choice(SPECIALTIES),
            )
            db.add(p)
            providers.append(p)

        # ------------------------------------------------------------------
        # Locations (2)
        # ------------------------------------------------------------------
        locations: list[Location] = []
        for _ in range(2):
            loc = Location(
                name=f"{fake.last_name()} Dental Center",
                address=fake.address().replace("\n", ", "),
                phone=fake.numerify("(###) ###-####"),
            )
            db.add(loc)
            locations.append(loc)

        # Flush to get auto-generated IDs before creating FK references
        db.flush()

        # ------------------------------------------------------------------
        # Appointment types (5 fixed)
        # ------------------------------------------------------------------
        appt_types: list[AppointmentType] = []
        for name, duration in APPOINTMENT_TYPE_DEFS:
            at = AppointmentType(name=name, duration_minutes=duration)
            db.add(at)
            appt_types.append(at)

        # ------------------------------------------------------------------
        # Patients (20)
        # ------------------------------------------------------------------
        patients: list[Patient] = []
        for _ in range(20):
            pt = Patient(
                first_name=fake.first_name(),
                last_name=fake.last_name(),
                dob=fake.date_of_birth(minimum_age=5, maximum_age=85),
                email=fake.unique.email(),
                phone=fake.numerify("(###) ###-####"),
            )
            db.add(pt)
            patients.append(pt)

        db.flush()

        # ------------------------------------------------------------------
        # Appointment history — 60 days back (mix of statuses)
        # ------------------------------------------------------------------
        today = date.today()
        for offset in range(60):
            day = today - timedelta(days=offset + 1)
            # 2–4 appointments per day
            for _ in range(rng.randint(2, 4)):
                appt_type = rng.choice(appt_types)
                start = _random_business_time(day)
                end = start + timedelta(minutes=appt_type.duration_minutes)
                status = rng.choices(
                    APPOINTMENT_STATUSES_HISTORY,
                    weights=[0.70, 0.20, 0.10],  # mostly completed
                )[0]
                appt = Appointment(
                    patient_id=rng.choice(patients).id,
                    provider_id=rng.choice(providers).id,
                    location_id=rng.choice(locations).id,
                    appointment_type_id=appt_type.id,
                    start_time=start,
                    end_time=end,
                    status=status,
                )
                db.add(appt)

        # ------------------------------------------------------------------
        # Available slots — next 14 days (30-min grid, 8am-5pm)
        # ------------------------------------------------------------------
        for offset in range(14):
            day = today + timedelta(days=offset)
            if day.weekday() >= 5:  # skip weekends
                continue
            for provider in providers:
                location = rng.choice(locations)
                # Generate 30-min slots from 8:00 to 16:30 (18 slots/provider/day)
                slot_start = datetime(day.year, day.month, day.day, 8, 0, tzinfo=timezone.utc)
                day_end = datetime(day.year, day.month, day.day, 17, 0, tzinfo=timezone.utc)
                while slot_start < day_end:
                    slot_end = slot_start + timedelta(minutes=30)
                    slot = AvailableSlot(
                        provider_id=provider.id,
                        location_id=location.id,
                        start_time=slot_start,
                        end_time=slot_end,
                        # ~20% of slots are already booked to simulate real-world fill
                        is_booked=rng.random() < 0.20,
                    )
                    db.add(slot)
                    slot_start = slot_end

        # ------------------------------------------------------------------
        # Overdue recalls — 15 patients with pending status and past due_date
        # ------------------------------------------------------------------
        recall_patients = rng.sample(patients, 15)
        for pt in recall_patients:
            days_overdue = rng.randint(30, 365)
            recall = PatientRecall(
                patient_id=pt.id,
                recall_type=rng.choice(RECALL_TYPES),
                due_date=today - timedelta(days=days_overdue),
                last_contacted_at=None,
                status="pending",
            )
            db.add(recall)

        # 5 additional non-overdue recalls for variety
        for pt in rng.sample(patients, 5):
            recall = PatientRecall(
                patient_id=pt.id,
                recall_type=rng.choice(RECALL_TYPES),
                due_date=today + timedelta(days=rng.randint(1, 90)),
                status=rng.choice(["pending", "contacted", "scheduled"]),
            )
            db.add(recall)

        db.commit()
        print("Seed complete.")
        print(f"  Providers    : {len(providers)}")
        print(f"  Locations    : {len(locations)}")
        print(f"  Appt types   : {len(appt_types)}")
        print(f"  Patients     : {len(patients)}")
        print("  Appointments : ~60 days of history")
        print("  Slots        : 14-day forward grid (weekdays only)")
        print("  Recalls      : 15 overdue + 5 upcoming")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
