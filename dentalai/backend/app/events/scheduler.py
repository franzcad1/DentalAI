"""APScheduler background job definitions.

Two recurring jobs:

  appointment_reminder_job  — every 2 minutes
    Scans for appointments starting within the next 24 hours that are still
    pending or confirmed and fires appointment.reminder for each one.

  recall_due_job            — every 5 minutes
    Scans for patient recalls whose due_date has passed and status is still
    'pending', fires recall.due for each one.

Design notes:
  - Each job creates its own SessionLocal() so threads never share state.
  - SQLite datetimes are stored as naive ISO strings; we use datetime.utcnow()
    consistently to avoid tz-aware vs tz-naive comparison errors.
  - In production you'd track "already notified" state to avoid re-firing the
    same events on every poll cycle. Here we fire every cycle for demo clarity;
    add a `last_reminder_sent_at` column or a dedup check for production use.
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.db.session import SessionLocal
from app.events.bus import emit_event
from app.models.orm import Appointment, PatientRecall

logger = logging.getLogger(__name__)

# Module-level scheduler instance — started and stopped inside the FastAPI
# lifespan so its lifetime is tied to the server process.
scheduler = BackgroundScheduler(timezone="UTC")


# ---------------------------------------------------------------------------
# Job: appointment reminders
# ---------------------------------------------------------------------------


def appointment_reminder_job() -> None:
    """Fire appointment.reminder for every upcoming appointment in 24 h."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        cutoff = now + timedelta(hours=24)

        appointments = (
            db.query(Appointment)
            .filter(Appointment.start_time >= now)
            .filter(Appointment.start_time <= cutoff)
            .filter(Appointment.status.in_(["pending", "confirmed"]))
            .all()
        )

        for appt in appointments:
            emit_event(
                "appointment.reminder",
                {
                    "appointment_id": appt.id,
                    "patient_id": appt.patient_id,
                    "provider_id": appt.provider_id,
                    "start_time": appt.start_time.isoformat(),
                },
            )

        if appointments:
            logger.info(
                "[SCHEDULER] appointment_reminder_job fired %d reminder(s)", len(appointments)
            )
        else:
            logger.debug("[SCHEDULER] appointment_reminder_job — no upcoming appointments")

    except Exception as exc:
        logger.error("[SCHEDULER] appointment_reminder_job failed: %s", exc, exc_info=True)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Job: overdue recalls
# ---------------------------------------------------------------------------


def recall_due_job() -> None:
    """Fire recall.due for every pending recall whose due_date has passed."""
    db = SessionLocal()
    try:
        today = datetime.utcnow().date()

        overdue = (
            db.query(PatientRecall)
            .filter(PatientRecall.due_date < today)
            .filter(PatientRecall.status == "pending")
            .all()
        )

        for recall in overdue:
            emit_event(
                "recall.due",
                {
                    "recall_id": recall.id,
                    "patient_id": recall.patient_id,
                    "recall_type": recall.recall_type,
                    "due": str(recall.due_date),
                },
            )

        if overdue:
            logger.info(
                "[SCHEDULER] recall_due_job fired %d recall.due event(s)", len(overdue)
            )
        else:
            logger.debug("[SCHEDULER] recall_due_job — no overdue recalls")

    except Exception as exc:
        logger.error("[SCHEDULER] recall_due_job failed: %s", exc, exc_info=True)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Lifecycle helpers called from main.py lifespan
# ---------------------------------------------------------------------------


def start_scheduler() -> None:
    """Register jobs and start the background scheduler."""
    scheduler.add_job(
        appointment_reminder_job,
        trigger="interval",
        minutes=2,
        id="appt_reminders",
        replace_existing=True,
    )
    scheduler.add_job(
        recall_due_job,
        trigger="interval",
        minutes=5,
        id="recall_due",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "[SCHEDULER] Started — appointment reminders every 2 min, recall checks every 5 min"
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler on server teardown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[SCHEDULER] Stopped")
