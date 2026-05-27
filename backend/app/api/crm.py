"""
CRM API endpoints — Customer 360 profiles, timeline, and stats for tenant dashboard
"""
import logging
import re
from typing import List, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_
from pydantic import BaseModel

from app.database import get_db
from app.models import Tenant, ChatSession
from app.models.whatsapp import (
    WhatsAppContact, WhatsAppMessage, ContactActivity, WhatsAppTentativeBooking,
    FollowUpTemplate, ScheduledMessage,
)
from app.api.tenants import _require_tenant_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenant/crm", tags=["CRM"])


# --- FastAPI dependency: extract tenant_id from JWT ---

async def _get_tenant_id(authorization: Optional[str] = Header(None)) -> str:
    token = _require_tenant_token(authorization)
    return token["tenant_id"]


# --- Normalization helpers for backward-compatible date/time display ---

_RELATIVE_DAYS = {"today": 0, "tomorrow": 1, "asap": 0}


def _normalize_date(date_str: Optional[str]) -> Optional[str]:
    """Convert relative date strings to YYYY-MM-DD. Pass through valid dates."""
    if not date_str:
        return None
    raw = date_str.strip().lower()
    offset = _RELATIVE_DAYS.get(raw)
    if offset is not None:
        return (datetime.utcnow() + timedelta(days=offset)).strftime("%Y-%m-%d")
    if re.match(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    return date_str


def _normalize_time(time_str: Optional[str]) -> Optional[str]:
    """Convert time strings like '3pm', '2:30pm' to HH:MM. Rejects invalid values."""
    if not time_str:
        return None
    raw = time_str.strip().lower()
    m = re.match(r"(\d{1,2}):?(\d{2})?\s*(am|pm)", raw)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        if hour > 12 or minute >= 60:
            return time_str
        if m.group(3) == "pm" and hour != 12:
            hour += 12
        elif m.group(3) == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    m = re.match(r"(\d{1,2}):(\d{2})", raw)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        if hour >= 24 or minute >= 60:
            return time_str
        return f"{hour:02d}:{minute:02d}"
    if raw in ("noon", "midday"):
        return "12:00"
    if raw == "midnight":
        return "00:00"
    return time_str


# --- Pydantic schemas ---

class ContactUpdate(BaseModel):
    contact_name: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    job_title: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    last_lead_status: Optional[str] = None


class _UtcIsoMixin:
    """Append +00:00 to naive datetime ISO strings for JS compatibility."""

    @classmethod
    def _utc_iso(cls, value):
        if value is None:
            return None
        iso = value.isoformat()
        if value.tzinfo is None and not iso.endswith('+00:00') and not iso.endswith('Z'):
            iso += '+00:00'
        return iso


class ContactResponse(BaseModel, _UtcIsoMixin):
    id: str
    tenant_id: str
    phone_number: str
    contact_name: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    job_title: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list] = None
    source_channel: str = "whatsapp"
    last_lead_status: Optional[str] = None
    total_messages: int = 0
    last_message_at: Optional[datetime] = None
    first_message_at: Optional[datetime] = None
    is_active: bool = True
    opted_out: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {datetime: _UtcIsoMixin._utc_iso}


class ActivityResponse(BaseModel, _UtcIsoMixin):
    id: str
    contact_id: str
    activity_type: str
    description: Optional[str] = None
    ref_type: Optional[str] = None
    ref_id: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {datetime: _UtcIsoMixin._utc_iso}


class ContactActivityRow(BaseModel):
    activity: ActivityResponse
    booking: Optional["LeadBookingResponse"] = None


