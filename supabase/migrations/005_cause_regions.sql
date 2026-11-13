-- Cause decomposition (engine kaun-0.2) and multi-region support. Idempotent.
-- cause: {top, shares, local: {share, top, candidates}, regional: {share, mechanism, composition, ...}, text_en, text_hi}
ALTER TABLE attributions  ADD COLUMN IF NOT EXISTS cause  JSONB;
-- Which airshed a station belongs to (attribution/regions.py id). NULL = delhi-ncr (legacy rows).
ALTER TABLE kaun_stations ADD COLUMN IF NOT EXISTS region TEXT;
