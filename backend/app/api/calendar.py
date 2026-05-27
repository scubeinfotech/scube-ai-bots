"""
Calendar API endpoints — Google Calendar integration and availability management.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant
from app.services.calendar_service import CalendarService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calendar", tags=["Calendar"])


# --------------------------------------------------------------------------- #
# Request / Response schemas
# --------------------------------------------------------------------------- #

class AvailabilitySlot(BaseModel):
    day_of_week: int
    start_time: str
    end_time: str
    timezone: Optional[str] = "Asia/Singapore"
    blocked_dates: Optional[list[str]] = None


class AvailabilityRequest(BaseModel):
    slots: list[AvailabilitySlot]


class BookingRequest(BaseModel):
    date: str
    start_time: str
    end_time: str
    attendee_name: str
    attendee_email: str


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@router.get("/status/{tenant_id}")
async def get_calendar_status(tenant_id: str, db: Session = Depends(get_db)):
    """Get calendar integration status for a tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    status = CalendarService.get_integration_status(tenant_id, db)
    return status


@router.get("/oauth/url/{tenant_id}")
async def get_oauth_url(
    tenant_id: str,
    redirect_uri: str = Query(..., description="OAuth callback URL"),
    db: Session = Depends(get_db),
):
    """Get Google OAuth authorization URL for calendar connection."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    url = CalendarService.get_oauth_url(tenant_id, redirect_uri)
    return {"oauth_url": url}


@router.post("/oauth/callback/{tenant_id}")
async def handle_oauth_callback(
    tenant_id: str,
    code: str,
    db: Session = Depends(get_db),
):
    """Handle Google OAuth callback and store tokens."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    result = CalendarService.handle_oauth_callback(tenant_id, code, db)
    return result


@router.post("/disconnect/{tenant_id}")
async def disconnect_calendar(tenant_id: str, db: Session = Depends(get_db)):
    """Disconnect calendar integration for a tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    success = CalendarService.disconnect(tenant_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="No calendar integration found")

    return {"status": "success", "message": "Calendar disconnected"}


@router.get("/availability/{tenant_id}")
async def get_availability(tenant_id: str, db: Session = Depends(get_db)):
    """Get weekly availability slots for a tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    slots = CalendarService.get_availability(tenant_id, db)
    return {"slots": slots}


@router.post("/availability/{tenant_id}")
async def set_availability(
    tenant_id: str,
    payload: AvailabilityRequest,
    db: Session = Depends(get_db),
):
    """Set weekly availability slots for a tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    slots_data = [s.model_dump() for s in payload.slots]
    created = CalendarService.set_availability(tenant_id, slots_data, db)
    return {"status": "success", "slots": created}


@router.get("/availability/{tenant_id}/check")
async def check_availability(
    tenant_id: str,
    date: str = Query(..., description="Date to check (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
):
    """Check available time slots for a specific date."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    slots = CalendarService.check_availability(tenant_id, date, db)
    return {"date": date, "available_slots": slots}


@router.post("/book/{tenant_id}")
async def book_appointment(
    tenant_id: str,
    payload: BookingRequest,
    db: Session = Depends(get_db),
):
    """Book an appointment slot."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    result = CalendarService.book_appointment(
        tenant_id=tenant_id,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        attendee_name=payload.attendee_name,
        attendee_email=payload.attendee_email,
        db=db,
    )

    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.post("/initialize-defaults/{tenant_id}")
async def initialize_default_availability(tenant_id: str, db: Session = Depends(get_db)):
    """Set default availability (Mon-Fri 9AM-5PM) for a tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    CalendarService.initialize_default_availability(tenant_id, db)
    return {"status": "success", "message": "Default availability set (Mon-Fri 9AM-5PM)"}
