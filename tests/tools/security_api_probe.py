"""
Test script for API Key security features
Tests cross-tenant blocking and domain validation
"""
import requests
import json

BASE_URL = "http://localhost:8000"

def get_tenant_info(tenant_id):
    """Get tenant details"""
    response = requests.get(f"{BASE_URL}/api/tenants/{tenant_id}")
    return response.json() if response.ok else None

def get_tenant_api_keys(tenant_id):
    """Get all API keys for a tenant"""
    response = requests.get(f"{BASE_URL}/api/admin/tenants/{tenant_id}/api-keys")
    return response.json() if response.ok else None

def get_api_key_usage(api_key_id):
    """Get usage stats for an API key"""
    response = requests.get(f"{BASE_URL}/api/admin/api-keys/{api_key_id}/usage")
    return response.json() if response.ok else None

def send_chat_message(tenant_id, api_key, message, origin=None):
    """Send a chat message (simulates widget)"""
    headers = {"X-API-Key": api_key}
    if origin:
        headers["Origin"] = origin
    
    response = requests.post(
        f"{BASE_URL}/api/chat/message/{tenant_id}",
        json={"content": message},
        headers=headers
    )
    return {
        "status_code": response.status_code,
        "response": response.json() if response.ok else response.text
    }

def main():
    print("=" * 60)
    print("API KEY SECURITY TEST")
    print("=" * 60)
    
    # Get all tenants
    print("\n1. Getting all tenants...")
    response = requests.get(f"{BASE_URL}/api/tenants")
    tenants = response.json()
    print(f"   Found {len(tenants)} tenants")
    
    if len(tenants) < 2:
        print("   ERROR: Need at least 2 tenants to test cross-tenant blocking")
        print("   Create another tenant first!")
        return
    
    tenant_a = tenants[0]
    tenant_b = tenants[1] if len(tenants) > 1 else None
    
    print(f"\n   Tenant A: {tenant_a['name']} (ID: {tenant_a['id']})")
    if tenant_b:
        print(f"   Tenant B: {tenant_b['name']} (ID: {tenant_b['id']})")
    
    # Get API keys for Tenant A
    print(f"\n2. Getting API keys for {tenant_a['name']}...")
    keys_a = get_tenant_api_keys(tenant_a['id'])
    if not keys_a or not keys_a.get('api_keys'):
        print("   ERROR: No API keys found for Tenant A")
        return
    
    api_key_a = keys_a['api_keys'][0]
    print(f"   Key ID: {api_key_a['id']}")
    print(f"   Key Name: {api_key_a['name']}")
    print(f"   Allowed Domains: {api_key_a.get('allowed_domains', 'not set')}")
    
    # Get API keys for Tenant B
    if tenant_b:
        print(f"\n3. Getting API keys for {tenant_b['name']}...")
        keys_b = get_tenant_api_keys(tenant_b['id'])
        if not keys_b or not keys_b.get('api_keys'):
            print("   WARNING: No API keys found for Tenant B")
            api_key_b = None
        else:
            api_key_b = keys_b['api_keys'][0]
            print(f"   Key ID: {api_key_b['id']}")
    
    # TEST 1: Cross-tenant blocking
    print("\n" + "=" * 60)
    print("TEST 1: Cross-Tenant API Key Usage")
    print("=" * 60)
    print(f"\nUsing Tenant A's API key to chat with Tenant B...")
    
    if tenant_b and api_key_a:
        result = send_chat_message(tenant_b['id'], api_key_a['key'], "Hello from wrong tenant!")
        print(f"\n   Status Code: {result['status_code']}")
        print(f"   Response: {json.dumps(result['response'], indent=2)}")
        
        if result['status_code'] == 401:
            print("   ✅ PASS: Cross-tenant usage correctly blocked!")
        else:
            print("   ❌ FAIL: Should have been blocked with 401!")
    else:
        print("   SKIP: Need two tenants to test this")
    
    # TEST 2: Valid tenant usage
    print("\n" + "=" * 60)
    print("TEST 2: Valid Tenant API Key Usage")
    print("=" * 60)
    print(f"\nUsing Tenant A's API key to chat with Tenant A (should work)...")
    
    if api_key_a:
        result = send_chat_message(tenant_a['id'], api_key_a['key'], "Hello from correct tenant!")
        print(f"\n   Status Code: {result['status_code']}")
        
        if result['status_code'] == 201:
            print("   ✅ PASS: Valid request succeeded!")
        else:
            print(f"   ⚠️  Response: {json.dumps(result['response'], indent=2)}")
    
    # TEST 3: Domain validation (if allowed_domains set)
    print("\n" + "=" * 60)
    print("TEST 3: Domain Validation")
    print("=" * 60)
    
    allowed_domains = api_key_a.get('allowed_domains') if api_key_a else None
    if allowed_domains:
        # Test with wrong domain
        print(f"\nTesting with unauthorized domain...")
        result = send_chat_message(
            tenant_a['id'], 
            api_key_a['key'], 
            "Test from evil.com",
            origin="https://evil.com"
        )
        print(f"   Status Code: {result['status_code']}")
        print(f"   Response: {json.dumps(result['response'], indent=2)}")
        
        if result['status_code'] == 403:
            print("   ✅ PASS: Wrong domain correctly blocked!")
        else:
            print("   ❌ FAIL: Should have been blocked with 403!")
        
        # Test with correct domain
        correct_domain = allowed_domains.split(',')[0].strip()
        print(f"\nTesting with authorized domain: {correct_domain}")
        result = send_chat_message(
            tenant_a['id'], 
            api_key_a['key'], 
            "Test from correct domain",
            origin=f"https://{correct_domain}"
        )
        print(f"   Status Code: {result['status_code']}")
        
        if result['status_code'] in [201, 200]:
            print("   ✅ PASS: Correct domain allowed!")
    else:
        print("   SKIP: No allowed_domains set on this key")
        print("   (Domain validation only works if allowed_domains is set)")
    
    # TEST 4: Rate limiting
    print("\n" + "=" * 60)
    print("TEST 4: Rate Limit Check")
    print("=" * 60)
    
    usage = get_api_key_usage(api_key_a['id'])
    if usage:
        print(f"\n   Rate Limit Per Minute: {usage['rate_limit_per_minute']}")
        print(f"   Rate Limit Per Hour: {usage['rate_limit_per_hour']}")
        print(f"   Current Minute Usage: {usage['current_minute_usage']}")
        print(f"   Current Hour Usage: {usage['current_hour_usage']}")
        print(f"   Last Used: {usage['last_used_at']}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()