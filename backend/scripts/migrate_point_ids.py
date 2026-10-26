"""
One-time migration — Qdrant point IDs
--------------------------------------
Points written before the embedder.py hash fix used abs(hash(vin)), which
Python randomises per process. This re-keys every existing point to the
deterministic vin_to_point_id() value so that re-running the pipeline
updates points in place instead of inserting duplicates.

Vectors are copied as-is — nothing is re-embedded.

Usage:
    docker compose exec api python -m scripts.migrate_point_ids [--apply]

Without --apply it runs as a dry run and changes nothing.
"""

from __future__ import annotations

import argparse

from qdrant_client.models import PointStruct
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.cache import clear_search_cache
from app.core.config import settings
from app.etl.embedder import _qdrant, vin_to_point_id

BATCH = 200

_sync_url = settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
_engine = create_engine(_sync_url, pool_pre_ping=True)


def main(apply: bool) -> None:
    with Session(_engine) as session:
        rows = session.execute(
            text("SELECT vin, vector_id FROM vehicle_inventory WHERE vector_id IS NOT NULL")
        ).fetchall()

    # vin -> (old_id, new_id), skipping anything already on the new scheme
    pending = []
    for vin, old_id in rows:
        new_id = vin_to_point_id(vin)
        if int(old_id) != new_id:
            pending.append((vin, int(old_id), new_id))

    print(f"rows with a vector_id : {len(rows)}")
    print(f"needing re-key        : {len(pending)}")
    if not pending:
        print("nothing to do — all point IDs already deterministic.")
        return

    if not apply:
        print("\nDRY RUN — re-run with --apply to perform the migration.")
        for vin, old, new in pending[:3]:
            print(f"  {vin}  {old} -> {new}")
        return

    # ── Stage 1: copy each point to its new ID (additive, reversible) ──
    copied = 0
    for i in range(0, len(pending), BATCH):
        chunk = pending[i:i + BATCH]
        old_ids = [old for _, old, _ in chunk]
        found = _qdrant.retrieve(
            collection_name=settings.qdrant_collection,
            ids=old_ids,
            with_vectors=True,
            with_payload=True,
        )
        by_old = {p.id: p for p in found}

        points = []
        for vin, old, new in chunk:
            p = by_old.get(old)
            if p is None:
                print(f"  WARN: old point missing for {vin} ({old}) — skipping")
                continue
            points.append(PointStruct(id=new, vector=p.vector, payload=p.payload))

        if points:
            _qdrant.upsert(collection_name=settings.qdrant_collection, points=points)
            copied += len(points)
        print(f"  copied {copied}/{len(pending)}", end="\r", flush=True)

    print(f"\nstage 1: copied {copied} points to new IDs")

    # ── Stage 2: verify every new ID landed with the right VIN ──
    new_ids = [new for _, _, new in pending]
    verified = 0
    for i in range(0, len(new_ids), BATCH):
        found = _qdrant.retrieve(
            collection_name=settings.qdrant_collection,
            ids=new_ids[i:i + BATCH],
            with_payload=True,
        )
        verified += len(found)
    print(f"stage 2: verified {verified}/{len(new_ids)} new points readable")
    if verified != len(new_ids):
        print("ABORT — verification failed, old points left untouched.")
        return

    # ── Stage 3: point PostgreSQL at the new IDs ──
    with Session(_engine) as session:
        for vin, _, new in pending:
            session.execute(
                text("UPDATE vehicle_inventory SET vector_id = :v WHERE vin = :vin"),
                {"v": str(new), "vin": vin},
            )
        session.commit()
    print(f"stage 3: updated {len(pending)} vector_id values in PostgreSQL")

    # ── Stage 4: drop the orphaned old points ──
    old_ids_all = [old for _, old, _ in pending]
    for i in range(0, len(old_ids_all), BATCH):
        _qdrant.delete(
            collection_name=settings.qdrant_collection,
            points_selector=old_ids_all[i:i + BATCH],
        )
    print(f"stage 4: deleted {len(old_ids_all)} orphaned points")

    count = _qdrant.count(collection_name=settings.qdrant_collection).count
    print(f"\ndone — collection now holds {count} points")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Re-key Qdrant point IDs to deterministic VIN hashes")
    ap.add_argument("--apply", action="store_true", help="perform the migration (default: dry run)")
    args = ap.parse_args()
    main(args.apply)
    if args.apply:
        clear_search_cache()