@router.get("/contacts")
def list_contacts(
    tenant_id: str = Depends(_get_tenant_id),
    search: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(WhatsAppContact).filter(WhatsAppContact.tenant_id == tenant_id)
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                WhatsAppContact.contact_name.ilike(like),
                WhatsAppContact.phone_number.ilike(like),
                WhatsAppContact.company.ilike(like),
            )
        )
    if tag:
        q = q.filter(WhatsAppContact.tags.any(tag))

    total = q.count()

    # Add message counts via subquery
    from sqlalchemy import func as sa_func
    msg_count = (
        db.query(
            WhatsAppMessage.contact_id,
            sa_func.count(WhatsAppMessage.id).label("cnt"),
            sa_func.max(WhatsAppMessage.created_at).label("last_msg"),
        )
        .filter(WhatsAppMessage.tenant_id == tenant_id)
        .group_by(WhatsAppMessage.contact_id)
        .subquery()
    )

    q = q.outerjoin(
        msg_count,
        WhatsAppContact.id == msg_count.c.contact_id,
    ).add_columns(
        sa_func.coalesce(msg_count.c.cnt, 0).label("total_msgs"),
        msg_count.c.last_msg,
    ).order_by(desc(msg_count.c.last_msg))

    rows = q.offset(offset).limit(limit).all()
    results = []
    for c, total_msgs, last_msg in rows:
        results.append(ContactResponse(
            id=c.id,
            tenant_id=c.tenant_id,
            phone_number=c.phone_number,
            contact_name=c.contact_name,
            company=c.company,
            email=c.email,
            job_title=c.job_title,
            notes=c.notes,
            tags=c.tags,
            source_channel=c.source_channel,
            last_lead_status=c.last_lead_status,
            total_messages=total_msgs or 0,
            last_message_at=last_msg or c.last_message_at,
            first_message_at=c.first_message_at,
            is_active=c.is_active,
            opted_out=c.opted_out,
            created_at=c.created_at,
            updated_at=c.updated_at,
        ))
    return {"total": total, "contacts": results}


@router.get("/contacts/{contact_id}")
def get_contact(
    contact_id: str,
    tenant_id: str = Depends(_get_tenant_id),
    db: Session = Depends(get_db),
):
    c = db.query(WhatsAppContact).filter(
        WhatsAppContact.id == contact_id,
        WhatsAppContact.tenant_id == tenant_id,
    ).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    msg_count = db.query(func.count(WhatsAppMessage.id)).filter(
        WhatsAppMessage.contact_id == contact_id,
        WhatsAppMessage.tenant_id == tenant_id,
    ).scalar() or 0
    return ContactResponse(
        id=c.id,
        tenant_id=c.tenant_id,
        phone_number=c.phone_number,
        contact_name=c.contact_name,
        company=c.company,
        email=c.email,
        job_title=c.job_title,
        notes=c.notes,
        tags=c.tags,
        source_channel=c.source_channel,
        last_lead_status=c.last_lead_status,
        total_messages=msg_count,
        last_message_at=c.last_message_at,
        first_message_at=c.first_message_at,
        is_active=c.is_active,
        opted_out=c.opted_out,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.patch("/contacts/{contact_id}")
def update_contact(
    contact_id: str,
    payload: ContactUpdate,
    tenant_id: str = Depends(_get_tenant_id),
    db: Session = Depends(get_db),
):
    c = db.query(WhatsAppContact).filter(
        WhatsAppContact.id == contact_id,
        WhatsAppContact.tenant_id == tenant_id,
    ).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    db.commit()
    db.refresh(c)
    return {"status": "updated"}


@router.get("/contacts/{contact_id}/activity")
@router.get("/contacts/{contact_id}/timeline")
def get_contact_activity(
    contact_id: str,
    tenant_id: str = Depends(_get_tenant_id),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
):
    activities = db.query(ContactActivity).filter(
        ContactActivity.contact_id == contact_id,
        ContactActivity.tenant_id == tenant_id,
    ).order_by(desc(ContactActivity.created_at)).limit(limit).all()

    return [ActivityResponse.model_validate(a) for a in activities]


# ── Stats endpoint ──────────────────────────────────────────────────────

@router.get("/stats")
def crm_stats(
    tenant_id: str = Depends(_get_tenant_id),
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    total_contacts = db.query(WhatsAppContact).filter(WhatsAppContact.tenant_id == tenant_id).count()
    active_contacts = db.query(WhatsAppContact).filter(
        WhatsAppContact.tenant_id == tenant_id, WhatsAppContact.is_active == True,
    ).count()

    total_leads = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.tenant_id == tenant_id).count()
    tentative = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.tenant_id == tenant_id, WhatsAppTentativeBooking.status == "tentative").count()
    confirmed = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.tenant_id == tenant_id, WhatsAppTentativeBooking.status == "confirmed").count()
    cancelled = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.tenant_id == tenant_id, WhatsAppTentativeBooking.status == "cancelled").count()

    leads_today = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.tenant_id == tenant_id, WhatsAppTentativeBooking.created_at >= today_start).count()
    leads_this_week = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.tenant_id == tenant_id, WhatsAppTentativeBooking.created_at >= week_start).count()
    leads_this_month = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.tenant_id == tenant_id, WhatsAppTentativeBooking.created_at >= month_start).count()

    conversion_rate = round((confirmed / total_leads * 100), 1) if total_leads > 0 else 0
    estimated_revenue = confirmed * 200

    return {
        "total_contacts": total_contacts,
        "active_contacts": active_contacts,
        "total_leads": total_leads,
        "tentative_leads": tentative,
        "confirmed_leads": confirmed,
        "cancelled_leads": cancelled,
        "leads_today": leads_today,
        "leads_this_week": leads_this_week,
        "leads_this_month": leads_this_month,
        "conversion_rate": conversion_rate,
        "estimated_revenue": estimated_revenue,
    }


