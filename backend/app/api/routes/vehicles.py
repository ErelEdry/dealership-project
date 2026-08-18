"""
Phase 3 — Vehicle listing + detail endpoints (pure PostgreSQL, no vectors).

    GET /api/vehicles        paginated, filterable, sortable listing
    GET /api/vehicles/{vin}  full detail for one vehicle
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.inventory import VehicleInventory
from app.schemas.search import (
    FacetCount,
    FacetsResponse,
    VehicleListResponse,
    VehicleOut,
)

router = APIRouter()

# Whitelisted sort options → ORDER BY column/direction.
_SORTS = {
    "price_asc":  VehicleInventory.price.asc(),
    "price_desc": VehicleInventory.price.desc(),
    "year_desc":  VehicleInventory.year.desc(),
    "year_asc":   VehicleInventory.year.asc(),
    "mileage_asc": VehicleInventory.mileage.asc(),
}


@router.get("", response_model=VehicleListResponse)
@router.get("/", response_model=VehicleListResponse, include_in_schema=False)
async def list_vehicles(
    db: AsyncSession = Depends(get_db),
    page:      int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    make:         Optional[str]   = None,
    fuel_type:    Optional[str]   = None,
    body_type:    Optional[str]   = None,
    segment:      Optional[str]   = None,
    min_price:    Optional[float] = Query(None, ge=0),
    max_price:    Optional[float] = Query(None, ge=0),
    min_year:     Optional[int]   = None,
    max_year:     Optional[int]   = None,
    stock_status: Optional[str]   = "available",
    sort:         str             = Query("year_desc", enum=list(_SORTS.keys())),
):
    conditions = []
    if stock_status and stock_status.lower() != "all":
        conditions.append(VehicleInventory.stock_status == stock_status)
    if make:
        conditions.append(VehicleInventory.make == make.strip().title())
    if fuel_type:
        conditions.append(VehicleInventory.fuel_type == fuel_type.strip().lower())
    if body_type:
        conditions.append(VehicleInventory.body_type == body_type.strip().lower())
    if segment:
        conditions.append(VehicleInventory.ai_segment == segment)
    if min_price is not None:
        conditions.append(VehicleInventory.price >= min_price)
    if max_price is not None:
        conditions.append(VehicleInventory.price <= max_price)
    if min_year is not None:
        conditions.append(VehicleInventory.year >= min_year)
    if max_year is not None:
        conditions.append(VehicleInventory.year <= max_year)

    total = await db.scalar(
        select(func.count()).select_from(VehicleInventory).where(*conditions)
    )

    rows = (await db.execute(
        select(VehicleInventory)
        .where(*conditions)
        .order_by(_SORTS[sort])
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    return VehicleListResponse(
        total=total or 0,
        page=page,
        page_size=page_size,
        results=[VehicleOut.model_validate(r) for r in rows],
    )


@router.get("/facets", response_model=FacetsResponse)
async def facets(
    db: AsyncSession = Depends(get_db),
    make:         Optional[str]   = None,
    fuel_type:    Optional[str]   = None,
    body_type:    Optional[str]   = None,
    segment:      Optional[str]   = None,
    min_price:    Optional[float] = Query(None, ge=0),
    max_price:    Optional[float] = Query(None, ge=0),
    min_year:     Optional[int]   = None,
    max_year:     Optional[int]   = None,
    stock_status: Optional[str]   = "available",
):
    """Grouped counts + price/year ranges for the current filter set — powers
    UI filter chips. Uses per-facet exclusion: each facet's counts apply every
    filter *except its own*, so users can still see (and pivot to) alternative
    values within a dimension they've already filtered on."""

    # One entry per filter dimension. price/year hold a list (range = 2 conds).
    dims: dict[str, list] = {}
    if stock_status and stock_status.lower() != "all":
        dims["stock_status"] = [VehicleInventory.stock_status == stock_status]
    if make:
        dims["make"] = [VehicleInventory.make == make.strip().title()]
    if fuel_type:
        dims["fuel_type"] = [VehicleInventory.fuel_type == fuel_type.strip().lower()]
    if body_type:
        dims["body_type"] = [VehicleInventory.body_type == body_type.strip().lower()]
    if segment:
        dims["ai_segment"] = [VehicleInventory.ai_segment == segment]
    price_c = []
    if min_price is not None:
        price_c.append(VehicleInventory.price >= min_price)
    if max_price is not None:
        price_c.append(VehicleInventory.price <= max_price)
    if price_c:
        dims["price"] = price_c
    year_c = []
    if min_year is not None:
        year_c.append(VehicleInventory.year >= min_year)
    if max_year is not None:
        year_c.append(VehicleInventory.year <= max_year)
    if year_c:
        dims["year"] = year_c

    def conds_excluding(*exclude: str) -> list:
        out: list = []
        for key, conds in dims.items():
            if key in exclude:
                continue
            out.extend(conds)
        return out

    async def _group(col, dim: str) -> list[FacetCount]:
        rows = (await db.execute(
            select(col, func.count().label("n"))
            .where(*conds_excluding(dim))
            .group_by(col)
            .order_by(func.count().desc())
        )).all()
        return [FacetCount(value=str(val), count=n) for val, n in rows if val is not None]

    # total reflects every active filter; ranges exclude their own dimension so
    # the slider bounds show the full span still reachable.
    total = await db.scalar(
        select(func.count()).select_from(VehicleInventory).where(*conds_excluding())
    )
    price_rng = (await db.execute(select(
        func.min(VehicleInventory.price), func.max(VehicleInventory.price),
    ).where(*conds_excluding("price")))).one()
    year_rng = (await db.execute(select(
        func.min(VehicleInventory.year), func.max(VehicleInventory.year),
    ).where(*conds_excluding("year")))).one()

    return FacetsResponse(
        total=total or 0,
        make=await _group(VehicleInventory.make, "make"),
        fuel_type=await _group(VehicleInventory.fuel_type, "fuel_type"),
        body_type=await _group(VehicleInventory.body_type, "body_type"),
        ai_segment=await _group(VehicleInventory.ai_segment, "ai_segment"),
        stock_status=await _group(VehicleInventory.stock_status, "stock_status"),
        price_min=price_rng[0], price_max=price_rng[1],
        year_min=year_rng[0], year_max=year_rng[1],
    )


@router.get("/{vin}", response_model=VehicleOut)
async def get_vehicle(vin: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(VehicleInventory, vin.strip().upper())
    if row is None:
        raise HTTPException(status_code=404, detail=f"Vehicle {vin} not found")
    return VehicleOut.model_validate(row)
