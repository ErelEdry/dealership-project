"""API tests for POST /api/bookings, with an in-memory stand-in for the DB.

The real bookings router is mounted on a bare FastAPI app and `get_db` is
overridden, so the full request → validation → handler path runs without
PostgreSQL. Concurrency against a real database is covered separately.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.routes import bookings
from app.core.config import settings
from app.core.database import get_db

VIN = "SYNABC12345678901"


class FakeSession:
    """Just enough of AsyncSession for the bookings route."""

    def __init__(self, vehicles=None, clash=False, violate=None):
        self.vehicles = vehicles if vehicles is not None else {
            VIN: SimpleNamespace(vin=VIN, stock_status="available")}
        self.clash = clash
        self.violate = violate      # constraint name the INSERT should violate
        self.added = []
        self.committed = self.rolled_back = False

    async def get(self, model, key):
        return self.vehicles.get(key)

    async def scalar(self, stmt):
        return "existing-id" if self.clash else None

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        if self.violate:
            # Shaped like asyncpg's error as SQLAlchemy wraps it.
            raise IntegrityError("INSERT INTO bookings ...", {}, Exception(
                f'duplicate key value violates constraint "{self.violate}"'))
        for obj in self.added:
            for col in obj.__table__.columns:
                if getattr(obj, col.key) is None and col.default is not None:
                    arg = col.default.arg
                    setattr(obj, col.key, arg(None) if callable(arg) else arg)

    async def refresh(self, obj):
        pass

    async def execute(self, stmt):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def _client(session):
    app = FastAPI()
    app.include_router(bookings.router, prefix="/api/bookings")

    async def _get_db():
        yield session

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app, raise_server_exceptions=False)


def _body(when):
    return {
        "vehicle_vin": VIN,
        "customer_name": "jane doe",
        "customer_email": "jane@example.com",
        "customer_phone": "+353 87 123 4567",
        "appointment_datetime": when,
    }


_FUTURE = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0)
_PAST = _FUTURE - timedelta(days=10)


@pytest.mark.parametrize("when", [
    _FUTURE.strftime("%Y-%m-%dT%H:%M:%SZ"),                              # Z
    _FUTURE.astimezone(timezone(timedelta(hours=3))).isoformat(),        # +03:00
    _FUTURE.replace(tzinfo=None).isoformat(),                            # no offset
])
def test_future_booking_is_created_in_any_form(when):
    session = FakeSession()
    r = _client(session).post("/api/bookings", json=_body(when))
    assert r.status_code == 201, r.text
    stored = session.added[0].appointment_datetime
    assert stored == _FUTURE                      # same instant regardless of form
    assert stored.utcoffset() == timedelta(0)     # always written as aware UTC


@pytest.mark.parametrize("when", [
    _PAST.strftime("%Y-%m-%dT%H:%M:%SZ"),
    _PAST.astimezone(timezone(timedelta(hours=3))).isoformat(),
    _PAST.replace(tzinfo=None).isoformat(),
])
def test_past_booking_is_422_not_500(when):
    r = _client(FakeSession()).post("/api/bookings", json=_body(when))
    assert r.status_code == 422, r.text


def test_unknown_vin_is_404():
    r = _client(FakeSession(vehicles={})).post(
        "/api/bookings", json=_body(_FUTURE.isoformat()))
    assert r.status_code == 404


def test_taken_slot_is_409():
    r = _client(FakeSession(clash=True)).post(
        "/api/bookings", json=_body(_FUTURE.isoformat()))
    assert r.status_code == 409


# ── DB-enforced slot rule (item 5) ───────────────────────────
def test_booking_is_committed_by_the_handler():
    session = FakeSession()
    r = _client(session).post("/api/bookings", json=_body(_FUTURE.isoformat()))
    assert r.status_code == 201
    assert session.committed


def test_lost_race_on_unique_slot_is_409_not_500():
    # The clash SELECT saw nothing (a concurrent request hadn't committed yet),
    # but the partial unique index rejects the INSERT.
    session = FakeSession(violate="uq_bookings_active_slot")
    r = _client(session).post("/api/bookings", json=_body(_FUTURE.isoformat()))
    assert r.status_code == 409
    assert "taken" in r.json()["detail"]
    assert session.rolled_back


def test_vin_fk_violation_is_404():
    session = FakeSession(violate="fk_bookings_vehicle_vin")
    r = _client(session).post("/api/bookings", json=_body(_FUTURE.isoformat()))
    assert r.status_code == 404


def test_unrelated_integrity_error_is_not_masked():
    session = FakeSession(violate="some_other_constraint")
    r = _client(session).post("/api/bookings", json=_body(_FUTURE.isoformat()))
    assert r.status_code == 500


# ── GET /api/bookings is admin-only (item 11) ────────────────
def test_listing_disabled_without_configured_token(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "")
    r = _client(FakeSession()).get("/api/bookings", headers={"X-Admin-Token": ""})
    assert r.status_code == 403


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "wrong"}])
def test_listing_rejects_missing_or_wrong_token(monkeypatch, headers):
    monkeypatch.setattr(settings, "admin_token", "s3cret-admin-token")
    r = _client(FakeSession()).get("/api/bookings", headers=headers)
    assert r.status_code == 401


def test_listing_with_admin_token(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret-admin-token")
    r = _client(FakeSession()).get("/api/bookings",
                                   headers={"X-Admin-Token": "s3cret-admin-token"})
    assert r.status_code == 200
    assert r.json() == []
