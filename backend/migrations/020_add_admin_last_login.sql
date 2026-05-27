-- Add last_login_at column to admin_users table for audit trail
ALTER TABLE admin_users ADD COLUMN last_login_at TIMESTAMP;
