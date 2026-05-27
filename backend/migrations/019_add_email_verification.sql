-- Add email verification columns to tenant_users table
ALTER TABLE tenant_users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE tenant_users ADD COLUMN verification_token VARCHAR(255);
