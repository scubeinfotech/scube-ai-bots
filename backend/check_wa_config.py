#!/usr/bin/env python3
"""Check WhatsApp configuration for scubeinfotech"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine
from sqlalchemy import text

def check_config():
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT phone_number_id, business_account_id, access_token, 
                   webhook_verify_token, is_active, config_metadata
            FROM whatsapp_configurations
            WHERE tenant_id = 'fb8a4ec0-e463-4678-8178-32b8332db73a'
        """))
        
        row = result.fetchone()
        if not row:
            print("No WhatsApp configuration found!")
            return
        
        phone_id, biz_id, token, verify_token, is_active, metadata = row
        
        print("WhatsApp Configuration for scubeinfotech:")
        print("=" * 60)
        print(f"Phone Number ID: {phone_id}")
        print(f"Business Account ID: {biz_id}")
        print(f"Access Token: {token[:20]}..." if token else "Access Token: None")
        print(f"Webhook Verify Token: {verify_token}")
        print(f"Is Active: {is_active}")
        print(f"\nConfig Metadata (JSON):")
        print(metadata)
        
        # Check for MSG91 specific fields
        if metadata:
            import json
            try:
                meta = json.loads(metadata) if isinstance(metadata, str) else metadata
                print(f"\nMSG91 Auth Key present: {'Yes' if meta.get('msg91_auth_key') else 'NO - MISSING!'}")
                print(f"MSG91 Integrated Number: {meta.get('msg91_integrated_number', 'Not set')}")
                print(f"MSG91 API Endpoint: {meta.get('msg91_api_endpoint', 'Using default')}")
            except:
                print("Could not parse metadata")

if __name__ == "__main__":
    check_config()
