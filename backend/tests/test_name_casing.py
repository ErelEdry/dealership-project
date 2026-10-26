"""Item 7: make/model keep their real casing; filters match case-insensitively."""

import csv
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import vehicles
from app.core.database import get_db
from app.models.inventory import VehicleInventory
from app.schemas.search import SearchRequest
from scripts.fix_name_casing import canonical_names, fix_text, mangled_forms, plan_updates

CSV = Path(__file__).resolve().parents[2] / "data" / "sample" / "inventory.csv"


# ── the data-fix script's pure logic ─────────────────────────
@pytest.fixture(scope="module")
def csv_names():
    with open(CSV, newline="", encoding="utf-8-sig") as f:
        return canonical_names(list(csv.DictReader(f)))


def test_csv_has_the_real_names(csv_names):
    makes_models = set(csv_names.values())
    for name in [("BMW", "X5"), ("Toyota", "RAV4"), ("Honda", "CR-V"), ("Mazda", "CX-5")]:
        assert name in makes_models


def test_mangled_forms_from_the_csv(csv_names):
    fixes = mangled_forms(csv_names.values())
    for wrong, right in [("Bmw", "BMW"), ("Rav4", "RAV4"), ("Cr-V", "CR-V"), ("Cx-5", "CX-5"),
                         ("Cx-30", "CX-30"), ("Gle", "GLE"), ("Xc60", "XC60"), ("Xc90", "XC90")]:
        assert fixes[wrong] == right
    # names .title() leaves alone are never rewritten
    assert "Toyota" not in fixes and "Mercedes-Benz" not in fixes


FIXES = {"Bmw": "BMW", "Rav4": "RAV4", "Cr-V": "CR-V", "Gle": "GLE"}


@pytest.mark.parametrize("before,after", [
    ("The 2019 Bmw X5 rivals the Mercedes-Benz Gle.", "The 2019 BMW X5 rivals the Mercedes-Benz GLE."),
    ("Toyota Rav4 or Honda Cr-V?", "Toyota RAV4 or Honda CR-V?"),
    ("Bmwx and Gleaming stay as they are", "Bmwx and Gleaming stay as they are"),  # whole words only
    ("Cr-Vs and Rav4-like", "Cr-Vs and Rav4-like"),
    (None, None),
])
def test_fix_text(before, after):
    assert fix_text(before, FIXES) == after


def _pg_row(**kw):
    row = dict(vin="VIN1", make="Bmw", model="X5", ai_summary="A Bmw X5.",
               embedding_doc="2019 Bmw X5", ai_selling_points=["Bmw quality"],
               ai_comparable_models='["Audi Q5", "Mercedes-Benz Gle"]')
    row.update(kw)
    return row


def test_plan_fixes_names_and_ai_text():
    [u] = plan_updates([_pg_row()], {"VIN1": ("BMW", "X5")}, FIXES)
    assert (u["make"], u["model"], u["renamed"]) == ("BMW", "X5", True)
    assert u["ai_summary"] == "A BMW X5."
    assert u["embedding_doc"] == "2019 BMW X5"
    assert u["ai_selling_points"] == ["BMW quality"]
    assert u["ai_comparable_models"] == ["Audi Q5", "Mercedes-Benz GLE"]


def test_plan_is_idempotent():
    [u] = plan_updates([_pg_row()], {"VIN1": ("BMW", "X5")}, FIXES)
    fixed = {k: v for k, v in u.items() if k != "renamed"}
    assert plan_updates([fixed], {"VIN1": ("BMW", "X5")}, FIXES) == []


def test_row_missing_from_csv_keeps_its_name():
    [u] = plan_updates([_pg_row(vin="NOT-IN-CSV")], {}, FIXES)
    assert (u["make"], u["renamed"]) == ("Bmw", False)    # only AI text fixed
    assert u["ai_summary"] == "A BMW X5."


# ── Qdrant search filter: make matches the lower-cased make_key ──
@pytest.mark.parametrize("make", ["BMW", "bmw", " Bmw "])
def test_search_make_filter_is_case_insensitive(search_route, make):
    [cond] = search_route._build_filter(
        SearchRequest(query="suv", make=make, stock_status="all")).must
    assert (cond.key, cond.match.value) == ("make_key", "bmw")


# ── PostgreSQL listing filter: lower(make) = lower(value) ────
class _SyncAsAsync:
    """Run the route's two awaited calls on a real (sync) SQLite session."""

    def __init__(self, session):
        self.s = session

    async def scalar(self, stmt):
        return self.s.scalar(stmt)

    async def execute(self, stmt):
        return self.s.execute(stmt)


@pytest.fixture
def listing():
    # TestClient runs the app on another thread: share one in-memory connection.
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    VehicleInventory.__table__.create(engine)
    session = Session(engine)
    for vin, make, model in [("V1", "BMW", "X5"), ("V2", "Toyota", "RAV4")]:
        session.add(VehicleInventory(vin=vin, dealer_id="D", make=make, model=model,
                                     year=2020, mileage=1, price=20000.0,
                                     stock_status="available"))
    session.commit()

    app = FastAPI()
    app.include_router(vehicles.router, prefix="/api/vehicles")

    async def _get_db():
        yield _SyncAsAsync(session)

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    session.close()


@pytest.mark.parametrize("make", ["BMW", "bmw", "Bmw"])
def test_listing_make_filter_is_case_insensitive(listing, make):
    body = listing.get("/api/vehicles", params={"make": make}).json()
    assert body["total"] == 1
    assert (body["results"][0]["make"], body["results"][0]["model"]) == ("BMW", "X5")
