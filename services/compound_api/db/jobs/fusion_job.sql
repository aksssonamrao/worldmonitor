-- Compound fusion job (PostGIS)
INSERT INTO alerts (event_id, hazard_id, score, created_at, geom, details)
SELECT
    e.id AS event_id,
    h.id AS hazard_id,
    LEAST(
        1.0,
        GREATEST(
            0.0,
            h.hazard_prob
            * e.event_prob
            * (
                CASE
                    WHEN e.type = 'earthquake' AND h.type = 'landslide' THEN 0.90
                    WHEN e.type = 'earthquake' AND h.type = 'liquefaction' THEN 0.95
                    WHEN e.type = 'wildfire' AND h.type = 'smoke' THEN 0.95
                    WHEN e.type = 'flood' AND h.type = 'inundation' THEN 0.95
                    WHEN e.type = 'storm' AND h.type = 'storm_surge' THEN 0.90
                    WHEN e.type = 'heatwave' AND h.type = 'power_grid_stress' THEN 0.85
                    ELSE 0.10
                END
            )
            * e.credibility
        )
    ) AS score,
    NOW() AS created_at,
    e.geom AS geom,
    jsonb_build_object(
        'hazard_prob', h.hazard_prob,
        'event_prob', e.event_prob,
        'compatibility',
            CASE
                WHEN e.type = 'earthquake' AND h.type = 'landslide' THEN 0.90
                WHEN e.type = 'earthquake' AND h.type = 'liquefaction' THEN 0.95
                WHEN e.type = 'wildfire' AND h.type = 'smoke' THEN 0.95
                WHEN e.type = 'flood' AND h.type = 'inundation' THEN 0.95
                WHEN e.type = 'storm' AND h.type = 'storm_surge' THEN 0.90
                WHEN e.type = 'heatwave' AND h.type = 'power_grid_stress' THEN 0.85
                ELSE 0.10
            END,
        'credibility', e.credibility,
        'event_type', e.type,
        'hazard_type', h.type
    ) AS details
FROM events e
JOIN hazards h
    ON ST_Intersects(h.geom, ST_Buffer(e.geom, e.confidence_radius_m))
WHERE e.ts >= NOW() - INTERVAL '24 hours'
  AND h.forecast_ts <= NOW() + INTERVAL '72 hours';
