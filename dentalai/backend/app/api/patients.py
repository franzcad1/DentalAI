from typing import Optional
from typing_extensions import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db.session import get_db
from app.models.orm import Patient
from app.models.schemas import (
    NexHealthResponse,
    PaginatedList,
    PatientCreate,
    PatientRead,
)

router = APIRouter(prefix="/patients", tags=["patients"])

Auth = Annotated[dict, Depends(require_auth)]
DB = Annotated[Session, Depends(get_db)]


@router.get("", response_model=NexHealthResponse[PaginatedList[PatientRead]])
def list_patients(
    _: Auth,
    db: DB,
    name: Optional[str] = Query(None, description="Partial match on first or last name"),
    email: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> NexHealthResponse[PaginatedList[PatientRead]]:
    q = db.query(Patient)
    if name:
        like = f"%{name}%"
        q = q.filter(or_(Patient.first_name.ilike(like), Patient.last_name.ilike(like)))
    if email:
        q = q.filter(Patient.email.ilike(f"%{email}%"))
    total = q.count()
    items = q.offset(skip).limit(limit).all()
    return NexHealthResponse(data=PaginatedList(items=items, total=total))


@router.get("/{patient_id}", response_model=NexHealthResponse[PatientRead])
def get_patient(_: Auth, db: DB, patient_id: int) -> NexHealthResponse[PatientRead]:
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return NexHealthResponse(data=patient)


@router.post("", response_model=NexHealthResponse[PatientRead], status_code=status.HTTP_201_CREATED)
def create_patient(_: Auth, db: DB, body: PatientCreate) -> NexHealthResponse[PatientRead]:
    patient = Patient(**body.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return NexHealthResponse(code=201, description="Created", data=patient)
