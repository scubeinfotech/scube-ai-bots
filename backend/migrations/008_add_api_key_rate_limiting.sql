-- Migration 008: Add rate limiting and key type to API Keys (PostgreSQL)
-- Enables per-API-key rate limiting to prevent cost abuse

BEGIN;

-- Add key type for scope control
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS key_type VARCHAR(50) DEFAULT 'chat';

-- Add rate limiting columns
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS rate_limit_per_minute INTEGER DEFAULT 60;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS rate_limit_per_hour INTEGER DEFAULT 1000;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS current_minute_count INTEGER DEFAULT 0;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS current_hour_count INTEGER DEFAULT 0;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS minute_reset_at TIMESTAMP;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS hour_reset_at TIMESTAMP;

-- Add domain restrictions - comma-separated list of allowed domains
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS allowed_domains VARCHAR(500);

-- Add index for faster lookups
CREATE INDEX IF NOT EXISTS idx_api_keys_key_type ON api_keys(key_type);
CREATE INDEX IF NOT EXISTS idx_api_keys_is_active ON api_keys(is_active);

COMMIT;