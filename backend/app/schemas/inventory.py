"""
Pydantic schemas for vehicle inventory.

Three layers:
  RawVehicle       — exactly what comes in from the CSV / DMS feed
  EnrichedVehicle  — after AI enrichment (all AI fields prefixed ai_)
  EmbeddingPayload — the text document sent to the embedding model
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.segments import normalize_segment


def utcnow() -> datetime:
    """Timezone-aware UTC now. Replaces the deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────

class StockStatus(str, Enum):
    AVAILABLE = "available"
    RESERVED  = "reserved"
    SOLD      = "sold"
    INCOMING  = "incoming"   # en route, not yet on-lot
    WORKSHOP  = "workshop"   # En Taller — in service/repair


class FuelType(str, Enum):
    PETROL   = "petrol"
    DIESEL   = "diesel"
    HYBRID   = "hybrid"
    PHEV     = "phev"          # plug-in hybrid
    ELECTRIC = "electric"
    HYDROGEN = "hydrogen"
    OTHER    = "other"


class Transmission(str, Enum):
    AUTOMATIC = "automatic"
    MANUAL    = "manual"
    CVT       = "cvt"
    OTHER     = "other"


class BodyType(str, Enum):
    SEDAN       = "sedan"
    HATCHBACK   = "hatchback"
    SUV         = "suv"
    COUPE       = "coupe"
    WAGON       = "wagon"
    UTE         = "ute"          # pickup truck / ute
    VAN         = "van"
    CONVERTIBLE = "convertible"
    OTHER       = "other"


# ─────────────────────────────────────────────────────────────
# RAW VEHICLE  (from source data — no AI fields)
# ─────────────────────────────────────────────────────────────

