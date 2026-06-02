"""Central event bus.

emit_event() is the single entry point for all event firing in the system:
  - Persists the event to the events table (audit trail)
  - Prints a structured line to stdout for easy console monitoring
  - Returns the persisted Event ORM object so callers can reference its id

Thread-safe: creates its own short-lived session so it can be called from
scheduler threads, request handlers, and agent tools without sharing state.

SQLite datetime note: stored datetimes are naive (no tzinfo). We use
datetime.utcnow() consistently throughout this module to keep comparisons
straightforward.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict

from app.db.session import SessionLocal
from app.models.orm import Event

logger = logging.getLogger(__name__)


def emit_event(event_type: str, payload: Dict[str, Any]) -> Event:
    """Persist and broadcast a single event.

    Args:
        event_type: Dot-namespaced string, e.g. 'appointment.booked'.
        payload:    Arbitrary dict — serialised to JSON for storage.

    Returns:
        The committed Event ORM row (id is populated).
    """
    db = SessionLocal()
    try:
        event = Event(
            event_type=event_type,
            payload=json.dumps(payload),
            fired_at=datetime.utcnow(),
            status="received",
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        # Human-readable console line: [EVENT] recall.due → patient_id=12 | due=2024-01-15
        parts = " | ".join(f"{k}={v}" for k, v in payload.items())
        logger.info("[EVENT] %s → %s", event_type, parts)

        return event
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
