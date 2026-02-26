CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL CHECK (source IN ('gdelt', 'reliefweb', 'rss')),
    source_event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    url TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('PROTEST','CONFLICT','STRIKE','DISASTER','OUTAGE','ACCIDENT','OTHER')),
    severity DOUBLE PRECISION NOT NULL CHECK (severity BETWEEN 0 AND 1),
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    country TEXT,
    region TEXT,
    occurred_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    geom geography(Point,4326) NOT NULL,
    raw JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(source, source_event_id)
);

CREATE INDEX IF NOT EXISTS events_geom_idx ON events USING GIST (geom);
CREATE INDEX IF NOT EXISTS events_occurred_at_idx ON events (occurred_at DESC);
CREATE INDEX IF NOT EXISTS events_event_type_idx ON events (event_type);

CREATE TABLE IF NOT EXISTS ingestion_state (
    source TEXT PRIMARY KEY,
    cursor JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS compound_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id TEXT NOT NULL,
    timestep INTEGER NOT NULL,
    alert_type TEXT NOT NULL DEFAULT 'COMPOUND',
    score DOUBLE PRECISION NOT NULL,
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    hazard_type TEXT NOT NULL CHECK (hazard_type IN ('WIND','RAIN','HEAT')),
    hazard_prob DOUBLE PRECISION NOT NULL CHECK (hazard_prob BETWEEN 0 AND 1),
    forecast_ts TIMESTAMPTZ NOT NULL,
    geom geography(Point,4326) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(run_id, timestep, event_id)
);

CREATE INDEX IF NOT EXISTS compound_alerts_run_timestep_idx ON compound_alerts (run_id, timestep);
CREATE INDEX IF NOT EXISTS compound_alerts_geom_idx ON compound_alerts USING GIST (geom);
CREATE INDEX IF NOT EXISTS compound_alerts_score_idx ON compound_alerts (score DESC);