class RawVehicle(BaseModel):
    """
    Represents one row from the raw inventory CSV or DMS API.
    All fields stay exactly as-received; only type coercion is applied.
    """

    # ── Identifiers ───────────────────────────────────────────
    vin:       str = Field(..., min_length=5, max_length=17, description="Vehicle Identification Number")
    dealer_id: str = Field(..., description="Dealer or branch identifier")
    stock_id:  Optional[str] = Field(None, description="Dealer's internal stock number")

    # ── Core specs ────────────────────────────────────────────
    make:         str       = Field(..., min_length=1)
    model:        str       = Field(..., min_length=1)
    year:         int       = Field(..., ge=1980, le=datetime.now().year + 1)
    trim:         Optional[str]  = None
    body_type:    Optional[BodyType] = None
    fuel_type:    Optional[FuelType] = None
    transmission: Optional[Transmission] = None
    engine:       Optional[str]  = None     # e.g. "2.5L 4-cyl Turbo"
    seats:        Optional[int]  = Field(None, ge=1, le=15)
    doors:        Optional[int]  = Field(None, ge=2, le=6)

    # ── Condition & pricing ───────────────────────────────────
    mileage:          int    = Field(..., ge=0, description="Kilometres on odometer")
    price:            float  = Field(..., gt=0, description="Listed price in local currency")
    acquisition_cost: Optional[float] = Field(None, gt=0, description="Dealer's cost to acquire the vehicle")
    condition:        Optional[str]   = None     # "new" | "used" | "demo"
    colour_ext:       Optional[str]   = None
    colour_int:       Optional[str]   = None

    # ── Media & features ──────────────────────────────────────
    features:  list[str] = Field(default_factory=list)
    images:    list[str] = Field(default_factory=list, description="Image URLs or paths")

    # ── Status ────────────────────────────────────────────────
    stock_status: StockStatus = StockStatus.AVAILABLE

    # ── Dealership metadata ───────────────────────────────────
    arrived_date:   Optional[str]     = None   # date vehicle entered lot (YYYY/MM/DD)

    # ── Ingestion metadata ────────────────────────────────────
    source_file:    Optional[str]     = None
    ingested_at:    datetime          = Field(default_factory=utcnow)

    # ── Validators ────────────────────────────────────────────

    @field_validator("vin")
    @classmethod
    def vin_uppercase(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("make", "model")
    @classmethod
    def title_case(cls, v: str) -> str:
        return v.strip().title()

    @field_validator("price", mode="before")
    @classmethod
    def parse_price(cls, v) -> float:
        """Accept '$32,500' or '32500' or 32500.0"""
        if isinstance(v, str):
            v = v.replace("$", "").replace(",", "").strip()
        return float(v)

    @field_validator("mileage", mode="before")
    @classmethod
    def parse_mileage(cls, v) -> int:
        if isinstance(v, str):
            v = v.replace(",", "").replace("km", "").strip()
        return int(float(v))

    @model_validator(mode="after")
    def flag_anomalies(self) -> "RawVehicle":
        issues = []
        if self.mileage > 400_000:
            issues.append(f"mileage unusually high: {self.mileage}")
        if self.price < 500:
            issues.append(f"price suspiciously low: {self.price}")
        # Attach as a private attribute — won't break validation
        object.__setattr__(self, "_anomaly_flags", issues)
        return self

    def content_hash(self) -> str:
        """MD5 of every spec field from the source row.

        The pipeline compares it with the stored hash to spot CSV changes (any
        field: make, year, price, stock status…) and resync that vehicle.
        Provenance fields (source_file, ingested_at) are excluded so the hash
        only moves when the vehicle itself changes.
        """
        spec = self.model_dump(mode="json", exclude={"source_file", "ingested_at"})
        spec["features"] = sorted(spec["features"])
        key = json.dumps(spec, sort_keys=True)
        return hashlib.md5(key.encode()).hexdigest()

    model_config = {"use_enum_values": True}


# ─────────────────────────────────────────────────────────────
# AI ENRICHMENT OUTPUT  (LLM response schema)
# ─────────────────────────────────────────────────────────────

class AIEnrichmentOutput(BaseModel):
    """
    Strict schema for what the LLM enrichment agent must return.
    Pass this as the response_format to GPT-4o.
    All fields are prefixed ai_ in the final DB record.
    """

    ai_lifestyle_tags:    list[str] = Field(
        ..., min_length=1, max_length=5,
        description="e.g. Family-friendly, Fuel-efficient, Sporty, Luxury, City-ready"
    )
    ai_segment:           str       = Field(
        ..., description="e.g. Compact SUV, Full-size Sedan, Performance Coupe"
    )
    ai_summary:           str       = Field(
        ..., min_length=50, max_length=400,
        description="Plain-English 2-3 sentence vehicle description"
    )
    ai_selling_points:    list[str] = Field(
        ..., min_length=1, max_length=6,
        description="Key features worth highlighting to a buyer"
    )
    ai_comparable_models: list[str] = Field(
        ..., min_length=1, max_length=4,
        description="Real models this vehicle is similar to"
    )
    ai_confidence:        float     = Field(
        ..., ge=0.0, le=1.0,
        description="Model's self-assessed confidence in the enrichment quality"
    )

    @field_validator("ai_lifestyle_tags", "ai_selling_points", "ai_comparable_models")
    @classmethod
    def non_empty_strings(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s.strip()]

    @field_validator("ai_segment")
    @classmethod
    def canonicalize_segment(cls, v: str) -> str:
        """Snap free-text segment onto the approved facet vocabulary."""
        return normalize_segment(v)


# ─────────────────────────────────────────────────────────────
# ENRICHED VEHICLE  (RawVehicle + AIEnrichmentOutput + metadata)
# ─────────────────────────────────────────────────────────────

class EnrichedVehicle(RawVehicle):
    """
    Full vehicle record after the enrichment pipeline.
    Extends RawVehicle — all original fields are preserved.
    """

    # AI enrichment fields
    ai_lifestyle_tags:    list[str]     = Field(default_factory=list)
    ai_segment:           Optional[str] = None
    ai_summary:           Optional[str] = None
    ai_selling_points:    list[str]     = Field(default_factory=list)
    ai_comparable_models: list[str]     = Field(default_factory=list)
    ai_confidence:        Optional[float] = None

    # Pipeline metadata
    content_hash_value: Optional[str]      = None
    embedding_doc:      Optional[str]      = None   # assembled text sent to embedder
    embedding_model:    Optional[str]      = None   # e.g. "text-embedding-3-large"
    vector_id:          Optional[str]      = None   # Qdrant point ID
    enriched_at:        Optional[datetime] = None
    needs_review:       bool               = False  # True if ai_confidence < 0.7

    def build_embedding_document(self) -> str:
        """
        Assemble the rich text string that gets converted to a vector.
        Concatenates structured + AI fields for maximum semantic coverage.
        """
        parts = [
            f"{self.year} {self.make} {self.model} {self.trim or ''}".strip(),
            f"Segment: {self.ai_segment or 'N/A'}",
            f"Tags: {', '.join(self.ai_lifestyle_tags)}",
            f"Price: ${self.price:,.0f}  |  Mileage: {self.mileage:,}km",
            f"Fuel: {self.fuel_type or 'N/A'}  |  Transmission: {self.transmission or 'N/A'}",
            f"Seats: {self.seats or 'N/A'}  |  Body: {self.body_type or 'N/A'}",
        ]
        if self.features:
            parts.append(f"Features: {', '.join(self.features[:15])}")  # cap at 15
        if self.ai_summary:
            parts.append("---")
            parts.append(self.ai_summary)
        if self.ai_selling_points:
            parts.append(f"Selling points: {', '.join(self.ai_selling_points)}")
        if self.ai_comparable_models:
            parts.append(f"Similar to: {', '.join(self.ai_comparable_models)}")

        return "\n".join(parts)

    def qdrant_metadata(self) -> dict:
        """
        Flat metadata dict for Qdrant payload filtering.
        Only store filterable fields here — keep it lean.
        """
        return {
            "vin":            self.vin,
            "dealer_id":      self.dealer_id,
            "make":           self.make,
            "model":          self.model,
            "year":           self.year,
            "price":          self.price,
            "mileage":        self.mileage,
            "fuel_type":      self.fuel_type,
            "transmission":   self.transmission,
            "body_type":      self.body_type,
            "seats":          self.seats,
            "stock_status":   self.stock_status,
            "ai_segment":     self.ai_segment,
            "ai_lifestyle_tags": self.ai_lifestyle_tags,
            "condition":      self.condition,
            "embedding_model": self.embedding_model,
        }


# ─────────────────────────────────────────────────────────────
# VALIDATION ERROR RECORD  (for quarantine table)
# ─────────────────────────────────────────────────────────────

class ValidationError(BaseModel):
    raw_row:      dict
    error_detail: str
    source_file:  Optional[str] = None
    row_number:   Optional[int] = None
    created_at:   datetime      = Field(default_factory=utcnow)
