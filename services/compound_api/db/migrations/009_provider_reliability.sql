CREATE TABLE IF NOT EXISTS provider_cache (
  provider TEXT NOT NULL,
  cache_key TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ttl_seconds INTEGER NOT NULL,
  PRIMARY KEY (provider, cache_key)
);

CREATE TABLE IF NOT EXISTS provider_status (
  provider TEXT PRIMARY KEY,
  last_success_at TIMESTAMPTZ,
  last_error_at TIMESTAMPTZ,
  last_error TEXT,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  circuit_open_until TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_provider_cache_fetched_at ON provider_cache (fetched_at DESC);
