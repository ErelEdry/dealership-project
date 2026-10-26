# dealership-project — Fix List

Reviewed against commit `b46755b`. Ordered by priority: P0 breaks behavior or setup, P1 correctness and robustness, P2 search quality / frontend / infra, P3 docs and cleanup.
Items marked "verified" were reproduced by actually running the code (pytest passes, 80/80).

Check off each box as the task is completed.

---

## P0 — Breaks behavior

### [x] 1. `.env.example` breaks API startup
- **File:** `.env.example`
- **Problem:** It sets `EMBEDDING_MODEL=models/text-embedding-004` (a Gemini model name). Anyone who runs `cp .env.example .env` as the Quickstart says overrides the `BAAI/bge-base-en-v1.5` default, and `TextEmbedding(...)` in `embedder.py` fails at import time. `GROQ_API_KEY` is missing (no enrichment without it), and there are unused Gemini and Cohere keys.
- **Fix:** Remove `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` (or set them to the bge values), add `GROQ_API_KEY=`, remove `GEMINI_API_KEY`.
- **Done when:** fresh clone → `cp .env.example .env` → `docker compose up -d` → `/health` returns 200 and `/api/search` works.

### [x] 2. Fresh setup never creates the tables
- **Files:** `README.md`, `docker-compose.yml`
- **Problem:** There is no `create_all` and Alembic is never run. The Quickstart jumps straight to `python -m app.etl.pipeline`, which INSERTs into a table that doesn't exist.
- **Fix:** Add a `docker compose exec api alembic upgrade head` step to the Quickstart, or run it automatically before uvicorn in the api service command.
- **Done when:** empty Postgres volume → the pipeline runs without errors.

### [ ] 3. `parse_price_intent` parses non-price numbers as prices (verified)
- **File:** `backend/app/core/query_intent.py`
- **Problem:**
  - `"car under 50000 km"` → `max_price = 50,000,000` (the `k` is captured from `km`).
  - `"suv from 2018 to 2022"` → price €2018–2022 → zero results.
  - `"under 5 years old"` → `max_price = 5` → zero results.
  - `"at least 7 seats"` → `min_price = 7`.
- **Fix:** Match `k` only as a whole word (`k\b`); don't parse a number followed by `km|miles|years?|yrs|seats|doors`; a number in 1990–2035 with no currency and no `k` is a year, not a price (optionally map it to `min_year/max_year`); ignore amounts under 1,000 with no currency and no `k`.
- **Done when:** every example above is a test case in `test_query_intent.py`, all green.

### [ ] 4. Booking with a timezone-aware datetime returns 500 (verified), and timezones are mixed up
- **Files:** `backend/app/schemas/booking.py`, `backend/app/models/booking.py`, `frontend/src/components/BookTestDrive.tsx`
- **Problem:** `must_be_future` compares against naive `datetime.utcnow()`. Any client that sends `...Z` or an offset gets a `TypeError` that isn't treated as a validation error → 500 instead of 422. Meanwhile the frontend sends local time with no offset (`YYYY-MM-DDTHH:MM`) and the server treats it as UTC: in Israel that's a 2–3 hour gap, both in the "is it in the future" check and in what's stored.
- **Fix:** In the validator: naive → assume UTC, aware → convert to UTC; compare against `datetime.now(timezone.utc)`. In the frontend send `new Date(value).toISOString()`. Preferably switch to `DateTime(timezone=True)` in the model and a migration. Also replace the remaining `datetime.utcnow` in `booking.py` and the booking model (PROGRESS says this was fixed, but only in inventory).
- **Done when:** POST with `Z`, with `+03:00`, and with no offset all return 201 or 422, never 500. A test for each case.