# ── Follow-up Template endpoints ────────────────────────────────────────

class FollowUpTemplateResponse(BaseModel, _UtcIsoMixin):
    id: str
    trigger_event: str
    industry: Optional[str] = None
    delay_hours: int
    template_text: str
    conclusive_line: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {datetime: _UtcIsoMixin._utc_iso}


class FollowUpTemplateCreate(BaseModel):
    trigger_event: str
    industry: Optional[str] = None
    delay_hours: int = 24
    template_text: str
    conclusive_line: Optional[str] = None
    is_active: bool = True


class FollowUpTemplateUpdate(BaseModel):
    is_active: Optional[bool] = None
    template_text: Optional[str] = None
    delay_hours: Optional[int] = None
    conclusive_line: Optional[str] = None


@router.post("/templates")
def create_template(
    payload: FollowUpTemplateCreate,
    tenant_id: str = Depends(_get_tenant_id),
    db: Session = Depends(get_db),
):
    import uuid
    tpl = FollowUpTemplate(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        trigger_event=payload.trigger_event,
        industry=payload.industry,
        delay_hours=payload.delay_hours,
        template_text=payload.template_text,
        conclusive_line=payload.conclusive_line,
        is_active=payload.is_active,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return FollowUpTemplateResponse.model_validate(tpl)


@router.get("/templates")
def list_templates(
    tenant_id: str = Depends(_get_tenant_id),
    db: Session = Depends(get_db),
):
    templates = db.query(FollowUpTemplate).filter(
        or_(FollowUpTemplate.tenant_id == tenant_id, FollowUpTemplate.tenant_id.is_(None)),
    ).order_by(FollowUpTemplate.trigger_event).all()
    return [FollowUpTemplateResponse.model_validate(t) for t in templates]


@router.patch("/templates/{template_id}")
def update_template(
    template_id: str,
    payload: FollowUpTemplateUpdate,
    tenant_id: str = Depends(_get_tenant_id),
    db: Session = Depends(get_db),
):
    tpl = db.query(FollowUpTemplate).filter(
        FollowUpTemplate.id == template_id,
        or_(FollowUpTemplate.tenant_id == tenant_id, FollowUpTemplate.tenant_id.is_(None)),
    ).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tpl, field, value)
    db.commit()
    db.refresh(tpl)
    return FollowUpTemplateResponse.model_validate(tpl)


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: str,
    tenant_id: str = Depends(_get_tenant_id),
    db: Session = Depends(get_db),
):
    tpl = db.query(FollowUpTemplate).filter(
        FollowUpTemplate.id == template_id,
        or_(FollowUpTemplate.tenant_id == tenant_id, FollowUpTemplate.tenant_id.is_(None)),
    ).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(tpl)
    db.commit()
    return {"status": "deleted"}


# ── Lead / Booking endpoints ─────────────────────────────────────────────

class LeadBookingResponse(BaseModel, _UtcIsoMixin):
    id: str
    contact_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    intent_type: str
    status: str
    source: str = "whatsapp"
    requested_date: Optional[str] = None
    requested_time: Optional[str] = None
    requested_persons: Optional[int] = None
    requested_type: Optional[str] = None
    raw_text: Optional[str] = None
    assigned_to: Optional[str] = None
    priority: str = "normal"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {datetime: _UtcIsoMixin._utc_iso}


class LeadActionInput(BaseModel):
    action: str


