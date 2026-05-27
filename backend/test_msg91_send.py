#!/usr/bin/env python3
"""Test MSG91 send directly to debug the issue"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import aiohttp
from app.database import engine
from sqlalchemy import text

async def test_msg91_send():
    """Test sending via MSG91 API directly"""
    
    # Get config
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT phone_number_id, config_metadata
            FROM whatsapp_configurations
            WHERE tenant_id = 'fb8a4ec0-e463-4678-8178-32b8332db73a'
        """))
        row = result.fetchone()
        if not row:
            print("No config found!")
            return
        
        phone_id, metadata = row
        import json
        meta = json.loads(metadata) if isinstance(metadata, str) else metadata
        
        auth_key = meta.get('msg91_auth_key', '')
        integrated_number = meta.get('msg91_integrated_number', '') or phone_id
        
        print("MSG91 Configuration:")
        print(f"  Auth Key: {auth_key[:10]}...")
        print(f"  Integrated Number: {integrated_number}")
        print()
    
    # Test numbers to try
    test_numbers = [
        "6594561045",      # Without +
        "+6594561045",     # With +
        "656594561045",    # With country code, no +
        "+656594561045",   # Full format
    ]
    
    base_url = "https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/"
    
    headers = {
        "authkey": auth_key,
        "Content-Type": "application/json",
        "accept": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        for phone in test_numbers:
            payload = {
                "integrated_number": integrated_number,
                "recipient_number": phone,
                "content_type": "text",
                "text": f"Test message to {phone} - please confirm if received"
            }
            
            print(f"\nTesting with recipient: {phone}")
            print(f"Payload: {payload}")
            
            try:
                async with session.post(
                    base_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    response_text = await resp.text()
                    print(f"Response Status: {resp.status}")
                    print(f"Response Body: {response_text[:500]}")
                    
                    if resp.status in (200, 201):
                        try:
                            data = await resp.json()
                            print(f"Parsed JSON: {data}")
                        except:
                            pass
                    else:
                        print(f"ERROR: HTTP {resp.status}")
                        
            except Exception as e:
                print(f"Exception: {e}")
            
            print("-" * 60)
            await asyncio.sleep(2)  # Small delay between tests

if __name__ == "__main__":
    asyncio.run(test_msg91_send())
