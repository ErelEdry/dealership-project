"""
Phase 3 — API request/response schemas for search and vehicle listing.

VehicleOut is buyer-facing: it deliberately omits `acquisition_cost` (the
dealer's internal buy-in cost) and pipeline internals (embedding_doc, vector_id).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─────────────────────────────────────────────────────────────
# Output — a vehicle as returned to clients
# ─────────────────────────────────────────────────────────────

class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vin:          str
    dealer_id:    Optional[str] = None
    stock_id:     Optional[str] = None
    make:         str
    model:        str
    year:         int
    trim:         Optional[str] = None
    body_type:    Optional[str] = None
    fuel_type:    Optional[str] = None
    transmission: Optional[str] = None
    engine:       Optional[str] = None
    seats:        Optional[int] = None
    doors:        Optional[int] = None
    mileage:      int
    price:        float
    condition:    Optional[str] = None
    colour_ext:   Optional[str] = None
    colour_int:   Optional[str] = None
    features:     list = Field(default_factory=list)
    images:       list = Field(default_factory=list)
    stock_status: str

    ai_lifestyle_tags:    list = Field(default_factory=list)
    ai_segment:           Optional[str] = None
    ai_summary:           Optional[str] = None
    ai_selling_points:    list = Field(default_factory=list)
    ai_comparable_models: list = Field(default_factory=list)
    ai_confidence:        Optional[float] = None
    needs_review:         Optional[bool] = None

    @field_validator(
        "features", "images", "ai_lifestyle_tags",
        "ai_selling_points", "ai_comparable_models",
        mode="before",
    )
    @classmethod
    def _none_to_list(cls, v):
        """JSON columns can be NULL in the DB — normalise to an empty list."""
        return v or []


# ─────────────────────────────────────────────────────────────
# Semantic search
# ─────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=400,
                       description="Natural-language search, e.g. 'family SUV under 40k'")
    limit: int = Field(10, ge=1, le=50)

    # Optional structured filters (applied inside Qdrant)
    make:         Optional[str]   = None
    fuel_type:    Optional[str]   = None
    body_type:    Optional[str]   = None
    segment:      Optional[str]   = Field(None, description="Canonical ai_segment, e.g. 'Compact SUV'")
    min_price:    Optional[float] = Field(None, ge=0)
    max_price:    Optional[float] = Field(None, ge=0)
    min_year:     Optional[int]   = None
    max_year:     Optional[int]   = None
    seats:        Optional[int]   = Field(None, ge=1, le=15)
    # Defaults to only purchasable stock; pass "all" to include everything.
    stock_status: Optional[str]   = "available"
    # Blend a bounded lexical bonus into the vector score (hybrid search) so
    # exact make/model/segment matches surface. Set false for pure ANN order.
    rerank:       bool            = True


class SearchHit(BaseModel):
    score:   float
    vehicle: VehicleOut


class SearchResponse(BaseModel):
    query:   str
    count:   int
    cached:  bool = False
    results: list[SearchHit]


# ─────────────────────────────────────────────────────────────
# Paginated listing
# ─────────────────────────────────────────────────────────────

class VehicleListResponse(BaseModel):
    total:     int
    page:      int
    page_size: int
    results:   list[VehicleOut]


# ─────────────────────────────────────────────────────────────
# Facets (for UI filter chips)
# ─────────────────────────────────────────────────────────────

class FacetCount(BaseModel):
    value: str
    count: int


class FacetsResponse(BaseModel):
    total:        int
    make:         list[FacetCount]
    fuel_type:    list[FacetCount]
    body_type:    list[FacetCount]
    ai_segment:   list[FacetCount]
    stock_status: list[FacetCount]
    price_min:    Optional[float] = None
    price_max:    Optional[float] = None
    year_min:     Optional[int]   = None
    year_max:     Optional[int]   = None
