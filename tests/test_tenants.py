"""
Tenant API tests
"""
import pytest
from conftest import client


def test_health_check():
    """Test API health endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_create_tenant():
    """Test creating a tenant"""
    response = client.post("/api/tenants/", json={
        "name": "Rapas Engineering",
        "slug": "rapas",
        "domain": "rapas.com.sg",
        "prompt_template": "You are a helpful assistant for Rapas Engineering"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Rapas Engineering"
    assert data["slug"] == "rapas"
    assert data["is_active"] is True


def test_get_tenant(db):
    """Test getting a tenant"""
    # Create tenant first
    create_response = client.post("/api/tenants/", json={
        "name": "Test Tenant",
        "slug": "test-tenant",
        "domain": "test.com"
    })
    tenant_id = create_response.json()["id"]
    
    # Get tenant
    response = client.get(f"/api/tenants/{tenant_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == tenant_id
    assert data["slug"] == "test-tenant"


def test_get_tenant_by_slug():
    """Test getting tenant by slug"""
    # Create tenant
    client.post("/api/tenants/", json={
        "name": "SDSFoodz",
        "slug": "sdsfoodz",
        "domain": "sdsfoodz.com"
    })
    
    # Get by slug
    response = client.get("/api/tenants/slug/sdsfoodz")
    assert response.status_code == 200
    data = response.json()
    assert data["slug"] == "sdsfoodz"


def test_duplicate_slug():
    """Test creating tenant with duplicate slug"""
    # Create first tenant
    client.post("/api/tenants/", json={
        "name": "First",
        "slug": "duplicate",
        "domain": "first.com"
    })
    
    # Try to create with same slug
    response = client.post("/api/tenants/", json={
        "name": "Second",
        "slug": "duplicate",
        "domain": "second.com"
    })
    assert response.status_code == 400


def test_list_tenants():
    """Test listing tenants"""
    # Create multiple tenants
    client.post("/api/tenants/", json={
        "name": "Tenant 1",
        "slug": "tenant-1",
        "domain": "tenant1.com"
    })
    client.post("/api/tenants/", json={
        "name": "Tenant 2",
        "slug": "tenant-2",
        "domain": "tenant2.com"
    })
    
    # List tenants
    response = client.get("/api/tenants/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2


def test_update_tenant_dynamic_config():
    """Test updating tenant knowledge/prompt without code changes."""
    create_response = client.post("/api/tenants/", json={
        "name": "Update Tenant",
        "slug": "update-tenant",
        "domain": "update.com"
    })
    tenant_id = create_response.json()["id"]

    response = client.patch(f"/api/tenants/{tenant_id}", json={
        "prompt_template": "You are an onboarding-ready assistant.",
        "knowledge_context": {
            "products": [
                {
                    "name": "ChronoBill",
                    "aliases": ["chronobill"],
                    "description": "Billing product"
                }
            ]
        }
    })

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == tenant_id
    assert data["name"] == "Update Tenant"
