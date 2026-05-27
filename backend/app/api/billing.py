"""
Billing API endpoints — Stripe + PayNow payment processing.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant
from app.services.stripe_service import StripeService
from app.services.paynow_service import PayNowService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["Billing"])


# --------------------------------------------------------------------------- #
# Request / Response schemas
# --------------------------------------------------------------------------- #

class CreatePaymentRequest(BaseModel):
    plan_name: str
    payment_method: str  # "stripe" or "paynow"


class VerifyPayNowRequest(BaseModel):
    invoice_id: str
    admin_notes: Optional[str] = ""


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@router.post("/checkout/{tenant_id}")
async def create_checkout(
    tenant_id: str,
    payload: CreatePaymentRequest,
    db: Session = Depends(get_db),
):
    """
    Create a payment checkout session.
    Supports Stripe and PayNow.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if payload.payment_method == "stripe":
        result = StripeService.create_checkout_session(tenant_id, payload.plan_name, db)
    elif payload.payment_method == "paynow":
        result = PayNowService.create_paynow_invoice(tenant_id, payload.plan_name, db)
    else:
        raise HTTPException(status_code=400, detail="Unsupported payment method")

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))

    return result


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    result = StripeService.handle_webhook(payload, sig_header, db)

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))

    return {"received": True}


@router.get("/invoice/{invoice_id}")
async def get_invoice(invoice_id: str, db: Session = Depends(get_db)):
    """Get invoice details."""
    invoice = PayNowService.get_invoice(invoice_id, db)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.post("/paynow/verify")
async def verify_paynow_payment(
    payload: VerifyPayNowRequest,
    db: Session = Depends(get_db),
):
    """
    Verify a PayNow payment (admin action).
    Admin checks bank statement and marks payment as confirmed.
    """
    result = PayNowService.verify_payment(payload.invoice_id, db, payload.admin_notes)

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))

    return result


@router.get("/paynow/pending")
async def get_pending_paynow_payments(db: Session = Depends(get_db)):
    """Get all pending PayNow payments for admin review."""
    payments = PayNowService.get_pending_payments(db)
    return {"payments": payments}


@router.post("/stripe/cancel/{tenant_id}")
async def cancel_stripe_subscription(tenant_id: str, db: Session = Depends(get_db)):
    """Cancel a tenant's Stripe subscription."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    result = StripeService.cancel_subscription(tenant_id, db)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))

    return result


@router.get("/stripe/portal/{tenant_id}")
async def get_customer_portal(tenant_id: str, db: Session = Depends(get_db)):
    """Get Stripe Customer Portal URL for tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    url = StripeService.get_customer_portal_url(tenant_id, db)
    if not url:
        raise HTTPException(status_code=404, detail="No Stripe customer found for tenant")

    return {"portal_url": url}
