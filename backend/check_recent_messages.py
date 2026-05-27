#!/usr/bin/env python3
"""Check recent WhatsApp messages with full details"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine
from sqlalchemy import text

def check_messages():
    with engine.connect() as conn:
        # Get recent messages to 94561045 with all fields
        result = conn.execute(text("""
            SELECT wm.id, wm.direction, wm.delivery_status, wm.whatsapp_message_id,
                   wm.content, wm.created_at, wm.error_message, wm.processing_error,
                   wm.msg_metadata, wm.message_type
            FROM whatsapp_messages wm
            JOIN whatsapp_contacts wc ON wm.contact_id = wc.id
            WHERE wc.phone_number = '6594561045'
            ORDER BY wm.created_at DESC
            LIMIT 10
        """))
        
        print("Recent messages for 6594561045:")
        print("=" * 80)
        for row in result:
            msg_id, direction, status, wa_msg_id, content, created_at, error, proc_error, metadata, msg_type = row
            print(f"\nTime: {created_at}")
            print(f"Direction: {direction}")
            print(f"Status: {status}")
            print(f"WhatsApp Msg ID: {wa_msg_id}")
            print(f"Message Type: {msg_type}")
            print(f"Content length: {len(content) if content else 0} chars")
            if content and len(content) > 100:
                print(f"Content: {content[:100]}...")
            else:
                print(f"Content: {content}")
            if error:
                print(f"ERROR: {error}")
            if proc_error:
                print(f"Proc Error: {proc_error}")
            print("-" * 60)

if __name__ == "__main__":
    check_messages()
