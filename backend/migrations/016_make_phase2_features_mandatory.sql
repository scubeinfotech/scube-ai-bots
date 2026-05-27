-- Migration 016: Make Phase 2 AI features mandatory for all tenants
-- Date: 2026-04-24
-- Description: Ensures sentiment analysis, conversation memory, and function calling are always enabled.
-- 1. Adds columns if missing (defensive for fresh deployments)
-- 2. Updates all existing tenants to have these features enabled
-- 3. Sets NOT NULL constraint and default TRUE for future inserts

DO $$
BEGIN
    -- Add enable_sentiment_analysis column if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'tenants' AND column_name = 'enable_sentiment_analysis'
    ) THEN
        ALTER TABLE tenants ADD COLUMN enable_sentiment_analysis BOOLEAN DEFAULT true NOT NULL;
    END IF;

    -- Add enable_conversation_memory column if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'tenants' AND column_name = 'enable_conversation_memory'
    ) THEN
        ALTER TABLE tenants ADD COLUMN enable_conversation_memory BOOLEAN DEFAULT true NOT NULL;
    END IF;

    -- Add enable_function_calling column if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'tenants' AND column_name = 'enable_function_calling'
    ) THEN
        ALTER TABLE tenants ADD COLUMN enable_function_calling BOOLEAN DEFAULT true NOT NULL;
    END IF;

    -- Add escalation_threshold column if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'tenants' AND column_name = 'escalation_threshold'
    ) THEN
        ALTER TABLE tenants ADD COLUMN escalation_threshold VARCHAR(10) DEFAULT '-0.5';
    END IF;
END $$;

-- Enable all Phase 2 features for existing tenants (in case they were false/null)
UPDATE tenants 
SET enable_sentiment_analysis = true 
WHERE enable_sentiment_analysis IS NULL OR enable_sentiment_analysis = false;

UPDATE tenants 
SET enable_conversation_memory = true 
WHERE enable_conversation_memory IS NULL OR enable_conversation_memory = false;

UPDATE tenants 
SET enable_function_calling = true 
WHERE enable_function_calling IS NULL OR enable_function_calling = false;

-- Ensure defaults are set correctly (idempotent)
ALTER TABLE tenants 
    ALTER COLUMN enable_sentiment_analysis SET DEFAULT true,
    ALTER COLUMN enable_conversation_memory SET DEFAULT true,
    ALTER COLUMN enable_function_calling SET DEFAULT true;

-- Ensure NOT NULL constraints are in place
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'tenants' 
          AND column_name = 'enable_sentiment_analysis' 
          AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE tenants ALTER COLUMN enable_sentiment_analysis SET NOT NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'tenants' 
          AND column_name = 'enable_conversation_memory' 
          AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE tenants ALTER COLUMN enable_conversation_memory SET NOT NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'tenants' 
          AND column_name = 'enable_function_calling' 
          AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE tenants ALTER COLUMN enable_function_calling SET NOT NULL;
    END IF;
END $$;

