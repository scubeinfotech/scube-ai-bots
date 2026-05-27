"""
Standalone test for chatbot hello message via API
"""
import sys
import os
import requests

# Adjust path to import app if needed (not global)
backend_path = os.path.join(os.path.dirname(__file__), '../backend')
sys.path.insert(0, os.path.abspath(backend_path))

API_URL = "http://localhost:8000"

def test_chatbot_hello():
    # 1. Create a tenant
    import random, string
    unique_slug = "test-tenant-script-" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    tenant_payload = {
        "name": "Test Tenant",
        "slug": unique_slug,
        "domain": "test-script.com"
    }
    r = requests.post(f"{API_URL}/api/tenants/", json=tenant_payload)
    assert r.status_code == 201, f"Tenant creation failed: {r.text}"
    tenant_id = r.json()["id"]

    # 2. Send a hello message
    chat_payload = {
        "content": "Hello",
        "user_id": "test-user-script"
    }
    headers = {"x-api-key": "test-api-key"}
    r2 = requests.post(f"{API_URL}/api/chat/message/{tenant_id}", json=chat_payload, headers=headers)
    assert r2.status_code == 201, f"Chat message failed: {r2.text}"
    data = r2.json()
    print("Assistant reply:", data.get("content"))
    assert data["role"] == "assistant"
    assert "hello" in data["content"].lower() or "hi" in data["content"].lower()

if __name__ == "__main__":
    test_chatbot_hello()
    print("Chatbot hello test passed.")
