-- Migration: Add password reset columns to admin_users
-- Date: 2026-03-31

ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS password_reset_token VARCHAR(255);
ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS password_reset_expires TIMESTAMP;
