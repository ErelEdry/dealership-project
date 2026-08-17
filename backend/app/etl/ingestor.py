"""
ETL Step 1: Ingestor & Validator
---------------------------------
Reads a CSV file row by row, validates each row against RawVehicle,
writes valid rows to the database, quarantines invalid rows.

Usage (from project root inside the container):
    python -m app.etl.ingestor data/sample/mock_inventory.csv
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Generator

import structlog

from app.schemas.inventory import RawVehicle, ValidationError

log = structlog.get_logger()


# ─────────────────────────────────────────────────────────────
# CSV Row Generator
# ─────────────────────────────────────────────────────────────

def read_csv(filepath: str) -> Generator[tuple[int, dict], None, None]:
    """Yield (row_number, row_dict) for every data row in the CSV."""
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):   # row 1 = header
            # Parse JSON array fields if they were stored as strings
            for field in ("features", "images"):
                raw = row.get(field, "")
                if raw and not isinstance(raw, list):
                    try:
                        row[field] = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        # Comma-separated fallback
                        row[field] = [x.strip() for x in raw.split(",") if x.strip()]
            yield i, dict(row)


# ─────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────

def validate_row(row_number: int, row: dict, source_file: str):
    """
    Returns (RawVehicle, None) on success.
    Returns (None, ValidationError) on failure.
    """
    try:
        vehicle = RawVehicle(source_file=source_file, **row)
        return vehicle, None
    except Exception as e:
        err = ValidationError(
            raw_row=row,
            error_detail=str(e),
            source_file=source_file,
            row_number=row_number,
        )
        return None, err


# ─────────────────────────────────────────────────────────────
# Main ingest function (sync — for CLI use)
# ─────────────────────────────────────────────────────────────

def ingest_csv(filepath: str) -> dict:
    """
    Validate all rows in a CSV.
    Returns a summary dict with valid/invalid counts and the parsed vehicles.

    In Phase 2, this will also trigger enrichment + embedding.
    For now it just validates and prints results.
    """
    source_file = Path(filepath).name
    valid_vehicles   = []
    invalid_records  = []

    for row_number, row in read_csv(filepath):
        vehicle, error = validate_row(row_number, row, source_file)
        if vehicle:
            # Check for anomaly flags
            flags = getattr(vehicle, "_anomaly_flags", [])
            if flags:
                log.warning("anomaly_detected", vin=vehicle.vin, flags=flags)
            valid_vehicles.append(vehicle)
            log.info("row_valid", row=row_number, vin=vehicle.vin)
        else:
            invalid_records.append(error)
            log.error("row_invalid", row=row_number, detail=error.error_detail)

    summary = {
        "total":   len(valid_vehicles) + len(invalid_records),
        "valid":   len(valid_vehicles),
        "invalid": len(invalid_records),
        "vehicles": valid_vehicles,
        "errors":   invalid_records,
    }

    log.info(
        "ingest_complete",
        file=source_file,
        total=summary["total"],
        valid=summary["valid"],
        invalid=summary["invalid"],
    )
    return summary


# ─────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/sample/mock_inventory.csv"
    result = ingest_csv(path)
    print(f"\nResult: {result['valid']} valid  |  {result['invalid']} invalid  (total: {result['total']})")
    if result["errors"]:
        print("\nInvalid rows:")
        for e in result["errors"]:
            print(f"  Row {e.row_number}: {e.error_detail}")
