-- Migration: Add out_of_scope_mode to tenants for polite boundary control
-- Date: 2026-03-12
-- Description: Enables tenant-level strategy for out-of-scope user requests

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS out_of_scope_mode VARCHAR(50) DEFAULT 'strict_business';

-- Backfill existing rows explicitly
UPDATE tenants
SET out_of_scope_mode = 'strict_business'
WHERE out_of_scope_mode IS NULL;

CREATE INDEX IF NOT EXISTS idx_tenants_out_of_scope_mode ON tenants(out_of_scope_mode);