### [ ] 5. Double-booking race condition
- **Files:** `backend/app/api/routes/bookings.py`, new migration
- **Problem:** Clash check then INSERT, with no DB constraint. Two concurrent requests for the same vehicle and time both succeed. There is also no FK from `bookings.vehicle_vin` to `vehicle_inventory`.
- **Fix:** Migration 002 with a partial unique index on `(vehicle_vin, appointment_datetime) WHERE status IN ('pending','confirmed')` plus the FK. In the handler: explicit `await db.commit()` inside a try, catch `IntegrityError` → 409. (Today the commit happens in `get_db` after the handler returns, so a constraint error there would surface as a 500.)
- **Optional:** block by time window (e.g. 30 minutes), not only exact match — today 10:00 and 10:01 are both accepted.
- **Done when:** two concurrent requests → one 201, one 409.

### [ ] 6. An embedding failure removes a vehicle from search permanently
- **File:** `backend/app/etl/pipeline.py`
- **Problem:** `embed_vehicle` returns `None` on failure, but `upsert_vehicle` is called anyway with `vector_id=NULL` and `enriched_at=now`. On the next run `vehicle_exists` skips it, so the vehicle exists in Postgres and never reaches Qdrant.
- **Fix:** If `point_id is None` → don't write (or write without `enriched_at`) and count it as failed; the skip check should also require `vector_id IS NOT NULL`.
- **Done when:** a simulated embedding failure → the vehicle is picked up again on the next run.

### [ ] 7. `.title()` corrupts make and model names (verified)
- **Files:** `backend/app/schemas/inventory.py` (make/model validator), `routes/search.py`, `routes/vehicles.py`
- **Problem:** The DB stores `Bmw` instead of `BMW`, and also `Rav4`, `Cr-V`, `Cx-5`, `Cx-30`, `Gle`, `Xc60`, `Xc90`. That's what the UI shows. The filters also apply `.title()` to match, so the bug is "consistent" but the names are wrong.
- **Fix:** Validator does `strip()` only. Case-insensitive filtering: `func.lower(col) == value.lower()` in Postgres; in Qdrant store an extra normalized payload field (e.g. lowercase `make_key`) and filter on it. An idempotent script that fixes PG + Qdrant from the CSV, in the same style as `scripts/regenerate_prices.py`.
- **Done when:** the UI shows BMW / RAV4 / CR-V, and both `make=bmw` and `make=BMW` filters work.

---

## P1 — Correctness and robustness

### [ ] 8. Blocking calls inside an async route
- **File:** `backend/app/api/routes/search.py`
- **Problem:** `embed_query(...)` (ONNX model inference) and `get_qdrant().query_points(...)` (sync client) run directly inside `async def` and block the event loop. Every search stalls all other requests, including `/health`.
- **Fix:** `await asyncio.to_thread(embed_query, req.query)` and `asyncio.to_thread` for the Qdrant query too (or `AsyncQdrantClient`). The same pattern already exists in `embedder.embed_vehicle`.

### [ ] 9. Upsert doesn't update spec columns → Postgres/Qdrant drift
- **File:** `backend/app/etl/pipeline.py` (`upsert_vehicle`, `vehicle_exists`)
- **Problem:** `ON CONFLICT DO UPDATE` updates only price/status/AI fields. If make/model/year/mileage/body/fuel/seats/acquisition_cost/condition change in the CSV, the Qdrant payload is updated and Postgres isn't. Also, `content_hash` is stored but unused: CSV changes are never picked up without `--force`.
- **Fix:** Update all spec columns in `DO UPDATE` (plus `content_hash`, `source_file`). Replace `vehicle_exists` with "exists and `content_hash` matches".

### [ ] 10. Quarantine is not implemented
- **Files:** `backend/app/etl/pipeline.py`, `README.md`
- **Problem:** The README says invalid rows go to the `validation_errors` table. In reality `validate_row` returns an error object and the pipeline only logs it. No code writes to the table.
- **Fix:** INSERT into `validation_errors` in the pipeline (the model and table already exist). Better than changing the README, since it's one of the highlights.
- **Done when:** a CSV with a broken row → a row in `validation_errors`.

