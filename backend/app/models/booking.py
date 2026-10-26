"""
SQLAlchemy ORM model for vehicle reservations.
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.models.inventory import Base, utcnow


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        # One active booking per vehicle + slot, enforced by the DB (migration
        # 002) so concurrent requests can't both pass the route's clash check.
        Index(
            "uq_bookings_active_slot", "vehicle_vin", "appointment_datetime",
            unique=True,
            postgresql_where=text("status IN ('pending', 'confirmed')"),
        ),
    )

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_vin          = Column(String(17),
                                  ForeignKey("vehicle_inventory.vin", name="fk_bookings_vehicle_vin"),
                                  nullable=False, index=True)
    customer_name        = Column(String(100), nullable=False)
    customer_email       = Column(String(255), nullable=False)
    customer_phone       = Column(String(30),  nullable=False)
    # timestamptz: stored as an absolute instant, always written as aware UTC
    appointment_datetime = Column(DateTime(timezone=True), nullable=False)
    notes                = Column(Text,        nullable=True)
    status               = Column(String(20),  nullable=False, default="pending", index=True)
    created_at           = Column(DateTime(timezone=True), default=utcnow)
    updated_at           = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
