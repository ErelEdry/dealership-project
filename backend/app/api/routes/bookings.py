"""
Phase 4 — Test-drive bookings.

    POST /api/bookings        create a test-drive request for a vehicle
    GET  /api/bookings        recent bookings (demo/admin listing)
    GET  /api/bookings/{id}   one booking

The data layer (model, schemas, migrated `bookings` table) was scaffolded in
Phase 1; this wires it to the API. A booking references a vehicle by VIN — we
404 if the VIN is unknown, and 409 if that exact slot (same vehicle + datetime)
is already held by an active booking. The slot rule is enforced by a partial
unique index (migration 002); the SELECT below is only the fast, friendly path.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.booking import Booking
from app.models.inventory import VehicleInventory
from app.schemas.booking import BookingCreate, BookingResponse

router = APIRouter()

# Statuses that still hold a time slot (so it can't be double-booked).
_ACTIVE = ("pending", "confirmed")

# DB constraints from migration 002, mapped to the HTTP error they mean.
_SLOT_INDEX = "uq_bookings_active_slot"
_VIN_FK = "fk_bookings_vehicle_vin"
_SLOT_TAKEN = "That time slot is already taken — please pick another."


@router.post("", response_model=BookingResponse, status_code=201)
@router.post("/", response_model=BookingResponse, status_code=201, include_in_schema=False)
async def create_booking(body: BookingCreate, db: AsyncSession = Depends(get_db)):
    vin = body.vehicle_vin.strip().upper()

    # Vehicle must exist and be purchasable.
    vehicle = await db.get(VehicleInventory, vin)
    if vehicle is None:
        raise HTTPException(status_code=404, detail=f"Vehicle {vin} not found")
    if vehicle.stock_status in ("sold",):
        raise HTTPException(status_code=409, detail="This vehicle is no longer available")

    # Double-book guard: same vehicle + same slot, still active.
    clash = await db.scalar(
        select(Booking.id).where(
            Booking.vehicle_vin == vin,
            Booking.appointment_datetime == body.appointment_datetime,
            Booking.status.in_(_ACTIVE),
        )
    )
    if clash is not None:
        raise HTTPException(
            status_code=409,
            detail=_SLOT_TAKEN,
        )

    booking = Booking(
        vehicle_vin=vin,
        customer_name=body.customer_name,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        appointment_datetime=body.appointment_datetime,
        notes=body.notes,
    )
    db.add(booking)
    # Commit here rather than in get_db after the response is built, so a
    # constraint violation (a concurrent request won the slot) becomes a 409
    # instead of escaping as a 500.
    try:
        await db.flush()       # populate id / created_at defaults
        await db.refresh(booking)
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        violated = str(e.orig)
        if _SLOT_INDEX in violated:
            raise HTTPException(status_code=409, detail=_SLOT_TAKEN) from e
        if _VIN_FK in violated:
            raise HTTPException(status_code=404, detail=f"Vehicle {vin} not found") from e
        raise
    return BookingResponse.model_validate(booking)


@router.get("", response_model=list[BookingResponse])
@router.get("/", response_model=list[BookingResponse], include_in_schema=False)
async def list_bookings(
    db: AsyncSession = Depends(get_db),
    vin: str | None = Query(None, description="Filter to one vehicle"),
    limit: int = Query(20, ge=1, le=100),
):
    stmt = select(Booking).order_by(Booking.created_at.desc()).limit(limit)
    if vin:
        stmt = stmt.where(Booking.vehicle_vin == vin.strip().upper())
    rows = (await db.execute(stmt)).scalars().all()
    return [BookingResponse.model_validate(r) for r in rows]


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(booking_id: UUID, db: AsyncSession = Depends(get_db)):
    booking = await db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return BookingResponse.model_validate(booking)