### [ ] 11. `GET /api/bookings` exposes customer data without auth
- **File:** `backend/app/api/routes/bookings.py`
- **Problem:** Anyone can list customer names, vehicles and appointment times.
- **Fix:** Protect with an admin token header (`secret_key` exists in config and is unused), or remove the endpoint from the public router.

---

## P2 — Search quality, frontend, infra

### [ ] 12. Lexical bonus matches substrings
- **File:** `backend/app/core/query_intent.py` (`lex_bonus`)
- **Problem:** `t in strong` is a substring check, so `ev` matches `chevrolet`.
- **Fix:** Tokenize make/model/tags and check set membership. Run `eval.run_eval` before and after to make sure the metrics don't drop.

### [ ] 13. `economy` and `value` trigger "cheap" intent
- **File:** `backend/app/core/query_intent.py`
- **Problem:** `"fuel economy hatchback"` → `direction="low"` (verified), i.e. sorting by price when the user didn't ask for it.
- **Fix:** Remove `economy` (and consider `value`) from `_BUDGET_LOW`, or ignore it when the previous word is `fuel`. Add a test.

### [ ] 14. Stale search responses can overwrite newer ones
- **File:** `frontend/src/components/SearchExperience.tsx`
- **Problem:** Clicking two chips quickly: if the first response arrives last, it's shown under the second query.
- **Fix:** `AbortController` or a request-id counter that ignores stale responses (`BrowseExperience` already has a `cancelled` flag — same idea).
- **Small, same area:** `getVehicle` in `lib/api.ts` doesn't `encodeURIComponent(vin)`.

### [ ] 15. Search cache isn't invalidated after data scripts
- **Files:** `routes/search.py`, `backend/scripts/*`
- **Problem:** After `regenerate_prices` or `rebalance_stock_status`, stale results are served for up to 5 minutes.
- **Fix:** Add a data version to the cache key, or delete `search:*` at the end of each `--apply` script.

### [ ] 16. Unpinned images in docker-compose
- **File:** `docker-compose.yml`
- **Problem:** `qdrant/qdrant:latest` and `dpage/pgadmin4:latest`, while the client is pinned to `qdrant-client==1.12.1`. A new server release could break compatibility.
- **Fix:** Pin versions (e.g. `qdrant/qdrant:v1.12.x`).

### [ ] 17. Config defaults
- **Files:** `backend/app/core/config.py`, `backend/main.py`, `requirements.txt`
- **Problems and fixes:**
  - `debug=True` by default → `echo=True` prints every SQL query. Default to `False`.
  - CORS hard-coded to `http://localhost:3000` → move to a setting.
  - `EmailStr` needs `email-validator`, which today only comes in transitively via `fastapi==0.111.0` (later versions moved it to `fastapi[standard]`). Add it explicitly to `requirements.txt`.

---

## P3 — Docs and cleanup (matters because this is a portfolio project)

### [ ] 18. Contradictions in the docs
- `PROGRESS.md` says the frontend is "Not containerised yet" — it is.
- `README.md` says an 18-value segment vocabulary, `PROGRESS.md` says 17 + `Other`. Pick one.
- After item 10: make sure the quarantine description is accurate.
- After items 4–5: update the README on booking 404/409/422 handling.

### [ ] 19. Personal files in the repo
- `daily_reenrich.ps1` contains a `C:\Users\Erel\...` path and a personal scheduled task.
- `SESSION_LOG.md`, `frontend/CLAUDE.md`, `frontend/AGENTS.md` — consider whether they belong in a public repo, or move them under `docs/`.
- `frontend/README.md` is probably the default create-next-app README.

---

## Suggested work order
1. Items 1–2 (without them nobody can run the project from a clone).
2. Item 3 + tests (user-visible bug, easy fix).
3. Items 4–5 together (same files, one migration).
4. Items 6, 9, 10 together (all in `pipeline.py`).
5. Item 7 (needs a data migration script).
6. Item 8, then P2 and P3.
