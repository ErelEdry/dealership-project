"""Unit tests for the ETL pipeline's control flow and DB helpers (no I/O).

app.etl.embedder loads the ~130 MB FastEmbed model at import and the enricher
builds a Groq client, so both are replaced with stub modules before the
pipeline is imported. The DB helpers run against in-memory SQLite tables built
from the real ORM models.
"""

import asyncio
import importlib
import sys
import types
from datetime import datetime

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.models.inventory import ValidationErrorLog, VehicleInventory
from app.schemas.inventory import EnrichedVehicle, RawVehicle

ROW = {
    "vin": "SYND21A267D28FA2F", "dealer_id": "DEALER_001", "stock_id": "S00001",
    "make": "Fiat", "model": "Panda", "year": "2015", "body_type": "hatchback",
    "fuel_type": "hybrid", "transmission": "automatic", "seats": "5",
    "mileage": "16300", "price": "5250.0", "acquisition_cost": "4252.5",
    "condition": "used", "stock_status": "available", "arrived_date": "2017/08/01",
}

BROKEN_ROW = {**ROW, "vin": "SYNBROKEN00000001", "year": "not-a-year"}

ENRICHMENT = types.SimpleNamespace(
    ai_lifestyle_tags=["city"], ai_segment="City Car",
    ai_summary="A small city car.", ai_selling_points=["cheap to run"],
    ai_comparable_models=["Fiat 500"], ai_confidence=0.9,
)

STORED_AT = datetime(2026, 8, 1, 9, 30)


def _hash(row):
    return RawVehicle(source_file="inventory.csv", **row).content_hash()


@pytest.fixture
def pipeline(monkeypatch):
    """Import app.etl.pipeline with stubbed embedder/enricher and a SQLite DB."""
    embedder = types.ModuleType("app.etl.embedder")
    embedder.ensure_collection = lambda: None
    embedder.embed_vehicle = None          # set per test via _embed
    enricher = types.ModuleType("app.etl.enricher")
    enricher.enrich_vehicle = None
    monkeypatch.setitem(sys.modules, "app.etl.embedder", embedder)
    monkeypatch.setitem(sys.modules, "app.etl.enricher", enricher)
    monkeypatch.delitem(sys.modules, "app.etl.pipeline", raising=False)
    mod = importlib.import_module("app.etl.pipeline")
    monkeypatch.delitem(sys.modules, "app.etl.pipeline")   # don't leak the stubbed copy

    engine = create_engine("sqlite://")
    VehicleInventory.__table__.create(engine)
    ValidationErrorLog.__table__.create(engine)
    monkeypatch.setattr(mod, "_engine", engine)
    monkeypatch.setattr(mod, "ENRICH_DELAY", 0)

    mod.enrich_calls = []

    async def _enrich(vehicle):
        mod.enrich_calls.append(vehicle.vin)
        return ENRICHMENT
    monkeypatch.setattr(mod, "enrich_vehicle", _enrich)
    monkeypatch.setattr(mod, "read_csv", lambda path: iter([(2, dict(ROW))]))

    mod.cache_clears = []
    monkeypatch.setattr(mod, "clear_search_cache", lambda: mod.cache_clears.append(1))

    mod.real_upsert_vehicle = mod.upsert_vehicle
    mod.upserts = []
    monkeypatch.setattr(mod, "upsert_vehicle",
                        lambda session, ev, point_id: mod.upserts.append((ev, point_id)))
    return mod


def _embed(pipeline, monkeypatch, point_id):
    async def _fake(ev):
        return point_id
    monkeypatch.setattr(pipeline, "embed_vehicle", _fake)


def _insert(pipeline, vin=ROW["vin"], enriched_at=STORED_AT, vector_id="123",
            content_hash=None):
    """A previously enriched row, as earlier runs left it."""
    if isinstance(enriched_at, str):
        enriched_at = datetime.fromisoformat(enriched_at)
    with Session(pipeline._engine) as s:
        s.add(VehicleInventory(
            vin=vin, dealer_id="DEALER_001", make="Fiat", model="Panda", year=2015,
            mileage=16300, price=5250.0, stock_status="available",
            enriched_at=enriched_at, vector_id=vector_id, content_hash=content_hash,
            ai_lifestyle_tags=["stored tag"], ai_segment="City Car",
            ai_summary="Stored summary.", ai_selling_points=["stored point"],
            ai_comparable_models=["Fiat 500"], ai_confidence=0.8,
        ))
        s.commit()