@router.get("/leads")
def list_leads(
    tenant_id: str = Depends(_get_tenant_id),
    source: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    intent: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    # Query 1: WhatsApp tentative bookings
    wa_q = db.query(WhatsAppTentativeBooking).filter(
        WhatsAppTentativeBooking.tenant_id == tenant_id
    )
    if status:
        wa_q = wa_q.filter(WhatsAppTentativeBooking.status == status)
    if intent:
        wa_q = wa_q.filter(WhatsAppTentativeBooking.intent_type == intent)

    wa_rows = wa_q.order_by(desc(WhatsAppTentativeBooking.created_at)).all()

    # Query 2: Chatbot leads from website widget
    chat_q = db.query(ChatSession).filter(
        ChatSession.tenant_id == tenant_id,
        ChatSession.lead_name.isnot(None),
    )
    if status == "tentative":
        chat_q = chat_q.filter(ChatSession.lead_collected_at.isnot(None))
    chat_rows = chat_q.order_by(desc(ChatSession.lead_collected_at)).all()

    # Normalize into unified list
    leads = []
    for b in wa_rows:
        contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == b.contact_id).first()
        
        # Extract fields from extracted_fields JSON if not in direct columns
        extracted = b.extracted_fields or {}
        # Use direct column if it has value, otherwise fall back to extracted_fields
        req_date = (b.requested_date if b.requested_date else None) or extracted.get("date") or extracted.get("requested_date") or ""
        req_time = (b.requested_time if b.requested_time else None) or extracted.get("time") or extracted.get("requested_time") or ""
        # Normalize relative dates ("tomorrow"→YYYY-MM-DD) and invalid times ("30pm"→HH:MM) at display time
        req_date = _normalize_date(req_date) or ""
        req_time = _normalize_time(req_time) or ""
        # Handle requested_persons - convert to int or None
        persons_val = (b.requested_persons if b.requested_persons else None) or extracted.get("persons") or extracted.get("requested_persons")
        req_persons = None
        if persons_val and str(persons_val).strip():
            try:
                req_persons = int(persons_val)
            except (ValueError, TypeError):
                req_persons = None
        req_type = (b.requested_type if b.requested_type else None) or extracted.get("type") or extracted.get("requested_type") or ""
        
        leads.append(LeadBookingResponse(
            id=b.id,
            contact_id=b.contact_id,
            contact_name=contact.contact_name if contact else None,
            contact_phone=contact.phone_number if contact else None,
            intent_type=b.intent_type,
            status=b.status,
            source="whatsapp",
            requested_date=req_date,
            requested_time=req_time,
            requested_persons=req_persons,
            requested_type=req_type,
            raw_text=b.raw_text,
            assigned_to=b.assigned_to,
            priority=b.priority,
            created_at=b.created_at,
            updated_at=b.updated_at,
            confirmed_at=b.confirmed_at,
            cancelled_at=b.cancelled_at,
        ))

    for s in chat_rows:
        msg = s.session_data.get("lead_message", "") if s.session_data else ""
        leads.append(LeadBookingResponse(
            id=s.id,
            contact_name=s.lead_name,
            contact_phone=s.lead_phone,
            intent_type="lead_form",
            status="collected",
            source="chatbot",
            raw_text=msg,
            created_at=s.lead_collected_at,
        ))

    # Apply source filter
    if source:
        leads = [l for l in leads if l.source == source]

    # Sort by created_at desc (all items have created_at)
    leads.sort(key=lambda l: l.created_at or datetime.min, reverse=True)

    total = len(leads)
    paged = leads[offset:offset + limit]

    return {"total": total, "limit": limit, "offset": offset, "leads": paged}


