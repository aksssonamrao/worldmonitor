CREATE EXTENSION IF NOT EXISTS pg_cron;

CREATE OR REPLACE FUNCTION route_score_cache_retention_cleanup(retention INTERVAL DEFAULT INTERVAL '30 days')
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM route_score_cache
    WHERE created_at < NOW() - retention;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;

DO $$
DECLARE
    existing_job_id INTEGER;
BEGIN
    SELECT jobid INTO existing_job_id
    FROM cron.job
    WHERE jobname = 'route_score_cache_retention';

    IF existing_job_id IS NOT NULL THEN
        PERFORM cron.unschedule(existing_job_id);
    END IF;

    PERFORM cron.schedule(
        'route_score_cache_retention',
        '15 * * * *',
        $$SELECT route_score_cache_retention_cleanup();$$
    );
END;
$$;
