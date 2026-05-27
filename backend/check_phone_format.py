#!/usr/bin/env python3
"""Check phone number format in database and messages"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine
from sqlalchemy import text

def check_format():
    with engine.connect() as conn:
        # Check contact phone format
        result = conn.execute(text("""
            SELECT phone_number, whatsapp_contact_id, contact_name, total_messages
            FROM whatsapp_contacts
            WHERE phone_number LIKE '%94561045%'
        """))
        
        print("Contact Info:")
        print("=" * 60)
        for row in result:
            phone, wa_id, name, total = row
            print(f"Phone in DB: '{phone}'")
            print(f"Has + prefix: {phone.startswith('+') if phone else 'N/A'}")
            print(f"WhatsApp ID: {wa_id}")
            print(f"Total messages: {total}")
        
        # Check outbound message recipient format
        print("\n\nOutbound Messages (recipient format):")
        print("=" * 60)
        result2 = conn.execute(text("""
            SELECT wm.content, wm.msg_metadata, wm.created_at
            FROM whatsapp_messages wm
            JOIN whatsapp_contacts wc ON wm.contact_id = wc.id
            WHERE wc.phone_number LIKE '%94561045%'
              AND wm.direction = 'outbound'
            ORDER BY wm.created_at DESC
            LIMIT 3
        """))
        
        for row in result2:
            content, metadata, created_at = row
            print(f"\nTime: {created_at}")
            print(f"Content: {content[:50]}...")
            if metadata:
                import json
                try:
                    meta = json.loads(metadata) if isinstance(metadata, str) else metadata
                    print(f"Metadata: {meta}")
                except:
                    print(f"Raw metadata: {metadata}")
            print("-" * 40)

if __name__ == "__main__":
    check_format()
