"""HTTP middleware for DentalAI.

RequestIdMiddleware does two things per request:
1. Assigns a trace ID (from X-Request-ID header or a fresh UUID) and stores it
   in request_id_var so every log line for this request carries the same ID.
2. Logs a single request-completed line with method, path, status code, and
   wall-clock duration — the most useful line for debugging and the one worth
   showing in an interview.
"""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import request_id_var

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status_code = 500  # default; overwritten on a normal response
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000)
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response
