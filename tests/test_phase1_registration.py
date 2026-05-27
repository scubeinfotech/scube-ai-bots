"""
Tests for Phase 1: Registration, Login, Trial Status, and Public Endpoints
"""
import pytest
from datetime import datetime, timedelta, timezone
from conftest import client, db, TestingSessionLocal
from app.models import Tenant, TenantUser, SubscriptionPlan


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def trial_plan(db):
    """Create a trial subscription plan."""
    plan = SubscriptionPlan(
        name="trial",
        display_name="Free Trial",
        description="7-day free trial",
        price_monthly=0,
        trial_days=7,
        is_active=True,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    yield plan
    db.delete(plan)
    db.commit()


@pytest.fixture
def starter_plan(db):
    """Create a starter subscription plan."""
    plan = SubscriptionPlan(
        name="starter",
        display_name="Starter",
        description="Perfect for small businesses",
        price_monthly=29,
        price_annual=290,
        trial_days=7,
        includes_chatbot=True,
        includes_whatsapp=False,
        monthly_message_limit=2000,
        max_documents=50,
        priority_support=False,
        is_active=True,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    yield plan
    db.delete(plan)
    db.commit()


@pytest.fixture
def registered_tenant(trial_plan, db):
    """Register a tenant via the public API and verify email."""
    response = client.post("/api/public/register", json={
        "business_name": "Test Business",
        "contact_email": "test@example.com",
        "website_url": "https://testbusiness.com",
        "password": "testpass123",
        "industry": "services",
    })
    assert response.status_code == 200
    data = response.json()
    # Auto-verify email for testing
    user = db.query(TenantUser).filter(TenantUser.tenant_id == data["tenant_id"]).first()
    user.email_verified = True
    db.commit()
    return data


# --------------------------------------------------------------------------- #
# Registration Tests
# --------------------------------------------------------------------------- #

class TestRegistration:
    def test_register_success(self, trial_plan):
        """Successful tenant registration."""
        response = client.post("/api/public/register", json={
            "business_name": "Acme Corp",
            "contact_email": "admin@acme.com",
            "website_url": "https://acme.com",
            "password": "password123",
            "industry": "technology",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["tenant_id"] is not None
        assert data["tenant_slug"] is not None
        assert "successful" in data["message"].lower()

    def test_register_duplicate_email(self, registered_tenant):
        """Registration with existing email should fail."""
        response = client.post("/api/public/register", json={
            "business_name": "Another Business",
            "contact_email": "test@example.com",
            "website_url": "https://another.com",
            "password": "password123",
        })
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    def test_register_duplicate_website(self, registered_tenant):
        """Registration with existing website should fail."""
        response = client.post("/api/public/register", json={
            "business_name": "Different Name",
            "contact_email": "different@example.com",
            "website_url": "https://testbusiness.com",
            "password": "password123",
        })
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    def test_register_empty_business_name(self, trial_plan):
        """Registration with empty business name should fail."""
        response = client.post("/api/public/register", json={
            "business_name": "",
            "contact_email": "new@example.com",
            "website_url": "https://new.com",
            "password": "password123",
        })
        assert response.status_code == 422

    def test_register_invalid_email(self, trial_plan):
        """Registration with invalid email should fail."""
        response = client.post("/api/public/register", json={
            "business_name": "Test",
            "contact_email": "not-an-email",
            "website_url": "https://test.com",
            "password": "password123",
        })
        assert response.status_code == 422

    def test_register_weak_password(self, trial_plan):
        """Registration with short password should fail."""
        response = client.post("/api/public/register", json={
            "business_name": "Test",
            "contact_email": "weak@example.com",
            "website_url": "https://weak.com",
            "password": "123",
        })
        assert response.status_code == 422

    def test_register_auto_adds_https(self, trial_plan):
        """Registration should auto-prepend https:// to website URL."""
        response = client.post("/api/public/register", json={
            "business_name": "HTTP Test",
            "contact_email": "http@example.com",
            "website_url": "example.com",
            "password": "password123",
        })
        assert response.status_code == 200

    def test_register_creates_tenant_with_trial(self, trial_plan, db):
        """Registration should create tenant with trial period."""
        response = client.post("/api/public/register", json={
            "business_name": "Trial Test",
            "contact_email": "trial@test.com",
            "website_url": "https://trialtest.com",
            "password": "password123",
        })
        assert response.status_code == 200
        data = response.json()

        # Verify tenant in DB
        tenant = db.query(Tenant).filter(
            Tenant.id == data["tenant_id"]
        ).first()
        assert tenant is not None
        assert tenant.subscription_plan == "trial"
        assert tenant.trial_ends_at is not None
        assert tenant.is_active is True

    def test_register_slug_uniqueness(self, trial_plan):
        """Registration with same business name should generate unique slugs."""
        resp1 = client.post("/api/public/register", json={
            "business_name": "Same Name",
            "contact_email": "first@same.com",
            "website_url": "https://first-same.com",
            "password": "password123",
        })
        resp2 = client.post("/api/public/register", json={
            "business_name": "Same Name",
            "contact_email": "second@same.com",
            "website_url": "https://second-same.com",
            "password": "password123",
        })
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["tenant_slug"] != resp2.json()["tenant_slug"]


# --------------------------------------------------------------------------- #
# Login Tests
# --------------------------------------------------------------------------- #

class TestLogin:
    def test_login_success(self, registered_tenant):
        """Successful login with valid credentials."""
        response = client.post("/api/public/login", json={
            "email": "test@example.com",
            "password": "testpass123",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["token"] is not None
        assert len(data["tenants"]) == 1
        assert data["tenants"][0]["tenant_id"] is not None
        assert data["tenants"][0]["tenant_name"] == "Test Business"
        assert data["tenants"][0]["subscription_plan"] == "trial"

    def test_login_wrong_password(self, registered_tenant):
        """Login with wrong password should fail."""
        response = client.post("/api/public/login", json={
            "email": "test@example.com",
            "password": "wrongpassword",
        })
        assert response.status_code == 401

    def test_login_nonexistent_email(self):
        """Login with non-existent email should fail."""
        response = client.post("/api/public/login", json={
            "email": "nobody@example.com",
            "password": "password123",
        })
        assert response.status_code == 401

    def test_login_case_insensitive_email(self, registered_tenant):
        """Login email should be case-insensitive."""
        response = client.post("/api/public/login", json={
            "email": "TEST@EXAMPLE.COM",
            "password": "testpass123",
        })
        assert response.status_code == 200


# --------------------------------------------------------------------------- #
# Trial Status Tests
# --------------------------------------------------------------------------- #

class TestTrialStatus:
    def test_trial_status_active(self, registered_tenant):
        """Trial status should show active trial with days remaining."""
        response = client.get(f"/api/public/trial/status/{registered_tenant['tenant_id']}")
        assert response.status_code == 200
        data = response.json()
        assert data["trial_active"] is True
        assert data["days_remaining"] > 0
        assert data["subscription_plan"] == "trial"

    def test_trial_status_nonexistent_tenant(self):
        """Trial status for non-existent tenant should return 404."""
        response = client.get("/api/public/trial/status/nonexistent-id")
        assert response.status_code == 404

    def test_trial_expired(self, trial_plan, db):
        """Trial status should show expired when trial_ends_at is in the past."""
        # Register a tenant
        resp = client.post("/api/public/register", json={
            "business_name": "Expired Trial",
            "contact_email": "expired@test.com",
            "website_url": "https://expired.com",
            "password": "password123",
        })
        tenant_id = resp.json()["tenant_id"]

        # Manually set trial to expired
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        tenant.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()

        response = client.get(f"/api/public/trial/status/{tenant_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["trial_active"] is False
        assert data["days_remaining"] == 0


# --------------------------------------------------------------------------- #
# Plans Tests
# --------------------------------------------------------------------------- #

class TestPlans:
    def test_get_plans_empty(self):
        """Get plans when no plans exist."""
        response = client.get("/api/public/plans")
        assert response.status_code == 200
        data = response.json()
        assert data["plans"] == []

    def test_get_plans(self, trial_plan, starter_plan):
        """Get active plans."""
        response = client.get("/api/public/plans")
        assert response.status_code == 200
        data = response.json()
        assert len(data["plans"]) == 2
        # Should be ordered by price
        assert data["plans"][0]["price_monthly"] <= data["plans"][1]["price_monthly"]


# --------------------------------------------------------------------------- #
# Forgot Password Tests
# --------------------------------------------------------------------------- #

class TestForgotPassword:
    def test_forgot_password_existing_email(self, registered_tenant):
        """Forgot password for existing email."""
        response = client.post("/api/public/forgot-password", json={
            "email": "test@example.com",
        })
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_forgot_password_nonexistent_email(self):
        """Forgot password for non-existent email (should not reveal existence)."""
        response = client.post("/api/public/forgot-password", json={
            "email": "nobody@example.com",
        })
        assert response.status_code == 200
        # Should return same message to prevent email enumeration
        assert response.json()["status"] == "success"
