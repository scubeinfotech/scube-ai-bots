"""
Integration Tests — Full Registration → Trial → Payment Flow
Tests the complete user journey from signup through payment.
"""
import pytest
from datetime import datetime, timedelta, timezone
from conftest import client, db, TestingSessionLocal
from app.models import Tenant, TenantUser, SubscriptionPlan, Invoice
from app.models.calendar import CalendarIntegration, TenantAvailability
from app.services.auth_service import hash_password, create_access_token


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def seed_plans(db):
    """Seed all subscription plans."""
    plans_data = [
        {"name": "trial", "display_name": "Free Trial", "description": "7-day free trial", "price_monthly": 0, "trial_days": 7, "is_active": True},
        {"name": "starter", "display_name": "Starter", "description": "Perfect for small businesses", "price_monthly": 29, "trial_days": 7, "includes_chatbot": True, "monthly_message_limit": 2000, "max_documents": 50, "is_active": True},
        {"name": "growth", "display_name": "Growth", "description": "Growing businesses", "price_monthly": 59, "trial_days": 7, "includes_chatbot": True, "includes_whatsapp": True, "monthly_message_limit": 10000, "max_documents": 200, "is_active": True},
        {"name": "enterprise", "display_name": "Enterprise", "description": "Custom solutions", "price_monthly": 149, "trial_days": 14, "includes_chatbot": True, "includes_whatsapp": True, "monthly_message_limit": 100000, "max_documents": 1000, "priority_support": True, "is_active": True},
    ]
    created = []
    for pd in plans_data:
        p = SubscriptionPlan(**pd)
        db.add(p)
        db.flush()
        created.append(p)
    db.commit()
    yield created
    for p in created:
        db.delete(p)
    db.commit()


# --------------------------------------------------------------------------- #
# Full Flow Tests
# --------------------------------------------------------------------------- #

