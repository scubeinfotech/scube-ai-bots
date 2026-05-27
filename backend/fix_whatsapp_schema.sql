-- Safe WhatsApp Schema Fix
-- Adds missing columns to whatsapp_configurations table
-- This is idempotent (safe to run multiple times)

-- Check if columns exist before adding (PostgreSQL syntax)
DO $$
BEGIN
    -- Add rate_limit_max_per_minute if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='whatsapp_configurations' 
                   AND column_name='rate_limit_max_per_minute') THEN
        ALTER TABLE whatsapp_configurations ADD COLUMN rate_limit_max_per_minute INTEGER DEFAULT 5;
        RAISE NOTICE 'Added column: rate_limit_max_per_minute';
    ELSE
        RAISE NOTICE 'Column already exists: rate_limit_max_per_minute';
    END IF;

    -- Add cooldown_seconds if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='whatsapp_configurations' 
                   AND column_name='cooldown_seconds') THEN
        ALTER TABLE whatsapp_configurations ADD COLUMN cooldown_seconds INTEGER DEFAULT 2;
        RAISE NOTICE 'Added column: cooldown_seconds';
    ELSE
        RAISE NOTICE 'Column already exists: cooldown_seconds';
    END IF;

    -- Add response_target_chars if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='whatsapp_configurations' 
                   AND column_name='response_target_chars') THEN
        ALTER TABLE whatsapp_configurations ADD COLUMN response_target_chars INTEGER DEFAULT 300;
        RAISE NOTICE 'Added column: response_target_chars';
    ELSE
        RAISE NOTICE 'Column already exists: response_target_chars';
    END IF;
END $$;

-- Verify the fix
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'whatsapp_configurations' 
ORDER BY ordinal_position;
