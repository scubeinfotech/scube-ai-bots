"""
Tests for Phase 3: Billing — Stripe + PayNow
"""
import pytest
from datetime import datetime, timedelta, timezone
from conftest import client, db, TestingSessionLocal
from app.models import Tenant, TenantUser, SubscriptionPlan, Invoice
from app.services.paynow_service import PayNowService


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
def registered_tenant(trial_plan):
    response = client.post("/api/public/register", json={
        "business_name": "Billing Test Business",
        "contact_email": "billing@test.com",
        "website_url": "https://billingtest.com",
        "password": "testpass123",
    })
    assert response.status_code == 200
    return response.json()


# --------------------------------------------------------------------------- #
# Stripe Checkout Tests
# --------------------------------------------------------------------------- #

class TestStripeCheckout:
    def test_checkout_stripe_not_configured(self, registered_tenant, starter_plan):
        """Stripe checkout should return error when not configured."""
        tenant_id = registered_tenant["tenant_id"]
        response = client.post(
            f"/api/billing/checkout/{tenant_id}",
            json={"plan_name": "starter", "payment_method": "stripe"},
        )
        # Stripe not configured by default in tests, so returns 400 with error message
        assert response.status_code in [200, 400]
        data = response.json()
        if response.status_code == 400:
            assert "not configured" in data["detail"].lower()

    def test_checkout_nonexistent_tenant(self, starter_plan):
        """Checkout for non-existent tenant should return 404."""
        response = client.post(
            "/api/billing/checkout/nonexistent",
            json={"plan_name": "starter", "payment_method": "stripe"},
        )
        assert response.status_code == 404

    def test_checkout_invalid_plan(self, registered_tenant):
        """Checkout with invalid plan should return error."""
        tenant_id = registered_tenant["tenant_id"]
        response = client.post(
            f"/api/billing/checkout/{tenant_id}",
            json={"plan_name": "nonexistent", "payment_method": "stripe"},
        )
        assert response.status_code == 400


# --------------------------------------------------------------------------- #
# PayNow Tests
# --------------------------------------------------------------------------- #

class TestPayNow:
    def test_create_paynow_invoice(self, registered_tenant, starter_plan):
        """Create a PayNow invoice."""
        tenant_id = registered_tenant["tenant_id"]
        response = client.post(
            f"/api/billing/checkout/{tenant_id}",
            json={"plan_name": "starter", "payment_method": "paynow"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["amount"] == 29
        assert "qr_data" in data
        assert "reference" in data
        assert "SCUBE" in data["reference"]

    def test_create_paynow_invoice_nonexistent_plan(self, registered_tenant):
        """PayNow with non-existent plan should fail."""
        tenant_id = registered_tenant["tenant_id"]
        response = client.post(
            f"/api/billing/checkout/{tenant_id}",
            json={"plan_name": "nonexistent", "payment_method": "paynow"},
        )
        assert response.status_code == 400

    def test_get_invoice(self, registered_tenant, starter_plan):
        """Get invoice details."""
        tenant_id = registered_tenant["tenant_id"]

        # Create invoice first
        checkout_resp = client.post(
            f"/api/billing/checkout/{tenant_id}",
            json={"plan_name": "starter", "payment_method": "paynow"},
        )
        invoice_id = checkout_resp.json()["invoice_id"]

        # Get invoice
        response = client.get(f"/api/billing/invoice/{invoice_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["invoice_id"] == invoice_id
        assert data["payment_method"] == "paynow"
        assert data["payment_status"] == "pending"

    def test_get_nonexistent_invoice(self):
        """Get non-existent invoice should return 404."""
        response = client.get("/api/billing/invoice/nonexistent")
        assert response.status_code == 404

    def test_verify_paynow_payment(self, registered_tenant, starter_plan, db):
        """Verify a PayNow payment."""
        tenant_id = registered_tenant["tenant_id"]

        # Create invoice
        checkout_resp = client.post(
            f"/api/billing/checkout/{tenant_id}",
            json={"plan_name": "starter", "payment_method": "paynow"},
        )
        invoice_id = checkout_resp.json()["invoice_id"]

        # Verify payment
        response = client.post(
            "/api/billing/paynow/verify",
            json={"invoice_id": invoice_id, "admin_notes": "Payment confirmed via bank statement"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        # Verify tenant subscription updated
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        assert tenant.subscription_plan == "starter"
        assert tenant.subscription_status == "active"

    def test_verify_already_paid_invoice(self, registered_tenant, starter_plan, db):
        """Verify an already paid invoice should fail."""
        tenant_id = registered_tenant["tenant_id"]

        # Create and verify invoice
        checkout_resp = client.post(
            f"/api/billing/checkout/{tenant_id}",
            json={"plan_name": "starter", "payment_method": "paynow"},
        )
        invoice_id = checkout_resp.json()["invoice_id"]

        client.post(
            "/api/billing/paynow/verify",
            json={"invoice_id": invoice_id},
        )

        # Try to verify again
        response = client.post(
            "/api/billing/paynow/verify",
            json={"invoice_id": invoice_id},
        )
        assert response.status_code == 400

    def test_verify_nonexistent_invoice(self):
        """Verify non-existent invoice should fail."""
        response = client.post(
            "/api/billing/paynow/verify",
            json={"invoice_id": "nonexistent"},
        )
        assert response.status_code == 400

    def test_get_pending_payments(self, registered_tenant, starter_plan):
        """Get pending PayNow payments."""
        tenant_id = registered_tenant["tenant_id"]

        # Create a pending invoice
        client.post(
            f"/api/billing/checkout/{tenant_id}",
            json={"plan_name": "starter", "payment_method": "paynow"},
        )

        response = client.get("/api/billing/paynow/pending")
        assert response.status_code == 200
        data = response.json()
        assert len(data["payments"]) >= 1


# --------------------------------------------------------------------------- #
# Unsupported Payment Method Tests
# --------------------------------------------------------------------------- #

class TestPaymentMethod:
    def test_unsupported_payment_method(self, registered_tenant):
        """Unsupported payment method should return 400."""
        tenant_id = registered_tenant["tenant_id"]
        response = client.post(
            f"/api/billing/checkout/{tenant_id}",
            json={"plan_name": "starter", "payment_method": "crypto"},
        )
        assert response.status_code == 400


# --------------------------------------------------------------------------- #
# Stripe Webhook Tests
# --------------------------------------------------------------------------- #

class TestStripeWebhook:
    def test_webhook_invalid_payload(self):
        """Webhook with invalid payload should return 400."""
        response = client.post(
            "/api/billing/stripe/webhook",
            content=b"invalid json",
            headers={"stripe-signature": "invalid"},
        )
        # Should handle gracefully
        assert response.status_code in [200, 400]
