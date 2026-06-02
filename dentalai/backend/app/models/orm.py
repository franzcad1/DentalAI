"""SQLAlchemy ORM models mirroring NexHealth's core entities.

Using Optional[X] instead of X | None in Mapped[] annotations because
SQLAlchemy 2.0 evaluates these at runtime via get_type_hints(), which
requires the union syntax to be evaluable on the target Python version.
"""

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dob: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    appointments: Mapped[List["Appointment"]] = relationship("Appointment", back_populates="patient")
    recalls: Mapped[List["PatientRecall"]] = relationship("PatientRecall", back_populates="patient")


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    specialty: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    appointments: Mapped[List["Appointment"]] = relationship("Appointment", back_populates="provider")
    available_slots: Mapped[List["AvailableSlot"]] = relationship("AvailableSlot", back_populates="provider")


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    appointments: Mapped[List["Appointment"]] = relationship("Appointment", back_populates="location")
    available_slots: Mapped[List["AvailableSlot"]] = relationship("AvailableSlot", back_populates="location")


class AppointmentType(Base):
    __tablename__ = "appointment_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    appointments: Mapped[List["Appointment"]] = relationship("Appointment", back_populates="appointment_type")


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    provider_id: Mapped[int] = mapped_column(Integer, ForeignKey("providers.id"), nullable=False, index=True)
    location_id: Mapped[int] = mapped_column(Integer, ForeignKey("locations.id"), nullable=False)
    appointment_type_id: Mapped[int] = mapped_column(Integer, ForeignKey("appointment_types.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Mirrors NexHealth statuses: pending, confirmed, completed, cancelled, no_show
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    patient: Mapped["Patient"] = relationship("Patient", back_populates="appointments")
    provider: Mapped["Provider"] = relationship("Provider", back_populates="appointments")
    location: Mapped["Location"] = relationship("Location", back_populates="appointments")
    appointment_type: Mapped["AppointmentType"] = relationship("AppointmentType", back_populates="appointments")


class AvailableSlot(Base):
    __tablename__ = "available_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider_id: Mapped[int] = mapped_column(Integer, ForeignKey("providers.id"), nullable=False, index=True)
    location_id: Mapped[int] = mapped_column(Integer, ForeignKey("locations.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_booked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    provider: Mapped["Provider"] = relationship("Provider", back_populates="available_slots")
    location: Mapped["Location"] = relationship("Location", back_populates="available_slots")


class PatientRecall(Base):
    __tablename__ = "patient_recalls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    recall_type: Mapped[str] = mapped_column(String(100), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    last_contacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # pending, contacted, scheduled, dismissed
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")

    patient: Mapped["Patient"] = relationship("Patient", back_populates="recalls")
