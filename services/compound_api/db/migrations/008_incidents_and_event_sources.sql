CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

INSERT INTO sources(name)
VALUES ('usgs'), ('firms'), ('planned')
ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS event_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL REFERENCES sources(name),
    source_event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    url TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    occurred_at TIMESTAMPTZ,
    country TEXT,
    event_type TEXT NOT NULL CHECK (event_type IN ('PROTEST','CONFLICT','STRIKE','DISASTER','OUTAGE','ACCIDENT','OTHER')),
    subtype TEXT,
    severity DOUBLE PRECISION NOT NULL CHECK (severity BETWEEN 0 AND 1),
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    geom geography(Point,4326) NOT NULL,
    geohash TEXT NOT NULL,
    time_bucket TIMESTAMPTZ NOT NULL,
    normalized_text TEXT NOT NULL,
    simhash64 BIGINT NOT NULL,
    raw JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(source, source_event_id)
);

CREATE INDEX IF NOT EXISTS event_sources_geom_idx ON event_sources USING GIST (geom);
CREATE INDEX IF NOT EXISTS event_sources_published_at_idx ON event_sources (published_at DESC);
CREATE INDEX IF NOT EXISTS event_sources_type_bucket_idx ON event_sources (event_type, time_bucket DESC);
CREATE INDEX IF NOT EXISTS event_sources_geohash_bucket_idx ON event_sources (geohash, time_bucket DESC);
CREATE INDEX IF NOT EXISTS event_sources_simhash_idx ON event_sources (simhash64);

CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_title TEXT NOT NULL,
    canonical_summary TEXT,
    event_type TEXT NOT NULL CHECK (event_type IN ('PROTEST','CONFLICT','STRIKE','DISASTER','OUTAGE','ACCIDENT','OTHER')),
    subtype TEXT,
    severity DOUBLE PRECISION NOT NULL CHECK (severity BETWEEN 0 AND 1),
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    country TEXT,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ,
    geom geography(Point,4326) NOT NULL,
    geohash TEXT NOT NULL,
    time_bucket TIMESTAMPTZ NOT NULL,
    incident_key TEXT NOT NULL UNIQUE,
    representative_simhash64 BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS incidents_geom_idx ON incidents USING GIST (geom);
CREATE INDEX IF NOT EXISTS incidents_start_at_idx ON incidents (start_at DESC);
CREATE INDEX IF NOT EXISTS incidents_type_bucket_idx ON incidents (event_type, time_bucket DESC);
CREATE INDEX IF NOT EXISTS incidents_geohash_bucket_idx ON incidents (geohash, time_bucket DESC);

CREATE TABLE IF NOT EXISTS incident_sources (
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    event_source_id UUID NOT NULL REFERENCES event_sources(id) ON DELETE CASCADE,
    PRIMARY KEY (incident_id, event_source_id)
);

ALTER TABLE compound_alerts ADD COLUMN IF NOT EXISTS incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS compound_alerts_incident_id_idx ON compound_alerts (incident_id);
ALTER TABLE compound_alerts DROP CONSTRAINT IF EXISTS compound_alerts_run_id_timestep_event_id_key;
ALTER TABLE compound_alerts ADD CONSTRAINT compound_alerts_run_timestep_incident_key UNIQUE (run_id, timestep, incident_id);
