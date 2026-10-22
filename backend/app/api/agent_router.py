"""Agent chat endpoint.

POST /agent/chat  →  { response, tool_calls, session_id }

It delegates entirely to run_agent() in app.agent.agent — this file is
intentionally thin so the agent logic can be tested independently of FastAPI.
"""

import logging

from typing import Optional

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import AgentChatRequest, AgentChatResponse, AgentToolCall

router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=AgentChatResponse)
def agent_chat(body: AgentChatRequest) -> AgentChatResponse:
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
    except (EnvironmentError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    except RuntimeError as exc:
        err_str = str(exc)
        http_status = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if "rate limit" in err_str.lower() or "token limit" in err_str.lower()
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        raise HTTPException(status_code=http_status, detail=err_str)
    except Exception as exc:
        err_str = str(exc)
        logger.error("[AGENT] Unexpected error during chat: %s", exc, exc_info=True)
        # Surface Groq rate-limit errors with a friendly message
        if "413" in err_str or "rate_limit_exceeded" in err_str or "too large" in err_str.lower():
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="The AI provider's rate limit was hit (request too large or too many requests). Please try again in a minute.",
            )
        if "429" in err_str:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="The AI provider is rate-limited right now. Please wait a moment and try again.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent encountered an unexpected error. Check server logs.",
        )

    tool_calls = [AgentToolCall(**tc) for tc in result["tool_calls"]]

    # Strip any raw HTML tags the model may have included
    import re
    clean_response = re.sub(r'<br\s*/?>', '\n', result["response"])
    clean_response = re.sub(r'<[^>]+>', '', clean_response)

    return AgentChatResponse(
        response=clean_response,
        tool_calls=tool_calls,
        session_id=body.session_id,
    )


@router.get("/status/{session_id}", tags=["agent"])
def agent_status(session_id: str) -> dict:
    """Return the current retry status for a session, if any.

    Returns { retrying: true, retry_in: int, remaining: int } while waiting,
    or { retrying: false } when idle.
    """
    from app.agent.agent import get_retry_status
    entry = get_retry_status(session_id)
    if entry:
        return {"retrying": True, "retry_in": entry["retry_in"], "remaining": entry["remaining"]}
    return {"retrying": False}
