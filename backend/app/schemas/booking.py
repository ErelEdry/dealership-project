"""
Pydantic schemas for the vehicle reservation / booking flow.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, EmailStr, Field, field_validator


class BookingStatus(str, Enum):
    PENDING   = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


# ── Request body (what the frontend sends) ────────────────────

class BookingCreate(BaseModel):
    """Submitted by the user via the Reserve modal."""

    vehicle_vin:          str      = Field(..., description="VIN of the vehicle to reserve")
    customer_name:        str      = Field(..., min_length=2, max_length=100)
    customer_email:       EmailStr
    customer_phone:       str      = Field(..., min_length=7, max_length=20)
    appointment_datetime: datetime = Field(..., description="Requested test-drive date/time (UTC)")
    notes:                Optional[str] = Field(None, max_length=500)

    @field_validator("customer_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return v.strip().title()

    @field_validator("customer_phone")
    @classmethod
    def clean_phone(cls, v: str) -> str:
        # Keep only digits, +, -, spaces
        return "".join(c for c in v if c.isdigit() or c in "+- ()")

    @field_validator("appointment_datetime")
    @classmethod
    def must_be_future(cls, v: datetime) -> datetime:
        if v <= datetime.utcnow():
            raise ValueError("Appointment must be in the future")
        return v


# ── Database record (what gets stored) ───────────────────────

class BookingRecord(BookingCreate):
    id:         UUID          = Field(default_factory=uuid4)
    status:     BookingStatus = BookingStatus.PENDING
    created_at: datetime      = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    model_config = {"use_enum_values": True}


# ── API response ──────────────────────────────────────────────

class BookingResponse(BaseModel):
    id:                   UUID
    vehicle_vin:          str
    customer_name:        str
    appointment_datetime: datetime
    status:               BookingStatus
    created_at:           datetime

    model_config = {"from_attributes": True}
