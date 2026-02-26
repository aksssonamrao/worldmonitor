# World Monitor — Route Risk Planner

World Monitor is a self-hosted route risk planner focused on supply-chain risk signals and weather-driven hazard planning.

## Scope

This repository now targets a single product:
- Route risk planning
- Supply chain decision support
- Compound hazard generation through Google Weather in the `services/compound_api` service

Out-of-scope systems were removed from this repo, including market/crypto dashboards, prediction market modules, live video streams, browser-side ML inference, and Vercel/Railway edge-relay architecture.

## Run (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

Services:
- Frontend: http://localhost:3000
- Compound API health: http://localhost:8090/compound/health
- Planner API: http://localhost:8091/health
- PostGIS: localhost:5432

## Backend tests

```bash
pip install -r services/compound_api/requirements.txt
pytest services/compound_api/tests
```

```bash
pip install -r services/planner/requirements.txt
pytest services/planner/tests
```

## Environment

Use `.env.example` for the minimal self-host configuration. Keep only routing/hazard-relevant keys enabled (Google Weather + optional event sources + map configuration).
