# AI Car Dealership — Project Session Log

> **Project:** AI-powered car dealership inventory & recommendation system  
> **Stack:** FastAPI · PostgreSQL · Redis · Qdrant · Groq (openai/gpt-oss-20b) · FastEmbed (local)  
> **Dataset:** 1,000 Spanish vehicles converted from SQLite → CSV  

---

## Phase 1 — Infrastructure (Previous Session)

### What Was Built
- Full Docker Compose stack: FastAPI, PostgreSQL 16, Redis 7, Qdrant, pgAdmin
- Pydantic v2 schemas (`RawVehicle`, `EnrichedVehicle`, `AIEnrichmentOutput`)
- SQLAlchemy async models + Alembic migration (`001_initial_schema.py`)
- Dataset B (Spanish SQLite) converted to `data/sample/inventory.csv` (1,000 vehicles, 20 brands)
- Ingestor/validator with 6 custom field validators

### Key Decisions
| Decision | Choice | Reason |
|---|---|---|
| LLM provider | Groq (final) | Gemini free tier blocked on school/workspace accounts |
| Embeddings | FastEmbed local | No API key, no quota, runs in container |
| Embedding model | `BAAI/bge-base-en-v1.5` | 768 dims, ~130 MB, same dims as original Gemini plan |
| Vector DB | Qdrant | Purpose-built, cosine similarity, easy Docker setup |
| Dataset | Spanish SQLite (Dataset B) | More realistic, 20 brands, richer condition data |

### Phase 1 Errors & Fixes
| Error | Fix |
|---|---|
| `docker` not found in WSL2 | Docker Desktop → Resources → WSL Integration → enable toggles |
| Permission denied on Docker socket | `sudo usermod -aG docker $USER` |
| pgAdmin crash loop | Email `admin@dealership.local` rejected — changed to valid format |
| 6 rows with negative mileage | Generator bug — wrapped with `max(0, ...)`, regenerated CSV |
| Alembic migration file truncated | Raw bytes regex replace to restore missing line |

---

## Phase 2 — AI Enrichment Pipeline (This Session)

### Architecture
```
CSV → validate → Groq enrich → FastEmbed embed → Qdrant + PostgreSQL
```

### Files Created / Modified

#### `backend/app/etl/enricher.py`
- Calls Groq `llama-3.1-8b-instant` with structured JSON prompt
- Returns validated `AIEnrichmentOutput` (lifestyle tags, segment, summary, selling points, comparable models, confidence)
- Tenacity retry: 3 attempts, exponential backoff 2–30s
- Compact prompt to stay within free-tier token limits (~300 tokens/vehicle)

#### `backend/app/etl/embedder.py`
- Uses `fastembed.TextEmbedding` with `BAAI/bge-base-en-v1.5` (768 dims, local)
- Model downloaded once (~130 MB) on first run, then cached
- Upserts to Qdrant with VIN-derived stable integer point ID
- `ensure_collection()` creates Qdrant collection idempotently at startup

#### `backend/app/etl/pipeline.py`
- CLI: `docker compose exec api python -m app.etl.pipeline [--limit N] [--force]`
- Skips already-enriched vehicles unless `--force`
- Prints live progress with segment + confidence per vehicle
- Sync SQLAlchemy engine (psycopg2) for CLI use
- Fixed `datetime.utcnow()` → `datetime.now(timezone.utc)`

#### `backend/requirements.txt`
```
groq==0.11.0          # enrichment
fastembed==0.3.6      # local embeddings, no API key
```
Removed: `google-generativeai` (was blocked by school account free-tier policy)

#### `backend/app/core/config.py`
```python
groq_api_key:      str = ""
groq_chat_model:   str = "llama-3.1-8b-instant"
embedding_model:   str = "BAAI/bge-base-en-v1.5"
embedding_dimensions: int = 768
```

#### `.env` (required values)
```env
GROQ_API_KEY=gsk_...          # from console.groq.com (free)
GEMINI_API_KEY=               # no longer needed
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
EMBEDDING_DIMENSIONS=768
QDRANT_COLLECTION=vehicles_v1
```

---

## Phase 2 Errors & Fixes (Chronological)

