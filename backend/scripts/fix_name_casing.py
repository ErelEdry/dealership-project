"""
One-off migration — restore make/model casing.
-----------------------------------------------
The ingest validator used to `.title()` make and model, so PostgreSQL and the
Qdrant payload hold "Bmw", "Rav4", "Cr-V", "Cx-5", "Gle", "Xc60"… while the
source CSV has the real names (BMW, RAV4, CR-V). The LLM was fed the mangled
names too, so they also leak into ai_summary / selling points / comparables.

The CSV is the source of truth: each VIN's make/model is its CSV value,
stripped. Re-running is idempotent — every write sets the canonical value.

    docker compose exec api python -m scripts.fix_name_casing           # dry run
    docker compose exec api python -m scripts.fix_name_casing --apply   # write

--apply updates PostgreSQL (make, model, and the mangled names inside
ai_summary / ai_selling_points / ai_comparable_models / embedding_doc — plain
regex, NO LLM tokens), the Qdrant payload (make, model, and the lower-cased
`make_key` that search now filters on), and the source CSV only if stripping
changed a value (backed up to <csv>.names.bak first, so the .bak written by
regenerate_prices is left alone).

Vectors are not re-embedded here: content_hash now covers make/model, so the
next pipeline run resyncs every vehicle (local re-embed, no LLM) from the
corrected rows anyway.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from qdrant_client import QdrantClient
from sqlalchemy import create_engine, text

from app.core.cache import clear_search_cache
from app.core.config import settings
from app.schemas.inventory import make_key

DEFAULT_CSV = "data/sample/inventory.csv"
_TEXT_COLUMNS = ("ai_summary", "embedding_doc")
_LIST_COLUMNS = ("ai_selling_points", "ai_comparable_models")


def _norm_vin(vin: str) -> str:
    return vin.strip().upper()


def vin_to_point_id(vin: str) -> int:
    """Same formula as app.etl.embedder.vin_to_point_id."""
    return int(hashlib.md5(_norm_vin(vin).encode()).hexdigest()[:16], 16) % (2 ** 63)


def canonical_names(csv_rows: list[dict]) -> dict[str, tuple[str, str]]:
    """VIN → (make, model) as the CSV spells them, stripped."""
    return {_norm_vin(r["vin"]): (r["make"].strip(), r["model"].strip())
            for r in csv_rows if r.get("vin")}


def mangled_forms(names) -> dict[str, str]:
    """Map each `.title()`-mangled name to its real spelling ("Bmw" → "BMW").

    Only names that `.title()` actually changes are included, so "Toyota" or
    "Model 3" never get touched.
    """
    fixes = {}
    for make, model in names:
        for name in (make, model):
            if name.title() != name:
                fixes[name.title()] = name
    return fixes


def fix_text(value: str | None, fixes: dict[str, str]) -> str | None:
    """Replace whole-word, case-sensitive occurrences of mangled names."""
    if not value or not fixes:
        return value
    pattern = re.compile(r"(?<![\w-])(" + "|".join(
        re.escape(k) for k in sorted(fixes, key=len, reverse=True)) + r")(?![\w-])")
    return pattern.sub(lambda m: fixes[m.group(1)], value)


def _as_list(value) -> list:
    if isinstance(value, str):
        value = json.loads(value)
    return value or []


def plan_updates(rows, names: dict[str, tuple[str, str]], fixes: dict[str, str]) -> list[dict]:
    """PostgreSQL rows whose names or AI text need rewriting (only those).

    Each update carries `renamed`: True if make/model changed (not just text).
    """
    updates = []
    for r in rows:
        make, model = names.get(_norm_vin(r["vin"]), (r["make"], r["model"]))
        new = {"vin": r["vin"], "make": make, "model": model,
               "renamed": (make, model) != (r["make"], r["model"])}
        for col in _TEXT_COLUMNS:
            new[col] = fix_text(r[col], fixes)
        for col in _LIST_COLUMNS:
            new[col] = [fix_text(x, fixes) for x in _as_list(r[col])]
        if (new["renamed"]
                or any(new[c] != r[c] for c in _TEXT_COLUMNS)
                or any(new[c] != _as_list(r[c]) for c in _LIST_COLUMNS)):
            updates.append(new)
    return updates


def main(apply: bool, csv_path: str) -> None:
    path = Path(csv_path)
    if not path.exists():
        raise SystemExit(f"CSV not found at {path} — it is the source of truth, aborting.")
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        csv_rows = list(reader)
    names = canonical_names(csv_rows)
    fixes = mangled_forms(names.values())

    sync_url = settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    engine = create_engine(sync_url, pool_pre_ping=True)
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT vin, make, model, " + ", ".join(_TEXT_COLUMNS + _LIST_COLUMNS)
            + " FROM vehicle_inventory"
        )).mappings().all()

    updates = plan_updates(rows, names, fixes)
    renamed = [u for u in updates if u["renamed"]]
    missing = sum(1 for r in rows if _norm_vin(r["vin"]) not in names)
    csv_dirty = [r for r in csv_rows
                 if (r["make"], r["model"]) != (r["make"].strip(), r["model"].strip())]

    # ── Report ────────────────────────────────────────────────
    print(f"{len(rows)} vehicles in PostgreSQL, {len(names)} in the CSV.")
    print(f"Mangled forms to fix: {', '.join(f'{k} → {v}' for k, v in sorted(fixes.items()))}")
    print(f"{len(renamed)} rows get a corrected make/model; "
          f"{len(updates) - len(renamed)} more only have AI text to fix.")
    if missing:
        print(f"!! {missing} PostgreSQL rows have no CSV row — their names are left as-is.")
    print(f"{len(csv_dirty)} CSV rows have stray whitespace in make/model.")

    if not apply:
        print("\nDry run — nothing written. Re-run with --apply to commit.")
        return

    # ── PostgreSQL ────────────────────────────────────────────
    if updates:
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE vehicle_inventory SET make = :make, model = :model, "
                "ai_summary = :ai_summary, embedding_doc = :embedding_doc, "
                "ai_selling_points = CAST(:ai_selling_points AS json), "
                "ai_comparable_models = CAST(:ai_comparable_models AS json), "
                "updated_at = now() WHERE vin = :vin"
            ), [{**u, **{c: json.dumps(u[c]) for c in _LIST_COLUMNS}} for u in updates])
    print(f"  -> PostgreSQL updated ({len(updates)} rows)")

    # ── Qdrant payload: every point, batched by identical names ─
    with engine.begin() as conn:
        final = conn.execute(text("SELECT vin, make, model FROM vehicle_inventory")).all()
    by_name: dict[tuple[str, str], list[int]] = defaultdict(list)
    for vin, make, model in final:
        by_name[(make, model)].append(vin_to_point_id(vin))
    qc = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    for (make, model), point_ids in by_name.items():
        qc.set_payload(
            collection_name=settings.qdrant_collection,
            payload={"make": make, "model": model, "make_key": make_key(make)},
            points=point_ids,
            wait=True,
        )
    print(f"  -> Qdrant payload updated ({len(final)} points, {len(by_name)} name groups)")

    # ── Source CSV: only if stripping changed something ───────
    if csv_dirty:
        shutil.copy2(path, path.with_suffix(path.suffix + ".names.bak"))
        for r in csv_rows:
            r["make"], r["model"] = r["make"].strip(), r["model"].strip()
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"  -> CSV rewritten; backup at {path.name}.names.bak")
    else:
        print("  -> CSV already canonical — unchanged")

    print("\nDone. Names restored.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Restore make/model casing from the CSV")
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    ap.add_argument("--csv", default=DEFAULT_CSV, help="Path to source CSV")
    args = ap.parse_args()
    main(args.apply, args.csv)
    if args.apply:
        clear_search_cache()
