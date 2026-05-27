#!/usr/bin/env python3
"""Check delivery status of WhatsApp messages to 94561045"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine
from sqlalchemy import text

def check_delivery():
    with engine.connect() as conn:
        # Find recent messages to/from 94561045
        result = conn.execute(text("""
            SELECT wm.id, wm.direction, wm.delivery_status, wm.content, wm.created_at, wm.error_message
            FROM whatsapp_messages wm
            JOIN whatsapp_contacts wc ON wm.contact_id = wc.id
            WHERE wc.phone_number = '6594561045'
            ORDER BY wm.created_at DESC
            LIMIT 10
        """))
        
        print("Recent messages for 6594561045:")
        print("=" * 80)
        for row in result:
            msg_id, direction, status, content, created_at, error = row
            content_preview = content[:60] + "..." if len(content) > 60 else content
            print(f"\nTime: {created_at}")
            print(f"Direction: {direction}")
            print(f"Status: {status}")
            print(f"Content: {content_preview}")
            if error:
                print(f"ERROR: {error}")
            print("-" * 40)

if __name__ == "__main__":
    check_delivery()
