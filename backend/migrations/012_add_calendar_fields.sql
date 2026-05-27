-- Migration 012: Step 3 – Google Calendar fields on tentative bookings
-- and tenant settings for calendar credentials

-- Add calendar fields to whatsapp_tentative_bookings
ALTER TABLE whatsapp_tentative_bookings
    ADD COLUMN IF NOT EXISTS google_calendar_event_id TEXT,
    ADD COLUMN IF NOT EXISTS calendar_synced_at        TIMESTAMP,
    ADD COLUMN IF NOT EXISTS confirmed_at              TIMESTAMP,
    ADD COLUMN IF NOT EXISTS cancelled_at              TIMESTAMP,
    ADD COLUMN IF NOT EXISTS confirmation_sent_at      TIMESTAMP;

-- Add Google Calendar credentials to tenant settings (JSON column already exists)
-- No schema change needed; stored in tenants.settings JSON as:
--   { "google_calendar_refresh_token": "...", "google_calendar_id": "primary" }

-- Index for fast lookup by calendar event ID
CREATE INDEX IF NOT EXISTS idx_wa_bookings_cal_event
    ON whatsapp_tentative_bookings(google_calendar_event_id)
    WHERE google_calendar_event_id IS NOT NULL;
