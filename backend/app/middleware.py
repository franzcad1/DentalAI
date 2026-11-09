"""HTTP middleware for DentalAI.

RequestIdMiddleware does three things per request:
1. Assigns a request ID (a valid X-Request-ID header, else a fresh UUID) and
   stores it in request_id_var so every log line carries the same ID. A header
   that is too long or has odd characters is replaced, not trusted.
2. Opens an "http.request" span and records request count and latency metrics
   labelled by route TEMPLATE (never the raw path, which can hold ids).
3. Logs a single request-completed line with method, path, route template,
   status code, and wall-clock duration.
"""

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import request_id_var
from app.observability import metrics, span

logger = logging.getLogger(__name__)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _clean_request_id(value):
    return value if value and _REQUEST_ID_RE.match(value) else str(uuid.uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = _clean_request_id(request.headers.get("X-Request-ID"))
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status_code = 500  # default; overwritten on a normal response
        error_type = None
        route = "unmatched"
        try:
            with span("http.request", method=request.method, request_id=request_id) as sp:
                try:
                    response = await call_next(request)
                    status_code = response.status_code
                except Exception as exc:
                    error_type = type(exc).__name__
                    raise
                finally:
                    route = getattr(request.scope.get("route"), "path", None) or "unmatched"
                    sp.set(route=route, status=status_code)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000)
            status_class = "%dxx" % (status_code // 100)
            metrics.inc("http_requests_total", route=route, method=request.method,
                        status_class=status_class)
            metrics.observe("http_request_duration_ms", duration_ms, route=route)
            if status_code >= 500:
                metrics.record_error(request_id=request_id, route=route,
                                     status=status_code, error_type=error_type or "http_5xx")
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "route": route,
                    "status": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response
