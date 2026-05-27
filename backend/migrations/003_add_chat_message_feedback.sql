-- Migration: Add feedback columns to chat_messages table
-- Date: 2026-03-12
-- Description: Enables thumbs up/down quality feedback per assistant message

ALTER TABLE chat_messages ADD COLUMN feedback_score INTEGER;
ALTER TABLE chat_messages ADD COLUMN feedback_comment TEXT;
ALTER TABLE chat_messages ADD COLUMN feedback_at TIMESTAMP;

-- Optional sanity checks
-- feedback_score should be -1 or 1 when present
-- Use application-level validation for now.
