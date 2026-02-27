# Refactor Merge Review

## Scope
Pre-merge hardening review for the unified backend refactor branch.

## Architecture (current)

```text
Browser (Frontend :3000)
  -> backend_api (:8080)
      -> Compound domain (embedded ASGI app in-process)
          -> Postgres (postgis)
          -> Google Weather API (external)
          -> Valhalla (:8002) direct calls
      -> Planner/Agent domain (in-process)
          -> Valhalla (:8002) direct calls
          -> Compound scoring endpoint (local backend URL)
      -> Internal admin endpoints (/internal/jobs/*, ADMIN_API_KEY required)

Scheduler (internal)
  -> Postgres job_queue enqueue on cadence

Worker (internal)
  -> Postgres job_queue claim (FOR UPDATE SKIP LOCKED)
  -> ingestion handlers (gdelt/reliefweb/rss optional)
  -> cache cleanup
  -> ingestion_runs updates
```

## What changed vs old multi-service design

- Removed `routing_api` from docker-compose. Backend calls Valhalla directly via new provider (`app/providers/valhalla.py`).
- Removed `ingestor` service from docker-compose; ingestion now runs via scheduler + worker over durable Postgres queue.
- Hardened queue + health visibility:
  - queue claims remain atomic (`FOR UPDATE SKIP LOCKED`), retries/backoff/dead-letter behavior preserved,
  - backend `/health` now reports DB status, valhalla status, queue counts, and last ingestion timestamps.
- Health script updated for new architecture and includes endpoint smoke checks (+ optional admin queue stats).
- Added smoke contract tests for core frontend-used API contracts.
- Added admin endpoint security tests (disabled without ADMIN_API_KEY; forbidden with wrong key).

## Risks identified and mitigations

1. **Routing dependency regression after removing routing_api**
   - **Mitigation**: Added dedicated Valhalla provider with shape decode parity and direct route/isochrone helpers.

2. **False-positive health endpoint**
   - **Mitigation**: `/health` now checks DB connectivity explicitly (`SELECT 1`), valhalla route health, queue stats, and ingestion timestamps.

3. **Admin endpoint exposure risk**
   - **Mitigation**: `/internal/jobs/*` remains protected behind `ADMIN_API_KEY` and is 404 when key is unset.

4. **Contract drift on critical frontend endpoints**
   - **Mitigation**: Added smoke tests for `/api/routes/options`, `/api/routes/score`, `/api/plan`, `/api/agent/brief`.

5. **Queue lifecycle correctness regression**
   - **Mitigation**: Expanded queue tests to cover enqueue->claim->succeed and stale lock reap, plus retry->dead path.

## Verification checklist (commands + outcome)

### Required checks run

- `docker compose up --build -d`
  - **Result**: failed in this execution environment (`docker: command not found`).
  - **Action**: compose file validated syntactically with Python YAML parser.

- `./scripts/health_check.sh`
  - **Result**: failed in this execution environment because backend was not running (`localhost:8080` connection refused).
  - **Action**: script hardened and aligned to current architecture; should pass when stack is up.

- `pytest services/backend_api/tests -q`
  - **Result**: pass (`15 passed`).

- `pytest tests -q` (service-local test runs)
  - `services/compound_api/tests`: pass (`16 passed`)
  - `services/planner/tests`: pass (`8 passed`)
  - `services/routing_api/tests`: pass (`4 passed`) (legacy service tests still green)

- `npm run typecheck`
  - **Result**: pass.

- `npm run build`
  - **Result**: pass.

- `python - <<'PY' ... yaml.safe_load(docker-compose.yml) ... PY`
  - **Result**: pass (`compose_ok`).

- `rg -n "VITE_COMPOUND_API_URL|VITE_PLANNER_API_URL|localhost:8090|localhost:8091" src Dockerfile.frontend docker-compose.yml`
  - **Result**: no matches (frontend only references unified backend API wiring).

## Manual merge checklist

- [x] Frontend still wired to single backend API (`VITE_API_URL`) only.
- [x] No `routing_api` in compose.
- [x] No `ingestor` in compose.
- [x] Worker/scheduler have no host-exposed ports.
- [x] Job queue claim uses `FOR UPDATE SKIP LOCKED`.
- [x] Admin endpoints gated by `ADMIN_API_KEY`.
- [x] Health script and backend `/health` reflect new architecture.

## Notes for maintainer running locally (with Docker installed)

Run in order:

```bash
docker compose up --build -d
./scripts/health_check.sh
pytest services/backend_api/tests -q
pytest tests -q -C services/compound_api
pytest tests -q -C services/planner
npm run typecheck
npm run build
```

If `ADMIN_API_KEY` is set, health check will also validate `/internal/jobs/stats`.
