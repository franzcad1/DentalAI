"""Pydantic v2 schemas — request/response shapes for all entities.

The NexHealth envelope wraps every response:
  { "code": 200, "description": "...", "data": { ... } }

Uses typing.Optional / Dict / List (not X|None / dict[] / list[]) so
the schemas are compatible with Python 3.8+.
"""

from datetime import date, datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# NexHealth-style response envelope
# ---------------------------------------------------------------------------


class NexHealthResponse(BaseModel, Generic[T]):
    code: int = 200
    description: str = "OK"
    data: T


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------


class PatientBase(BaseModel):
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    dob: Optional[date] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=30)


class PatientCreate(PatientBase):
    pass


class PatientRead(PatientBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class ProviderBase(BaseModel):
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    specialty: Optional[str] = Field(None, max_length=100)


class ProviderCreate(ProviderBase):
    pass


class ProviderRead(ProviderBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


class LocationBase(BaseModel):
    name: str = Field(..., max_length=200)
    address: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, max_length=30)


class LocationCreate(LocationBase):
    pass


class LocationRead(LocationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


# ---------------------------------------------------------------------------
# AppointmentType
# ---------------------------------------------------------------------------


class AppointmentTypeBase(BaseModel):
    name: str = Field(..., max_length=100)
    duration_minutes: int = Field(30, ge=5, le=480)


class AppointmentTypeCreate(AppointmentTypeBase):
    pass


class AppointmentTypeRead(AppointmentTypeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


# ---------------------------------------------------------------------------
# Appointment
# ---------------------------------------------------------------------------

APPOINTMENT_STATUSES = {"pending", "confirmed", "completed", "cancelled", "no_show"}


class AppointmentBase(BaseModel):
    patient_id: int
    provider_id: int
    location_id: int
    appointment_type_id: int
    start_time: datetime
    end_time: datetime
    status: str = Field("pending", pattern=r"^(pending|confirmed|completed|cancelled|no_show)$")
    notes: Optional[str] = None


class AppointmentCreate(AppointmentBase):
    pass


class AppointmentUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern=r"^(pending|confirmed|completed|cancelled|no_show)$")
    notes: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class AppointmentRead(AppointmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


# ---------------------------------------------------------------------------
# AvailableSlot
# ---------------------------------------------------------------------------


class AvailableSlotBase(BaseModel):
    provider_id: int
    location_id: int
    start_time: datetime
    end_time: datetime
    is_booked: bool = False


class AvailableSlotCreate(AvailableSlotBase):
    pass


class AvailableSlotRead(AvailableSlotBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


# ---------------------------------------------------------------------------
# PatientRecall
# ---------------------------------------------------------------------------

RECALL_STATUSES = {"pending", "contacted", "scheduled", "dismissed"}


class PatientRecallBase(BaseModel):
    patient_id: int
    recall_type: str = Field(..., max_length=100)
    due_date: date
    last_contacted_at: Optional[datetime] = None
    status: str = Field("pending", pattern=r"^(pending|contacted|scheduled|dismissed)$")


class PatientRecallCreate(PatientRecallBase):
    pass


class PatientRecallRead(PatientRecallBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    payload: Optional[str] = None
    fired_at: datetime
    status: str


# ---------------------------------------------------------------------------
# Webhook simulation
# ---------------------------------------------------------------------------


class WebhookSimulateRequest(BaseModel):
    event_type: str = Field(..., description="e.g. appointment.created, patient.updated")
    payload: Dict[str, Any]


class WebhookSimulateResponse(BaseModel):
    received: bool = True
    event_type: str
    message: str
    event_id: int


# ---------------------------------------------------------------------------
# Agent chat
# ---------------------------------------------------------------------------


class AgentToolCall(BaseModel):
    """A single tool invocation made during an agent turn."""

    tool: str
    input: Dict[str, Any]
    output: str


class AgentChatRequest(BaseModel):
    message: str = Field(..., description="User message to the AI agent")
    session_id: str = Field("default", description="Conversation session ID for memory continuity")


class AgentChatResponse(BaseModel):
    response: str
    tool_calls: List[AgentToolCall]
    session_id: str


# ---------------------------------------------------------------------------
# Paginated list wrapper (used as the `data` value inside the envelope)
# ---------------------------------------------------------------------------


class PaginatedList(BaseModel, Generic[T]):
    items: List[T]
    total: int
