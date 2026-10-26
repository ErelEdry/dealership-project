"""
One-off migration — regenerate believable prices.
--------------------------------------------------
The synthetic feed assigned `price` independently of the car, producing a
€155k Fiat 500 and a €17.5k BMW X5. This recomputes a DETERMINISTIC,
plausible price per VIN from:

    segment baseline  ×  brand tier  ×  fuel  ×  depreciation(year)
                      ×  mileage penalty  ×  a small per-VIN jitter

Same idea as scripts.rebalance_stock_status: the price is a pure function of
the row (+ a salted-VIN jitter), so PostgreSQL, the Qdrant payload, and the
source CSV all land on the identical value and re-running is idempotent.

Also:
  * recomputes `acquisition_cost` (dealer buy-in) as a margin below the new
    price — otherwise a €14.5k car keeps its old €45k buy-in;
  * rewrites the stale "$55,000" figures baked into `ai_summary` to the new
    €-price, with NO LLM tokens (plain regex).

    docker compose exec api python -m scripts.regenerate_prices           # dry run
    docker compose exec api python -m scripts.regenerate_prices --apply   # write

--apply updates PostgreSQL (price, acquisition_cost, ai_summary) + the Qdrant
`price` payload (so the budget-search range filter stays correct) AND rewrites
the source CSV (backing it up to <csv>.bak first).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import statistics
from collections import defaultdict
from pathlib import Path

from qdrant_client import QdrantClient
from sqlalchemy import create_engine, text

from app.core.cache import clear_search_cache
from app.core.config import settings
from app.core.segments import normalize_segment

DEFAULT_CSV = "data/sample/inventory.csv"
REF_YEAR = 2026  # depreciation reference (current year)

# ── Brand tier: relative new-car premium ─────────────────────
_TIER = {
    "fiat": 0.85, "suzuki": 0.85, "renault": 0.88, "peugeot": 0.88,
    "kia": 0.90, "hyundai": 0.90, "mitsubishi": 0.88, "chevrolet": 0.92,
    "toyota": 1.00, "honda": 1.00, "nissan": 1.00, "ford": 1.00,
    "mazda": 1.02, "subaru": 1.02, "volkswagen": 1.08,
    "volvo": 1.30, "audi": 1.38, "bmw": 1.40, "mercedes-benz": 1.42,
    "tesla": 1.45,
}
_TIER_DEFAULT = 1.0

# ── Segment baseline: typical NEW price, mainstream tier (EUR) ─
_SEG_BASE = {
    "City Car": 17000, "Supermini": 19000, "Compact Car": 25000,
    "Sedan": 33000, "Executive Sedan": 55000, "Estate": 34000,
    "Compact SUV": 33000, "Mid-Size SUV": 45000, "Full-Size SUV": 60000,
    "Coupe": 43000, "Convertible": 49000, "Sports Car": 66000,
    "Hot Hatch": 35000, "MPV": 34000, "Pickup Truck": 41000,
    "Van": 30000, "Luxury Car": 78000, "Other": 28000,
}
_SEG_DEFAULT = 28000

_FUEL = {"electric": 1.18, "hybrid": 1.08, "petrol": 1.0, "diesel": 1.02}

PRICE_FLOOR = 5000
PRICE_CAP = 185000


def _norm_vin(vin: str) -> str:
    return vin.strip().upper()


def vin_to_point_id(vin: str) -> int:
    """Same formula as app.etl.embedder.vin_to_point_id."""
    return int(hashlib.md5(_norm_vin(vin).encode()).hexdigest()[:16], 16) % (2 ** 63)


def _jitter(vin: str, salt: str, lo: float, hi: float) -> float:
    """Deterministic value in [lo, hi] from a salted VIN hash."""
    h = int(hashlib.md5(f"{salt}:{_norm_vin(vin)}".encode()).hexdigest()[:8], 16)
    steps = round((hi - lo) * 100) + 1
    return lo + (h % steps) / 100.0


def price_for(vin: str, make: str, year: int | None, fuel: str | None,
              segment: str | None, mileage: int | None) -> int:
    """Deterministic, plausible price for one vehicle, rounded to €250."""
    seg = normalize_segment(segment)
    base = _SEG_BASE.get(seg, _SEG_DEFAULT)
    tier = _TIER.get((make or "").strip().lower(), _TIER_DEFAULT)
    fuel_adj = _FUEL.get((fuel or "").strip().lower(), 1.0)

    age = max(0, min(30, REF_YEAR - (year or REF_YEAR)))
    deprec = max(0.30, 0.91 ** age)

    km = mileage or 0
    mileage_factor = max(0.70, 1.0 - km / 400000.0)

    jitter = _jitter(vin, "price", 0.93, 1.07)

    raw = base * tier * fuel_adj * deprec * mileage_factor * jitter
    raw = max(PRICE_FLOOR, min(PRICE_CAP, raw))
    return int(round(raw / 250.0) * 250)


def acquisition_for(vin: str, price: int) -> float:
    """Dealer buy-in: a deterministic 80–90% of the sale price."""
    return round(price * _jitter(vin, "acq", 0.80, 0.90), 2)


# Currency figures baked into summaries: "$55,000", "€ 19,500", "$18900.00"…
_MONEY_RE = re.compile(r"[$€]\s?\d[\d,]*(?:\.\d+)?")


def fix_summary(summary: str | None, price: int) -> str | None:
    """Replace any $/€ figure in the summary with the new €-price. No LLM."""
    if not summary or not _MONEY_RE.search(summary):
        return summary
    return _MONEY_RE.sub(f"€{price:,.0f}", summary)


def main(apply: bool, csv_path: str) -> None:
    sync_url = settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    engine = create_engine(sync_url, pool_pre_ping=True)

    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT vin, make, model, year, fuel_type, ai_segment, mileage, "
            "price, ai_summary FROM vehicle_inventory"
        )).mappings().all()

    updates: list[dict] = []          # vin, price, acq
    summary_updates: list[dict] = []  # vin, summary  (only where a $ figure changed)
    by_seg_prices: dict[str, list[int]] = defaultdict(list)
    new_prices: list[int] = []
    samples = []

    for r in rows:
        new_price = price_for(r["vin"], r["make"], r["year"], r["fuel_type"],
                              r["ai_segment"], r["mileage"])
        acq = acquisition_for(r["vin"], new_price)
        updates.append({"vin": r["vin"], "price": float(new_price), "acq": acq})
        new_prices.append(new_price)
        by_seg_prices[normalize_segment(r["ai_segment"])].append(new_price)

        new_summary = fix_summary(r["ai_summary"], new_price)
        if new_summary != r["ai_summary"]:
            summary_updates.append({"vin": r["vin"], "summary": new_summary})

        if len(samples) < 10:
            samples.append((r["make"], r["model"], r["year"], normalize_segment(r["ai_segment"]),
                            int(r["price"]), new_price))

    # ── Report ────────────────────────────────────────────────
    print(f"{len(rows)} vehicles. New price spread:")
    print(f"    min €{min(new_prices):,}  ·  median €{int(statistics.median(new_prices)):,}"
          f"  ·  max €{max(new_prices):,}")
    print("\nMedian new price by segment:")
    for seg, ps in sorted(by_seg_prices.items(), key=lambda kv: statistics.median(kv[1])):
        print(f"    {seg:16} n={len(ps):4}  €{int(min(ps)):>7,} – €{int(max(ps)):>7,}"
              f"   (median €{int(statistics.median(ps)):,})")
    print("\nSample before → after:")
    for mk, md, yr, seg, old, new in samples:
        print(f"    {mk} {md} {yr} [{seg}]  €{old:,} → €{new:,}")
    print(f"\n{len(summary_updates)} summaries have a $/€ figure to rewrite.")

    if not apply:
        print("\nDry run — nothing written. Re-run with --apply to commit.")
        return

    # ── PostgreSQL: price + acquisition_cost, then summaries ───
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE vehicle_inventory SET price = :price, "
                 "acquisition_cost = :acq, updated_at = now() WHERE vin = :vin"),
            updates,
        )
        if summary_updates:
            conn.execute(
                text("UPDATE vehicle_inventory SET ai_summary = :summary, "
                     "updated_at = now() WHERE vin = :vin"),
                summary_updates,
            )
    print(f"  -> PostgreSQL updated ({len(updates)} prices, {len(summary_updates)} summaries)")

    # ── Qdrant: price payload (batched by identical price value) ─
    qc = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    by_price: dict[float, list[int]] = defaultdict(list)
    for u in updates:
        by_price[u["price"]].append(vin_to_point_id(u["vin"]))
    for price, point_ids in by_price.items():
        qc.set_payload(
            collection_name=settings.qdrant_collection,
            payload={"price": price},
            points=point_ids,
            wait=True,
        )
    print(f"  -> Qdrant price payload updated ({len(by_price)} distinct prices)")

    # ── Source CSV (durability for future pipeline runs) ──────
    path = Path(csv_path)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            csv_rows = list(reader)
        by_vin = {_norm_vin(u["vin"]): u for u in updates}
        for row in csv_rows:
            u = by_vin.get(_norm_vin(row["vin"]))
            if u:
                row["price"] = u["price"]
                if "acquisition_cost" in row:
                    row["acquisition_cost"] = u["acq"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"  -> CSV rewritten; backup at {path.name}.bak")
    else:
        print(f"  !! CSV not found at {path} — skipped (DB/Qdrant still updated)")

    print("\nDone. Prices regenerated.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Regenerate believable prices")
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    ap.add_argument("--csv", default=DEFAULT_CSV, help="Path to source CSV")
    args = ap.parse_args()
    main(args.apply, args.csv)
    if args.apply:
        clear_search_cache()
