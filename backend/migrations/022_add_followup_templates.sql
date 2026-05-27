-- Migration 022: CRM Follow-up Templates & Scheduled Messages
-- Adds follow_up_templates (industry-aware message blueprints) and scheduled_messages queue.

CREATE TABLE IF NOT EXISTS follow_up_templates (
    id              VARCHAR(36)  PRIMARY KEY,
    tenant_id       VARCHAR(36)  REFERENCES tenants(id),
    industry        VARCHAR(50),
    trigger_event   VARCHAR(50)  NOT NULL,
    delay_hours     INTEGER      DEFAULT 24,
    template_text   TEXT         NOT NULL,
    conclusive_line TEXT,
    is_active       BOOLEAN      DEFAULT TRUE,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fut_tenant_event
    ON follow_up_templates(tenant_id, trigger_event);

CREATE INDEX IF NOT EXISTS idx_fut_industry_event
    ON follow_up_templates(industry, trigger_event)
    WHERE tenant_id IS NULL;

CREATE TABLE IF NOT EXISTS scheduled_messages (
    id              VARCHAR(36)  PRIMARY KEY,
    tenant_id       VARCHAR(36)  NOT NULL REFERENCES tenants(id),
    contact_id      VARCHAR(36)  NOT NULL REFERENCES whatsapp_contacts(id),
    template_id     VARCHAR(36)  REFERENCES follow_up_templates(id),
    trigger_event   VARCHAR(50),
    scheduled_at    TIMESTAMP    NOT NULL,
    status          VARCHAR(20)  DEFAULT 'pending',
    message_text    TEXT,
    sent_at         TIMESTAMP,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sched_pending
    ON scheduled_messages(status, scheduled_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_sched_tenant
    ON scheduled_messages(tenant_id, status);

-- Seed global templates for common industries
INSERT INTO follow_up_templates (id, industry, trigger_event, delay_hours, template_text, conclusive_line, is_active) VALUES
-- Lead Created templates
('fut_lead_created_generic', NULL, 'lead_created', 24,
 'Hi {{name}}, we noted your {{service}} request for {{date}}. Reply CONFIRM to proceed.',
 'No need to call us — confirm right here. You''ll get a notification when it''s booked.', TRUE),

('fut_lead_created_repair', 'services', 'lead_created', 24,
 'Hi {{name}}, regarding your {{service}} request for {{date}}. Reply CONFIRM to book our technician.',
 'We''ll dispatch a technician at your preferred time. Save a phone call — just reply CONFIRM.', TRUE),

('fut_lead_created_legal', 'accounting', 'lead_created', 24,
 'Dear {{name}}, re: {{service}} on {{date}}. Reply CONFIRM to secure your consultation.',
 'Your consultation slot is reserved tentatively. Confirm now to lock it in.', TRUE),

-- Lead Confirmed templates
('fut_confirmed_generic', NULL, 'lead_confirmed', 0,
 'Confirmed! {{service}} is set for {{date}} {{time}}. We''ll send a reminder before then.',
 'All set! We handle reminders automatically — you just show up. Your dashboard will update.', TRUE),

-- Abandoned conversation templates
('fut_abandoned_generic', NULL, 'abandoned', 4,
 'Hi {{name}}, still need help with {{service}}? Reply YES and we''ll continue where we left off.',
 'No need to repeat yourself — your conversation is saved. Just reply and we''re here.', TRUE),

-- Inactive 7-day re-engagement
('fut_inactive_generic', NULL, 'inactive_7d', 168,
 'Hi {{name}}, it''s been a while! We''re still here if you need {{service}} assistance. Reply anytime.',
 'We value your time — no pressure, just a friendly check-in. Reply whenever you''re ready.', TRUE);
