-- Compound Risk MVP schema (PostgreSQL + PostGIS)
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    type TEXT NOT NULL,
    event_prob DOUBLE PRECISION NOT NULL CHECK (event_prob BETWEEN 0 AND 1),
    ts TIMESTAMPTZ NOT NULL,
    confidence_radius_m DOUBLE PRECISION NOT NULL CHECK (confidence_radius_m >= 0),
    source TEXT NOT NULL,
    credibility DOUBLE PRECISION NOT NULL CHECK (credibility BETWEEN 0 AND 1),
    geom geography(Point, 4326) NOT NULL
);

CREATE TABLE IF NOT EXISTS hazards (
    id BIGSERIAL PRIMARY KEY,
    type TEXT NOT NULL,
    hazard_prob DOUBLE PRECISION NOT NULL CHECK (hazard_prob BETWEEN 0 AND 1),
    forecast_ts TIMESTAMPTZ NOT NULL,
    timestep INTEGER NOT NULL CHECK (timestep >= 0),
    run_id TEXT NOT NULL,
    geom geography(Polygon, 4326) NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    hazard_id BIGINT NOT NULL REFERENCES hazards(id) ON DELETE CASCADE,
    score DOUBLE PRECISION NOT NULL CHECK (score BETWEEN 0 AND 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    geom geography(Point, 4326) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS events_geom_idx ON events USING GIST (geom);
CREATE INDEX IF NOT EXISTS hazards_geom_idx ON hazards USING GIST (geom);
CREATE INDEX IF NOT EXISTS alerts_geom_idx ON alerts USING GIST (geom);
CREATE INDEX IF NOT EXISTS events_ts_idx ON events (ts);
CREATE INDEX IF NOT EXISTS hazards_forecast_ts_idx ON hazards (forecast_ts);
CREATE INDEX IF NOT EXISTS hazards_timestep_idx ON hazards (timestep);
