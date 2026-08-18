"""
SQLAlchemy ORM models for the inventory pipeline.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer,
    JSON, String, Text
)
from sqlalchemy.orm import DeclarativeBase


def utcnow() -> datetime:
    """Timezone-aware UTC now. Replaces the deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class VehicleInventory(Base):
    """
    Master inventory table.
    One row per vehicle (keyed by VIN).
    All ai_ columns are NULL until enrichment runs.
    """
    __tablename__ = "vehicle_inventory"

    # ── Primary key ───────────────────────────────────────────
    vin        = Column(String(17),  primary_key=True)
    dealer_id  = Column(String(50),  nullable=False, index=True)
    stock_id   = Column(String(50),  nullable=True)

    # ── Core specs ────────────────────────────────────────────
    make         = Column(String(50),  nullable=False, index=True)
    model        = Column(String(100), nullable=False, index=True)
    year         = Column(Integer,     nullable=False, index=True)
    trim         = Column(String(100), nullable=True)
    body_type    = Column(String(30),  nullable=True)
    fuel_type    = Column(String(30),  nullable=True)
    transmission = Column(String(30),  nullable=True)
    engine       = Column(String(100), nullable=True)
    seats        = Column(Integer,     nullable=True)
    doors        = Column(Integer,     nullable=True)

    # ── Condition & pricing ───────────────────────────────────
    mileage          = Column(Integer, nullable=False)
    price            = Column(Float,   nullable=False)
    acquisition_cost = Column(Float,   nullable=True)  # dealer's buy-in cost
    condition        = Column(String(20), nullable=True)
    colour_ext       = Column(String(50), nullable=True)
    colour_int       = Column(String(50), nullable=True)

    # ── Media & features (stored as JSON arrays) ──────────────
    features   = Column(JSON, default=list)
    images     = Column(JSON, default=list)

    # ── Stock status ──────────────────────────────────────────
    stock_status = Column(String(20), nullable=False, default="available", index=True)

    # ── Dealership metadata ───────────────────────────────────
    arrived_date = Column(String(20), nullable=True)   # date entered lot

    # ── AI enrichment fields ──────────────────────────────────
    ai_lifestyle_tags    = Column(JSON,    nullable=True)
    ai_segment           = Column(String(100), nullable=True)
    ai_summary           = Column(Text,    nullable=True)
    ai_selling_points    = Column(JSON,    nullable=True)
    ai_comparable_models = Column(JSON,    nullable=True)
    ai_confidence        = Column(Float,   nullable=True)

    # ── Vector / embedding metadata ───────────────────────────
    content_hash    = Column(String(32),  nullable=True)   # MD5 for change detection
    embedding_doc   = Column(Text,        nullable=True)   # assembled text
    embedding_model = Column(String(100), nullable=True)   # model version
    vector_id       = Column(String(100), nullable=True)   # Qdrant point ID

    # ── Pipeline state ────────────────────────────────────────
    needs_review = Column(Boolean,  default=False, index=True)
    enriched_at  = Column(DateTime, nullable=True)
    source_file  = Column(String(255), nullable=True)
    ingested_at  = Column(DateTime, default=utcnow)
    updated_at   = Column(DateTime, default=utcnow, onupdate=utcnow)


class ValidationErrorLog(Base):
    """
    Quarantine table for rows that failed Pydantic validation.
    Never lost, always fixable.
    """
    __tablename__ = "validation_errors"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    raw_row      = Column(JSON,       nullable=False)   # original row as-received
    error_detail = Column(Text,       nullable=False)
    source_file  = Column(String(255), nullable=True)
    row_number   = Column(Integer,    nullable=True)
    created_at   = Column(DateTime,   default=utcnow)
