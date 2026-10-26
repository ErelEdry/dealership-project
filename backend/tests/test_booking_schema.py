"""Unit tests for BookingCreate validation."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.booking import BookingCreate


def _now():
    return datetime.now(timezone.utc)


def _booking(**kw):
    base = dict(
        vehicle_vin="SYNABC1234567",
        customer_name="jane doe",
        customer_email="jane@example.com",
        customer_phone="+353 87 123 4567",
        appointment_datetime=_now() + timedelta(days=3),
    )
    base.update(kw)
    return base


def test_valid_booking_titles_name():
    assert BookingCreate(**_booking()).customer_name == "Jane Doe"


def test_phone_is_cleaned_of_letters():
    # raw must be <= max_length=20 (checked before the cleaner runs)
    b = BookingCreate(**_booking(customer_phone="087 123 4567 ext"))
    assert all(c.isdigit() or c in "+- ()" for c in b.customer_phone)
    assert "e" not in b.customer_phone


def test_past_appointment_rejected():
    with pytest.raises(ValidationError):
        BookingCreate(**_booking(
            appointment_datetime=_now() - timedelta(days=1)))


def test_invalid_email_rejected():
    with pytest.raises(ValidationError):
        BookingCreate(**_booking(customer_email="not-an-email"))


def test_too_short_name_rejected():
    with pytest.raises(ValidationError):
        BookingCreate(**_booking(customer_name="x"))


# ── appointment_datetime: timezone handling ──────────────────
def test_utc_z_suffix_is_accepted_as_utc():
    b = BookingCreate(**_booking(appointment_datetime="2030-06-01T10:00:00Z"))
    assert b.appointment_datetime == datetime(2030, 6, 1, 10, tzinfo=timezone.utc)


def test_offset_is_converted_to_utc():
    b = BookingCreate(**_booking(appointment_datetime="2030-06-01T10:00:00+03:00"))
    assert b.appointment_datetime == datetime(2030, 6, 1, 7, tzinfo=timezone.utc)
    assert b.appointment_datetime.utcoffset() == timedelta(0)


def test_naive_is_assumed_utc():
    b = BookingCreate(**_booking(appointment_datetime="2030-06-01T10:00"))
    assert b.appointment_datetime == datetime(2030, 6, 1, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize("when", [
    "2020-06-01T10:00:00Z",
    "2020-06-01T10:00:00+03:00",
    "2020-06-01T10:00",
])
def test_past_appointment_rejected_in_any_form(when):
    # Used to raise a bare TypeError (naive vs aware compare) for the aware forms.
    with pytest.raises(ValidationError):
        BookingCreate(**_booking(appointment_datetime=when))


def test_future_check_uses_the_real_instant():
    # 30 min from now, written in a +03:00 wall clock: still in the future.
    soon = (_now() + timedelta(minutes=30)).astimezone(timezone(timedelta(hours=3)))
    assert BookingCreate(**_booking(appointment_datetime=soon.isoformat()))
    # 30 min ago, written in a -05:00 wall clock (wall time is "earlier"): past.
    ago = (_now() - timedelta(minutes=30)).astimezone(timezone(timedelta(hours=-5)))
    with pytest.raises(ValidationError):
        BookingCreate(**_booking(appointment_datetime=ago.isoformat()))