def _run(pipeline, **kw):
    asyncio.run(pipeline.run_pipeline("inventory.csv", **kw))


def _upserted_vins(pipeline):
    return [(ev.vin, point_id) for ev, point_id in pipeline.upserts]


# ── item 6: an embedding failure must not mark the vehicle done ─
def test_embedding_failure_writes_nothing(pipeline, monkeypatch, capsys):
    _embed(pipeline, monkeypatch, None)
    _run(pipeline)
    assert pipeline.upserts == []
    out = capsys.readouterr().out
    assert "embedding failed" in out
    assert "Failed      : 1" in out


def test_vehicle_is_retried_after_an_embedding_failure(pipeline, monkeypatch):
    _embed(pipeline, monkeypatch, None)
    _run(pipeline)
    _embed(pipeline, monkeypatch, "123")
    _run(pipeline)
    assert _upserted_vins(pipeline) == [(ROW["vin"], "123")]


def test_legacy_row_without_vector_is_picked_up(pipeline, monkeypatch):
    # A row written by the old code: enriched_at set, vector_id NULL.
    _insert(pipeline, vector_id=None, content_hash=_hash(ROW))
    _embed(pipeline, monkeypatch, "123")
    _run(pipeline)
    assert _upserted_vins(pipeline) == [(ROW["vin"], "123")]
    assert pipeline.enrich_calls == [ROW["vin"]]


# ── item 9: skip only unchanged vehicles; resync changed ones for free ─
def test_unchanged_vehicle_is_skipped(pipeline, monkeypatch, capsys):
    _insert(pipeline, content_hash=_hash(ROW))
    _embed(pipeline, monkeypatch, "123")
    _run(pipeline)
    assert pipeline.upserts == []
    assert pipeline.enrich_calls == []
    assert "Skipped     : 1" in capsys.readouterr().out


def test_changed_specs_resync_without_llm(pipeline, monkeypatch, capsys):
    _insert(pipeline, content_hash="stale-hash-from-an-older-csv")
    _embed(pipeline, monkeypatch, "123")
    _run(pipeline)

    assert pipeline.enrich_calls == []                 # no Groq tokens spent
    [(ev, point_id)] = pipeline.upserts
    assert point_id == "123"
    assert ev.content_hash_value == _hash(ROW)         # hash now matches the CSV
    assert ev.ai_summary == "Stored summary."          # stored enrichment kept
    assert ev.ai_lifestyle_tags == ["stored tag"]
    assert ev.enriched_at == STORED_AT                 # enrichment age unchanged
    assert "Stored summary." in ev.embedding_doc       # re-embedded with it
    assert "Resynced    : 1" in capsys.readouterr().out


def test_force_reenriches_unchanged_vehicle(pipeline, monkeypatch):
    _insert(pipeline, content_hash=_hash(ROW))
    _embed(pipeline, monkeypatch, "123")
    _run(pipeline, force=True)
    assert pipeline.enrich_calls == [ROW["vin"]]
    [(ev, _)] = pipeline.upserts
    assert ev.ai_summary == ENRICHMENT.ai_summary


def test_reenrich_before_resyncs_recent_changed_rows(pipeline, monkeypatch):
    # Enriched after the cutoff (no LLM needed) but its specs changed since.
    _insert(pipeline, enriched_at="2026-09-01", content_hash="stale")
    _embed(pipeline, monkeypatch, "123")
    _run(pipeline, reenrich_before="2026-08-17")
    assert pipeline.enrich_calls == []
    assert len(pipeline.upserts) == 1


def test_reenrich_before_reenriches_old_rows(pipeline, monkeypatch):
    _insert(pipeline, enriched_at="2026-07-01", content_hash=_hash(ROW))
    _embed(pipeline, monkeypatch, "123")
    _run(pipeline, reenrich_before="2026-08-17")
    assert pipeline.enrich_calls == [ROW["vin"]]


@pytest.mark.parametrize("field,value", [
    ("make", "Abarth"), ("model", "500"), ("year", "2016"), ("seats", "4"),
    ("mileage", "20000"), ("price", "5500"), ("acquisition_cost", "4000"),
    ("condition", "demo"), ("body_type", "coupe"), ("fuel_type", "petrol"),
    ("stock_status", "sold"), ("arrived_date", "2018/01/01"),
])
def test_content_hash_covers_every_spec_field(field, value):
    assert _hash({**ROW, field: value}) != _hash(ROW)


