-- Migration 021: CRM Enrichment — Customer 360 Profiles
-- Adds enrichment fields to whatsapp_contacts and creates contact_activities timeline table.

ALTER TABLE whatsapp_contacts
    ADD COLUMN IF NOT EXISTS company VARCHAR(255),
    ADD COLUMN IF NOT EXISTS email VARCHAR(255),
    ADD COLUMN IF NOT EXISTS job_title VARCHAR(255),
    ADD COLUMN IF NOT EXISTS notes TEXT,
    ADD COLUMN IF NOT EXISTS tags JSON DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS source_channel VARCHAR(50) DEFAULT 'whatsapp',
    ADD COLUMN IF NOT EXISTS last_lead_status VARCHAR(50);

CREATE TABLE IF NOT EXISTS contact_activities (
    id              VARCHAR(36)  PRIMARY KEY,
    tenant_id       VARCHAR(36)  NOT NULL REFERENCES tenants(id),
    contact_id      VARCHAR(36)  NOT NULL REFERENCES whatsapp_contacts(id),
    activity_type   VARCHAR(50)  NOT NULL,
    description     TEXT,
    ref_type        VARCHAR(50),
    ref_id          VARCHAR(36),
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contact_activities_contact
    ON contact_activities(contact_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_contact_activities_tenant
    ON contact_activities(tenant_id, activity_type, created_at DESC);

-- Note: GIN index on tags (JSON) column skipped — requires jsonb column type.
-- Use application-level filtering for tag searches instead.

CREATE INDEX IF NOT EXISTS idx_wa_contacts_email
    ON whatsapp_contacts(tenant_id, email)
    WHERE email IS NOT NULL;