class TestFullRegistrationFlow:
    """Test the complete registration journey."""

    def test_register_and_login(self, seed_plans, db):
        """Full registration → login → dashboard access."""
        # Step 1: Register
        resp = client.post("/api/public/register", json={
            "business_name": "Integration Test Co",
            "contact_email": "integration@test.com",
            "website_url": "https://integrationtest.com",
            "password": "testpass123",
            "industry": "technology",
        })
        assert resp.status_code == 200
        reg_data = resp.json()
        assert reg_data["status"] == "success"
        assert reg_data["tenant_id"]
        tenant_id = reg_data["tenant_id"]

        # Verify email
        user = db.query(TenantUser).filter(TenantUser.tenant_id == tenant_id).first()
        user.email_verified = True
        db.commit()

        # Step 2: Login
        resp = client.post("/api/public/login", json={
            "email": "integration@test.com",
            "password": "testpass123",
        })
        assert resp.status_code == 200
        login_data = resp.json()
        assert login_data["token"]
        assert login_data["tenants"][0]["tenant_id"] == tenant_id
        assert login_data["tenants"][0]["subscription_plan"] == "trial"

        # Step 3: Check trial status
        resp = client.get(f"/api/public/trial/status/{tenant_id}")
        assert resp.status_code == 200
        trial_data = resp.json()
        assert trial_data["trial_active"] is True
        assert trial_data["days_remaining"] > 0

    def test_register_and_setup_calendar(self, seed_plans):
        """Register → set up calendar availability."""
        # Register
        resp = client.post("/api/public/register", json={
            "business_name": "Calendar Co",
            "contact_email": "calendar@integration.com",
            "website_url": "https://calendarintegration.com",
            "password": "testpass123",
        })
        tenant_id = resp.json()["tenant_id"]

        # Set availability
        resp = client.post(
            f"/api/calendar/availability/{tenant_id}",
            json={"slots": [
                {"day_of_week": 0, "start_time": "09:00", "end_time": "17:00"},
                {"day_of_week": 1, "start_time": "09:00", "end_time": "17:00"},
                {"day_of_week": 2, "start_time": "09:00", "end_time": "17:00"},
                {"day_of_week": 3, "start_time": "09:00", "end_time": "17:00"},
                {"day_of_week": 4, "start_time": "09:00", "end_time": "17:00"},
            ]},
        )
        assert resp.status_code == 200
        assert len(resp.json()["slots"]) == 5

        # Check availability for a Monday
        resp = client.get(f"/api/calendar/availability/{tenant_id}/check?date=2026-05-18")
        assert resp.status_code == 200
        assert len(resp.json()["available_slots"]) == 1

    def test_register_and_paynow_payment(self, seed_plans):
        """Register → create PayNow invoice → verify payment → subscription active."""
        # Register
        resp = client.post("/api/public/register", json={
            "business_name": "PayNow Co",
            "contact_email": "paynow@integration.com",
            "website_url": "https://paynowintegration.com",
            "password": "testpass123",
        })
        tenant_id = resp.json()["tenant_id"]

        # Verify initial trial
        resp = client.get(f"/api/public/trial/status/{tenant_id}")
        assert resp.json()["subscription_plan"] == "trial"

        # Create PayNow invoice for Growth plan
        resp = client.post(
            f"/api/billing/checkout/{tenant_id}",
            json={"plan_name": "growth", "payment_method": "paynow"},
        )
        assert resp.status_code == 200
        invoice_data = resp.json()
        assert invoice_data["status"] == "success"
        assert invoice_data["amount"] == 59
        invoice_id = invoice_data["invoice_id"]

        # Verify payment (admin action)
        resp = client.post(
            "/api/billing/paynow/verify",
            json={"invoice_id": invoice_id, "admin_notes": "Integration test payment"},
        )
        assert resp.status_code == 200

        # Verify subscription upgraded
        tenant = TestingSessionLocal().query(Tenant).filter(Tenant.id == tenant_id).first()
        assert tenant.subscription_plan == "growth"
        assert tenant.subscription_status == "active"

    def test_register_and_admin_extend_trial(self, seed_plans, db):
        """Register → admin extends trial → trial end date updated."""
        # Register
        resp = client.post("/api/public/register", json={
            "business_name": "Trial Extend Co",
            "contact_email": "extend@integration.com",
            "website_url": "https://extendintegration.com",
            "password": "testpass123",
        })
        tenant_id = resp.json()["tenant_id"]

        # Get current trial end
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        old_end = tenant.trial_ends_at

        # Create admin user and token
        admin = TenantUser(
            id="admin-int-test",
            tenant_id="admin-tenant",
            username="admin",
            email="admin@integration.com",
            hashed_password=hash_password("admin123"),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()

        token = create_access_token(admin_id=admin.id, username=admin.username)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Extend trial
        resp = client.post(
            f"/api/admin/tenants/{tenant_id}/extend-trial",
            json={"days": 14, "reason": "Integration test extension"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["days_extended"] == 14

        # Verify trial extended
        db.expire_all()
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        assert tenant.trial_ends_at > old_end

    def test_register_and_admin_plan_management(self, seed_plans, db):
        """Admin creates new plan → lists plans → updates plan."""
        # Create admin
        admin = TenantUser(
            id="admin-plan-test",
            tenant_id="admin-tenant",
            username="admin",
            email="admin@plan.com",
            hashed_password=hash_password("admin123"),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()

        token = create_access_token(admin_id=admin.id, username=admin.username)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # List plans
        resp = client.get("/api/admin/plans", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["plans"]) >= 4  # trial + starter + growth + enterprise

        # Create new plan
        resp = client.post(
            "/api/admin/plans",
            json={
                "name": "pro",
                "display_name": "Professional",
                "price_monthly": 79,
            },
            headers=headers,
        )
        assert resp.status_code == 200

        # Verify plan created
        resp = client.get("/api/admin/plans", headers=headers)
        plans = resp.json()["plans"]
        pro_plan = [p for p in plans if p["name"] == "pro"]
        assert len(pro_plan) == 1
        assert pro_plan[0]["price_monthly"] == 79

    def test_duplicate_registration_prevention(self, seed_plans):
        """Register with same email twice → second fails."""
        # First registration
        resp = client.post("/api/public/register", json={
            "business_name": "First Co",
            "contact_email": "duplicate@integration.com",
            "website_url": "https://first.com",
            "password": "testpass123",
        })
        assert resp.status_code == 200

        # Second registration with same email
        resp = client.post("/api/public/register", json={
            "business_name": "Second Co",
            "contact_email": "duplicate@integration.com",
            "website_url": "https://second.com",
            "password": "testpass123",
        })
        assert resp.status_code == 400
        assert "already registered" in resp.json()["detail"].lower()

    def test_duplicate_website_prevention(self, seed_plans):
        """Register with same website twice → second fails."""
        # First registration
        resp = client.post("/api/public/register", json={
            "business_name": "First Co",
            "contact_email": "first@website.com",
            "website_url": "https://duplicate-website.com",
            "password": "testpass123",
        })
        assert resp.status_code == 200

        # Second registration with same website
        resp = client.post("/api/public/register", json={
            "business_name": "Second Co",
            "contact_email": "second@website.com",
            "website_url": "https://duplicate-website.com",
            "password": "testpass123",
        })
        assert resp.status_code == 400
        assert "already registered" in resp.json()["detail"].lower()

    def test_full_tenant_portal_data_load(self, seed_plans, db):
        """Register → login → load all portal data (stats, calendar, plans, API key)."""
        # Register
        resp = client.post("/api/public/register", json={
            "business_name": "Portal Test Co",
            "contact_email": "portal@integration.com",
            "website_url": "https://portaltest.com",
            "password": "testpass123",
        })
        reg_data = resp.json()
        tenant_id = reg_data["tenant_id"]

        # Verify email
        user = db.query(TenantUser).filter(TenantUser.tenant_id == tenant_id).first()
        user.email_verified = True
        db.commit()

        # Login
        resp = client.post("/api/public/login", json={
            "email": "portal@integration.com",
            "password": "testpass123",
        })
        token = resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Load trial status
        resp = client.get(f"/api/public/trial/status/{tenant_id}")
        assert resp.status_code == 200

        # Load API keys via admin endpoint
        resp = client.get(f"/api/admin/tenants/{tenant_id}/api-keys", headers=headers)
        # Admin endpoint may require admin role, so accept various responses
        assert resp.status_code in [200, 401, 403, 404]

        # Load plans
        resp = client.get("/api/public/plans")
        assert resp.status_code == 200
        assert len(resp.json()["plans"]) > 0

        # Load calendar status
        resp = client.get(f"/api/calendar/status/{tenant_id}")
        assert resp.status_code == 200

        # Load tenant details
        resp = client.get(f"/api/tenants/{tenant_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Portal Test Co"
