CREATE TABLE IF NOT EXISTS ingestion_runs (
  source TEXT PRIMARY KEY,
  last_success_at TIMESTAMPTZ NULL,
  last_error TEXT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
