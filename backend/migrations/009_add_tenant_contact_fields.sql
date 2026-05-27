-- Migration 009: Add contact fields to tenants
-- Adds business hours and contact email for better customer info

BEGIN;

-- Add contact fields
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contact_email VARCHAR(255);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS business_hours VARCHAR(100);

COMMIT;