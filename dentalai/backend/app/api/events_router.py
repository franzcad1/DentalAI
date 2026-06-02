"""Read-only event log endpoint.

The Agent Log view polls this every 10 seconds to show a live feed
of every event the system has fired (scheduler jobs, bookings, webhooks).
"""

import json
from typing import Any, Dict, List, Optional
from typing_extensions import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db.session import get_db
from app.models.orm import Event

router = APIRouter(prefix="/events", tags=["events"])

Auth = Annotated[dict, Depends(require_auth)]
DB = Annotated[Session, Depends(get_db)]


class EventOut:
    """Lightweight projection returned to the frontend.

    We deserialise `payload` from JSON text here so the client gets a
    proper object rather than a JSON-encoded string.
    """


@router.get("")
def list_events(
    _: Auth,
    db: DB,
    event_type: Optional[str] = Query(None, description="Filter by event_type prefix"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
) -> List[Dict[str, Any]]:
    """Return recent events, newest first.

    Returns a plain list (no NexHealth envelope) because this endpoint
    is polled by the real-time log view and the simpler shape is easier
    to work with in the frontend without any wrapping.
    """
    q = db.query(Event).order_by(Event.fired_at.desc())
    if event_type:
        q = q.filter(Event.event_type.like(f"{event_type}%"))
    rows = q.offset(skip).limit(limit).all()

    result = []
    for ev in rows:
        payload_obj: Dict[str, Any] = {}
        if ev.payload:
            try:
                payload_obj = json.loads(ev.payload)
            except (json.JSONDecodeError, TypeError):
                payload_obj = {"raw": ev.payload}

        result.append(
            {
                "id": ev.id,
                "event_type": ev.event_type,
                "payload": payload_obj,
                "fired_at": ev.fired_at.isoformat(),
                "status": ev.status,
            }
        )
    return result
