"""Unit tests for BookingCreate validation."""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.booking import BookingCreate


def _booking(**kw):
    base = dict(
        vehicle_vin="SYNABC1234567",
        customer_name="erel edry",
        customer_email="erel@example.com",
        customer_phone="+353 87 123 4567",
        appointment_datetime=datetime.utcnow() + timedelta(days=3),
    )
    base.update(kw)
    return base


def test_valid_booking_titles_name():
    assert BookingCreate(**_booking()).customer_name == "Erel Edry"


def test_phone_is_cleaned_of_letters():
    # raw must be <= max_length=20 (checked before the cleaner runs)
    b = BookingCreate(**_booking(customer_phone="087 123 4567 ext"))
    assert all(c.isdigit() or c in "+- ()" for c in b.customer_phone)
    assert "e" not in b.customer_phone


def test_past_appointment_rejected():
    with pytest.raises(ValidationError):
        BookingCreate(**_booking(
            appointment_datetime=datetime.utcnow() - timedelta(days=1)))


def test_invalid_email_rejected():
    with pytest.raises(ValidationError):
        BookingCreate(**_booking(customer_email="not-an-email"))


def test_too_short_name_rejected():
    with pytest.raises(ValidationError):
        BookingCreate(**_booking(customer_name="x"))