@router.patch("/leads/{lead_id}")
def update_lead_status(
    lead_id: str,
    action: LeadActionInput,
    tenant_id: str = Depends(_get_tenant_id),
    db: Session = Depends(get_db),
):
    booking = db.query(WhatsAppTentativeBooking).filter(
        WhatsAppTentativeBooking.id == lead_id,
        WhatsAppTentativeBooking.tenant_id == tenant_id,
    ).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Lead not found")

    now = datetime.utcnow()
    if action.action == "confirm":
        if booking.status == "confirmed":
            raise HTTPException(status_code=400, detail="Lead already confirmed")
        booking.status = "confirmed"
        booking.confirmed_at = now
    elif action.action == "cancel":
        if booking.status == "cancelled":
            raise HTTPException(status_code=400, detail="Lead already cancelled")
        booking.status = "cancelled"
        booking.cancelled_at = now
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'confirm' or 'cancel'")

    # Update contact's last_lead_status
    db.query(WhatsAppContact).filter(WhatsAppContact.id == booking.contact_id).update(
        {"last_lead_status": booking.status}
    )

    # Log activity
    db.add(ContactActivity(
        tenant_id=tenant_id,
        contact_id=booking.contact_id,
        activity_type=f"lead_{action.action}ed",
        description=f"Lead ({booking.intent_type}) {action.action}ed via dashboard",
        ref_type="whatsapp_tentative_booking",
        ref_id=booking.id,
    ))
    db.commit()
    db.refresh(booking)

    contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == booking.contact_id).first()
    return LeadBookingResponse(
        id=booking.id,
        contact_id=booking.contact_id,
        contact_name=contact.contact_name if contact else None,
        contact_phone=contact.phone_number if contact else None,
        intent_type=booking.intent_type,
        status=booking.status,
        requested_date=booking.requested_date,
        requested_time=booking.requested_time,
        requested_persons=booking.requested_persons,
        requested_type=booking.requested_type,
        raw_text=booking.raw_text,
        assigned_to=booking.assigned_to,
        priority=booking.priority,
        created_at=booking.created_at,
        updated_at=booking.updated_at,
        confirmed_at=booking.confirmed_at,
        cancelled_at=booking.cancelled_at,
    )


class AppointmentResponse(BaseModel, _UtcIsoMixin):
    id: str
    person_name: Optional[str] = None
    person_phone: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    status: str
    location_type: Optional[str] = None
    intent_type: str
    source: str = "whatsapp"
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {datetime: _UtcIsoMixin._utc_iso}


@router.get("/appointments")
def list_appointments(
    tenant_id: str = Depends(_get_tenant_id),
    limit: int = Query(20, le=50),
    db: Session = Depends(get_db),
):
    today = datetime.utcnow().strftime("%Y-%m-%d")

    bookings = db.query(WhatsAppTentativeBooking).filter(
        WhatsAppTentativeBooking.tenant_id == tenant_id,
        WhatsAppTentativeBooking.status.in_(["confirmed", "tentative"]),
        WhatsAppTentativeBooking.requested_date >= today,
        WhatsAppTentativeBooking.requested_date.isnot(None),
    ).order_by(
        WhatsAppTentativeBooking.requested_date,
        WhatsAppTentativeBooking.requested_time,
    ).limit(limit).all()

    results = []
    for b in bookings:
        contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == b.contact_id).first()
        extracted = b.extracted_fields or {}
        date = b.requested_date or extracted.get("date") or extracted.get("requested_date") or None
        time = b.requested_time or extracted.get("time") or extracted.get("requested_time") or None
        date = _normalize_date(date)
        time = _normalize_time(time)
        loc_type = b.requested_type or extracted.get("type") or extracted.get("requested_type") or None
        results.append(AppointmentResponse(
            id=b.id,
            person_name=contact.contact_name if contact else None,
            person_phone=contact.phone_number if contact else None,
            date=date,
            time=time,
            status=b.status,
            location_type=loc_type,
            intent_type=b.intent_type,
            source="whatsapp",
            created_at=b.created_at,
        ))

    return results


# ── Scheduled Message endpoints ───────────────────────────────────────────

class ScheduledMessageResponse(BaseModel, _UtcIsoMixin):
    id: str
    contact_id: str
    trigger_event: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    status: str = "pending"
    message_text: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {datetime: _UtcIsoMixin._utc_iso}


@router.get("/scheduled")
def list_scheduled(
    tenant_id: str = Depends(_get_tenant_id),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(ScheduledMessage).filter(ScheduledMessage.tenant_id == tenant_id)
    if status:
        q = q.filter(ScheduledMessage.status == status)
    msgs = q.order_by(desc(ScheduledMessage.scheduled_at)).limit(limit).all()
    return [ScheduledMessageResponse.model_validate(m) for m in msgs]


@router.post("/scheduled/{msg_id}/cancel")
def cancel_scheduled(
    msg_id: str,
    tenant_id: str = Depends(_get_tenant_id),
    db: Session = Depends(get_db),
):
    msg = db.query(ScheduledMessage).filter(
        ScheduledMessage.id == msg_id,
        ScheduledMessage.tenant_id == tenant_id,
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Scheduled message not found")
    if msg.status != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot cancel message with status '{msg.status}'")
    msg.status = "cancelled"
    db.commit()
    return {"status": "cancelled"}
