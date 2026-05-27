-- Migration 015: Add enabled channels for multi-channel support
-- Tracks which channels (chat, whatsapp, sms, messenger, etc.) are enabled per tenant
-- Supports unlimited future channels without schema changes

ALTER TABLE tenants ADD COLUMN enabled_channels JSON DEFAULT '{"chat": false, "whatsapp": false}';

-- Create index for faster queries on channel status
CREATE INDEX IF NOT EXISTS idx_tenants_enabled_channels 
    ON tenants USING btree (id);
