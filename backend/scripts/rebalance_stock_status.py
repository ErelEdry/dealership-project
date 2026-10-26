"""
One-off migration — rebalance stock_status toward a purchasable-heavy mix.
-------------------------------------------------------------------------
The source feed had only ~26% available, so search results were dominated by
workshop/sold cars. For the demo we want mostly buyable inventory while still
exercising the stock_status filter, so we reassign to roughly:

    available 85% · reserved 6% · sold 5% · workshop 4%

Assignment is DETERMINISTIC per VIN (md5 of a salted VIN), so PostgreSQL, the
Qdrant payloads, and the source CSV all receive the exact same status without
any coordination — and re-running is idempotent.

    docker compose exec api python -m scripts.rebalance_stock_status            # dry run
    docker compose exec api python -m scripts.rebalance_stock_status --apply    # write

--apply updates PostgreSQL + Qdrant payloads AND rewrites the source CSV
(backing it up to <csv>.bak first) so future pipeline runs stay consistent.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
from collections import Counter
from pathlib import Path

from qdrant_client import QdrantClient
from sqlalchemy import bindparam, create_engine, text

from app.core.cache import clear_search_cache
from app.core.config import settings

# ── Target distribution (cumulative thresholds on a 0–1 hash) ─
# available < 0.85 <= reserved < 0.91 <= sold < 0.96 <= workshop
_THRESHOLDS = (
    (0.85, "available"),
    (0.91, "reserved"),
    (0.96, "sold"),
    (1.01, "workshop"),
)

DEFAULT_CSV = "data/sample/inventory.csv"


def _norm_vin(vin: str) -> str:
    """Match RawVehicle's VIN normalisation (strip + upper) so CSV and DB agree."""
    return vin.strip().upper()


def status_for_vin(vin: str) -> str:
    """Deterministic 0–1 hash of the VIN → a target status."""
    digest = hashlib.md5(f"status:{_norm_vin(vin)}".encode()).hexdigest()[:8]
    h = int(digest, 16) / 0xFFFFFFFF
    for threshold, status in _THRESHOLDS:
        if h < threshold:
            return status
    return "workshop"  # unreachable


def vin_to_point_id(vin: str) -> int:
    """Same formula as app.etl.embedder.vin_to_point_id (replicated to avoid
    importing FastEmbed just for this)."""
    return int(hashlib.md5(_norm_vin(vin).encode()).hexdigest()[:16], 16) % (2 ** 63)


def main(apply: bool, csv_path: str) -> None:
    sync_url = settings.database_url.replace(
        "postgresql+asyncpg", "postgresql+psycopg2"
    )
    engine = create_engine(sync_url, pool_pre_ping=True)

    # ── Compute the new assignment from the DB's VINs ─────────
    with engine.begin() as conn:
        vins = [r[0] for r in conn.execute(
            text("SELECT vin FROM vehicle_inventory")
        ).fetchall()]

    assignment: dict[str, list[str]] = {s: [] for _, s in _THRESHOLDS}
    for vin in vins:
        assignment[status_for_vin(vin)].append(vin)

    print(f"{len(vins)} vehicles. Target distribution:")
    for status, group in sorted(assignment.items(), key=lambda kv: -len(kv[1])):
        pct = 100 * len(group) / len(vins) if vins else 0
        print(f"    {status:12} {len(group):5}  ({pct:.1f}%)")

    if not apply:
        print("\nDry run — nothing written. Re-run with --apply to commit.")
        return

    # ── PostgreSQL ────────────────────────────────────────────
    with engine.begin() as conn:
        for status, group in assignment.items():
            if not group:
                continue
            stmt = text(
                "UPDATE vehicle_inventory SET stock_status = :st, updated_at = now() "
                "WHERE vin IN :vins"
            ).bindparams(bindparam("vins", expanding=True))
            conn.execute(stmt, {"st": status, "vins": group})
    print("  -> PostgreSQL updated")

    # ── Qdrant payloads ───────────────────────────────────────
    qc = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    for status, group in assignment.items():
        if not group:
            continue
        qc.set_payload(
            collection_name=settings.qdrant_collection,
            payload={"stock_status": status},
            points=[vin_to_point_id(v) for v in group],
            wait=True,
        )
    print("  -> Qdrant payloads updated")

    # ── Source CSV (durability for future pipeline runs) ──────
    path = Path(csv_path)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)
        written = Counter()
        for row in rows:
            row["stock_status"] = status_for_vin(row["vin"])
            written[row["stock_status"]] += 1
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"  -> CSV rewritten ({dict(written)}); backup at {path.name}.bak")
    else:
        print(f"  !! CSV not found at {path} — skipped (DB/Qdrant still updated)")

    print("\nDone. Inventory rebalanced to ~85% available.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rebalance stock_status to ~85% available")
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    ap.add_argument("--csv", default=DEFAULT_CSV, help="Path to source CSV")
    args = ap.parse_args()
    main(args.apply, args.csv)
    if args.apply:
        clear_search_cache()
