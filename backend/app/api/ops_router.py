"""Read-only operations endpoints (M1b), protected by OPS_TOKEN.

Returns 404 when OPS_TOKEN is not set, 401 on a missing or wrong token.
Responses hold counts, timings, route templates, request IDs and error types
only, never message text or patient data.
"""

import hmac
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, status

from app.observability import config
from app.observability.metrics import metrics
from app.observability.runtime import deep_health, get_evaluator

router = APIRouter(prefix="/ops", tags=["ops"])


def _check(token: Optional[str]) -> None:
    expected = config.ops_token()
    if not expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@router.get("/summary")
def ops_summary(window_s: int = 300,
                x_ops_token: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check(x_ops_token)
    window_s = max(60, min(window_s, 6 * 3600))
    data = metrics.summary(window_s)
    data["active_alerts"] = sorted(get_evaluator().active)
    data["health"] = deep_health()
    return data
