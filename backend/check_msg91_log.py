#!/usr/bin/env python3
"""Check for MSG91 send errors in logs"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine
from sqlalchemy import text

def check_errors():
    with engine.connect() as conn:
        # Find the most recent outbound message that might have failed
        result = conn.execute(text("""
            SELECT wm.id, wm.direction, wm.delivery_status, wm.content, 
                   wm.created_at, wm.error_message, wm.processing_error,
                   wm.whatsapp_message_id, wm.msg_metadata,
                   wc.phone_number
            FROM whatsapp_messages wm
            JOIN whatsapp_contacts wc ON wm.contact_id = wc.id
            WHERE wc.phone_number = '6594561045'
              AND wm.direction = 'outbound'
            ORDER BY wm.created_at DESC
            LIMIT 5
        """))
        
        print("Outbound messages to 6594561045:")
        print("=" * 80)
        for row in result:
            msg_id, direction, status, content, created_at, error, proc_error, wa_msg_id, metadata, phone = row
            content_preview = content[:60] + "..." if len(content) > 60 else content
            print(f"\nTime: {created_at}")
            print(f"Status: {status}")
            print(f"WhatsApp Msg ID: {wa_msg_id}")
            print(f"Content: {content_preview}")
            if error:
                print(f"ERROR: {error}")
            if proc_error:
                print(f"Processing Error: {proc_error}")
            if metadata:
                print(f"Metadata: {metadata}")
            print("-" * 40)
        
        # Also check system logs if available
        print("\n\nChecking for send errors...")
        result2 = conn.execute(text("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN delivery_status = 'failed' THEN 1 ELSE 0 END) as failed,
                   SUM(CASE WHEN delivery_status = 'sent' THEN 1 ELSE 0 END) as sent,
                   SUM(CASE WHEN delivery_status = 'pending' THEN 1 ELSE 0 END) as pending
            FROM whatsapp_messages
            WHERE direction = 'outbound'
              AND created_at >= NOW() - INTERVAL '1 hour'
        """))
        
        row2 = result2.fetchone()
        if row2:
            total, failed, sent, pending = row2
            print(f"\nOutbound in last hour:")
            print(f"  Total: {total}")
            print(f"  Sent: {sent or 0}")
            print(f"  Failed: {failed or 0}")
            print(f"  Pending: {pending or 0}")

if __name__ == "__main__":
    check_errors()
