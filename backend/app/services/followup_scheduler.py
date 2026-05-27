"""
CRM Follow-up Scheduler
Matches trigger events to templates, renders messages, and creates ScheduledMessage records.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session

from app.models.whatsapp import (
    FollowUpTemplate, ScheduledMessage, WhatsAppContact,
    WhatsAppTentativeBooking, ContactActivity
)
from app.models import Tenant

logger = logging.getLogger(__name__)

TEMPLATE_VARS = {"name", "service", "date", "time"}


def _render_template(text: str, contact: Optional[WhatsAppContact] = None, booking: Optional[WhatsAppTentativeBooking] = None) -> str:
    """Replace {{placeholders}} with contact/booking values."""
    replacements = {
        "name": contact.contact_name or contact.phone_number if contact else "Valued Customer",
        "service": (booking.requested_type or "service") if booking else "service",
        "date": (booking.requested_date or "soon") if booking else "soon",
        "time": (booking.requested_time or "") if booking else "",
    }
    result = text
    for key, value in replacements.items():
        result = result.replace("{{" + key + "}}", value)
    return result


def schedule_follow_up(
    db: Session,
    tenant_id: str,
    contact_id: str,
    trigger_event: str,
    booking: Optional[WhatsAppTentativeBooking] = None,
    delay_hours: Optional[int] = None,
) -> Optional[ScheduledMessage]:
    """
    Find the best matching template for trigger_event and create a ScheduledMessage.

    Template priority:
    1. Tenant-specific template matching the trigger_event
    2. Tenant's industry + global template matching trigger_event
    3. Global (NULL industry) template matching trigger_event
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return None

    contact = db.query(WhatsAppContact).filter(
        WhatsAppContact.id == contact_id,
        WhatsAppContact.tenant_id == tenant_id
    ).first()
    if not contact:
        return None

    # Check for opted-out contacts
    if contact.opted_out:
        return None

    # Find best template
    template = _find_template(db, tenant_id, tenant.industry, trigger_event)
    if not template:
        return None

    hours = delay_hours or template.delay_hours
    rendered = _render_template(template.template_text, contact, booking)
    conclusive = template.conclusive_line or ""
    if conclusive:
        rendered = f"{rendered}\n\n{conclusive}"

    scheduled_at = datetime.utcnow() + timedelta(hours=hours)

    msg = ScheduledMessage(
        tenant_id=tenant_id,
        contact_id=contact_id,
        template_id=template.id,
        trigger_event=trigger_event,
        scheduled_at=scheduled_at,
        status="pending",
        message_text=rendered,
    )
    db.add(msg)
    db.add(ContactActivity(
        tenant_id=tenant_id,
        contact_id=contact_id,
        activity_type="followup_scheduled",
        description=f"Follow-up scheduled: {trigger_event} at {scheduled_at.strftime('%Y-%m-%d %H:%M UTC')}",
        ref_type="scheduled_message",
        ref_id=msg.id,
    ))
    db.commit()
    logger.info(f"[CRM] Scheduled {trigger_event} for contact {contact_id} at {scheduled_at}")
    return msg


def _find_template(
    db: Session,
    tenant_id: str,
    industry: Optional[str],
    trigger_event: str,
) -> Optional[FollowUpTemplate]:
    """Find best matching template: tenant-specific → industry+global → global."""
    # 1. Tenant-specific
    tpl = db.query(FollowUpTemplate).filter(
        FollowUpTemplate.tenant_id == tenant_id,
        FollowUpTemplate.trigger_event == trigger_event,
        FollowUpTemplate.is_active == True,
    ).first()
    if tpl:
        return tpl

    # 2. Industry + global
    if industry:
        tpl = db.query(FollowUpTemplate).filter(
            FollowUpTemplate.tenant_id.is_(None),
            FollowUpTemplate.industry == industry,
            FollowUpTemplate.trigger_event == trigger_event,
            FollowUpTemplate.is_active == True,
        ).first()
        if tpl:
            return tpl

    # 3. Generic global
    tpl = db.query(FollowUpTemplate).filter(
        FollowUpTemplate.tenant_id.is_(None),
        FollowUpTemplate.industry.is_(None),
        FollowUpTemplate.trigger_event == trigger_event,
        FollowUpTemplate.is_active == True,
    ).first()
    return tpl


def dispatch_pending_messages(db: Session, batch_size: int = 50) -> int:
    """
    Dispatch all pending scheduled messages that are due.
    Returns the number of messages sent.
    Called by APScheduler job.
    """
    now = datetime.utcnow()
    messages = db.query(ScheduledMessage).filter(
        ScheduledMessage.status == "pending",
        ScheduledMessage.scheduled_at <= now,
    ).limit(batch_size).all()

    if not messages:
        return 0

    from app.adapters.whatsapp import get_whatsapp_provider
    from app.models.whatsapp import WhatsAppConfiguration

    sent_count = 0
    for msg in messages:
        try:
            config = db.query(WhatsAppConfiguration).filter(
                WhatsAppConfiguration.tenant_id == msg.tenant_id,
                WhatsAppConfiguration.is_active == True,
            ).first()
            if not config:
                msg.status = "cancelled"
                continue

            contact = db.query(WhatsAppContact).filter(
                WhatsAppContact.id == msg.contact_id
            ).first()
            if not contact or contact.opted_out:
                msg.status = "cancelled"
                continue

            provider_type = "meta"
            if config.config_metadata and config.config_metadata.get("msg91_auth_key"):
                provider_type = "msg91"

            provider = get_whatsapp_provider(
                provider_type,
                phone_number_id=config.phone_number_id,
                access_token=config.access_token,
                api_version=config.api_version,
                **(config.config_metadata or {}),
            )

            result = asyncio.run(provider.send_message(recipient_phone=contact.phone_number, message_text=msg.message_text))
            if result.get("success"):
                msg.status = "sent"
                msg.sent_at = datetime.utcnow()
                sent_count += 1

                db.add(ContactActivity(
                    tenant_id=msg.tenant_id,
                    contact_id=msg.contact_id,
                    activity_type="followup_sent",
                    description=f"Follow-up sent: {msg.trigger_event}",
                    ref_type="scheduled_message",
                    ref_id=msg.id,
                ))
            else:
                logger.warning(f"[CRM] Failed to send scheduled msg {msg.id}")
        except Exception as e:
            logger.error(f"[CRM] Error dispatching msg {msg.id}: {e}")

    db.commit()
    return sent_count
