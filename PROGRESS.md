# AI Car Dealership — Project Progress

**Last verified:** 2026-08-18 · **Status:** Phases 1–2 complete · issues #1, #3 & #6 fixed · Phase 3 built (+ budget-intent search) · Phase 4 redesigned (Night-Drive HMI) · **unit tests + CI · retrieval eval · full-stack Docker**

> This is a *current state* snapshot. For the chronological build history and
> the errors hit along the way, see [docs/SESSION_LOG.md](docs/SESSION_LOG.md).

---

## Status at a glance

| Phase | Scope | Status |
|---|---|---|
| 1 | Infrastructure, schema, ingestion, validation | ✅ Complete |
| 2 | AI enrichment + embedding pipeline | ✅ Complete — 1,000/1,000 vehicles |
| 3 | RAG search API | 🟡 Core built — `/api/search`, `/api/vehicles`, `/api/vehicles/{vin}` live & tested; **+ budget-intent parsing** (cheap/luxury/under €X → price filter + ordering) |
| 4 | Frontend (Next.js) | 🟡 Built + **redesigned** — Night-Drive HMI theme; search, browse (facets), detail; **test-drive booking flow live**; Next 16 + Tailwind v4 |
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
| Avg AI confidence | 0.787 |
| Flagged `needs_review` (confidence < 0.7) | 55 |
| Distinct `ai_segment` (canonical vocab) | 15 (of 17) |
| Distinct makes | 20 |
| Model years | 2000–2025 |
| Price range | €5,000 – €93,750 *(regenerated to realistic values — issue #6)* |

**Stock status:** available 843 · reserved 64 · sold 60 · workshop 33 *(rebalanced ~85% available — issue #3)*
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

# Canonicalise ai_segment on existing rows — no LLM (idempotent; --apply to write)
docker compose exec api python -m scripts.normalize_segments

# Rebalance stock_status to ~85% available across DB + Qdrant + CSV (--apply to write)
docker compose exec api python -m scripts.rebalance_stock_status

# Regenerate realistic prices across DB + Qdrant + CSV; also fixes $→€ in
# summaries and recomputes acquisition_cost (idempotent; --apply to write)
docker compose exec api python -m scripts.regenerate_prices
```

**Interfaces:** API docs `:8000/docs` · Qdrant dashboard `:6333/dashboard` · pgAdmin `:5050`

---

## Verified working

- **Semantic search end-to-end.** Query *"cheap fuel efficient city car for a student"*
  returns cheap City/Compact cars first (€5k–5.25k Fiat 500 / Panda / Suzuki
  Swift / Peugeot 208); *"luxury SUV"* returns €70–80k premium cars. Segment
  retrieval sound; budget intent now orders by price (issue #6 + budget parsing).
- **Pipeline re-runs.** `--limit 3 --force` → 3 processed, 0 failed, confidence 0.90,
  and the Qdrant point count held at exactly 1,000 (no duplication).
- **Data integrity.** All 1,000 PostgreSQL `vector_id` values resolve to Qdrant
  points with matching VINs — 0 mismatches.

---

## Testing & CI

**80 unit tests, all green** (`backend/tests/`, pytest). Focused on the pure
logic that carries real risk — no DB/network needed, so they run in seconds:
- `test_query_intent.py` — budget-intent parsing (explicit bounds, EU/US
  separators, `k`/`grand`, qualitative direction, false-positive guards) +
  lexical rerank bonus (cap enforced). **These tests caught a real bug**:
  `"no more than 30k"` was setting a lower bound too (the `over` pattern's
  `"more than"` matched inside it) — fixed with a `(?<!no )` lookbehind.
- `test_segments.py` — `normalize_segment` exact/alias/keyword/fallback.
- `test_pricing.py` — `regenerate_prices` determinism, €250 rounding, floor,
  segment ordering, depreciation, `acquisition_cost < price`, `$→€` rewrite.
- `test_ingestion_schema.py` — `RawVehicle` coercion (VIN upper, price/mileage
  string parsing, enum values) + constraints + anomaly flags.
- `test_booking_schema.py` — `BookingCreate` validators (future date, phone
  clean, name title, email, min-length).

**Refactor for testability:** the pure query helpers were extracted from
`app/api/routes/search.py` into [app/core/query_intent.py](backend/app/core/query_intent.py)
so they carry no FastEmbed/Qdrant import weight — tests import them without
triggering the 130 MB model load. `search.py` imports them back.

**CI:** [.github/workflows/ci.yml](.github/workflows/ci.yml) runs on push/PR —
a backend job (`ruff check --select F` + `pytest`) and a frontend job
(`npm ci` + `npm run build`). Dev deps in
[requirements-dev.txt](backend/requirements-dev.txt).

**Run locally:**
```bash
docker compose exec api sh -c "pip install -r requirements-dev.txt && pytest"
```

**Not yet tested:** API integration paths (search/vehicles/bookings) — they need
the live stack (Postgres/Qdrant/Redis/embeddings), so they're excluded from the
fast unit CI; the endpoints are verified manually in the sections above.

### Retrieval evaluation harness

[eval/run_eval.py](backend/eval/run_eval.py) scores the search endpoint on a
labelled query set ([golden_queries.json](backend/eval/golden_queries.json), 18
queries) and compares pure ANN vs the hybrid rerank. Relevance is predicate-based
(segment/body/fuel/price band = a scalable proxy for human labels), evaluated
over available stock. Metrics: precision@k, recall@k, MRR, nDCG@k.

**Result (k=10): hybrid rerank beats pure ANN on every metric** —
P@5 0.844→0.911, P@10 0.789→0.844, MRR 0.944→**1.000**, nDCG@10 0.832→0.893.
Run: `docker compose exec api python -m eval.run_eval --detail`.

---

## Known issues and tech debt

### 1. ✅ RESOLVED — `ai_segment` canonicalised
The LLM was never given a fixed segment vocabulary, so 1,000 vehicles produced
**68 distinct free-text values** — unusable as a filter facet.

Fixed by adding a canonical vocabulary ([app/core/segments.py](backend/app/core/segments.py),
17 values + `Other`) that is now the single source of truth. It:
- **constrains the enrichment prompt** ([enricher.py](backend/app/etl/enricher.py)) so
  new enrichment only emits approved values;
- **snaps LLM output** via a validator on `AIEnrichmentOutput.ai_segment`;
- **normalises legacy rows** without spending tokens —
  `scripts.normalize_segments` maps the old free text (exact → alias → keyword
  heuristic → `Other`) across PostgreSQL **and** Qdrant payloads.

Result: **15 distinct canonical segments**, 0 off-vocab. The 10 `Other` rows are
old `Electric Vehicle` labels (a fuel type, not a body segment) awaiting re-enrichment.

### 2. Mixed enrichment provenance — *partially addressed, blocked by token cap*
Originally 997 `llama-3.1-8b-instant` + 3 `gpt-oss-20b`. A full `--force` re-run
was started to make the corpus uniform but **stopped at 169/1,000** when it hit
Groq's free-tier **daily token cap (200,000 TPD)** for `gpt-oss-20b`. The full
1,000 needs ~1.2M tokens (~6 days of free budget).

Current state: **169 `gpt-oss-20b` + 831 `llama`**. Segments and facets are
already uniform (fixed via #1), so this is now purely cosmetic provenance.

**To finish** — resume without redoing the 169 already migrated:
```bash
docker compose exec api python -m app.etl.pipeline --reenrich-before 2026-08-17
```
`--reenrich-before` re-enriches only rows last enriched before that date (the
original 2026-05-28 build) and skips newer ones, so every token targets a
not-yet-migrated vehicle. The cutoff is fixed at 2026-08-17, so repeated daily
runs keep skipping already-done rows and self-terminate once all 831 are done
(~5–6 days on the 200k-TPD free tier, or one shot on Dev Tier).

**Optional automation (Windows):** [daily_reenrich.ps1](daily_reenrich.ps1)
brings the stack up, runs the resume command, and once `scripts.reenrich_status`
reports 0 stale rows **disables its own scheduled task**
(`DealershipAI-ReenrichProvenance`). Logs go to `logs/reenrich_*.log`. The
script's header shows how to register the daily task; manage it with:
```powershell
Get-ScheduledTaskInfo DealershipAI-ReenrichProvenance   # status / next run
Start-ScheduledTask    DealershipAI-ReenrichProvenance   # run now
Unregister-ScheduledTask DealershipAI-ReenrichProvenance -Confirm:$false  # remove
```

The pipeline is now **quota-resilient**: a 429 no longer crashes the run — a
rate-limit/quota error stops it cleanly with a resume note (already-enriched
vehicles are skipped on the next run unless `--force`), and any other per-vehicle
error is logged and skipped instead of aborting. See `_is_rate_limit()` /
the enrichment try-except in [pipeline.py](backend/app/etl/pipeline.py).

### 3. ✅ RESOLVED — inventory rebalanced to ~85% available
Was 260 `available` / 1,000 (26%). `scripts.rebalance_stock_status` reassigns
`stock_status` deterministically per-VIN to **available 843 · reserved 64 ·
sold 60 · workshop 33** across PostgreSQL, Qdrant payloads, and the source CSV
(backup at `data/sample/inventory.csv.bak`), keeping all three in sync and
future `--force` runs consistent. Phase 3 search should still default to
`stock_status='available'`.

### 6. ✅ RESOLVED — prices regenerated to realistic values
The synthetic feed assigned `price` independently of the car (a €155k Fiat 500,
a €17.5k BMW X5, a €17.5k Tesla Model S), so "cheap" searches surfaced €62k
city cars and `/browse` looked absurd. `scripts.regenerate_prices` recomputes a
**deterministic, plausible price per VIN** from segment baseline × brand tier ×
fuel × depreciation(year) × mileage penalty × salted-VIN jitter, synced across
PostgreSQL + Qdrant `price` payload + source CSV (backup at
`data/sample/inventory.csv.bak`). It also **recomputes `acquisition_cost`**
(~85% of the new price, never above it) and **rewrites the stale `$` figures
baked into `ai_summary` to the new €-price with no LLM tokens** (851 fixed, 0
`$` left). New range €5,000–€93,750, monotonic by segment (City Car cheapest →
Luxury Car priciest). Idempotent — price is a pure function of the row.

### 4. Bind-mount race on Docker cold boot
The `./backend:/app` mount can start before Docker Desktop's file-sharing layer
is ready, leaving `/app` empty and uvicorn logging `Could not import module "main"`.
Environmental, not fixable from compose. Clear it with:
`docker compose up -d --force-recreate api`

### 5. Minor
- ✅ `datetime.utcnow()` deprecation fixed — replaced with a tz-aware `utcnow()`
  helper in `app/models/inventory.py` and `app/schemas/inventory.py`.
- ✅ Unused `csv` import removed from `app/etl/pipeline.py`.
- Source CSV has no `trim`, `engine`, `doors`, `colour_*`, or `features` columns,
  so enrichment runs on a thinner spec sheet than the schema allows for. *(data
  limitation — not fixable in code)*

---

## Phase 3 — RAG search API (core built)

Endpoints are live in [main.py](backend/main.py) and tested end-to-end.

**Endpoints**
- `POST /api/search` — [routes/search.py](backend/app/api/routes/search.py):
  embed query locally (`embed_query`, bge query instruction) → filtered ANN
  search in Qdrant (`query_points`) → hydrate full records from PostgreSQL in
  relevance order. Filters: make, fuel, body, segment, seats, price/year ranges.
- `GET /api/vehicles` — [routes/vehicles.py](backend/app/api/routes/vehicles.py):
  paginated, filterable, sortable listing (pure PostgreSQL).
- `GET /api/vehicles/facets` — grouped counts (make/fuel/body/segment/stock) +
  price/year ranges; powers UI filter chips. Uses **per-facet exclusion** (each
  facet applies every filter except its own) so users can pivot within a
  filtered dimension.
- `GET /api/vehicles/{vin}` — full detail (404 on miss).

**Decisions taken**
- **Filtering happens inside Qdrant** (payload filters, one round trip);
  PostgreSQL is used only to hydrate full records by VIN.
- **Default `stock_status='available'`** on both search and listing; pass
  `"all"` to include every status.
- **Redis cache** on `POST /api/search`, key = sha1 of the request JSON, TTL
  300s, best-effort (a Redis outage never breaks search).
- `ai_segment` already canonical (issue #1), so it works as a filter facet.
- `VehicleOut` is buyer-facing — **omits `acquisition_cost`** (dealer buy-in cost).
- **Hybrid rerank** (`rerank`, default on): over-fetch 40 ANN candidates, add a
  bounded lexical bonus (≤0.10) for query-term hits on make/model (0.02 each) and
  segment/body/fuel/tags (0.008 each), re-sort, trim. Dependency-free; a clean
  seam to swap in Cohere / a cross-encoder later.
- **Budget-intent parsing** (`parse_price_intent` in
  [search.py](backend/app/api/routes/search.py)): natural-language price cues in
  the query become structured constraints. Explicit relational amounts
  (*"under €20k"*, *"between 30k and 40k"*, *"around 25k"*; EU/US separators,
  `k`/`grand`) → a **hard Qdrant price filter**. Qualitative words
  (*cheap/budget/affordable* vs *luxury/premium/expensive*) → a **soft price
  preference** (`_PRICE_W`) that decides ordering within the relevant candidate
  pool. Crucially the **displayed match % stays the semantic score** — the price
  nudge reorders but never inflates the gauge. Fixes "cheap → €62k car".

**Verified:** semantic relevance sound (city-car query → Fiat 500 / Suzuki Swift
/ compacts); filters honoured (petrol SUV ≤€40k, 5 seats → all Compact SUV);
cache hit on repeat (`cached:true`); listing pagination/sort; 404 + 422 paths.

**Done in polish pass:** hybrid lexical rerank, `/facets` endpoint, per-facet
exclusion in `/facets`, and budget-intent parsing (see above).

**Not yet done (Phase 3 polish):**
- **Neural reranking** — `settings.cohere_api_key` is reserved but unset, and this
  FastEmbed (0.3.6) predates `fastembed.rerank`. The hybrid lexical rerank is the
  interim; swap in Cohere or a local cross-encoder (needs a key or an image
  rebuild) at the same seam in [search.py](backend/app/api/routes/search.py).
- Search-side handling of `needs_review` / low-confidence vehicles.

**Note:** `qdrant-client` 1.12.1 — uses `query_points()` (not the deprecated `search()`).

---

## Phase 4 — Frontend (Next.js, redesigned)

Lives in [frontend/](frontend/). **Next.js 16 + React 19 + Tailwind v4** (App
Router, TypeScript, `src/`). Runs locally on `:3000` against the API on `:8000`
(CORS already allows that origin). Not containerised yet.

**Design system — "Night-Drive Instrument Cluster".** Replaced the default
indigo/slate MVP look with a dark automotive-HMI identity in
[globals.css](frontend/src/app/globals.css): ink/panel/line/haze/lume tokens +
two fixed-meaning signals — **amber = the car** (price, reserved tell-tale),
**cyan = the AI** (match score, semantic marks). Type is **Archivo** (display) /
**IBM Plex Sans** (body) / **IBM Plex Mono** (telemetry & data). Signature
element: [MatchGauge.tsx](frontend/src/components/MatchGauge.tsx) — the semantic
match % (and AI confidence on detail) rendered as a 270° cyan gauge that sweeps
up on mount (respects `prefers-reduced-motion`). Cards are dark instrument tiles
with a deterministic per-make backlight hue ([format.ts](frontend/src/lib/format.ts),
`tileBackground`/`hueFor`) and dashboard tell-tale stock lights (`stockTell`);
the old rainbow gradients and pill badges are gone.

> ⚠️ Next 16 has breaking changes vs older docs (see `frontend/AGENTS.md`). Uses
> the new route-props helpers: `PageProps<'/route'>` / `LayoutProps<'/'>` (global,
> no import) and **async `params`** (`const { vin } = await props.params`).

**Pages**
- `/` — [page.tsx](frontend/src/app/page.tsx) → `SearchExperience` (client):
  natural-language search box + example chips → `POST /api/search` → result grid
  with % match badges.
- `/browse` — `BrowseExperience` (client): facet sidebar (fuel/body/segment/make
  with live counts via `/api/vehicles/facets`) + sortable, paginated grid via
  `/api/vehicles`.
- `/vehicles/[vin]` — server component, SSR-fetches `GET /api/vehicles/{vin}`;
  spec grid, AI summary/highlights, comparables; `notFound()` → 404.

**Shape:** typed API client + types mirror the backend
([lib/api.ts](frontend/src/lib/api.ts), [lib/types.ts](frontend/src/lib/types.ts));
shared `VehicleCard` / `Navbar` / `MatchGauge`; deterministic per-make instrument
tiles carry a per-`body_type` car silhouette
([CarSilhouette.tsx](frontend/src/components/CarSilhouette.tsx)) in place of photos
(dataset image URLs don't resolve). Fixed a latent
`qs()` type error in `lib/api.ts` that was silently failing `next build` (dev
never type-checks it).

**Run it**
```bash
cd frontend && npm install && npm run dev   # http://localhost:3000
```

**Verified:** `next build` passes clean (compile + TypeScript + static gen for
`/`, `/browse`; `/vehicles/[vin]` dynamic); driven live in headless Chrome —
all three pages render with real API data and **zero console/page errors**;
match gauges sweep; per-make tiles + tell-tales render.

### Test-drive booking flow (Phase 4 — done)

The data layer (`Booking` model, `BookingCreate`/`BookingResponse` schemas, and
the migrated `bookings` table) was scaffolded in Phase 1; this session wired it
end-to-end.

- **API** — [routes/bookings.py](backend/app/api/routes/bookings.py), registered
  in [main.py](backend/main.py):
  - `POST /api/bookings` — validates the body (name/email/phone, future
    appointment), **404** if the VIN is unknown, **409** if the vehicle is sold
    or that exact slot (same VIN + datetime) is already held by an active
    booking, else **201** with the created record.
  - `GET /api/bookings?vin=&limit=` — recent bookings (demo/admin listing).
  - `GET /api/bookings/{id}` — one booking (404 on miss).
- **Frontend** — [BookTestDrive.tsx](frontend/src/components/BookTestDrive.tsx):
  the detail-page button opens an accessible modal (role=dialog, ESC/backdrop
  close, focus management, scroll lock, `datetime-local` min = now+1h) → posts
  via [createBooking](frontend/src/lib/api.ts) → shows a confirmation with the
  booking ref, status and appointment. Server error messages (409/404/422)
  surface inline. Dates pinned to `en-IE` to match the €/price formatting.
- **Verified** — all API paths (201/404/409/422) tested; driven live in headless
  Chrome (open → fill → submit → confirmation) with zero console errors; test
  rows cleared afterward (table back to 0).

### Polish pass (Phase 4 — done)

- **Loading skeletons** — [VehicleCardSkeleton.tsx](frontend/src/components/VehicleCardSkeleton.tsx)
  (shimmer, reduced-motion aware) replace the blank/dim wait on both search and
  browse initial loads; browse dims the existing grid on refetch to keep context.
- **Price & year range sliders** — [RangeSlider.tsx](frontend/src/components/RangeSlider.tsx)
  dual-thumb sliders in the browse sidebar, seeded from the facet bounds,
  debounced (350 ms), wired to `min/max_price` + `min/max_year`. (Browse had no
  price filter before.) Verified live: capping at €12k → 843 → 436 vehicles.
- **Error + retry** — browse no longer swallows fetch errors; shows a themed
  panel with a Retry that re-runs the query.
- **Error boundary + 404** — [app/error.tsx](frontend/src/app/error.tsx)
  ("Signal lost" + reset) and [app/not-found.tsx](frontend/src/app/not-found.tsx)
  ("No route.") replace Next's defaults, on-theme.
- **Image assets** — [CarSilhouette.tsx](frontend/src/components/CarSilhouette.tsx):
  bundled, dependency-free side-profile SVG silhouettes keyed by `body_type`
  (6 shapes: suv/sedan/hatchback/ute→pickup/coupe/wagon + sedan fallback), drawn
  as quiet backlit line-art on the card + detail tiles in place of the make
  monogram. No external images/licensing; keeps the HMI identity. Verified each
  body type renders a distinct, recognizable shape.

### Full-stack Docker (done)

The frontend is now containerised: [frontend/Dockerfile](frontend/Dockerfile)
(multi-stage → Next `output: "standalone"` slim runtime) + a `web` service in
[docker-compose.yml](docker-compose.yml), so **`docker compose up -d` runs the
whole stack incl. the UI** on `:3000`. The SSR-vs-browser API-base split lives in
[lib/api.ts](frontend/src/lib/api.ts): `typeof window` picks
`API_URL_INTERNAL=http://api:8000` for server-rendered fetches (detail page) and
the baked `NEXT_PUBLIC_API_URL=http://localhost:8000` for the browser. Verified:
containerised SSR detail renders real data, 404/routes 200, no errors. Dev
hot-reload still works via `docker compose stop web && npm run dev`.

**Phase 4 complete.** Remaining nice-to-haves are forward-looking (neural rerank,
API integration tests, accounts) — see the README roadmap.
