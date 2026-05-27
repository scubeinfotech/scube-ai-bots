-- Step 2: Intent Detection Middleware persistence table
-- Stores tentative booking/callback/demo records extracted from WhatsApp messages.

CREATE TABLE IF NOT EXISTS whatsapp_tentative_bookings (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    contact_id VARCHAR(36) NOT NULL,
    whatsapp_session_id VARCHAR(36),
    source_message_id VARCHAR(36),

    intent_type VARCHAR(50) NOT NULL,
    status VARCHAR(50) DEFAULT 'tentative',

    requested_date VARCHAR(50),
    requested_time VARCHAR(50),
    requested_persons INTEGER,
    requested_type VARCHAR(100),

    raw_text TEXT NOT NULL,
    extracted_fields JSON,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_wa_tentative_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    CONSTRAINT fk_wa_tentative_contact
        FOREIGN KEY (contact_id) REFERENCES whatsapp_contacts(id),
    CONSTRAINT fk_wa_tentative_session
        FOREIGN KEY (whatsapp_session_id) REFERENCES whatsapp_sessions(id),
    CONSTRAINT fk_wa_tentative_message
        FOREIGN KEY (source_message_id) REFERENCES whatsapp_messages(id)
);

CREATE INDEX IF NOT EXISTS idx_wa_tentative_tenant_created
    ON whatsapp_tentative_bookings(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_wa_tentative_intent_status
    ON whatsapp_tentative_bookings(intent_type, status);