### 1. Gemini quota `limit: 0` for `gemini-2.0-flash`
**Error:** `GenerateRequestsPerDayPerProjectPerModel-FreeTier limit: 0`  
**Cause:** School email = Google Workspace account → free tier disabled at org level  
**Fix:** Switched enrichment to Groq (free for any account)

### 2. `KeyError: 'GEMINI_API_KEY'`
**Cause:** Key named `Gemini_API_KEY` (wrong case) in `.env` — Docker env is case-sensitive  
**Fix:** Renamed to `GEMINI_API_KEY` (all caps)

### 3. `gemini-1.5-flash` → 404 Not Found
**Cause:** `google-generativeai==0.8.3` uses v1beta API; `gemini-1.5-*` models not available on this account  
**Fix:** Listed available models with `genai.list_models()` → confirmed no 1.5 models → switched to Groq entirely

### 4. `DefaultCredentialsError` on embeddings
**Cause:** `GEMINI_API_KEY` was empty; SDK fell back to Google Application Default Credentials (not found)  
**Fix:** Replaced Gemini embeddings with FastEmbed (local, no key needed)

### 5. `EMBEDDING_MODEL=models/text-embedding-004` in `.env` overriding config
**Cause:** Old `.env` value persisted after code change  
**Fix:** `sed -i 's|EMBEDDING_MODEL=models/text-embedding-004|EMBEDDING_MODEL=BAAI/bge-base-en-v1.5|' .env`

### 6. Groq TPD limit hit at vehicle 159
**Error:** `Rate limit reached for llama-3.3-70b-versatile, Limit 100000, Used 99793`  
**Cause:** 100K tokens/day limit for `llama-3.3-70b`; 1,000 vehicles × ~633 tokens = 633K tokens  
**Fix:** Switched to `llama-3.1-8b-instant` (500K TPD) + trimmed prompts (~300 tokens/vehicle)

### 7. Qdrant collection created with wrong 1536 dims
**Cause:** Old `.env` had `EMBEDDING_DIMENSIONS` from OpenAI days  
**Fix:** 
```bash
docker compose exec api python -c "
from qdrant_client import QdrantClient
c = QdrantClient(host='qdrant', port=6333)
c.delete_collection('vehicles_v1')
"
```
Collection recreated automatically on next pipeline run with correct 768 dims.

---

## Pipeline Commands

```bash
# Test — first 10 vehicles
docker compose exec api python -m app.etl.pipeline --limit 10

# Test + force re-enrich already-processed vehicles
docker compose exec api python -m app.etl.pipeline --limit 10 --force

# Full run — all 1,000 vehicles (skips already-enriched)
docker compose exec api python -m app.etl.pipeline

# List available Groq/Gemini models (diagnostic)
docker compose exec api python -c "
import os, google.generativeai as genai
genai.configure(api_key=os.environ['GEMINI_API_KEY'])
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)
"

# Delete Qdrant collection (if wrong dims)
docker compose exec api python -c "
from qdrant_client import QdrantClient
c = QdrantClient(host='qdrant', port=6333)
c.delete_collection('vehicles_v1')
"

# Rebuild after requirements.txt change
docker compose build api && docker compose up -d --force-recreate api
```

---

## Current State (as of this session)

| Component | Status |
|---|---|
| Docker stack (5 services) | ✅ Running |
| PostgreSQL schema + migrations | ✅ Applied |
| 1,000 vehicle CSV | ✅ Generated |
| Phase 1 ingestor/validator | ✅ Working |
| Groq enrichment (llama-3.1-8b-instant) | ✅ Working |
| FastEmbed local embeddings (768 dim) | ✅ Working |
| Qdrant vector storage | ✅ Working |
| Full pipeline (enrich + embed + store) | ✅ Working |
| Vehicles enriched & embedded | ✅ 1,000/1,000 (completed 2026-05-28) |

---

## Test Batch Results (10 vehicles)

