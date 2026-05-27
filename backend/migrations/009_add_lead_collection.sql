-- Add lead collection fields to chat_sessions
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS lead_name VARCHAR(255);
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS lead_email VARCHAR(255);
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS lead_phone VARCHAR(50);
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS lead_collected_at TIMESTAMP;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS lead_prompt_count INTEGER DEFAULT 0;