-- Migration 013: Step 5 – Human handoff fields on tentative bookings

ALTER TABLE whatsapp_tentative_bookings
    ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(120),
    ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal',
    ADD COLUMN IF NOT EXISTS due_by TIMESTAMP,
    ADD COLUMN IF NOT EXISTS escalation_level INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS handoff_notes TEXT,
    ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_wa_bookings_assignment
    ON whatsapp_tentative_bookings(tenant_id, assigned_to)
    WHERE assigned_to IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_wa_bookings_due
    ON whatsapp_tentative_bookings(tenant_id, due_by)
    WHERE due_by IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_wa_bookings_escalation
    ON whatsapp_tentative_bookings(tenant_id, escalation_level)
    WHERE escalation_level > 0;