| Vehicle | Segment | Confidence | Notes |
|---|---|---|---|
| 2000 Fiat Panda | City Hatchback | 0.80 | ✓ |
| 2005 Mitsubishi Outlander | Compact SUV | 0.70 | ✓ |
| 2007 Tesla Model 3 | Compact Sedan | 0.80 | ✓ |
| 2009 Ford Explorer | Full-size SUV | 0.70 | ✓ |
| 2001 Kia Rio | City Hatchback | 0.60 | ⚠ low confidence |
| 2020 Suzuki Jimny | Compact SUV | 0.80 | ✓ |
| 2025 Audi Q5 | Compact SUV | 0.70 | ✓ |
| 2017 Chevrolet Equinox | Compact SUV | 0.80 | ✓ |
| 2004 Volvo XC90 | Mid-size SUV | 0.80 | ✓ |
| 2002 Tesla Model S | Full-size Sedan | 0.60 | ⚠ correct — Model S didn't exist in 2002 |

---

## Phase 2.5 — Restart & Repair (2026-08-17)

Picked the project back up after ~3 months idle. First finding: **Phase 2 was
already complete** — the "~158/1,000" note above was written the day before the
full pipeline run and never updated. All four Docker volumes survived intact.

### Verified state on return
| Check | Result |
|---|---|
| Vehicles in PostgreSQL | 1,000 / 1,000, all with `enriched_at` |
| Qdrant points | 1,000 (768-dim, cosine) |
| Null summaries / vector_ids | 0 |
| Validation quarantine | 0 rows |
| Avg AI confidence | 0.766 (76 flagged `needs_review`) |
| PG `vector_id` → Qdrant cross-check | 500 sampled, 0 mismatches |
| Semantic search smoke test | Working — sensible results at ~0.70 similarity |

### What broke over the 3 months
| Issue | Fix |
|---|---|
| Groq retired `llama-3.1-8b-instant` (all Llama chat models gone) | Switched to `openai/gpt-oss-20b` — drop-in, no prompt changes. `qwen/qwen3.6-27b` was tested and fails: reasoning tokens exhaust the budget before valid JSON |
| API container dead — `./backend:/app` bind mount raced ahead of Docker Desktop's file sharing on cold start, so `/app` was empty and uvicorn logged `Could not import module "main"` | `docker compose up -d --force-recreate api`. Expect this after any Docker cold boot |

### Bugs fixed
| Bug | Fix |
|---|---|
| `embedder.py` used `abs(hash(vin))` for "stable" point IDs — Python randomises string hashing per process, so every run produced different IDs. A `--force` re-run would have inserted duplicate points and orphaned the old vectors | Replaced with `vin_to_point_id()` using MD5. Verified identical across separate processes |
| The 1,000 existing points still carried the old random IDs | One-time migration `scripts/migrate_point_ids.py` re-keyed all 1,000 in place (vectors copied, nothing re-embedded), updated PG `vector_id`, deleted orphans. Idempotent — re-running reports "nothing to do" |
| FastEmbed's ~130 MB model cached to `/tmp` in the container's writable layer, re-downloading on every recreate | `cache_dir` now points at a named volume (`fastembed_cache:/opt/fastembed_cache`). Load time 15.4s → 4.5s on second run |
| `ENRICH_DELAY = 4.5` was sized for Gemini's old 15 RPM free tier | Lowered to 2.0s (~30 RPM). Dead `EMBED_DELAY` constant removed |
| `qdrant-client==1.9.1` predates `query_points()` | Bumped to 1.12.1 |
| No version control at all — 3 months of work, no history | `git init` + first commit. `.gitignore` already excluded `.env` |

### Post-fix verification
- `pipeline --limit 3 --force` → 3 processed, 0 failed, confidence 0.90
- Qdrant point count held at exactly **1,000** through the forced re-run — duplication bug confirmed gone
- Search results byte-identical before and after the ID migration (vectors preserved)

---

## What's Next

### Phase 3 — RAG Search Engine
FastAPI endpoints for natural-language vehicle search:
- `POST /api/search` — takes a plain-English query, embeds it locally, searches Qdrant, reranks with PostgreSQL filters
- `GET /api/vehicles/{vin}` — full vehicle detail
- `GET /api/vehicles` — paginated listing with filters
- Redis caching for repeated queries

### Phase 4 — Frontend
React/Next.js UI with:
- Natural language search bar
- Vehicle cards with AI summary + lifestyle tags
- Booking form (test drive appointment)
- Inventory browsing with filters

### Phase 5 — Production Hardening
- Cohere reranker for search quality
- Auth + rate limiting
- Monitoring + structured logging
- CI/CD pipeline
