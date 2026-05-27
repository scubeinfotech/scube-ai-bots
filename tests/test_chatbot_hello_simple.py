"""
Reusable chatbot hello test using pre-existing tenant and API key.
Update TENANT_ID and API_KEY as needed for your environment.
"""
import requests

API_URL = "http://localhost:8000"
TENANT_ID = "c66e96d3-999c-4746-b11c-1758a9c2e982"  # Example from widget/test.html
API_KEY = "test-api-key"  # Example from widget/test.html

def test_chatbot_hello():
    chat_payload = {
        "content": "Hello",
        "user_id": "test-user-script"
    }
    headers = {"x-api-key": API_KEY}
    r = requests.post(f"{API_URL}/api/chat/message/{TENANT_ID}", json=chat_payload, headers=headers)
    assert r.status_code == 201, f"Chat message failed: {r.text}"
    data = r.json()
    print("Assistant reply:", data.get("content"))
    assert data["role"] == "assistant"
    assert "hello" in data["content"].lower() or "hi" in data["content"].lower()

if __name__ == "__main__":
    test_chatbot_hello()
    print("Chatbot hello test passed.")
