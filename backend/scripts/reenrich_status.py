"""
Print how many vehicles still await re-enrichment (last enriched before the
migration cutoff, or never). Prints a single integer on stdout — used by the
daily automation to decide when issue #2 is finished.

    docker compose exec api python -m scripts.reenrich_status --cutoff 2026-08-17
"""

from __future__ import annotations

import argparse

from sqlalchemy import create_engine, text

from app.core.config import settings


def main(cutoff: str) -> None:
    engine = create_engine(settings.database_url.replace(
        "postgresql+asyncpg", "postgresql+psycopg2"
    ))
    with engine.begin() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM vehicle_inventory "
            "WHERE enriched_at IS NULL OR enriched_at < :cutoff"
        ), {"cutoff": cutoff}).scalar()
    print(int(n))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Count vehicles awaiting re-enrichment")
    ap.add_argument("--cutoff", default="2026-08-17")
    main(ap.parse_args().cutoff)
