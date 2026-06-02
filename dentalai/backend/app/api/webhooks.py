"""Webhook simulation endpoint.

Allows manual testing of the event pipeline without a real NexHealth
subscription. POST a typed event and the system processes it as if
NexHealth had sent it.
"""

import logging
from typing_extensions import Annotated

from fastapi import APIRouter, Depends

from app.auth import require_auth
from app.models.schemas import NexHealthResponse, WebhookSimulateRequest, WebhookSimulateResponse

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

Auth = Annotated[dict, Depends(require_auth)]
logger = logging.getLogger(__name__)


@router.post("/simulate", response_model=NexHealthResponse[WebhookSimulateResponse])
def simulate_webhook(
    _: Auth,
    body: WebhookSimulateRequest,
) -> NexHealthResponse[WebhookSimulateResponse]:
    logger.info("Simulated webhook received: event_type=%s payload=%s", body.event_type, body.payload)
    return NexHealthResponse(
        data=WebhookSimulateResponse(
            received=True,
            event_type=body.event_type,
            message=f"Event '{body.event_type}' queued for processing",
        )
    )
