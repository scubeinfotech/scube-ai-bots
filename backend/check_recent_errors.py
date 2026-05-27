#!/usr/bin/env python3
"""Check for recent WhatsApp errors"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine
from sqlalchemy import text
from datetime import datetime, timedelta

def check_recent_errors():
    with engine.connect() as conn:
        # Check for failed messages in last hour
        result = conn.execute(text("""
            SELECT wm.id, wm.direction, wm.delivery_status, wm.content, 
                   wm.created_at, wm.error_message, wm.processing_error,
                   wc.phone_number
            FROM whatsapp_messages wm
            JOIN whatsapp_contacts wc ON wm.contact_id = wc.id
            WHERE wm.created_at >= NOW() - INTERVAL '1 hour'
            ORDER BY wm.created_at DESC
        """))
        
        print("WhatsApp messages in last hour:")
        print("=" * 80)
        found = False
        for row in result:
            found = True
            msg_id, direction, status, content, created_at, error, proc_error, phone = row
            content_preview = content[:50] + "..." if len(content) > 50 else content
            print(f"\nTime: {created_at}")
            print(f"Phone: {phone}")
            print(f"Direction: {direction}")
            print(f"Status: {status}")
            print(f"Content: {content_preview}")
            if error:
                print(f"Delivery Error: {error}")
            if proc_error:
                print(f"Processing Error: {proc_error}")
            print("-" * 40)
        
        if not found:
            print("No messages found in last hour.")
            print("\nThis means the outbound message was NEVER SAVED.")
            print("The send operation failed before reaching the database.")

if __name__ == "__main__":
    check_recent_errors()
