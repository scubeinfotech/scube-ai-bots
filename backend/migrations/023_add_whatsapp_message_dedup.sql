-- Migration 023: Add unique constraint on whatsapp_message_id
-- Prevents duplicate processing of the same incoming WhatsApp message

-- First clean up any remaining duplicates (belt-and-suspenders)
DELETE FROM whatsapp_messages
WHERE id IN (
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (
            PARTITION BY whatsapp_message_id ORDER BY created_at
        ) AS rn
        FROM whatsapp_messages
        WHERE whatsapp_message_id IS NOT NULL
    ) sub
    WHERE sub.rn > 1
);

-- Add unique constraint
ALTER TABLE whatsapp_messages
ADD CONSTRAINT uq_whatsapp_message_id UNIQUE (whatsapp_message_id);
