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
- Compound API: http://localhost:8090/compound/health
- Planner API (+ `/agent/brief`, `/agent/mitigation`): http://localhost:8091/health
- Routing API (Valhalla wrapper): http://localhost:8093/health
- Valhalla: http://localhost:8002
- PostGIS: localhost:5432


## One-command health check

```bash
./scripts/health_check.sh
```

The script checks routing, compound, planner, ingestor, and system status endpoints and prints freshness timestamps when available.

## Key APIs

- `POST /routes/options` (compound_api): returns `Fastest/Balanced/Safest` with geometry + summary risk.
- `POST /routes/score` (compound_api): corridor-scoped risk scoring with `segment_scores` and `top_evidence`.
- `POST /plan` (planner): deterministic planner; accepts `selected_route_geometry`.
- `POST /agent/brief` (planner): template markdown brief + citations (works without OpenAI key).

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
