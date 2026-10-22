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


def _random_business_time(base_date: date, duration_minutes: int = 30) -> datetime:
    """Return a random start time that guarantees the appointment finishes by 17:00."""
    latest_start_minutes = 17 * 60 - duration_minutes  # e.g. 16:30 for a 30-min appt
    start_minutes = rng.randint(8 * 60, latest_start_minutes)
    # Round down to nearest 15-min boundary
    start_minutes = (start_minutes // 15) * 15
    hour, minute = divmod(start_minutes, 60)
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
                start = _random_business_time(day, appt_type.duration_minutes)
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
                slot_start = datetime(day.year, day.month, day.day, 8, 0)
                day_end = datetime(day.year, day.month, day.day, 17, 0)
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

        # ------------------------------------------------------------------
        # Today's appointments — so the Schedule view has data on first load
        # ------------------------------------------------------------------
        today_appts = 0
        for _ in range(rng.randint(5, 7)):
            appt_type = rng.choice(appt_types)
            start = _random_business_time(today, appt_type.duration_minutes)
            end = start + timedelta(minutes=appt_type.duration_minutes)
            # Mix of confirmed/completed/no_show for a realistic day
            status = rng.choices(
                ["confirmed", "completed", "no_show"],
                weights=[0.55, 0.35, 0.10],
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
            today_appts += 1

        db.commit()
        print("Seed complete.")
        print(f"  Providers    : {len(providers)}")
        print(f"  Locations    : {len(locations)}")
        print(f"  Appt types   : {len(appt_types)}")
        print(f"  Patients     : {len(patients)}")
        print("  Appointments : ~60 days of history + today")
        print(f"  Today        : {today_appts} appointments")
        print("  Slots        : 14-day forward grid (weekdays only)")
        print("  Recalls      : 15 overdue + 5 upcoming")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def refresh_slots() -> None:
    """Delete all future unbooked slots and regenerate a fresh 14-day grid.

    Safe to call on every startup — only touches AvailableSlot rows that
    are in the future and not yet booked, so existing bookings are untouched.
    """
    import random as _rng_mod
    rng = _rng_mod.Random(42)

    db = SessionLocal()
    try:
        today = date.today()
        now = datetime.utcnow()  # naive UTC to match how SQLite stores datetimes

        # Remove stale future unbooked slots
        db.query(AvailableSlot).filter(
            AvailableSlot.is_booked == False,  # noqa: E712
            AvailableSlot.start_time >= now,
        ).delete(synchronize_session=False)

        providers = db.query(Provider).all()
        locations = db.query(Location).all()
        if not providers or not locations:
            db.rollback()
            return

        for offset in range(28):
            day = today + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            for provider in providers:
                location = rng.choice(locations)
                slot_start = datetime(day.year, day.month, day.day, 8, 0)
                day_end = datetime(day.year, day.month, day.day, 17, 0)
                while slot_start < day_end:
                    slot_end = slot_start + timedelta(minutes=30)
                    db.add(AvailableSlot(
                        provider_id=provider.id,
                        location_id=location.id,
                        start_time=slot_start,
                        end_time=slot_end,
                        is_booked=rng.random() < 0.20,
                    ))
                    slot_start = slot_end

        db.commit()
        print("==> Slots refreshed for next 28 days.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def fix_late_appointments() -> None:
    """Clamp any existing appointment that ends after 17:00 to end at 17:00.

    Safe to run on every startup — is a no-op when no violations exist.
    """
    db = SessionLocal()
    try:
        appts = db.query(Appointment).all()
        fixed = 0
        for appt in appts:
            closing = appt.end_time.replace(hour=17, minute=0, second=0, microsecond=0)
            if appt.end_time > closing:
                appt.end_time = closing
                fixed += 1
        if fixed:
            db.commit()
            print(f"[fix_late_appointments] Clamped {fixed} appointment(s) to 5:00 PM.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
