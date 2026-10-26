"""Unit tests for the ETL pipeline's control flow and skip checks (no I/O).

app.etl.embedder loads the ~130 MB FastEmbed model at import and the enricher
builds a Groq client, so both are replaced with stub modules before the
pipeline is imported. The skip-check SQL runs against an in-memory SQLite table.
"""

import asyncio
import importlib
import sys
import types

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.models.inventory import ValidationErrorLog

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


@pytest.fixture
def pipeline(monkeypatch):
    """Import app.etl.pipeline with stubbed embedder/enricher and a SQLite DB."""
    embedder = types.ModuleType("app.etl.embedder")
    embedder.ensure_collection = lambda: None
    embedder.embed_vehicle = None          # set per test via `embed`
    enricher = types.ModuleType("app.etl.enricher")
    enricher.enrich_vehicle = None
    monkeypatch.setitem(sys.modules, "app.etl.embedder", embedder)
    monkeypatch.setitem(sys.modules, "app.etl.enricher", enricher)
    monkeypatch.delitem(sys.modules, "app.etl.pipeline", raising=False)
    mod = importlib.import_module("app.etl.pipeline")
    monkeypatch.delitem(sys.modules, "app.etl.pipeline")   # don't leak the stubbed copy

    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE vehicle_inventory ("
                       "vin TEXT PRIMARY KEY, enriched_at TEXT, vector_id TEXT)"))
    ValidationErrorLog.__table__.create(engine)
    monkeypatch.setattr(mod, "_engine", engine)
    monkeypatch.setattr(mod, "ENRICH_DELAY", 0)

    async def _enrich(vehicle):
        return ENRICHMENT
    monkeypatch.setattr(mod, "enrich_vehicle", _enrich)
    monkeypatch.setattr(mod, "read_csv", lambda path: iter([(2, dict(ROW))]))

    mod.upserts = []
    monkeypatch.setattr(mod, "upsert_vehicle",
                        lambda session, ev, point_id: mod.upserts.append((ev.vin, point_id)))
    return mod


def _embed(pipeline, monkeypatch, point_id):
    async def _fake(ev):
        return point_id
    monkeypatch.setattr(pipeline, "embed_vehicle", _fake)


def _insert(pipeline, vin, enriched_at, vector_id):
    with pipeline._engine.begin() as c:
        c.execute(text("INSERT INTO vehicle_inventory VALUES (:v, :e, :p)"),
                  {"v": vin, "e": enriched_at, "p": vector_id})


def _run(pipeline, **kw):
    asyncio.run(pipeline.run_pipeline("inventory.csv", **kw))


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
    assert pipeline.upserts == [(ROW["vin"], "123")]


def test_legacy_row_without_vector_is_picked_up(pipeline, monkeypatch):
    # A row written by the old code: enriched_at set, vector_id NULL.
    _insert(pipeline, ROW["vin"], "2026-08-01T00:00:00+00:00", None)
    _embed(pipeline, monkeypatch, "123")
    _run(pipeline)
    assert pipeline.upserts == [(ROW["vin"], "123")]


def test_indexed_vehicle_is_skipped(pipeline, monkeypatch, capsys):
    _insert(pipeline, ROW["vin"], "2026-08-01T00:00:00+00:00", "123")
    _embed(pipeline, monkeypatch, "123")
    _run(pipeline)
    assert pipeline.upserts == []
    assert "Skipped     : 1" in capsys.readouterr().out


# ── skip-check helpers ───────────────────────────────────────
@pytest.mark.parametrize("enriched_at,vector_id,expected", [
    ("2026-08-01", "123", True),
    ("2026-08-01", None, False),    # embedding failed
    (None, "123", False),           # never enriched
])
def test_is_indexed(pipeline, enriched_at, vector_id, expected):
    _insert(pipeline, "VIN1", enriched_at, vector_id)
    with Session(pipeline._engine) as s:
        assert pipeline.is_indexed(s, "VIN1") is expected
        assert pipeline.is_indexed(s, "MISSING") is False


@pytest.mark.parametrize("enriched_at,vector_id,expected", [
    ("2026-09-01", "123", False),   # done after the cutoff → leave alone
    ("2026-07-01", "123", True),    # done before the cutoff → re-enrich
    ("2026-09-01", None, True),     # after the cutoff but never indexed
])
def test_needs_reenrich(pipeline, enriched_at, vector_id, expected):
    _insert(pipeline, "VIN1", enriched_at, vector_id)
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
    assert pipeline.upserts == [(ROW["vin"], "123")]   # valid row still processed
    assert "Quarantined : 1" in capsys.readouterr().out


def test_rerun_does_not_duplicate_quarantine(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, "read_csv",
                        lambda path: iter([(7, dict(BROKEN_ROW))]))
    _run(pipeline)
    _run(pipeline)
    assert len(_quarantine_rows(pipeline)) == 1
