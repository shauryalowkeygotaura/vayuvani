-- Extra evidence variables for the fusion model, and the OSM land-use cache. Idempotent.
ALTER TABLE hourly_obs ADD COLUMN IF NOT EXISTS no   REAL;   -- ug/m3
ALTER TABLE hourly_obs ADD COLUMN IF NOT EXISTS nox  REAL;   -- ug/m3, NO2-equivalent
ALTER TABLE hourly_obs ADD COLUMN IF NOT EXISTS rh   REAL;   -- %
ALTER TABLE hourly_obs ADD COLUMN IF NOT EXISTS temp REAL;   -- deg C

CREATE TABLE IF NOT EXISTS station_landuse (
    station_id  TEXT PRIMARY KEY REFERENCES kaun_stations(id) ON DELETE CASCADE,
    grid        JSONB NOT NULL,      -- {feature: {sector: weighted amount}}
    updated_at  TIMESTAMPTZ NOT NULL
);
ALTER TABLE station_landuse ENABLE ROW LEVEL SECURITY;
