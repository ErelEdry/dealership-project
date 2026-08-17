# AI Car Dealership — Project Progress

**Last verified:** 2026-08-17 · **Status:** Phases 1–2 complete, Phase 3 not started

> This is a *current state* snapshot. For the chronological build history and
> the errors hit along the way, see [SESSION_LOG.md](SESSION_LOG.md).

---

## Status at a glance

| Phase | Scope | Status |
|---|---|---|
| 1 | Infrastructure, schema, ingestion, validation | ✅ Complete |
| 2 | AI enrichment + embedding pipeline | ✅ Complete — 1,000/1,000 vehicles |
| 3 | RAG search API | ⬜ Not started — retrieval proven, endpoints unwritten |
| 4 | Frontend (Next.js) | ⬜ Not started |
| 5 | Production hardening | ⬜ Not started |

All five Docker services run. All data survived a ~3-month idle period intact.

---

## What's actually in the system

Verified by direct query on 2026-08-17:

| Metric | Value |
|---|---|
| Vehicles in PostgreSQL | 1,000 (all with `enriched_at`) |
| Qdrant points | 1,000 · 768-dim · cosine |
| Rows with null `ai_summary` or `vector_id` | 0 |
| Validation quarantine (`validation_errors`) | 0 rows |
| Avg AI confidence | 0.767 |
| Flagged `needs_review` (confidence < 0.7) | 76 |
| Distinct makes | 20 |
| Model years | 2000–2025 |
| Price range | €17,500 – €155,000 |

**Stock status:** workshop 265 · available 260 · reserved 250 · sold 225
**Fuel type:** electric 381 · petrol 316 · hybrid 303 *(no diesel in this dataset)*

---

## Architecture

```
data/sample/inventory.csv
        │
        ▼
   ingestor.py      Pydantic validation, 6 custom field validators
        │           failures → validation_errors table (currently 0)
        ▼
   enricher.py      Groq · openai/gpt-oss-20b
        │           → tags, segment, summary, selling points, comparables, confidence
        │           tenacity: 3 attempts, exponential backoff 2–30s
        ▼
   embedder.py      FastEmbed · BAAI/bge-base-en-v1.5 (local, 768 dims, no API key)
        │           point ID = MD5(VIN) — deterministic across processes
        ├──────────────────────────► Qdrant  (vector + filterable payload)
        └──────────────────────────► PostgreSQL (full record, upsert on VIN)
```

**Services:** FastAPI · PostgreSQL 16 · Redis 7 · Qdrant · pgAdmin
**Named volumes:** `postgres_data` · `redis_data` · `qdrant_data` · `pgadmin_data` · `fastembed_cache`

---

## Running it

```bash
# Bring the stack up
docker compose up -d

# Health check
curl http://localhost:8000/health

# Pipeline — skips already-enriched vehicles unless --force
docker compose exec api python -m app.etl.pipeline --limit 10
docker compose exec api python -m app.etl.pipeline

# One-time point-ID migration (idempotent; dry-run without --apply)
docker compose exec api python -m scripts.migrate_point_ids
```

**Interfaces:** API docs `:8000/docs` · Qdrant dashboard `:6333/dashboard` · pgAdmin `:5050`

---

## Verified working

- **Semantic search end-to-end.** Query *"cheap fuel efficient city car for a student"*
  returns VW Polo (0.707), Hyundai Elantra (0.706), Toyota Corolla (0.702),
  Renault Clio (0.699), Fiat Panda (0.698). Retrieval quality is sound.
- **Pipeline re-runs.** `--limit 3 --force` → 3 processed, 0 failed, confidence 0.90,
  and the Qdrant point count held at exactly 1,000 (no duplication).
- **Data integrity.** All 1,000 PostgreSQL `vector_id` values resolve to Qdrant
  points with matching VINs — 0 mismatches.

---

## Known issues and tech debt

### 1. `ai_segment` is uncontrolled free text — blocks faceted filtering
The LLM was never given a fixed segment vocabulary, so 1,000 vehicles produced
**68 distinct segment values**, 12 of them appearing exactly once. Near-duplicates
abound: `Pickup` (33) vs `Pickup Truck` (22); `Compact Car` (58) vs `City Car` (39)
vs `Supermini` (32). `Compact SUV` alone absorbs 351.

This is fine for embedding text but unusable as a filter facet in Phase 3.
Fix by either constraining the enrichment prompt to an approved list (as was
already done for `ai_lifestyle_tags`) or mapping the 68 values onto a canonical
set at query time.

### 2. Mixed enrichment provenance
997 vehicles carry output from the retired `llama-3.1-8b-instant`; 3 were
re-enriched with `openai/gpt-oss-20b` during testing. Harmless, but a full
`--force` re-run (~35 min at the current 2.0s delay) would make the corpus uniform.

### 3. Only 26% of inventory is actually purchasable
260 `available` out of 1,000. Search endpoints should filter on `stock_status`
by default or results will be dominated by workshop/sold vehicles.

### 4. Bind-mount race on Docker cold boot
The `./backend:/app` mount can start before Docker Desktop's file-sharing layer
is ready, leaving `/app` empty and uvicorn logging `Could not import module "main"`.
Environmental, not fixable from compose. Clear it with:
`docker compose up -d --force-recreate api`

### 5. Minor
- `datetime.utcnow()` is deprecated on Python 3.12 — still used in
  `app/models/inventory.py` and `app/schemas/inventory.py`.
- `csv` is imported but unused in `app/etl/pipeline.py`.
- Source CSV has no `trim`, `engine`, `doors`, `colour_*`, or `features` columns,
  so enrichment runs on a thinner spec sheet than the schema allows for.

---

## Next up — Phase 3 (RAG search API)

The hard part is already proven; this is wiring. [app/api/routes/](backend/app/api/routes/)
is currently empty and the routers in [main.py](backend/main.py) are commented out.

**Endpoints**
- `POST /api/search` — embed query locally → Qdrant search → PostgreSQL filter/rerank
- `GET  /api/vehicles/{vin}` — full detail
- `GET  /api/vehicles` — paginated listing with filters

**Decisions to make before writing code**
- Filter *inside* Qdrant (payload filters, one round trip) or post-filter in
  PostgreSQL? Payload already carries price, year, make, fuel, body, seats,
  `stock_status`, and `ai_segment`.
- Default `stock_status` filter — see issue 3 above.
- Redis cache key and TTL for repeated queries.
- Whether to normalise `ai_segment` first — see issue 1.

**Note:** `qdrant-client` is now 1.12.1, so use `query_points()`. The older
`search()` still works but is deprecated.
