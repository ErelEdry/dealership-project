"""
SQLAlchemy ORM model for vehicle reservations.
"""

from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.models.inventory import Base


class Booking(Base):
    __tablename__ = "bookings"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_vin          = Column(String(17),  nullable=False, index=True)
    customer_name        = Column(String(100), nullable=False)
    customer_email       = Column(String(255), nullable=False)
    customer_phone       = Column(String(30),  nullable=False)
    appointment_datetime = Column(DateTime,    nullable=False)
    notes                = Column(Text,        nullable=True)
    status               = Column(String(20),  nullable=False, default="pending", index=True)
    created_at           = Column(DateTime,    default=datetime.utcnow)
    updated_at           = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)
