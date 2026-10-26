"""
One-off migration — canonicalise ai_segment on existing rows (no LLM).
---------------------------------------------------------------------
The full --force re-enrichment is throttled by Groq's daily token cap, so
instead of paying tokens to regenerate segments we map the existing free-text
values onto the approved vocabulary with app.core.segments.normalize_segment().

Updates the ai_segment column in PostgreSQL and the ai_segment key in every
Qdrant payload (that's what Phase 3 filters on). The embedding_doc / vector are
left untouched, so doc↔vector stay internally consistent — only the filter
facet is canonicalised.

Idempotent. Dry-run by default; pass --apply to write.

    docker compose exec api python -m scripts.normalize_segments            # dry run
    docker compose exec api python -m scripts.normalize_segments --apply    # write
"""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter, defaultdict

from qdrant_client import QdrantClient
from sqlalchemy import bindparam, create_engine, text

from app.core.cache import clear_search_cache
from app.core.config import settings
from app.core.segments import normalize_segment


def vin_to_point_id(vin: str) -> int:
    """Same formula as app.etl.embedder.vin_to_point_id."""
    return int(hashlib.md5(vin.encode()).hexdigest()[:16], 16) % (2 ** 63)


def main(apply: bool) -> None:
    engine = create_engine(settings.database_url.replace(
        "postgresql+asyncpg", "postgresql+psycopg2"
    ))

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT vin, ai_segment FROM vehicle_inventory")
        ).fetchall()

    changes = [(vin, seg, normalize_segment(seg))
               for vin, seg in rows
               if normalize_segment(seg) != seg]

    after = Counter(normalize_segment(seg) for _, seg in rows)
    print(f"{len(rows)} vehicles · {len(changes)} need normalizing")
    print(f"resulting distinct segments: {len(after)}")
    for seg, n in after.most_common():
        print(f"    {seg:16} {n}")

    if not apply:
        print("\nDry run — nothing written. Re-run with --apply to commit.")
        return

    by_new: dict[str, list[str]] = defaultdict(list)
    for vin, _old, new in changes:
        by_new[new].append(vin)

    # ── PostgreSQL ────────────────────────────────────────────
    with engine.begin() as conn:
        for new, vins in by_new.items():
            stmt = text(
                "UPDATE vehicle_inventory SET ai_segment = :s, updated_at = now() "
                "WHERE vin IN :vins"
            ).bindparams(bindparam("vins", expanding=True))
            conn.execute(stmt, {"s": new, "vins": vins})
    print(f"  -> PostgreSQL: updated {len(changes)} rows")

    # ── Qdrant payloads ───────────────────────────────────────
    qc = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    for new, vins in by_new.items():
        qc.set_payload(
            collection_name=settings.qdrant_collection,
            payload={"ai_segment": new},
            points=[vin_to_point_id(v) for v in vins],
            wait=True,
        )
    print(f"  -> Qdrant: updated {len(changes)} payloads")
    print("\nDone. All ai_segment values are now canonical.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Canonicalise ai_segment on existing rows")
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = ap.parse_args()
    main(args.apply)
    if args.apply:
        clear_search_cache()
