CREATE TABLE IF NOT EXISTS aois (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    geom geography(GEOMETRY, 4326) NOT NULL,
    country_tags TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS aois_geom_idx ON aois USING GIST (geom);
CREATE INDEX IF NOT EXISTS aois_created_at_idx ON aois (created_at DESC);

CREATE TABLE IF NOT EXISTS aoi_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aoi_id UUID NOT NULL REFERENCES aois(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    timestep INTEGER NOT NULL DEFAULT 0,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    summary_json JSONB NOT NULL,
    hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS aoi_snapshots_aoi_captured_idx ON aoi_snapshots (aoi_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS aoi_deltas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aoi_id UUID NOT NULL REFERENCES aois(id) ON DELETE CASCADE,
    from_snapshot_id UUID NOT NULL REFERENCES aoi_snapshots(id) ON DELETE CASCADE,
    to_snapshot_id UUID NOT NULL REFERENCES aoi_snapshots(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delta_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS aoi_deltas_aoi_created_idx ON aoi_deltas (aoi_id, created_at DESC);
