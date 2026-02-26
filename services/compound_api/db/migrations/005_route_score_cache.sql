CREATE TABLE IF NOT EXISTS route_score_cache (
    route_hash TEXT NOT NULL,
    time_bucket TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (route_hash, time_bucket)
);

CREATE INDEX IF NOT EXISTS route_score_cache_created_at_idx ON route_score_cache (created_at DESC);