def test_content_hash_ignores_provenance():
    a = RawVehicle(source_file="a.csv", **ROW)
    b = RawVehicle(source_file="b.csv", **ROW)
    assert a.content_hash() == b.content_hash()


def test_upsert_overwrites_spec_columns(pipeline):
    def ev(row, source_file):
        return EnrichedVehicle(**{
            **RawVehicle(source_file=source_file, **row).model_dump(),
            "ai_segment": "City Car", "ai_confidence": 0.9,
            "content_hash_value": _hash(row), "enriched_at": STORED_AT,
        })

    changed = {**ROW, "make": "Abarth", "model": "595", "year": "2016",
               "mileage": "20000", "seats": "4", "condition": "demo",
               "acquisition_cost": "4000"}
    with Session(pipeline._engine) as s:
        pipeline.real_upsert_vehicle(s, ev(ROW, "old.csv"), "123")
        pipeline.real_upsert_vehicle(s, ev(changed, "new.csv"), "123")
        row = s.execute(text(
            "SELECT make, model, year, mileage, seats, condition, acquisition_cost, "
            "content_hash, source_file FROM vehicle_inventory")).one()
    assert tuple(row) == ("Abarth", "595", 2016, 20000, 4, "demo", 4000.0,
                          _hash(changed), "new.csv")


def test_upsert_sql_updates_every_inserted_column(pipeline):
    cols = ["vin", "make", "year", "features", "content_hash", "source_file"]
    sql = pipeline.upsert_sql(cols)
    insert, update = sql.split("DO UPDATE SET")
    for c in cols[1:]:
        assert f"{c} = EXCLUDED.{c}" in update
    assert "vin = EXCLUDED" not in update
    assert "CAST(:features AS json)" in insert


# ── skip-check helpers ───────────────────────────────────────
@pytest.mark.parametrize("enriched_at,vector_id,expected", [
    (STORED_AT, "123", True),
    (STORED_AT, None, False),       # embedding failed
    (None, "123", False),           # never enriched
])
def test_is_indexed(pipeline, enriched_at, vector_id, expected):
    _insert(pipeline, vin="VIN1", enriched_at=enriched_at, vector_id=vector_id)
    with Session(pipeline._engine) as s:
        assert pipeline.is_indexed(s, "VIN1") is expected
        assert pipeline.is_indexed(s, "MISSING") is False


@pytest.mark.parametrize("enriched_at,vector_id,expected", [
    ("2026-09-01", "123", False),   # done after the cutoff → leave alone
    ("2026-07-01", "123", True),    # done before the cutoff → re-enrich
    ("2026-09-01", None, True),     # after the cutoff but never indexed
])
def test_needs_reenrich(pipeline, enriched_at, vector_id, expected):
    _insert(pipeline, vin="VIN1", enriched_at=enriched_at, vector_id=vector_id)
    with Session(pipeline._engine) as s:
        assert pipeline.needs_reenrich(s, "VIN1", "2026-08-17") is expected


# ── item 10: invalid rows are quarantined ────────────────────
def _quarantine_rows(pipeline):
    with Session(pipeline._engine) as s:
        return s.scalars(select(ValidationErrorLog)).all()


def test_broken_row_is_quarantined(pipeline, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "read_csv",
                        lambda path: iter([(7, dict(BROKEN_ROW)), (8, dict(ROW))]))
    _embed(pipeline, monkeypatch, "123")
    _run(pipeline)

    [q] = _quarantine_rows(pipeline)
    assert q.raw_row == BROKEN_ROW            # original row kept as received
    assert q.row_number == 7
    assert q.source_file == "inventory.csv"
    assert "year" in q.error_detail
    assert _upserted_vins(pipeline) == [(ROW["vin"], "123")]   # valid row still processed
    assert "Quarantined : 1" in capsys.readouterr().out


def test_rerun_does_not_duplicate_quarantine(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, "read_csv",
                        lambda path: iter([(7, dict(BROKEN_ROW))]))
    _run(pipeline)
    _run(pipeline)
    assert len(_quarantine_rows(pipeline)) == 1


# ── item 15: a run that wrote data clears the search cache ───
def test_search_cache_cleared_after_writes(pipeline, monkeypatch):
    _embed(pipeline, monkeypatch, "123")
    _run(pipeline)
    assert pipeline.cache_clears == [1]


def test_search_cache_kept_when_nothing_changed(pipeline, monkeypatch):
    _insert(pipeline, content_hash=_hash(ROW))
    _embed(pipeline, monkeypatch, "123")
    _run(pipeline)
    assert pipeline.cache_clears == []
