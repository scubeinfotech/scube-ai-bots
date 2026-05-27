"""
Serve .ics calendar files for booking confirmations.
GET /api/ics/{booking_id}.ics  →  generates and returns an .ics file on the fly.
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.tenants import _require_tenant_token
from app.models.whatsapp import WhatsAppTentativeBooking, WhatsAppContact
from app.models import Tenant
from app.services.ics import generate_booking_ics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ics", tags=["ICS"])


@router.get("/{booking_id}.ics")
def download_ics(
    booking_id: str,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Generate and return an .ics calendar file for a booking."""
    token = _require_tenant_token(authorization)
    tenant_id = token["tenant_id"]

    booking = db.query(WhatsAppTentativeBooking).filter(
        WhatsAppTentativeBooking.id == booking_id,
        WhatsAppTentativeBooking.tenant_id == tenant_id,
    ).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    contact = db.query(WhatsAppContact).filter(
        WhatsAppContact.id == booking.contact_id
    ).first()
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()

    contact_name = contact.contact_name if contact else ""
    contact_phone = contact.phone_number if contact else ""
    tenant_name = tenant.name if tenant else ""
    tenant_address = tenant.domain if tenant else ""

    ef = booking.extracted_fields or {}
    date = (booking.requested_date if booking.requested_date else None) or ef.get("date") or ""
    time = (booking.requested_time if booking.requested_time else None) or ef.get("time") or ""
    service_type = (booking.requested_type if booking.requested_type else None) or ef.get("type") or "booking"
    persons = (booking.requested_persons if booking.requested_persons else None) or ef.get("persons") or 1

    ics_content = generate_booking_ics(
        booking_id=booking.id,
        date=date,
        time=time,
        service_type=service_type,
        contact_name=contact_name,
        contact_phone=contact_phone,
        persons=int(persons) if persons else 1,
        tenant_name=tenant_name,
        tenant_address=tenant_address,
    )

    if not ics_content:
        raise HTTPException(status_code=400, detail="Could not generate calendar file — missing date or time")

    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={
            "Content-Disposition": f'attachment; filename="booking-{booking_id[:8]}.ics"',
            "Cache-Control": "no-cache",
        },
    )
