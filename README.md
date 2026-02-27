# World Monitor — Map-first Shipment Route Risk Planner

World Monitor is a self-hosted shipment planning product where the map is primary:
- Build shipment
- Generate 3 route options
- Inspect route risk overlays and evidence
- Produce deterministic plan + brief

## Run (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

Services:
- Frontend: http://localhost:3000
- Backend API (frontend entrypoint): http://localhost:8080/health
- Compound + Planner + Agent APIs: served by backend_api (`/api/*`, `/compound/*`, `/system/*`, `/aois*`)
- Valhalla routing: internal-only (`valhalla:8002`)
- Scheduler (job enqueuer): internal-only (`scheduler`)
- Worker (job queue consumer): internal-only (`worker`)
- PostGIS: localhost:5432


## One-command health check

```bash
./scripts/health_check.sh
```

The script checks compound, planner, and system status endpoints and prints freshness timestamps when available. Frontend requests should target backend_api (`VITE_API_URL`) only.

## Key APIs

- `POST /api/routes/options` (backend_api): returns `Fastest/Balanced/Safest` with geometry + summary risk.
- `POST /api/routes/score` (backend_api): corridor-scoped risk scoring with `segment_scores` and `top_evidence` + cache behavior.
- `POST /api/plan` (backend_api): deterministic planner; accepts `selected_route_geometry`.
- `POST /api/agent/brief` and `POST /api/agent/mitigation` (backend_api).


## Durable Job Queue

- Queue storage is Postgres table `job_queue` (created idempotently on backend startup).
- Worker service polls/claims jobs using `FOR UPDATE SKIP LOCKED` and retries with exponential backoff + jitter.
- Internal admin endpoints (disabled unless `ADMIN_API_KEY` is set):
  - `POST /internal/jobs/enqueue`
  - `GET /internal/jobs/stats`
  - `POST /internal/jobs/reap-stale`

## Tests

```bash
pytest services/compound_api/tests
pytest services/planner/tests
npm run typecheck
npm run build
```

## UX architecture

Frontend layer system:
- base map
- routes layer (all 3 options)
- selected route gradient layer (segment-scored)
- events cluster layer
- alerts cluster layer
- hazards polygon layer

Route scoring cache is persisted in `route_score_cache` and cleaned hourly via `route_score_cache_retention_cleanup()` (default retention 30 days), backed by `route_score_cache_created_at_idx`.


## Valhalla quickstart

```bash
./scripts/valhalla/build_tiles.sh
```

This downloads a small-region extract (India by default) and builds tiles into `./valhalla_data`.
