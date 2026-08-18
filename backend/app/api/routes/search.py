"""
Phase 3 — Semantic search endpoint.

Flow: embed the query locally → filter + ANN search inside Qdrant (one round
trip, payload filters) → hydrate full records from PostgreSQL in Qdrant's
relevance order. Results are cached in Redis (best-effort) keyed by the request.
"""

from __future__ import annotations

import hashlib
import json

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.query_intent import lex_bonus, parse_price_intent, query_terms
from app.etl.embedder import embed_query, get_qdrant
from app.models.inventory import VehicleInventory
from app.schemas.search import SearchHit, SearchRequest, SearchResponse, VehicleOut

log = structlog.get_logger()
router = APIRouter()

# Best-effort cache — search never fails just because Redis is down.
_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
CACHE_TTL = 300  # seconds

# ── Hybrid lexical rerank + budget intent ────────────────────
# Over-fetch ANN candidates, then add a *bounded* lexical bonus so exact
# make/model/segment matches surface above near-tied vector scores, and let
# budget/luxury intent nudge ordering by price. The pure helpers
# (query_terms / lex_bonus / parse_price_intent) live in app.core.query_intent
# so they carry no FastEmbed/Qdrant import weight and are unit-testable.
_RERANK_POOL = 40   # candidates pulled from Qdrant before reranking
_PRICE_W     = 0.5  # weight of the budget/luxury price preference on ordering
                    # (large vs the ~0.04 cosine spread, so an explicit "cheap"
                    #  clearly leads with price within the pool)


def _build_filter(req: SearchRequest) -> Filter | None:
    """Translate the request's structured filters into a Qdrant payload filter.

    Values are normalised to how the payload stores them: make is title-cased,
    fuel/body are lower-cased enum values, segment/stock_status are verbatim.
    """
    must: list[FieldCondition] = []

    if req.stock_status and req.stock_status.lower() != "all":
        must.append(FieldCondition(key="stock_status", match=MatchValue(value=req.stock_status)))
    if req.make:
        must.append(FieldCondition(key="make", match=MatchValue(value=req.make.strip().title())))
    if req.fuel_type:
        must.append(FieldCondition(key="fuel_type", match=MatchValue(value=req.fuel_type.strip().lower())))
    if req.body_type:
        must.append(FieldCondition(key="body_type", match=MatchValue(value=req.body_type.strip().lower())))
    if req.segment:
        must.append(FieldCondition(key="ai_segment", match=MatchValue(value=req.segment)))
    if req.seats is not None:
        must.append(FieldCondition(key="seats", match=MatchValue(value=req.seats)))
    if req.min_price is not None or req.max_price is not None:
        must.append(FieldCondition(key="price", range=Range(gte=req.min_price, lte=req.max_price)))
    if req.min_year is not None or req.max_year is not None:
        must.append(FieldCondition(key="year", range=Range(gte=req.min_year, lte=req.max_year)))

    return Filter(must=must) if must else None


@router.post("", response_model=SearchResponse)
@router.post("/", response_model=SearchResponse, include_in_schema=False)
async def search(req: SearchRequest, db: AsyncSession = Depends(get_db)):
    cache_key = "search:" + hashlib.sha1(req.model_dump_json().encode()).hexdigest()

    # ── 1. Cache lookup (best-effort) ─────────────────────────
    try:
        hit = await _redis.get(cache_key)
        if hit:
            data = json.loads(hit)
            data["cached"] = True
            return data
    except Exception as e:  # noqa: BLE001 — cache must never break search
        log.warning("cache_read_failed", error=str(e))

    # ── 1b. Budget intent: hard price bounds + a soft ordering direction ──
    # Explicit amounts only fill bounds the caller didn't set; qualitative
    # "cheap"/"luxury" just steers ordering (price_dir), never a hard cap.
    min_p, max_p, price_dir = parse_price_intent(req.query)
    if req.min_price is None and min_p is not None:
        req.min_price = min_p
    if req.max_price is None and max_p is not None:
        req.max_price = max_p

    # ── 2. Embed + filtered ANN search in Qdrant ──────────────
    # Over-fetch a candidate pool when reranking, then trim to req.limit.
    candidate_limit = max(req.limit, _RERANK_POOL) if req.rerank else req.limit
    vector = embed_query(req.query)
    result = get_qdrant().query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        query_filter=_build_filter(req),
        limit=candidate_limit,
        with_payload=True,
    )
    points = result.points
    if not points:
        return SearchResponse(query=req.query, count=0, results=[])

    # ── 3. Hydrate full records from PostgreSQL ───────────────
    ann = {p.payload["vin"]: p.score for p in points}
    vins = list(ann.keys())
    rows = (await db.execute(
        select(VehicleInventory).where(VehicleInventory.vin.in_(vins))
    )).scalars().all()
    by_vin = {r.vin: r for r in rows}

    # ── 4. Rank: semantic relevance (+ bounded lexical bonus), with a soft
    #        price preference deciding order for budget/luxury intent. The
    #        *displayed* score stays the semantic relevance — the gauge reports
    #        match confidence, not the price nudge.
    terms = query_terms(req.query) if req.rerank else set()
    prices = [
        float(by_vin[v].price) for v in vins
        if v in by_vin and by_vin[v].price is not None
    ]
    p_min = min(prices) if prices else 0.0
    p_span = (max(prices) - p_min if prices else 1.0) or 1.0

    def _price_pref(v) -> float:
        if price_dir is None or v.price is None:
            return 0.0
        norm = (float(v.price) - p_min) / p_span  # 0 = cheapest … 1 = priciest
        return _PRICE_W * ((1.0 - norm) if price_dir == "low" else norm)

    scored = []
    for vin in vins:
        v = by_vin.get(vin)
        if v is None:
            continue
        relevance = ann[vin] + lex_bonus(terms, v)
        scored.append((relevance + _price_pref(v), relevance, v))
    scored.sort(key=lambda t: t[0], reverse=True)

    results = [
        SearchHit(score=round(min(relevance, 1.0), 4),
                  vehicle=VehicleOut.model_validate(v))
        for _order, relevance, v in scored[:req.limit]
    ]

    resp = SearchResponse(query=req.query, count=len(results), cached=False, results=results)

    # ── 4. Cache store (best-effort) ──────────────────────────
    try:
        await _redis.set(cache_key, resp.model_dump_json(), ex=CACHE_TTL)
    except Exception as e:  # noqa: BLE001
        log.warning("cache_write_failed", error=str(e))

    return resp
