-- VayuVani — Supabase Schema
-- Run this in your Supabase SQL editor (dashboard.supabase.com → SQL Editor)

-- ============================================================
-- 1. STATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS stations (
    id          TEXT PRIMARY KEY,               -- station name (human-readable PK)
    name        TEXT NOT NULL,
    latitude    DOUBLE PRECISION NOT NULL,
    longitude   DOUBLE PRECISION NOT NULL,
    source      TEXT NOT NULL CHECK (source IN ('openaq', 'cpcb', 'citizen')),
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS stations_coords ON stations (latitude, longitude);
CREATE INDEX IF NOT EXISTS stations_source ON stations (source);


-- ============================================================
-- 2. AQI READINGS
-- ============================================================
CREATE TABLE IF NOT EXISTS aqi_readings (
    id                  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    station_id          TEXT NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
    ts                  TIMESTAMPTZ NOT NULL,

    -- Pollutants (µg/m³, except co in mg/m³)
    pm25                REAL,
    pm10                REAL,
    no2                 REAL,
    so2                 REAL,
    co                  REAL,
    o3                  REAL,
    nh3                 REAL,

    -- Calculated NAQI
    aqi                 INTEGER,
    category            TEXT CHECK (category IN ('Good','Satisfactory','Moderate','Poor','Very Poor','Severe')),
    dominant_pollutant  TEXT,

    source              TEXT,
    raw_data            JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (station_id, ts)             -- idempotent upserts
);

CREATE INDEX IF NOT EXISTS readings_station_time ON aqi_readings (station_id, ts DESC);
CREATE INDEX IF NOT EXISTS readings_time         ON aqi_readings (ts DESC);
CREATE INDEX IF NOT EXISTS readings_aqi          ON aqi_readings (aqi);


-- ============================================================
-- 3. CITIZEN REPORTS
-- ============================================================
CREATE TABLE IF NOT EXISTS citizen_reports (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    call_id         TEXT,                           -- VAPI call ID
    caller_number   TEXT,                           -- anonymized if needed
    neighborhood    TEXT,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    pollution_type  TEXT CHECK (pollution_type IN ('dust','vehicular','industrial','burning','other')),
    description     TEXT,                           -- Whisper transcript
    timestamp       TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS citizen_reports_time  ON citizen_reports (timestamp DESC);
CREATE INDEX IF NOT EXISTS citizen_reports_type  ON citizen_reports (pollution_type);
CREATE INDEX IF NOT EXISTS citizen_reports_area  ON citizen_reports (latitude, longitude);


-- ============================================================
-- 4. ADVISORY LOGS (A/B test data)
-- ============================================================
CREATE TABLE IF NOT EXISTS advisory_logs (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    call_id         TEXT UNIQUE,                    -- VAPI call ID
    caller_number   TEXT,
    neighborhood    TEXT,
    aqi_value       INTEGER,
    category        TEXT,
    advisory_text   TEXT,
    language        TEXT CHECK (language IN ('hi', 'en')),
    group_label     TEXT CHECK (group_label IN ('A', 'B')),  -- A/B test group
    changed_plans   BOOLEAN,                        -- from follow-up survey
    timestamp       TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS advisory_logs_time    ON advisory_logs (timestamp DESC);
CREATE INDEX IF NOT EXISTS advisory_logs_group   ON advisory_logs (group_label);
CREATE INDEX IF NOT EXISTS advisory_logs_call    ON advisory_logs (call_id);


-- ============================================================
-- 5. NEIGHBORHOODS (Delhi neighborhood → coordinates lookup)
-- ============================================================
CREATE TABLE IF NOT EXISTS neighborhoods (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    name_hi     TEXT,                               -- Hindi name for TTS matching
    latitude    DOUBLE PRECISION NOT NULL,
    longitude   DOUBLE PRECISION NOT NULL,
    district    TEXT
);

-- Seed common Delhi neighborhoods
INSERT INTO neighborhoods (name, name_hi, latitude, longitude, district) VALUES
    ('Anand Vihar',      'आनंद विहार',      28.6466, 77.3152, 'East Delhi'),
    ('Chandni Chowk',    'चांदनी चौक',      28.6506, 77.2304, 'Central Delhi'),
    ('Connaught Place',  'कनॉट प्लेस',      28.6315, 77.2167, 'Central Delhi'),
    ('Dwarka',           'द्वारका',          28.5921, 77.0460, 'South West Delhi'),
    ('ITO',              'आईटीओ',            28.6275, 77.2436, 'Central Delhi'),
    ('Jahangirpuri',     'जहांगीरपुरी',     28.7251, 77.1645, 'North Delhi'),
    ('Lodhi Road',       'लोधी रोड',        28.5975, 77.2217, 'South Delhi'),
    ('Mandir Marg',      'मंदिर मार्ग',      28.6404, 77.1987, 'Central Delhi'),
    ('Mayur Vihar',      'मयूर विहार',      28.6092, 77.2938, 'East Delhi'),
    ('NSIT Dwarka',      'एनएसआईटी द्वारका',28.6089, 77.0339, 'South West Delhi'),
    ('Okhla',            'ओखला',             28.5500, 77.2700, 'South Delhi'),
    ('Punjabi Bagh',     'पंजाबी बाग',      28.6700, 77.1300, 'West Delhi'),
    ('RK Puram',         'आरके पुरम',        28.5644, 77.1765, 'South West Delhi'),
    ('Rohini',           'रोहिणी',           28.7354, 77.1148, 'North West Delhi'),
    ('Saket',            'साकेत',            28.5244, 77.2066, 'South Delhi'),
    ('Shadipur',         'शादीपुर',          28.6481, 77.1472, 'West Delhi'),
    ('Siri Fort',        'सिरी फोर्ट',      28.5486, 77.2169, 'South Delhi'),
    ('Vasundhara Enclave','वसुंधरा एन्क्लेव',28.6265, 77.3098, 'East Delhi'),
    ('Wazirpur',         'वज़ीरपुर',         28.6956, 77.1676, 'North West Delhi')
ON CONFLICT (name) DO NOTHING;


-- ============================================================
-- 6. RPC: get_nearest_reading
-- Used by the voice webhook to find AQI near caller's neighborhood
-- Haversine distance — no PostGIS required
-- ============================================================
CREATE OR REPLACE FUNCTION get_nearest_reading(
    p_lat       DOUBLE PRECISION,
    p_lon       DOUBLE PRECISION,
    p_radius_km DOUBLE PRECISION DEFAULT 5.0
)
RETURNS TABLE (
    station_name        TEXT,
    distance_km         DOUBLE PRECISION,
    aqi                 INTEGER,
    category            TEXT,
    dominant_pollutant  TEXT,
    pm25                REAL,
    pm10                REAL,
    no2                 REAL,
    reading_ts          TIMESTAMPTZ
)
LANGUAGE sql STABLE AS $$
    SELECT
        s.name                                              AS station_name,
        6371.0 * 2 * ASIN(SQRT(
            POWER(SIN(RADIANS(s.latitude  - p_lat) / 2), 2) +
            COS(RADIANS(p_lat)) * COS(RADIANS(s.latitude)) *
            POWER(SIN(RADIANS(s.longitude - p_lon) / 2), 2)
        ))                                                  AS distance_km,
        r.aqi,
        r.category,
        r.dominant_pollutant,
        r.pm25,
        r.pm10,
        r.no2,
        r.ts                                                AS reading_ts
    FROM stations s
    JOIN LATERAL (
        SELECT *
        FROM aqi_readings ar
        WHERE ar.station_id = s.id
        ORDER BY ar.ts DESC
        LIMIT 1
    ) r ON TRUE
    WHERE 6371.0 * 2 * ASIN(SQRT(
        POWER(SIN(RADIANS(s.latitude  - p_lat) / 2), 2) +
        COS(RADIANS(p_lat)) * COS(RADIANS(s.latitude)) *
        POWER(SIN(RADIANS(s.longitude - p_lon) / 2), 2)
    )) <= p_radius_km
    AND s.is_active = TRUE
    ORDER BY distance_km ASC
    LIMIT 1;
$$;
