-- Migration: Add welcome_message column to tenants table
-- Date: 2026-03-09
-- Description: Adds centralized welcome message support for tenant widgets

ALTER TABLE tenants ADD COLUMN welcome_message VARCHAR(500);

-- Update Scube Infotech tenant with default greeting
UPDATE tenants 
SET welcome_message = '👋 Hello! I''m your SCUBE Infotech AI Assistant. How can I help you with your IT needs today?'
WHERE slug = 'scube' OR domain LIKE '%scubeinfotech.com.sg%';

-- Update other existing tenants with a generic greeting (optional, can customize per tenant)
UPDATE tenants 
SET welcome_message = '👋 Hi! How can I assist you today?'
WHERE welcome_message IS NULL AND is_active = TRUE;
