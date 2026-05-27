"""
Chat API tests
"""
import pytest
from conftest import client


def test_send_message(db):
    """Test sending a chat message"""
    # Create tenant first
    create_tenant_response = client.post("/api/tenants/", json={
        "name": "Test Tenant",
        "slug": "test-tenant",
        "domain": "test.com"
    })
    tenant_id = create_tenant_response.json()["id"]
    
    # Send message
    response = client.post(f"/api/chat/message/{tenant_id}", json={
        "content": "Hello, how can I help?",
        "user_id": "user-123"
    })
    
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["role"] == "assistant"
    assert "session_id" in data


def test_get_session_messages(db):
    """Test getting messages from a session"""
    # Create tenant
    create_tenant_response = client.post("/api/tenants/", json={
        "name": "Test Tenant",
        "slug": "test-tenant-2",
        "domain": "test2.com"
    })
    tenant_id = create_tenant_response.json()["id"]
    
    # Send first message
    msg1_response = client.post(f"/api/chat/message/{tenant_id}", json={
        "content": "First message"
    })
    session_id = msg1_response.json()["session_id"]
    
    # Send second message to same session
    msg2_response = client.post(f"/api/chat/message/{tenant_id}", json={
        "content": "Second message",
        "session_id": session_id
    })
    
    # Get all messages in session
    response = client.get(f"/api/chat/session/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2  # At least user + assistant messages


def test_message_invalid_tenant():
    """Test sending message to non-existent tenant"""
    response = client.post("/api/chat/message/invalid-tenant-id", json={
        "content": "Hello"
    })
    assert response.status_code == 404
