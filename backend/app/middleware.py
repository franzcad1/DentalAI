"""HTTP middleware for DentalAI.

RequestIdMiddleware assigns a unique trace ID to every incoming request.
The ID flows into every log line via RequestIdFilter (see logging_config.py),
so all log output for one HTTP call shares the same request_id — making it
possible to reconstruct exactly what happened for a given request even under
concurrent load.

The ID is either taken from the incoming X-Request-ID header (so upstream
proxies or the frontend can set their own) or generated as a UUID if absent.
It is echoed back in the response header so clients can correlate their
own logs with backend logs.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import request_id_var


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response
