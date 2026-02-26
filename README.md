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
- Planner API (+ `/agent/brief`): http://localhost:8091/health
- PostGIS: localhost:5432

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
