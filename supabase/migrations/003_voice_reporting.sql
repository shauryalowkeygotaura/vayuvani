-- Phone line + autonomous agency reporting. Run after 002_kaun.sql. Idempotent.

-- complaint_queue now also holds citizen-report clusters, which have no
-- attribution row: drop the FK and add routing/sending columns.
ALTER TABLE complaint_queue DROP CONSTRAINT IF EXISTS complaint_queue_attribution_id_fkey;
ALTER TABLE complaint_queue ADD COLUMN IF NOT EXISTS kind         TEXT DEFAULT 'spike';
ALTER TABLE complaint_queue ADD COLUMN IF NOT EXISTS top_source   TEXT;
ALTER TABLE complaint_queue ADD COLUMN IF NOT EXISTS confidence   TEXT;
ALTER TABLE complaint_queue ADD COLUMN IF NOT EXISTS latitude     DOUBLE PRECISION;
ALTER TABLE complaint_queue ADD COLUMN IF NOT EXISTS longitude    DOUBLE PRECISION;
ALTER TABLE complaint_queue ADD COLUMN IF NOT EXISTS window_start TIMESTAMPTZ;
ALTER TABLE complaint_queue ADD COLUMN IF NOT EXISTS sent_at      TIMESTAMPTZ;
ALTER TABLE complaint_queue ADD COLUMN IF NOT EXISTS digest_id    TEXT;
ALTER TABLE complaint_queue DROP CONSTRAINT IF EXISTS complaint_queue_status_check;
ALTER TABLE complaint_queue ADD CONSTRAINT complaint_queue_status_check
    CHECK (status IN ('pending','approved','rejected','held','ready_to_send','sent'));

-- One digest per agency per IST day; the unique key makes reruns safe.
CREATE TABLE IF NOT EXISTS report_digests (
    id          TEXT PRIMARY KEY,
    agency      TEXT NOT NULL,
    day         DATE NOT NULL,
    recipients  JSONB,
    items       JSONB,
    subject     TEXT,
    message_id  TEXT,
    status      TEXT NOT NULL CHECK (status IN ('sent','failed')),
    sent_at     TIMESTAMPTZ,
    UNIQUE (agency, day)
);
ALTER TABLE report_digests ENABLE ROW LEVEL SECURITY;

-- Citizen reports from the phone line (table from 001_base.sql). The webhook
-- writes with the service key; nothing here is public.
ALTER TABLE citizen_reports ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS citizen_reports_time_type ON citizen_reports (timestamp DESC, pollution_type);
