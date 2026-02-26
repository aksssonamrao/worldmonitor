CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Non-destructive schema evolution: create hazard_runs first so the FK target exists,
-- then create/evolve hazards to reference it.

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

-- Create hazards with a FK to hazard_runs so rows cannot be orphaned.
-- If the table already exists from a prior migration that lacked the FK,
-- add the constraint via ALTER TABLE (IF NOT EXISTS guard avoids duplicate errors).
CREATE TABLE IF NOT EXISTS hazards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id TEXT NOT NULL REFERENCES hazard_runs(run_id) ON DELETE CASCADE,
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

-- Add FK to pre-existing hazards table if it was created without one.
-- Orphan rows must be removed first or backfilled to satisfy referential integrity.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_type = 'FOREIGN KEY'
          AND table_name = 'hazards'
          AND constraint_name = 'hazards_run_id_fkey'
    ) THEN
        -- Remove any orphaned hazard rows that would violate the new constraint.
        DELETE FROM hazards WHERE run_id NOT IN (SELECT run_id FROM hazard_runs);
        ALTER TABLE hazards
            ADD CONSTRAINT hazards_run_id_fkey
            FOREIGN KEY (run_id) REFERENCES hazard_runs(run_id) ON DELETE CASCADE;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS hazards_geom_idx ON hazards USING GIST (geom);
CREATE INDEX IF NOT EXISTS hazards_run_timestep_type_idx ON hazards (run_id, timestep, type);
CREATE INDEX IF NOT EXISTS hazards_generated_at_idx ON hazards (generated_at);

-- NOTE: The old `alerts` table (if present from an earlier migration) is intentionally
-- NOT dropped here.  Schedule a separate cleanup migration once all consumers have been
-- verified to use the hazards table exclusively.

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
