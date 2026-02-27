CREATE TABLE IF NOT EXISTS job_queue (
  id UUID PRIMARY KEY,
  job_type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','dead')) DEFAULT 'queued',
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 5,
  run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
  locked_at TIMESTAMPTZ NULL,
  locked_by TEXT NULL,
  last_error TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_job_queue_status_runafter ON job_queue (status, run_after);
CREATE INDEX IF NOT EXISTS idx_job_queue_locked_at ON job_queue (locked_at);
CREATE INDEX IF NOT EXISTS idx_job_queue_job_type ON job_queue (job_type);
