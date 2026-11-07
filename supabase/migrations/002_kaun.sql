-- Kaun? (pollution attribution) tables. Run in the Supabase SQL editor after schema.sql.
-- Idempotent: safe to re-run. Upserts in attribution/store.py rely on these unique keys.

CREATE TABLE IF NOT EXISTS kaun_stations (
    id                  TEXT PRIMARY KEY,           -- slug of the station name
    name                TEXT NOT NULL,
    latitude            DOUBLE PRECISION NOT NULL,
    longitude           DOUBLE PRECISION NOT NULL,
    openaq_location_id  BIGINT,
    active              BOOLEAN DEFAULT TRUE,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Pollutants per station-hour. ug/m3, CO in mg/m3. hour = start of the hour, UTC.
CREATE TABLE IF NOT EXISTS hourly_obs (
    station_id  TEXT NOT NULL REFERENCES kaun_stations(id) ON DELETE CASCADE,
    hour        TIMESTAMPTZ NOT NULL,
    pm25        REAL, pm10 REAL, no2 REAL, so2 REAL, co REAL, o3 REAL,
    source      TEXT,                                -- openaq | cpcb | openaq+cpcb
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (station_id, hour)
);
CREATE INDEX IF NOT EXISTS hourly_obs_hour ON hourly_obs (hour DESC);

CREATE TABLE IF NOT EXISTS wind_obs (
    station_id  TEXT NOT NULL REFERENCES kaun_stations(id) ON DELETE CASCADE,
    hour        TIMESTAMPTZ NOT NULL,
    wind_speed  REAL,                                -- m/s, 10 m
    wind_dir    REAL,                                -- degrees, direction wind blows FROM
    pbl_height  REAL,                                -- m, boundary layer height
    source      TEXT,
    PRIMARY KEY (station_id, hour)
);
CREATE INDEX IF NOT EXISTS wind_obs_hour ON wind_obs (hour DESC);

CREATE TABLE IF NOT EXISTS fire_points (
    source              TEXT NOT NULL,               -- VIIRS_SNPP_NRT, MODIS_NRT, ...
    latitude            DOUBLE PRECISION NOT NULL,
    longitude           DOUBLE PRECISION NOT NULL,
    acq_time            TIMESTAMPTZ NOT NULL,
    frp                 REAL,                        -- fire radiative power, MW
    confidence          TEXT CHECK (confidence IN ('low','nominal','high')),
    daynight            TEXT,
    dist_km             REAL,
    bearing_from_delhi  REAL,
    PRIMARY KEY (source, latitude, longitude, acq_time)
);
CREATE INDEX IF NOT EXISTS fire_points_time ON fire_points (acq_time DESC);

CREATE TABLE IF NOT EXISTS attributions (
    id              TEXT UNIQUE NOT NULL,            -- sha1(station|window_start)[:16]
    station_id      TEXT NOT NULL REFERENCES kaun_stations(id) ON DELETE CASCADE,
    station_name    TEXT,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    window_start    TIMESTAMPTZ NOT NULL,
    window_end      TIMESTAMPTZ NOT NULL,
    n_hours         INTEGER,
    peak_pm25       REAL,
    baseline_pm25   REAL,
    excess_pm25     REAL,
    shares          JSONB NOT NULL,                  -- {source: fraction}
    top_source      TEXT,
    sector          TEXT,
    regional_share  REAL,
    confidence      TEXT NOT NULL CHECK (confidence IN ('low','medium','high')),
    summary_en      TEXT,
    summary_hi      TEXT,
    evidence        JSONB,
    engine_version  TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (station_id, window_start)
);
CREATE INDEX IF NOT EXISTS attributions_time ON attributions (window_start DESC);

-- Human-approved complaint queue. Nothing here is sent automatically.
CREATE TABLE IF NOT EXISTS complaint_queue (
    attribution_id  TEXT PRIMARY KEY REFERENCES attributions(id) ON DELETE CASCADE,
    station_id      TEXT,
    agencies        JSONB,
    summary         TEXT,
    evidence_md     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected','ready_to_send','sent')),
    approve_url     TEXT,
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- RLS: the cron writes with the service_role key (bypasses RLS). Public read of
-- attributions only; the queue and raw tables stay private.
ALTER TABLE kaun_stations   ENABLE ROW LEVEL SECURITY;
ALTER TABLE hourly_obs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE wind_obs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE fire_points     ENABLE ROW LEVEL SECURITY;
ALTER TABLE attributions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE complaint_queue ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS attributions_public_read ON attributions;
CREATE POLICY attributions_public_read ON attributions FOR SELECT USING (true);
DROP POLICY IF EXISTS kaun_stations_public_read ON kaun_stations;
CREATE POLICY kaun_stations_public_read ON kaun_stations FOR SELECT USING (true);
