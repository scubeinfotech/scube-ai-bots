"""
PayNow Service — Payment processing via PayNow (Singapore).
Handles QR code generation, payment reference tracking, and manual verification.
"""
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Tenant, Invoice, SubscriptionPlan

logger = logging.getLogger(__name__)

# PayNow configuration
PAYNOW_UEN = os.getenv("PAYNOW_UEN", "202600001A")  # Company UEN
PAYNOW_EMAIL = os.getenv("PAYNOW_EMAIL", "payments@scubeinfotech.com.sg")


class PayNowService:
    """Service for PayNow payment integration."""

    @classmethod
    def generate_payment_reference(cls, tenant_id: str, invoice_id: str) -> str:
        """Generate a unique PayNow payment reference."""
        # Format: SCUBE-{tenant_slug_part}-{invoice_short}-{random}
        short_tenant = tenant_id[:8]
        short_invoice = invoice_id[:8]
        random_part = uuid.uuid4().hex[:6].upper()
        return f"SCUBE-{short_tenant}-{short_invoice}-{random_part}"

    @classmethod
    def generate_qr_data(cls, amount: float, reference: str, currency: str = "SGD") -> str:
        """
        Generate PayNow QR code data string.

        In production: Use actual PayNow QR generation library or API.
        For now: Generate a simplified string that encodes payment details.
        """
        # Simplified PayNow QR data format
        # In production, this would use EMV QR Code standard
        return f"PAYNOW|{PAYNOW_UEN}|{amount:.2f}|{currency}|{reference}"

    @classmethod
    def create_paynow_invoice(cls, tenant_id: str, plan_name: str,
                              db: Session) -> dict:
        """
        Create a PayNow payment invoice with QR code.
        """
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

        # Generate reference and QR data
        invoice_id = str(uuid.uuid4())
        reference = cls.generate_payment_reference(tenant_id, invoice_id)
        qr_data = cls.generate_qr_data(plan.price_monthly, reference, plan.currency)

        # Create invoice record
        invoice = Invoice(
            id=invoice_id,
            tenant_id=tenant_id,
            amount=plan.price_monthly,
            currency=plan.currency,
            description=f"{plan.display_name} - Monthly Subscription (PayNow)",
            plan=plan_name,
            payment_method="paynow",
            payment_status="pending",
            paynow_qr_data=qr_data,
            paynow_reference=reference,
            due_date=datetime.now(timezone.utc) + timedelta(days=3),
        )
        db.add(invoice)
        db.commit()
        db.refresh(invoice)

        logger.info(f"[PayNow] Invoice created for tenant {tenant_id}, ref {reference}")

        return {
            "status": "success",
            "invoice_id": invoice.id,
            "amount": plan.price_monthly,
            "currency": plan.currency,
            "qr_data": qr_data,
            "reference": reference,
            "paynow_uen": PAYNOW_UEN,
            "paynow_email": PAYNOW_EMAIL,
            "due_date": invoice.due_date.isoformat(),
            "instructions": (
                f"1. Open your bank app and scan the QR code\n"
                f"2. Or pay via PayNow to UEN: {PAYNOW_UEN}\n"
                f"3. Reference: {reference}\n"
                f"4. Payment will be verified within 24 hours"
            ),
        }

    @classmethod
    def verify_payment(cls, invoice_id: str, db: Session,
                       admin_notes: str = "") -> dict:
        """
        Manually verify a PayNow payment (admin action).

        Admin checks bank statement, matches reference, then marks as paid.
        """
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            return {"status": "error", "message": "Invoice not found"}

        if invoice.payment_status == "paid":
            return {"status": "error", "message": "Invoice already paid"}

        # Mark as paid
        invoice.payment_status = "paid"
        invoice.paid_at = datetime.now(timezone.utc)
        invoice.notes = admin_notes or invoice.notes

        # Update tenant subscription
        tenant = db.query(Tenant).filter(Tenant.id == invoice.tenant_id).first()
        if tenant:
            tenant.subscription_plan = invoice.plan
            tenant.subscription_status = "active"
            tenant.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=30)

        db.commit()

        logger.info(f"[PayNow] Payment verified for invoice {invoice_id}")
        return {
            "status": "success",
            "message": "Payment verified and subscription activated",
            "invoice_id": invoice_id,
        }

    @classmethod
    def get_pending_payments(cls, db: Session) -> list[dict]:
        """Get all pending PayNow payments for admin review."""
        invoices = db.query(Invoice).filter(
            Invoice.payment_method == "paynow",
            Invoice.payment_status == "pending",
        ).order_by(Invoice.created_at).all()

        return [
            {
                "invoice_id": inv.id,
                "tenant_id": inv.tenant_id,
                "amount": inv.amount,
                "currency": inv.currency,
                "reference": inv.paynow_reference,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
                "due_date": inv.due_date.isoformat() if inv.due_date else None,
            }
            for inv in invoices
        ]

    @classmethod
    def get_invoice(cls, invoice_id: str, db: Session) -> Optional[dict]:
        """Get invoice details."""
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            return None

        return {
            "invoice_id": invoice.id,
            "tenant_id": invoice.tenant_id,
            "amount": invoice.amount,
            "currency": invoice.currency,
            "description": invoice.description,
            "plan": invoice.plan,
            "payment_method": invoice.payment_method,
            "payment_status": invoice.payment_status,
            "reference": invoice.paynow_reference,
            "qr_data": invoice.paynow_qr_data,
            "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
            "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        }
