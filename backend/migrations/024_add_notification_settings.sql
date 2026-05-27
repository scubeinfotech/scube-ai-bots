-- Migration: Add notification settings to tenants table
-- Created: 2026-05-25

-- Add notification_email column for booking/callback notifications
ALTER TABLE tenants 
ADD COLUMN notification_email VARCHAR(255) NULL;

-- Add notify_on_booking toggle (default: true)
ALTER TABLE tenants 
ADD COLUMN notify_on_booking BOOLEAN DEFAULT TRUE;

-- Add comment for documentation
COMMENT ON COLUMN tenants.notification_email IS 'Email address for booking/callback notifications (defaults to daily_report_email if not set)';
COMMENT ON COLUMN tenants.notify_on_booking IS 'Whether to email tenant when new booking/callback is requested via WhatsApp';
