-- Seed data for Compound Risk MVP
INSERT INTO events (id, type, event_prob, ts, confidence_radius_m, source, credibility, geom)
VALUES
    (1, 'earthquake', 0.80, NOW() - INTERVAL '2 hours', 120000, 'usgs', 0.90, ST_SetSRID(ST_MakePoint(-122.4, 37.8), 4326)::geography),
    (2, 'wildfire', 0.70, NOW() - INTERVAL '4 hours', 90000, 'firms', 0.80, ST_SetSRID(ST_MakePoint(-121.8, 37.4), 4326)::geography),
    (3, 'flood', 0.60, NOW() - INTERVAL '8 hours', 150000, 'glofas', 0.75, ST_SetSRID(ST_MakePoint(-90.1, 29.9), 4326)::geography),
    (4, 'storm', 0.55, NOW() - INTERVAL '10 hours', 140000, 'noaa', 0.70, ST_SetSRID(ST_MakePoint(-80.2, 25.9), 4326)::geography),
    (5, 'heatwave', 0.50, NOW() - INTERVAL '12 hours', 130000, 'meteo', 0.60, ST_SetSRID(ST_MakePoint(2.35, 48.85), 4326)::geography),
    (6, 'earthquake', 0.65, NOW() - INTERVAL '16 hours', 110000, 'usgs', 0.85, ST_SetSRID(ST_MakePoint(139.69, 35.68), 4326)::geography),
    (7, 'wildfire', 0.45, NOW() - INTERVAL '20 hours', 75000, 'firms', 0.70, ST_SetSRID(ST_MakePoint(151.21, -33.87), 4326)::geography),
    (8, 'flood', 0.52, NOW() - INTERVAL '23 hours', 160000, 'glofas', 0.72, ST_SetSRID(ST_MakePoint(77.2, 28.6), 4326)::geography),
    (9, 'storm', 0.40, NOW() - INTERVAL '26 hours', 100000, 'noaa', 0.65, ST_SetSRID(ST_MakePoint(-3.7, 40.4), 4326)::geography),
    (10, 'heatwave', 0.48, NOW() - INTERVAL '30 hours', 90000, 'meteo', 0.58, ST_SetSRID(ST_MakePoint(31.2, 30.0), 4326)::geography)
ON CONFLICT (id) DO NOTHING;

INSERT INTO hazards (id, type, hazard_prob, forecast_ts, timestep, run_id, geom)
VALUES
    (1, 'landslide', 0.70, NOW() + INTERVAL '6 hours', 0, 'run-001', ST_GeogFromText('POLYGON((-122.8 37.4,-121.9 37.4,-121.9 38.2,-122.8 38.2,-122.8 37.4))')),
    (2, 'smoke', 0.80, NOW() + INTERVAL '8 hours', 0, 'run-001', ST_GeogFromText('POLYGON((-122.2 37.0,-121.4 37.0,-121.4 37.8,-122.2 37.8,-122.2 37.0))')),
    (3, 'inundation', 0.75, NOW() + INTERVAL '24 hours', 1, 'run-001', ST_GeogFromText('POLYGON((-90.7 29.4,-89.4 29.4,-89.4 30.5,-90.7 30.5,-90.7 29.4))')),
    (4, 'storm_surge', 0.60, NOW() + INTERVAL '30 hours', 1, 'run-001', ST_GeogFromText('POLYGON((-80.8 25.3,-79.6 25.3,-79.6 26.4,-80.8 26.4,-80.8 25.3))')),
    (5, 'power_grid_stress', 0.55, NOW() + INTERVAL '54 hours', 2, 'run-001', ST_GeogFromText('POLYGON((1.8 48.2,3.0 48.2,3.0 49.2,1.8 49.2,1.8 48.2))')),
    (6, 'liquefaction', 0.73, NOW() + INTERVAL '60 hours', 2, 'run-001', ST_GeogFromText('POLYGON((139.1 35.1,140.2 35.1,140.2 36.2,139.1 36.2,139.1 35.1))'))
ON CONFLICT (id) DO NOTHING;
