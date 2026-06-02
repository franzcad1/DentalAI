"""Provider read endpoints.

The frontend needs provider names to enrich the schedule view
(appointments only store provider_id).
"""

from typing_extensions import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db.session import get_db
from app.models.orm import Provider
from app.models.schemas import NexHealthResponse, PaginatedList, ProviderRead

router = APIRouter(prefix="/providers", tags=["providers"])

Auth = Annotated[dict, Depends(require_auth)]
DB = Annotated[Session, Depends(get_db)]


@router.get("", response_model=NexHealthResponse[PaginatedList[ProviderRead]])
def list_providers(_: Auth, db: DB) -> NexHealthResponse[PaginatedList[ProviderRead]]:
    providers = db.query(Provider).order_by(Provider.last_name).all()
    return NexHealthResponse(data=PaginatedList(items=providers, total=len(providers)))
