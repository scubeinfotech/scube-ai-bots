"""
Stripe Service — Payment processing via Stripe Checkout.
Handles checkout session creation, webhook handling, and customer management.
"""
import logging
import os
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Tenant, Invoice, SubscriptionPlan

logger = logging.getLogger(__name__)

# Stripe configuration (set via environment variables in production)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "http://localhost:8000/payment/success")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "http://localhost:8000/payment/cancel")


class StripeService:
    """Service for Stripe payment integration."""

    @classmethod
    def is_configured(cls) -> bool:
        """Check if Stripe is properly configured."""
        return bool(STRIPE_SECRET_KEY and STRIPE_SECRET_KEY != "")

    @classmethod
    def create_checkout_session(cls, tenant_id: str, plan_name: str,
                                db: Session) -> dict:
        """
        Create a Stripe Checkout Session for a tenant's subscription.

        Returns checkout URL that the tenant can be redirected to.
        """
        if not cls.is_configured():
            return {
                "status": "error",
                "message": "Stripe is not configured. Contact admin to set up payments.",
                "mode": "manual",
            }

        # Get plan details
        plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.name == plan_name,
            SubscriptionPlan.is_active == True,
        ).first()

        if not plan:
            return {
                "status": "error",
                "message": f"Plan '{plan_name}' not found",
            }

        # Get tenant
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return {
                "status": "error",
                "message": "Tenant not found",
            }

        # In production: Use stripe Python SDK to create checkout session
        # For now: Return a mock checkout URL
        checkout_url = f"https://checkout.stripe.com/pay/mock_{tenant_id}_{plan_name}"

        # Create invoice record
        invoice = Invoice(
            tenant_id=tenant_id,
            amount=plan.price_monthly,
            currency=plan.currency,
            description=f"{plan.display_name} - Monthly Subscription",
            plan=plan_name,
            payment_method="stripe",
            payment_status="pending",
            due_date=datetime.now(timezone.utc),
        )
        db.add(invoice)
        db.commit()
        db.refresh(invoice)

        logger.info(f"[Stripe] Checkout session created for tenant {tenant_id}, plan {plan_name}")

        return {
            "status": "success",
            "checkout_url": checkout_url,
            "amount": plan.price_monthly,
            "currency": plan.currency,
            "invoice_id": invoice.id,
        }

    @classmethod
    def handle_webhook(cls, payload: bytes, sig_header: str, db: Session) -> dict:
        """
        Handle Stripe webhook events.

        In production: Use stripe.Webhook.construct_event to verify signature.
        For now: Parse the payload directly.
        """
        import json

        try:
            event = json.loads(payload)
            event_type = event.get("type", "")

            if event_type == "checkout.session.completed":
                session_data = event.get("data", {}).get("object", {})
                client_reference_id = session_data.get("client_reference_id", "")
                payment_intent = session_data.get("payment_intent", "")

                # Find and update invoice
                invoice = db.query(Invoice).filter(
                    Invoice.stripe_checkout_session_id == session_data.get("id"),
                ).first()

                if invoice:
                    invoice.payment_status = "paid"
                    invoice.paid_at = datetime.now(timezone.utc)
                    invoice.stripe_payment_intent_id = payment_intent

                    # Update tenant subscription
                    tenant = db.query(Tenant).filter(Tenant.id == invoice.tenant_id).first()
                    if tenant:
                        tenant.subscription_plan = invoice.plan
                        tenant.subscription_status = "active"
                        # Extend trial / set next billing date
                        from datetime import timedelta
                        tenant.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=30)

                    db.commit()
                    logger.info(f"[Stripe] Payment completed for invoice {invoice.id}")

                return {"status": "success", "event": "checkout.session.completed"}

            elif event_type == "checkout.session.expired":
                session_data = event.get("data", {}).get("object", {})
                invoice = db.query(Invoice).filter(
                    Invoice.stripe_checkout_session_id == session_data.get("id"),
                ).first()

                if invoice:
                    invoice.payment_status = "expired"
                    db.commit()

                return {"status": "success", "event": "checkout.session.expired"}

            elif event_type == "invoice.payment_failed":
                logger.warning(f"[Stripe] Payment failed: {event}")
                return {"status": "success", "event": "invoice.payment_failed"}

            return {"status": "ignored", "event": event_type}

        except Exception as e:
            logger.error(f"[Stripe] Webhook processing error: {e}")
            return {"status": "error", "message": str(e)}

    @classmethod
    def get_customer_portal_url(cls, tenant_id: str, db: Session) -> Optional[str]:
        """
        Get Stripe Customer Portal URL for tenant to manage subscription.

        In production: Use stripe.billing_portal.Session.create.
        """
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant or not tenant.stripe_customer_id:
            return None

        # In production: return actual portal URL
        return f"https://billing.stripe.com/p/{tenant.stripe_customer_id}"

    @classmethod
    def cancel_subscription(cls, tenant_id: str, db: Session) -> dict:
        """Cancel a tenant's subscription."""
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return {"status": "error", "message": "Tenant not found"}

        # In production: Cancel via Stripe API
        tenant.subscription_status = "cancelled"
        db.commit()

        logger.info(f"[Stripe] Subscription cancelled for tenant {tenant_id}")
        return {"status": "success", "message": "Subscription cancelled"}
