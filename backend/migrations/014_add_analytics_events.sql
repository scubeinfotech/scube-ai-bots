-- Migration 014: WhatsApp Analytics Events
-- Stores per-event analytics log for intent detection, booking lifecycle,
-- human intervention, and automation side-effects.

CREATE TABLE IF NOT EXISTS whatsapp_analytics_events (
    id              VARCHAR(36)  PRIMARY KEY,
    tenant_id       VARCHAR(36)  NOT NULL,
    event_type      VARCHAR(50)  NOT NULL,   -- intent_detected | booking_created | booking_confirmed | booking_cancelled | human_intervention | calendar_synced | crm_synced
    intent          VARCHAR(50)  NULL,        -- populated for intent_detected events
    confidence_score FLOAT       NULL,        -- 0.0–1.0 from intent middleware
    session_id      VARCHAR(36)  NULL,
    contact_id      VARCHAR(36)  NULL,
    booking_id      VARCHAR(36)  NULL,
    sub_type        VARCHAR(50)  NULL,        -- e.g. claim / reassign / escalate for human_intervention
    event_metadata  JSON         NULL,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wae_tenant_created
    ON whatsapp_analytics_events (tenant_id, created_at);

CREATE INDEX IF NOT EXISTS idx_wae_event_type
    ON whatsapp_analytics_events (event_type);
