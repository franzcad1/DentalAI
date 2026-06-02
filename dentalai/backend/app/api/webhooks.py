"""Webhook simulation endpoint.

POST /webhooks/simulate lets you manually inject any event_type + payload
into the system during testing — identical to what the scheduler and route
handlers do automatically. The event is persisted to the events table and
logged to the console exactly like a real event.
"""

import logging
from typing_extensions import Annotated

from fastapi import APIRouter, Depends

from app.auth import require_auth
from app.events.bus import emit_event
from app.models.schemas import NexHealthResponse, WebhookSimulateRequest, WebhookSimulateResponse

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)

Auth = Annotated[dict, Depends(require_auth)]


@router.post("/simulate", response_model=NexHealthResponse[WebhookSimulateResponse])
def simulate_webhook(
    _: Auth,
    body: WebhookSimulateRequest,
) -> NexHealthResponse[WebhookSimulateResponse]:
    # Route through the same bus as all other events so it's persisted +
    # printed with the same [EVENT] format.
    event = emit_event(body.event_type, body.payload)

    return NexHealthResponse(
        data=WebhookSimulateResponse(
            received=True,
            event_type=body.event_type,
            message=f"Event '{body.event_type}' persisted and logged (event_id={event.id})",
            event_id=event.id,
        )
    )
