-- Add registration_source column to tenants table
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS registration_source VARCHAR(20) DEFAULT 'self';
