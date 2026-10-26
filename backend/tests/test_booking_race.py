"""Integration test: two concurrent bookings for the same slot → one 201, one 409.

Needs a real, migrated PostgreSQL with at least one non-sold vehicle, so it is
skipped unless TEST_DATABASE_URL is set, e.g. inside the stack:

    docker compose exec -e TEST_DATABASE_URL="$DATABASE_URL" api pytest tests/test_booking_race.py

It writes to the bookings table and deletes its own rows afterwards.
"""

import asyncio
import os
import random
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.routes import bookings
from app.core.database import get_db
from app.models.booking import Booking
from app.models.inventory import VehicleInventory

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

ATTEMPTS = 5   # races are timing-dependent; repeat on fresh slots


async def _race() -> list[list[int]]:
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db():
        async with Session() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app = FastAPI()
    app.include_router(bookings.router, prefix="/api/bookings")
    app.dependency_overrides[get_db] = _get_db

    async with Session() as s:
        vin = await s.scalar(
            select(VehicleInventory.vin)
            .where(VehicleInventory.stock_status != "sold").limit(1))
    assert vin, "no bookable vehicle in the test database"

    # Far-future, random, minute-aligned slots so reruns never collide.
    base = datetime(2035, 1, 1, tzinfo=timezone.utc) + timedelta(
        minutes=random.randrange(0, 500_000))
    slots = [base + timedelta(minutes=i) for i in range(ATTEMPTS)]

    def body(slot):
        return {
            "vehicle_vin": vin,
            "customer_name": "race test",
            "customer_email": "race@example.com",
            "customer_phone": "+353 87 000 0000",
            "appointment_datetime": slot.isoformat(),
        }

    statuses = []
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            for slot in slots:
                rs = await asyncio.gather(
                    c.post("/api/bookings", json=body(slot)),
                    c.post("/api/bookings", json=body(slot)),
                )
                statuses.append(sorted(r.status_code for r in rs))
    finally:
        async with Session() as s:
            await s.execute(delete(Booking).where(
                Booking.vehicle_vin == vin,
                Booking.appointment_datetime.in_(slots)))
            await s.commit()
        await engine.dispose()
    return statuses


def test_concurrent_same_slot_bookings_one_wins():
    for pair in asyncio.run(_race()):
        assert pair == [201, 409]
