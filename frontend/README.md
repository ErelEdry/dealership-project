# Frontend — AUTO·AI

Next.js 16 · React 19 · Tailwind v4 (App Router, TypeScript). The UI for the
semantic dealership search; see the [root README](../README.md) for the whole
system.

## Pages

| Route | What it does |
|---|---|
| `/` | Natural-language search → `POST /api/search`, results with match gauges |
| `/browse` | Facet sidebar + range sliders → `GET /api/vehicles` and `/facets` |
| `/vehicles/[vin]` | Server-rendered detail page + test-drive booking modal |

API calls live in [src/lib/api.ts](src/lib/api.ts); types mirroring the backend
schemas in [src/lib/types.ts](src/lib/types.ts).

## Running

The whole stack (including this UI on :3000) runs with `docker compose up -d`
from the repo root. For hot reload against the containerised API:

```bash
docker compose stop web     # free port 3000
npm install
npm run dev                 # http://localhost:3000
```

| Variable | Used for | Default |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | API base for browser requests (baked in at build time) | `http://localhost:8000` |
| `API_URL_INTERNAL` | API base for server-side rendering inside Docker | — (falls back to the public URL) |

`npm run build` type-checks and builds the production bundle (CI runs it on
every push).

> `AGENTS.md` / `CLAUDE.md` are written by `next dev` for coding agents (Next 16
> differs from older docs); they are kept so the tree stays clean after a dev run.
