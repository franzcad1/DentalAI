"""Agent chat endpoint.

POST /agent/chat  →  { response, tool_calls, session_id }

The endpoint is protected by the same JWT middleware as every other route.
It delegates entirely to run_agent() in app.agent.agent — this file is
intentionally thin so the agent logic can be tested independently of FastAPI.
"""

import logging
from typing_extensions import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import require_auth
from app.models.schemas import AgentChatRequest, AgentChatResponse, AgentToolCall

router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger(__name__)

Auth = Annotated[dict, Depends(require_auth)]


@router.post("/chat", response_model=AgentChatResponse)
def agent_chat(_: Auth, body: AgentChatRequest) -> AgentChatResponse:
    """Send a message to the DentalAI agent and receive a structured reply.

    The agent has access to five tools: check_available_slots, book_appointment,
    get_patient_context, get_recall_queue, and draft_recall_message.

    The response includes a `tool_calls` list showing every tool the agent
    invoked during this turn — useful for debugging and transparency.
    """
    # Import here to avoid a circular import: agent.py → bus.py → orm.py
    # and to let the server start cleanly even if OPENAI_API_KEY is missing.
    from app.agent.agent import run_agent

    try:
        result = run_agent(message=body.message, session_id=body.session_id)
    except (RuntimeError, EnvironmentError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error("[AGENT] Unexpected error during chat: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent encountered an unexpected error. Check server logs.",
        )

    tool_calls = [AgentToolCall(**tc) for tc in result["tool_calls"]]

    return AgentChatResponse(
        response=result["response"],
        tool_calls=tool_calls,
        session_id=body.session_id,
    )
