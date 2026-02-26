CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DROP TABLE IF EXISTS alerts;
DROP TABLE IF EXISTS hazards;

CREATE TABLE IF NOT EXISTS hazards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id TEXT NOT NULL,
    timestep INTEGER NOT NULL,
    forecast_ts TIMESTAMPTZ NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('WIND','RAIN','HEAT')),
    hazard_prob DOUBLE PRECISION NOT NULL CHECK (hazard_prob BETWEEN 0 AND 1),
    provider TEXT NOT NULL DEFAULT 'google_weather',
    bbox JSONB NOT NULL,
    thresholds JSONB NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    geom geography(Polygon,4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS hazards_geom_idx ON hazards USING GIST (geom);
CREATE INDEX IF NOT EXISTS hazards_run_timestep_type_idx ON hazards (run_id, timestep, type);
CREATE INDEX IF NOT EXISTS hazards_generated_at_idx ON hazards (generated_at);

CREATE TABLE IF NOT EXISTS weather_samples (
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    forecast_ts TIMESTAMPTZ NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    wind_kph DOUBLE PRECISION NOT NULL,
    precip_mm_hr DOUBLE PRECISION NOT NULL,
    temp_c DOUBLE PRECISION NOT NULL,
    humidity DOUBLE PRECISION,
    UNIQUE(lat, lon, forecast_ts)
);

CREATE TABLE IF NOT EXISTS hazard_runs (
    run_id TEXT PRIMARY KEY,
    bbox JSONB NOT NULL,
    timesteps JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('SUCCESS','FAILED','RUNNING')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    points_requested INTEGER NOT NULL DEFAULT 0,
    points_fetched INTEGER NOT NULL DEFAULT 0,
    cache_hits INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
