from datetime import date
from typing import Optional
from typing_extensions import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db.session import get_db
from app.models.orm import Appointment
from app.models.schemas import (
    AppointmentCreate,
    AppointmentRead,
    AppointmentUpdate,
    NexHealthResponse,
    PaginatedList,
)

router = APIRouter(prefix="/appointments", tags=["appointments"])

Auth = Annotated[dict, Depends(require_auth)]
DB = Annotated[Session, Depends(get_db)]


@router.get("", response_model=NexHealthResponse[PaginatedList[AppointmentRead]])
def list_appointments(
    _: Auth,
    db: DB,
    provider_id: Optional[int] = Query(None),
    date: Optional[date] = Query(None, description="Filter appointments on this calendar date"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> NexHealthResponse[PaginatedList[AppointmentRead]]:
    q = db.query(Appointment)
    if provider_id is not None:
        q = q.filter(Appointment.provider_id == provider_id)
    if date is not None:
        # SQLite stores datetimes as strings; cast to date for comparison
        q = q.filter(Appointment.start_time >= f"{date}T00:00:00").filter(
            Appointment.start_time < f"{date}T23:59:59"
        )
    total = q.count()
    items = q.order_by(Appointment.start_time).offset(skip).limit(limit).all()
    return NexHealthResponse(data=PaginatedList(items=items, total=total))


@router.post("", response_model=NexHealthResponse[AppointmentRead], status_code=status.HTTP_201_CREATED)
def create_appointment(_: Auth, db: DB, body: AppointmentCreate) -> NexHealthResponse[AppointmentRead]:
    appt = Appointment(**body.model_dump())
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return NexHealthResponse(code=201, description="Created", data=appt)


@router.patch("/{appointment_id}", response_model=NexHealthResponse[AppointmentRead])
def update_appointment(
    _: Auth, db: DB, appointment_id: int, body: AppointmentUpdate
) -> NexHealthResponse[AppointmentRead]:
    appt = db.get(Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(appt, field, value)
    db.commit()
    db.refresh(appt)
    return NexHealthResponse(data=appt)
