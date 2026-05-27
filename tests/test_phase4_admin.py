"""
Tests for Phase 4: Simplified Admin Dashboard — Trial Extension, Plan Management
"""
import pytest
from datetime import datetime, timedelta, timezone
from conftest import client, db, TestingSessionLocal
from app.models import Tenant, TenantUser, SubscriptionPlan, AdminUser
from app.services.auth_service import hash_password, create_access_token


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def trial_plan(db):
    plan = SubscriptionPlan(
        name="trial", display_name="Free Trial", description="7-day free trial",
        price_monthly=0, trial_days=7, is_active=True,
    )
    db.add(plan); db.commit(); db.refresh(plan)
    yield plan
    db.delete(plan); db.commit()


@pytest.fixture
def starter_plan(db):
    plan = SubscriptionPlan(
        name="starter", display_name="Starter", description="Perfect for small businesses",
        price_monthly=29, price_annual=290, trial_days=7,
        includes_chatbot=True, includes_whatsapp=False,
        monthly_message_limit=2000, max_documents=50,
        priority_support=False, is_active=True,
    )
    db.add(plan); db.commit(); db.refresh(plan)
    yield plan
    db.delete(plan); db.commit()


@pytest.fixture
def admin_user(db):
    user = AdminUser(
        id="admin-test-001",
        username="admin",
        email="admin@test.com",
        hashed_password=hash_password("admin123"),
        is_active=True,
    )
    db.add(user); db.commit(); db.refresh(user)
    yield user
    db.delete(user); db.commit()


@pytest.fixture
def admin_token(admin_user):
    return create_access_token(admin_id=admin_user.id, username=admin_user.username)


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture
def registered_tenant(trial_plan):
    response = client.post("/api/public/register", json={
        "business_name": "Admin Test Business",
        "contact_email": "admin@test.com",
        "website_url": "https://admintest.com",
        "password": "testpass123",
    })
    assert response.status_code == 200
    return response.json()


# --------------------------------------------------------------------------- #
# Trial Extension Tests
# --------------------------------------------------------------------------- #

class TestTrialExtension:
    def test_extend_trial_success(self, registered_tenant, admin_headers, db):
        """Extend a tenant's trial."""
        tenant_id = registered_tenant["tenant_id"]

        # Get current trial end
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        old_end = tenant.trial_ends_at

        response = client.post(
            f"/api/admin/tenants/{tenant_id}/extend-trial",
            json={"days": 14, "reason": "Customer requested extension"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["days_extended"] == 14

        # Verify trial extended
        db.expire_all()
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        assert tenant.trial_ends_at > old_end

    def test_extend_trial_nonexistent_tenant(self, admin_headers):
        """Extend trial for non-existent tenant should return 404."""
        response = client.post(
            "/api/admin/tenants/nonexistent/extend-trial",
            json={"days": 7},
            headers=admin_headers,
        )
        assert response.status_code == 404

    def test_extend_trial_invalid_days(self, registered_tenant, admin_headers):
        """Extend trial with invalid days should fail validation."""
        tenant_id = registered_tenant["tenant_id"]
        response = client.post(
            f"/api/admin/tenants/{tenant_id}/extend-trial",
            json={"days": 0},
            headers=admin_headers,
        )
        assert response.status_code == 422

        response = client.post(
            f"/api/admin/tenants/{tenant_id}/extend-trial",
            json={"days": 31},
            headers=admin_headers,
        )
        assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Plan Management Tests
# --------------------------------------------------------------------------- #

class TestPlanManagement:
    def test_list_plans(self, admin_headers, trial_plan, starter_plan):
        """List all plans."""
        response = client.get("/api/admin/plans", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["plans"]) == 2

    def test_create_plan(self, admin_headers):
        """Create a new subscription plan."""
        response = client.post(
            "/api/admin/plans",
            json={
                "name": "premium",
                "display_name": "Premium",
                "description": "For large businesses",
                "price_monthly": 99,
                "price_annual": 990,
                "trial_days": 14,
                "includes_chatbot": True,
                "includes_whatsapp": True,
                "monthly_message_limit": 50000,
                "max_documents": 500,
                "priority_support": True,
            },
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["plan"]["name"] == "premium"

    def test_create_duplicate_plan(self, admin_headers, starter_plan):
        """Create plan with duplicate name should fail."""
        response = client.post(
            "/api/admin/plans",
            json={
                "name": "starter",
                "display_name": "Starter Copy",
                "price_monthly": 29,
            },
            headers=admin_headers,
        )
        assert response.status_code == 400

    def test_update_plan(self, admin_headers, starter_plan):
        """Update an existing plan."""
        response = client.put(
            f"/api/admin/plans/{starter_plan.id}",
            json={"price_monthly": 39, "display_name": "Starter Plus"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_update_nonexistent_plan(self, admin_headers):
        """Update non-existent plan should return 404."""
        response = client.put(
            "/api/admin/plans/nonexistent",
            json={"price_monthly": 39},
            headers=admin_headers,
        )
        assert response.status_code == 404

    def test_delete_plan(self, admin_headers, starter_plan):
        """Soft-delete a plan."""
        response = client.delete(
            f"/api/admin/plans/{starter_plan.id}",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        # Verify plan is deactivated
        get_response = client.get("/api/admin/plans", headers=admin_headers)
        plans = get_response.json()["plans"]
        starter = [p for p in plans if p["name"] == "starter"]
        assert len(starter) == 1
        assert starter[0]["is_active"] is False

    def test_delete_nonexistent_plan(self, admin_headers):
        """Delete non-existent plan should return 404."""
        response = client.delete(
            "/api/admin/plans/nonexistent",
            headers=admin_headers,
        )
        assert response.status_code == 404
