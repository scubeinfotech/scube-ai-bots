"""
analytics_logger.py – Step 6
Thin helper that inserts a WhatsAppAnalyticsEvent row.
Callers must commit the session themselves; this only flushes.
Failures are swallowed so that a logging hiccup never breaks the
main request flow.
"""
import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.whatsapp import WhatsAppAnalyticsEvent

logger = logging.getLogger(__name__)

# ── Public event-type constants ───────────────────────────────────────────────
INTENT_DETECTED      = "intent_detected"
BOOKING_CREATED      = "booking_created"
BOOKING_CONFIRMED    = "booking_confirmed"
BOOKING_CANCELLED    = "booking_cancelled"
HUMAN_INTERVENTION   = "human_intervention"
CALENDAR_SYNCED      = "calendar_synced"
CRM_SYNCED           = "crm_synced"


def log_analytics_event(
    db: Session,
    tenant_id: str,
    event_type: str,
    *,
    intent: Optional[str] = None,
    confidence_score: Optional[float] = None,
    session_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    booking_id: Optional[str] = None,
    sub_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Append one analytics event to the DB session (no commit)."""
    try:
        event = WhatsAppAnalyticsEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            event_type=event_type,
            intent=intent,
            confidence_score=confidence_score,
            session_id=session_id,
            contact_id=contact_id,
            booking_id=booking_id,
            sub_type=sub_type,
            event_metadata=metadata,
        )
        db.add(event)
        db.flush()
    except Exception as exc:  # pragma: no cover
        logger.warning("[AnalyticsLogger] Failed to log %s: %s", event_type, exc)
