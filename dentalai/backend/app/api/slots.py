from datetime import date
from typing import Optional
from typing_extensions import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db.session import get_db
from app.models.orm import AvailableSlot
from app.models.schemas import AvailableSlotRead, NexHealthResponse, PaginatedList

router = APIRouter(prefix="/available_slots", tags=["slots"])

Auth = Annotated[dict, Depends(require_auth)]
DB = Annotated[Session, Depends(get_db)]


@router.get("", response_model=NexHealthResponse[PaginatedList[AvailableSlotRead]])
def list_available_slots(
    _: Auth,
    db: DB,
    provider_id: Optional[int] = Query(None),
    date: Optional[date] = Query(None, description="Filter slots on this calendar date"),
    booked: Optional[bool] = Query(None, description="True=include booked, False=open only"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> NexHealthResponse[PaginatedList[AvailableSlotRead]]:
    q = db.query(AvailableSlot)
    if provider_id is not None:
        q = q.filter(AvailableSlot.provider_id == provider_id)
    if date is not None:
        q = q.filter(AvailableSlot.start_time >= f"{date} 00:00:00").filter(
            AvailableSlot.start_time <= f"{date} 23:59:59"
        )
    if booked is not None:
        q = q.filter(AvailableSlot.is_booked == booked)
    total = q.count()
    items = q.order_by(AvailableSlot.start_time).offset(skip).limit(limit).all()
    return NexHealthResponse(data=PaginatedList(items=items, total=total))
