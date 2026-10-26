"""
Phase 2 — Full ETL Pipeline
-----------------------------
Orchestrates the complete flow:
  CSV → Validate → Enrich (Groq/llama) → Embed (FastEmbed/local) → Qdrant + PostgreSQL

Re-runs are incremental: vehicles whose CSV specs are unchanged (content_hash)
are skipped; changed ones are resynced from their stored AI fields with a local
re-embed and no LLM call; only new/unindexed vehicles (or --force) hit Groq.
Invalid rows go to the validation_errors quarantine table.

Usage:
    # Test: enrich first 10 vehicles only
    docker compose exec api python -m app.etl.pipeline --limit 10

    # Full run: all vehicles
    docker compose exec api python -m app.etl.pipeline

    # Re-run from scratch (re-enrich everything)
    docker compose exec api python -m app.etl.pipeline --force

    # Resume a partial re-run: only vehicles enriched before a date
    docker compose exec api python -m app.etl.pipeline --reenrich-before 2026-08-17
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog
from groq import RateLimitError
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from tenacity import RetryError

from app.core.cache import clear_search_cache
from app.core.config import settings
from app.etl.embedder import embed_vehicle, ensure_collection
from app.etl.enricher import enrich_vehicle
from app.etl.ingestor import read_csv, validate_row
from app.models.inventory import ValidationErrorLog
from app.schemas.inventory import EnrichedVehicle, ValidationError

log = structlog.get_logger()


def _is_rate_limit(exc: BaseException) -> bool:
    """True if the error is (or wraps) a Groq 429 rate-limit / quota error.

    Enrichment is wrapped by tenacity, so a persistent 429 surfaces as a
    RetryError around the original RateLimitError — unwrap one level.
    """
    if isinstance(exc, RetryError) and exc.last_attempt is not None:
        exc = exc.last_attempt.exception() or exc
    return isinstance(exc, RateLimitError)

# ── Sync DB engine for pipeline CLI ─────────────────────────
_sync_url = settings.database_url.replace(
    "postgresql+asyncpg", "postgresql+psycopg2"
)
_engine = create_engine(_sync_url, pool_pre_ping=True)

# ── Delay between Groq enrichment calls ──────────────────────
# Groq's free tier is far more permissive than the old Gemini 15 RPM limit
# this was originally sized for. Raise if you start seeing 429s.
ENRICH_DELAY  = 2.0   # seconds between enrichment calls  (~30 RPM)


# ── Database helpers ─────────────────────────────────────────

_AI_FIELDS = (
    "ai_lifestyle_tags", "ai_segment", "ai_summary",
    "ai_selling_points", "ai_comparable_models", "ai_confidence",
)
_AI_LIST_FIELDS = ("ai_lifestyle_tags", "ai_selling_points", "ai_comparable_models")
_JSON_COLUMNS = {"features", "images", *_AI_LIST_FIELDS}


def load_indexed(session: Session, vin: str):
    """The stored state of a vehicle that is enriched *and* has a Qdrant point.

    Returns a mapping (content_hash, enriched_at, ai_* fields) or None. A row
    with no vector_id (its embedding failed) must not count as done, or it
    would stay in PostgreSQL forever without ever reaching search.
    """
    return session.execute(
        text("SELECT content_hash, enriched_at, " + ", ".join(_AI_FIELDS)
             + " FROM vehicle_inventory WHERE vin = :vin "
             "AND enriched_at IS NOT NULL AND vector_id IS NOT NULL"),
        {"vin": vin}
    ).mappings().fetchone()


def is_indexed(session: Session, vin: str) -> bool:
    """True if the vehicle is enriched *and* has a Qdrant point."""
    return load_indexed(session, vin) is not None


def stored_enrichment(stored) -> dict:
    """The ai_* fields of a load_indexed() row, JSON lists decoded."""
    ai = {f: stored[f] for f in _AI_FIELDS}
    for f in _AI_LIST_FIELDS:
        if isinstance(ai[f], str):
            ai[f] = json.loads(ai[f])
        ai[f] = ai[f] or []
    return ai


def needs_reenrich(session: Session, vin: str, cutoff: str) -> bool:
    """True if the vehicle should be re-enriched under --reenrich-before.

    Returns True when the row is new, never enriched, has no Qdrant point, or
    was last enriched *before* `cutoff` (a date/timestamp string). Rows already
    enriched and indexed on/after the cutoff are left alone — this is what lets
    a partial re-run resume without redoing rows that are already on the new model.
    """
    row = session.execute(
        text("SELECT 1 FROM vehicle_inventory "
             "WHERE vin = :vin AND enriched_at IS NOT NULL AND enriched_at >= :cutoff "
             "AND vector_id IS NOT NULL"),
        {"vin": vin, "cutoff": cutoff}
    ).fetchone()
    return row is None


def quarantine(session: Session, error: ValidationError) -> bool:
    """Record an invalid row in validation_errors. Returns True if newly added.

    Re-running the pipeline over the same CSV must not pile up copies, so a row
    already quarantined with the same file, row number and error is skipped.
    """
    exists = session.scalar(select(ValidationErrorLog.id).where(
        ValidationErrorLog.source_file == error.source_file,
        ValidationErrorLog.row_number == error.row_number,
        ValidationErrorLog.error_detail == error.error_detail,
    ).limit(1))
    if exists is not None:
        return False
    session.add(ValidationErrorLog(
        raw_row=error.raw_row,
        error_detail=error.error_detail,
        source_file=error.source_file,
        row_number=error.row_number,
        created_at=error.created_at,
    ))
    session.commit()
    return True


def upsert_vehicle(session: Session, vehicle: EnrichedVehicle, point_id: str) -> None:
    """Insert or update a fully enriched vehicle in PostgreSQL.

    On conflict every column is overwritten (spec columns included), so
    PostgreSQL always matches the CSV row and the Qdrant payload written from it.
    """
    enriched_at = vehicle.enriched_at or datetime.now(timezone.utc)
    data = {
        "vin":                  vehicle.vin,
        "dealer_id":            vehicle.dealer_id,
        "stock_id":             vehicle.stock_id,
        "make":                 vehicle.make,
        "model":                vehicle.model,
        "year":                 vehicle.year,
        "trim":                 vehicle.trim,
        "body_type":            vehicle.body_type,
        "fuel_type":            vehicle.fuel_type,
        "transmission":         vehicle.transmission,
        "engine":               vehicle.engine,
        "seats":                vehicle.seats,
        "doors":                vehicle.doors,
        "mileage":              vehicle.mileage,
        "price":                vehicle.price,
        "acquisition_cost":     vehicle.acquisition_cost,
        "condition":            vehicle.condition,
        "colour_ext":           vehicle.colour_ext,
        "colour_int":           vehicle.colour_int,
        "features":             json.dumps(vehicle.features),
        "images":               json.dumps(vehicle.images),
        "stock_status":         vehicle.stock_status,
        "arrived_date":         vehicle.arrived_date,
        "ai_lifestyle_tags":    json.dumps(vehicle.ai_lifestyle_tags),
        "ai_segment":           vehicle.ai_segment,
        "ai_summary":           vehicle.ai_summary,
        "ai_selling_points":    json.dumps(vehicle.ai_selling_points),
        "ai_comparable_models": json.dumps(vehicle.ai_comparable_models),
        "ai_confidence":        vehicle.ai_confidence,
        "content_hash":         vehicle.content_hash_value,
        "embedding_doc":        vehicle.embedding_doc,
        "embedding_model":      settings.embedding_model,
        "vector_id":            point_id,
        "needs_review":         vehicle.needs_review,
        # A resync keeps the original enrichment time (no LLM call was made),
        # so --reenrich-before still sees the vehicle's real enrichment age.
        "enriched_at":          enriched_at.isoformat(),
        "source_file":          vehicle.source_file,
    }
    session.execute(text(upsert_sql(list(data))), data)
    session.commit()


def upsert_sql(columns: list[str]) -> str:
    """INSERT … ON CONFLICT (vin) DO UPDATE that overwrites every given column.

    Built from one column list so the INSERT and the UPDATE can't drift apart
    (the old hand-written UPDATE silently skipped every spec column).
    """
    values = ", ".join(f"CAST(:{c} AS json)" if c in _JSON_COLUMNS else f":{c}"
                       for c in columns)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "vin")
    return (f"INSERT INTO vehicle_inventory ({', '.join(columns)}) VALUES ({values}) "
            f"ON CONFLICT (vin) DO UPDATE SET {updates}, updated_at = CURRENT_TIMESTAMP")


# ── Main pipeline ────────────────────────────────────────────

async def run_pipeline(
    csv_path: str,
    limit: int | None = None,
    force: bool = False,
    reenrich_before: str | None = None,
) -> None:
    """
    Full enrichment pipeline.

    csv_path        : path to the inventory CSV
    limit           : stop after N vehicles enriched or resynced (None = all)
    force           : re-enrich even vehicles that already have enriched_at set
    reenrich_before : re-enrich only vehicles last enriched before this date
                      (skips newer ones); ignored when force is set
    """
    log.info("pipeline_start", csv=csv_path, limit=limit, force=force)

    # Ensure Qdrant collection exists with correct dimensions
    ensure_collection()

    source_file = Path(csv_path).name
    processed = resynced = skipped = failed = quarantined = needs_review_count = 0
    rate_limited = False
    start_time = time.time()

    with Session(_engine) as session:
        for row_number, row in read_csv(csv_path):

            # ── 1. Validate raw row (invalid → quarantine) ───
            vehicle, error = validate_row(row_number, row, source_file)
            if error:
                is_new = quarantine(session, error)
                log.warning("validation_quarantined", row=row_number,
                            new=is_new, detail=error.error_detail)
                quarantined += 1
                continue

            # ── 2. Decide: skip, free resync, or (re)enrich ──
            # Enrich (LLM) when forced, new, unindexed, or older than the
            # --reenrich-before cutoff. Otherwise compare the CSV specs with the
            # stored hash: unchanged → skip; changed → resync without the LLM.
            stored = None if force else load_indexed(session, vehicle.vin)
            enrich = stored is None or (
                reenrich_before is not None
                and needs_reenrich(session, vehicle.vin, reenrich_before))
            content_hash = vehicle.content_hash()
            if not enrich and stored["content_hash"] == content_hash:
                skipped += 1
                continue

            label = (f"[{processed + resynced + 1}{'/' + str(limit) if limit else ''}] "
                     f"{vehicle.year} {vehicle.make} {vehicle.model}")
            if enrich:
                # ── 3a. Enrich with Groq ─────────────────────
                print(f"{label}: enriching...", end=" ", flush=True)
                try:
                    enrichment = await enrich_vehicle(vehicle)
                except Exception as e:
                    # A quota/rate-limit 429 will fail every subsequent call too —
                    # stop cleanly so progress so far is kept and the run is resumable.
                    if _is_rate_limit(e):
                        print("✗ rate limit / daily quota reached")
                        log.warning("pipeline_rate_limited", vin=vehicle.vin, error=str(e))
                        rate_limited = True
                        break
                    # Any other error: skip this one vehicle and keep going.
                    print("✗ enrichment failed")
                    log.error("enrichment_skipped", vin=vehicle.vin, error=str(e))
                    failed += 1
                    await asyncio.sleep(ENRICH_DELAY)
                    continue

                if enrichment is None:
                    print("✗ enrichment failed")
                    failed += 1
                    continue
                ai = {f: getattr(enrichment, f) for f in _AI_FIELDS}
                enriched_at = datetime.now(timezone.utc)
            else:
                # ── 3b. Specs changed in the CSV: free resync ─
                # Keep the stored AI fields; only PostgreSQL, the Qdrant payload
                # and the (local) embedding are refreshed. No LLM tokens spent.
                print(f"{label}: specs changed, resyncing...", end=" ", flush=True)
                ai = stored_enrichment(stored)
                enriched_at = stored["enriched_at"]

            # ── 4. Build EnrichedVehicle ─────────────────────
            ev = EnrichedVehicle(**{
                **vehicle.model_dump(),
                **ai,
                "content_hash_value":   content_hash,
                "needs_review":         (ai["ai_confidence"] or 0) < 0.7,
                "enriched_at":          enriched_at,
                "embedding_model":      settings.embedding_model,
            })
            ev.embedding_doc = ev.build_embedding_document()

            # ── 5. Embed + upsert to Qdrant ──────────────────
            point_id = await embed_vehicle(ev)
            if point_id is None:
                # Don't record it as enriched without a vector: leave the row
                # as it was so the next run picks this vehicle up again.
                print("✗ embedding failed")
                log.error("embedding_skipped", vin=vehicle.vin)
                failed += 1
                if enrich:
                    await asyncio.sleep(ENRICH_DELAY)
                continue

            # ── 6. Write to PostgreSQL ───────────────────────
            upsert_vehicle(session, ev, point_id)

            if enrich:
                status = "⚠ low confidence" if ev.needs_review else "✓"
                print(f"{status}  [{ev.ai_segment}]  confidence={ev.ai_confidence:.2f}")
                if ev.needs_review:
                    needs_review_count += 1
                processed += 1
            else:
                print("✓ resynced")
                resynced += 1

            # ── 7. Check limit ───────────────────────────────
            if limit and processed + resynced >= limit:
                print(f"\nLimit of {limit} reached — stopping.")
                break

            # ── 8. Rate limit pause (only after an LLM call) ──
            if enrich:
                await asyncio.sleep(ENRICH_DELAY)

    # Search results cached before this run would be stale for up to the TTL.
    if processed or resynced:
        clear_search_cache()

    elapsed = time.time() - start_time
    header = "Pipeline stopped (rate limit)" if rate_limited else "Pipeline complete"
    resume_note = (
        "\n  ⚠ Stopped on Groq quota — re-run the same command later to resume\n"
        "    (already-enriched vehicles are skipped unless --force)."
        if rate_limited else ""
    )
    print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {header}
  Processed   : {processed} (LLM-enriched)
  Resynced    : {resynced} (specs changed, no LLM call)
  Skipped     : {skipped} (unchanged)
  Failed      : {failed}
  Quarantined : {quarantined} (invalid rows → validation_errors)
  Needs review: {needs_review_count} (confidence < 0.7)
  Time        : {elapsed:.1f}s{resume_note}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━""")

    log.info("pipeline_complete",
             processed=processed, resynced=resynced, skipped=skipped,
             failed=failed, quarantined=quarantined, needs_review=needs_review_count,
             rate_limited=rate_limited, elapsed_s=round(elapsed, 1))


# ── CLI entry point ──────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the vehicle enrichment pipeline")
    parser.add_argument(
        "--csv",    default="data/sample/inventory.csv",
        help="Path to inventory CSV"
    )
    parser.add_argument(
        "--limit",  type=int, default=None,
        help="Only process the first N vehicles (useful for testing)"
    )
    parser.add_argument(
        "--force",  action="store_true",
        help="Re-enrich vehicles that are already in the database"
    )
    parser.add_argument(
        "--reenrich-before", default=None, metavar="DATE",
        help="Re-enrich only vehicles last enriched before DATE (e.g. 2026-08-17), "
             "skipping newer ones. Use to resume a partial re-run without redoing "
             "already-migrated rows."
    )
    args = parser.parse_args()

    asyncio.run(run_pipeline(args.csv, args.limit, args.force, args.reenrich_before))
