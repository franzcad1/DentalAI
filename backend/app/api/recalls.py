from datetime import date, datetime
from typing import Optional
from typing_extensions import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db.session import get_db
from app.models.orm import PatientRecall
from app.models.schemas import NexHealthResponse, PaginatedList, PatientRecallRead

router = APIRouter(prefix="/patient_recalls", tags=["recalls"])

Auth = Annotated[dict, Depends(require_auth)]
DB = Annotated[Session, Depends(get_db)]


@router.get("", response_model=NexHealthResponse[PaginatedList[PatientRecallRead]])
def list_patient_recalls(
    _: Auth,
    db: DB,
    status: Optional[str] = Query(None, description="pending | contacted | scheduled | dismissed"),
    due_before: Optional[date] = Query(None, description="Return recalls with due_date <= this date"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> NexHealthResponse[PaginatedList[PatientRecallRead]]:
    q = db.query(PatientRecall)
    if status is not None:
        q = q.filter(PatientRecall.status == status)
    if due_before is not None:
        q = q.filter(PatientRecall.due_date <= due_before)
    total = q.count()
    items = q.order_by(PatientRecall.due_date).offset(skip).limit(limit).all()
    return NexHealthResponse(data=PaginatedList(items=items, total=total))


class RecallUpdate(BaseModel):
    status: Optional[str] = None
    last_contacted_at: Optional[datetime] = None


@router.patch("/{recall_id}", response_model=NexHealthResponse[PatientRecallRead])
def update_recall(
    _: Auth,
    db: DB,
    recall_id: int,
    body: RecallUpdate,
) -> NexHealthResponse[PatientRecallRead]:
    recall = db.get(PatientRecall, recall_id)
    if not recall:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recall not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(recall, field, value)
    db.commit()
    db.refresh(recall)
    return NexHealthResponse(data=recall)
