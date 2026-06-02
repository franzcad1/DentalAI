"""Appointment type read endpoint — used by the frontend booking flow."""

from typing_extensions import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db.session import get_db
from app.models.orm import AppointmentType
from app.models.schemas import AppointmentTypeRead, NexHealthResponse, PaginatedList

router = APIRouter(prefix="/appointment_types", tags=["appointment_types"])

Auth = Annotated[dict, Depends(require_auth)]
DB = Annotated[Session, Depends(get_db)]


@router.get("", response_model=NexHealthResponse[PaginatedList[AppointmentTypeRead]])
def list_appointment_types(
    _: Auth, db: DB
) -> NexHealthResponse[PaginatedList[AppointmentTypeRead]]:
    types = db.query(AppointmentType).order_by(AppointmentType.name).all()
    return NexHealthResponse(data=PaginatedList(items=types, total=len(types)))
