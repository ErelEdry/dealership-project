"""
Phase 2 — Embedder
-------------------
1. Takes an EnrichedVehicle
2. Builds the rich embedding document (text string)
3. Generates a 768-dim vector locally via FastEmbed (BAAI/bge-base-en-v1.5)
4. Upserts the vector + metadata payload into Qdrant

No external API key required — the model runs inside the container.
Model is downloaded once (~130 MB) and cached automatically.

Usage:
    from app.etl.embedder import embed_vehicle, ensure_collection
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Optional

import structlog
from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.core.config import settings
from app.schemas.inventory import EnrichedVehicle

log = structlog.get_logger()

# ── Clients (initialised once at import time) ────────────────
# FastEmbed downloads the model on first use (~130 MB), then caches it.
# cache_dir is a named Docker volume, so the model survives container
# recreation instead of re-downloading into the writable layer each time.
_embedder = TextEmbedding(
    model_name=settings.embedding_model,
    cache_dir=settings.embedding_cache_dir,
)

_qdrant = QdrantClient(
    host=settings.qdrant_host,
    port=settings.qdrant_port,
)


# ── Qdrant collection setup ──────────────────────────────────

def ensure_collection() -> None:
    """
    Create the Qdrant collection if it doesn't exist yet.
    Safe to call multiple times — idempotent.
    """
    existing = [c.name for c in _qdrant.get_collections().collections]

    if settings.qdrant_collection not in existing:
        _qdrant.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(
                size=settings.embedding_dimensions,   # 768 for bge-base-en-v1.5
                distance=Distance.COSINE,
            ),
        )
        log.info(
            "qdrant_collection_created",
            collection=settings.qdrant_collection,
            dimensions=settings.embedding_dimensions,
        )
    else:
        log.info("qdrant_collection_exists", collection=settings.qdrant_collection)


# ── Embedding ────────────────────────────────────────────────

def _get_embedding(text: str) -> list[float]:
    """
    Generate a 768-dim embedding vector locally using FastEmbed.
    BAAI/bge-base-en-v1.5 is optimised for semantic search / retrieval.

    Vehicle documents are embedded as *passages* (plain .embed(), no instruction).
    """
    # embed() returns a generator of numpy arrays
    vectors = list(_embedder.embed([text]))
    return vectors[0].tolist()


def embed_query(text: str) -> list[float]:
    """
    Embed a search query. bge models are asymmetric: queries get a short
    retrieval instruction that passages do not, so use FastEmbed's query_embed
    (documents above were stored with the plain passage embedding).
    """
    vectors = list(_embedder.query_embed([text]))
    return vectors[0].tolist()


def get_qdrant() -> QdrantClient:
    """Expose the shared Qdrant client to the API layer (avoids a second client)."""
    return _qdrant


# ── Qdrant upsert ────────────────────────────────────────────

def vin_to_point_id(vin: str) -> int:
    """
    Derive a Qdrant point ID from a VIN.

    Uses MD5 rather than the builtin hash(): Python randomises string hashing
    per process (PYTHONHASHSEED), so hash(vin) returns a different value on
    every run. That would make re-runs insert duplicate points instead of
    updating the existing one, orphaning the previous vector.
    """
    return int(hashlib.md5(vin.encode()).hexdigest()[:16], 16) % (2 ** 63)


def _upsert_to_qdrant(vehicle: EnrichedVehicle, vector: list[float]) -> str:
    """
    Upsert one point to Qdrant.
    Uses a stable, process-independent ID derived from the VIN.
    Returns the point ID string.
    """
    point_id = vin_to_point_id(vehicle.vin)

    _qdrant.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload=vehicle.qdrant_metadata(),
            )
        ],
    )
    return str(point_id)


# ── Public API ───────────────────────────────────────────────

async def embed_vehicle(vehicle: EnrichedVehicle) -> Optional[str]:
    """
    Build embedding doc → generate vector locally → upsert to Qdrant.
    Returns the Qdrant point ID on success, None on failure.
    """
    try:
        doc      = vehicle.build_embedding_document()
        vector   = await asyncio.to_thread(_get_embedding, doc)
        point_id = await asyncio.to_thread(_upsert_to_qdrant, vehicle, vector)

        log.info(
            "embed_success",
            vin=vehicle.vin,
            point_id=point_id,
            doc_length=len(doc),
        )
        return point_id

    except Exception as e:
        log.error("embed_failed", vin=vehicle.vin, error=str(e))
        return None
