


"""
Admin API endpoints
"""
from datetime import date, datetime, timedelta, timezone
import shutil
import os
import asyncio
import logging
from typing import Optional, Any, Dict, List
from collections import Counter
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Request, Header, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
import jwt

logger = logging.getLogger(__name__)

from app.database import get_db
from app.config import settings
from app.api.health import get_provider_health_tracker
from app.adapters.llm import get_llm_stats
from app.models import (
    AdminUser,
    Agreement,
    Tenant,
    TenantUser,
    APIKey,
    ChatMessage,
    ChatSession,
    Document,
    DocumentChunk,
    UnansweredQuery,
    WhatsAppTentativeBooking,
    WhatsAppContact,
    WhatsAppMessage,
    WhatsAppSession,
    WhatsAppConfiguration,
    OnboardingRequest,
    SubscriptionPlan,
)
from app.services.auth_service import (
    hash_password, verify_password, create_access_token, decode_token
)
from app.services.document import DocumentService
from app.services.document_parser import parse_document
from app.services.website_crawler import WebsiteCrawlerService
from app.services.canary_monitor import get_canary_state, set_canary_enabled, run_canary_check
from app.services.google_calendar import get_calendar_service
from app.services.crm_sync import get_crm_sync_service
from app.adapters.whatsapp import get_whatsapp_provider
from app.middleware import invalidate_cors_cache
from app.services.analytics_logger import (
    log_analytics_event,
    BOOKING_CONFIRMED,
    BOOKING_CANCELLED,
    HUMAN_INTERVENTION,
    CALENDAR_SYNCED,
    CRM_SYNCED,
)
from app.models.quality import QualityScore, FailurePattern, ImprovementCandidate, QualityMetric

router = APIRouter(prefix="/api/admin", tags=["Admin"])


@router.post("/cleanup-tenant/{tenant_id}")
async def cleanup_tenant_data(
    tenant_id: str,
    db: Session = Depends(get_db),
):
    """Fully cleanup all documents, vector data, and knowledge context for a tenant."""
    from app.models import Document, DocumentChunk, Tenant
    from app.services.vector_knowledge import VectorKnowledgeService

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Deactivate all documents
    docs = db.query(Document).filter(Document.tenant_id == tenant_id).all()
    doc_ids = [doc.id for doc in docs]
    for doc in docs:
        doc.is_active = False
    db.flush()

    # Delete all document chunks (vector data)
    db.query(DocumentChunk).filter(DocumentChunk.tenant_id == tenant_id).delete(synchronize_session=False)
    db.flush()

    # Clear knowledge context, crawl status, and prompt template
    tenant.knowledge_context = {}
    tenant.onboarding_stage = None
    tenant.onboarding_notes = None
    tenant.prompt_template = None  # Reset prompt template to prevent stale content
    tenant.guardrails = {}
    db.commit()

    # Optionally, remove from vector DB if using external vector store
    try:
        VectorKnowledgeService.delete_all_vectors_for_tenant(db, tenant_id)
    except Exception:
        pass

    return {
        "status": "tenant_data_cleaned",
        "tenant_id": tenant_id,
        "documents_deactivated": len(doc_ids),
        "vector_chunks_deleted": True,
        "knowledge_context_cleared": True,
    }


TENANT_TOKEN_SECRET = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
TENANT_TOKEN_ALGO = "HS256"


def recommended_models(industry: Optional[str], subscription_tier: Optional[str]) -> list:
    """Industry-aware model policy by subscription tier."""
    tier = (subscription_tier or "starter").lower()
    ind = (industry or "other").lower()

    default_model = "llama-3.3-70b-versatile"
    balanced = "llama-3.3-70b-versatile"
    broad_context = "mixtral-8x7b-32768"
    cautious = "gemma2-9b-it"

    if ind in {"accounting", "insurance"}:
        base = [balanced, cautious]
    elif ind in {"food", "services", "retail"}:
        base = [balanced, broad_context]
    else:
        base = [balanced, broad_context]

    if tier == "starter":
        return [default_model, balanced]
    elif tier == "growth":
        return [balanced, default_model, broad_context]
    elif tier == "enterprise":
        return [balanced, broad_context, cautious]
    return [default_model, balanced, broad_context, cautious]


def subscription_features(subscription_tier: Optional[str]) -> dict:
    tier = (subscription_tier or "starter").lower()
    if tier == "enterprise":
        return {
            "monthly_messages_limit": 200000,
            "max_documents": 5000,
            "max_vector_chunks": 500000,
            "tenant_user_seats": 20,
            "sla": "99.9%",
        }
    if tier == "growth":
        return {
            "monthly_messages_limit": 50000,
            "max_documents": 1200,
            "max_vector_chunks": 100000,
            "tenant_user_seats": 8,
            "sla": "99.5%",
        }
    return {
        "monthly_messages_limit": 10000,
        "max_documents": 250,
        "max_vector_chunks": 20000,
        "tenant_user_seats": 3,
        "sla": "best-effort",
    }


def create_tenant_user_token(user: TenantUser, tenant: Tenant) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=24)
    payload = {
        "tenant_user_id": user.id,
        "tenant_id": tenant.id,
        "tenant_slug": tenant.slug,
        "username": user.username,
        "exp": exp,
    }
    return jwt.encode(payload, TENANT_TOKEN_SECRET, algorithm=TENANT_TOKEN_ALGO)


def decode_tenant_user_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, TENANT_TOKEN_SECRET, algorithms=[TENANT_TOKEN_ALGO])
    except Exception:
        return None


def _format_bytes(size_bytes: int) -> str:
    """Human-readable byte formatter."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    units = ["KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    for unit in units:
        value /= 1024.0
        if value < 1024:
            return f"{value:.2f} {unit}"
    return f"{value:.2f} PB"


def _tenant_integration_settings(tenant: Optional[Tenant]) -> Dict[str, Any]:
    """Collect integration settings from current tenant JSON fields plus legacy settings."""
    merged: Dict[str, Any] = {}

    for container_name in ("guardrails", "knowledge_context", "settings"):
        container = getattr(tenant, container_name, None)
        if not isinstance(container, dict):
            continue

        integrations = container.get("integrations")
        if isinstance(integrations, dict):
            merged.update(integrations)

        # Support flat legacy calendar keys living directly in the JSON blob.
        if container.get("google_calendar_refresh_token"):
            merged.setdefault(
                "google_calendar",
                {
                    "google_calendar_refresh_token": container.get("google_calendar_refresh_token"),
                    "google_calendar_id": container.get("google_calendar_id", "primary"),
                },
            )

    return merged


def _calendar_settings(tenant: Optional[Tenant]) -> Dict[str, Any]:
    integrations = _tenant_integration_settings(tenant)
    calendar = integrations.get("google_calendar")
    if isinstance(calendar, dict):
        return calendar
    return {}


def _crm_settings(tenant: Optional[Tenant]) -> Dict[str, Any]:
    integrations = _tenant_integration_settings(tenant)
    crm = integrations.get("crm")
    if isinstance(crm, dict):
        return crm
    return {}


def _has_active_whatsapp_config(db: Session, tenant_id: Optional[str]) -> bool:
    if not tenant_id:
        return False
    return (
        db.query(WhatsAppConfiguration)
        .filter(
            WhatsAppConfiguration.tenant_id == tenant_id,
            WhatsAppConfiguration.is_active == True,
        )
        .first()
        is not None
    )


def _with_readiness(
    response: Dict[str, Any],
    tenant: Optional[Tenant],
    db: Session,
    booking_tenant_id: Optional[str],
) -> Dict[str, Any]:
    """Attach integration readiness flags to any lead action response."""
    response["calendar_integration_configured"] = bool(get_calendar_service(_calendar_settings(tenant)))
    response["crm_integration_configured"] = bool(get_crm_sync_service(_crm_settings(tenant)))
    response["whatsapp_delivery_configured"] = _has_active_whatsapp_config(db, booking_tenant_id)
    return response


def _serialize_whatsapp_booking(
    booking: WhatsAppTentativeBooking,
    contact: Optional[WhatsAppContact] = None,
    tenant: Optional[Tenant] = None,
) -> Dict[str, Any]:
    extracted_fields = booking.extracted_fields or {}
    crm_sync = extracted_fields.get("crm_sync") if isinstance(extracted_fields, dict) else None
    manual_override = extracted_fields.get("manual_override") if isinstance(extracted_fields, dict) else None

    return {
        "id": booking.id,
        "tenant_id": tenant.id if tenant else booking.tenant_id,
        "tenant_name": tenant.name if tenant else None,
        "contact_id": contact.id if contact else booking.contact_id,
        "phone_number": contact.phone_number if contact else None,
        "intent_type": booking.intent_type,
        "status": booking.status,
        "requested_date": booking.requested_date,
        "requested_time": booking.requested_time,
        "requested_persons": booking.requested_persons,
        "requested_type": booking.requested_type,
        "raw_text": booking.raw_text,
        "extracted_fields": extracted_fields,
        "google_calendar_event_id": booking.google_calendar_event_id,
        "calendar_synced": bool(booking.google_calendar_event_id),
        "crm_sync": crm_sync,
        "human_reviewed": bool(manual_override) or booking.status in {"confirmed", "cancelled"},
        "assigned_to": booking.assigned_to,
        "assigned_at": booking.assigned_at.isoformat() if booking.assigned_at else None,
        "priority": booking.priority or "normal",
        "due_by": booking.due_by.isoformat() if booking.due_by else None,
        "escalation_level": int(booking.escalation_level or 0),
        "handoff_notes": booking.handoff_notes,
        "resolved_at": booking.resolved_at.isoformat() if booking.resolved_at else None,
        "confirmed_at": booking.confirmed_at.isoformat() if booking.confirmed_at else None,
        "cancelled_at": booking.cancelled_at.isoformat() if booking.cancelled_at else None,
        "created_at": booking.created_at.isoformat() if booking.created_at else None,
        "updated_at": booking.updated_at.isoformat() if booking.updated_at else None,
    }


def _normalize_booking_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload or {})

    if "requested_persons" in normalized and normalized["requested_persons"] not in (None, ""):
        try:
            normalized["requested_persons"] = int(normalized["requested_persons"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="requested_persons must be an integer")

    if "status" in normalized and normalized["status"] is not None:
        normalized["status"] = str(normalized["status"]).strip().lower()
        if normalized["status"] not in {"tentative", "confirmed", "cancelled", "closed"}:
            raise HTTPException(status_code=400, detail="Status must be tentative, confirmed, cancelled, or closed")

    for key in ("requested_date", "requested_time", "requested_type"):
        if key in normalized and normalized[key] is not None:
            normalized[key] = str(normalized[key]).strip() or None

    if "priority" in normalized and normalized["priority"] is not None:
        normalized["priority"] = str(normalized["priority"]).strip().lower()
        if normalized["priority"] not in {"low", "normal", "high", "urgent"}:
            raise HTTPException(status_code=400, detail="Priority must be low, normal, high, or urgent")

    if "assigned_to" in normalized:
        assigned = normalized.get("assigned_to")
        normalized["assigned_to"] = str(assigned).strip() if assigned not in (None, "") else None

    if "handoff_note" in normalized and normalized["handoff_note"] is not None:
        normalized["handoff_note"] = str(normalized["handoff_note"]).strip()

    if "escalation_level" in normalized and normalized["escalation_level"] not in (None, ""):
        try:
            normalized["escalation_level"] = max(0, int(normalized["escalation_level"]))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="escalation_level must be an integer")

    if "due_by" in normalized and normalized["due_by"] not in (None, ""):
        try:
            due_raw = str(normalized["due_by"]).strip().replace("Z", "+00:00")
            normalized["due_by"] = datetime.fromisoformat(due_raw)
        except ValueError:
            raise HTTPException(status_code=400, detail="due_by must be ISO datetime")
    elif "due_by" in normalized:
        normalized["due_by"] = None

    return normalized


def _append_handoff_event(extracted_fields: Dict[str, Any], event_type: str, actor: str, details: Dict[str, Any]) -> None:
    history = extracted_fields.get("handoff_history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "event_type": event_type,
            "actor": actor,
            "at": datetime.utcnow().isoformat(),
            "details": details,
        }
    )
    extracted_fields["handoff_history"] = history[-100:]


def _to_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _priority_sla_minutes(priority: Optional[str]) -> int:
    value = (priority or "normal").strip().lower()
    if value == "urgent":
        return 30
    if value == "high":
        return 60
    if value == "low":
        return 360
    return 120


def _is_booking_overdue(booking: WhatsAppTentativeBooking, now: datetime) -> bool:
    if booking.status != "tentative":
        return False

    due_by = _to_naive_utc(booking.due_by)
    if due_by is not None:
        return now >= due_by

    created_at = _to_naive_utc(booking.created_at)
    if created_at is None:
        return False

    elapsed_minutes = max(0.0, (now - created_at).total_seconds() / 60.0)
    threshold = _priority_sla_minutes(booking.priority) * (int(booking.escalation_level or 0) + 1)
    return elapsed_minutes >= threshold


def _compute_handoff_counts(rows: List[WhatsAppTentativeBooking]) -> Dict[str, int]:
    now = datetime.utcnow()
    overdue = sum(1 for row in rows if _is_booking_overdue(row, now))
    escalated = sum(1 for row in rows if int(row.escalation_level or 0) > 0)
    return {
        "pending": len(rows),
        "overdue": overdue,
        "escalated": escalated,
    }


def _auto_escalate_tentative_handoffs(db: Session, tenant_id: Optional[str] = None) -> Dict[str, int]:
    now = datetime.utcnow()
    query = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.status == "tentative")
    if tenant_id:
        query = query.filter(WhatsAppTentativeBooking.tenant_id == tenant_id)

    rows = query.all()
    escalated_now = 0
    for booking in rows:
        if not _is_booking_overdue(booking, now):
            continue

        extracted_fields = dict(booking.extracted_fields or {})
        booking.escalation_level = int(booking.escalation_level or 0) + 1
        if booking.escalation_level >= 2 and (booking.priority or "normal") in {"low", "normal"}:
            booking.priority = "high"
        if booking.escalation_level >= 3:
            booking.priority = "urgent"

        _append_handoff_event(
            extracted_fields,
            "auto_escalate",
            "system:sla",
            {
                "escalation_level": booking.escalation_level,
                "priority": booking.priority,
            },
        )
        booking.extracted_fields = extracted_fields
        escalated_now += 1

    if escalated_now:
        db.commit()

    counts = _compute_handoff_counts(rows)
    counts["auto_escalated_now"] = escalated_now
    return counts


def _apply_booking_update(
    booking: WhatsAppTentativeBooking,
    payload: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    payload = _normalize_booking_payload(payload)
    extracted_fields = dict(booking.extracted_fields or {})
    now = datetime.utcnow()

    tracked_fields = ["requested_date", "requested_time", "requested_persons", "requested_type"]
    fields_changed = False
    for field_name in tracked_fields:
        if field_name not in payload:
            continue
        new_value = payload.get(field_name)
        if getattr(booking, field_name) != new_value:
            setattr(booking, field_name, new_value)
            extracted_key = field_name.removeprefix("requested_")
            extracted_fields[extracted_key] = new_value
            fields_changed = True

    for meta_field in ("priority", "due_by", "escalation_level"):
        if meta_field in payload and getattr(booking, meta_field) != payload.get(meta_field):
            setattr(booking, meta_field, payload.get(meta_field))
            fields_changed = True

    if "assigned_to" in payload:
        new_assignee = payload.get("assigned_to")
        if booking.assigned_to != new_assignee:
            booking.assigned_to = new_assignee
            booking.assigned_at = now if new_assignee else None
            fields_changed = True
            _append_handoff_event(
                extracted_fields,
                "assigned" if new_assignee else "unassigned",
                actor,
                {"assigned_to": new_assignee},
            )

    action = payload.get("action")
    if action:
        action = str(action).strip().lower()
        if action == "claim":
            assignee = payload.get("assigned_to") or actor
            booking.assigned_to = assignee
            booking.assigned_at = now
            fields_changed = True
            _append_handoff_event(extracted_fields, "claim", actor, {"assigned_to": assignee})
        elif action == "reassign":
            assignee = payload.get("assigned_to")
            if not assignee:
                raise HTTPException(status_code=400, detail="assigned_to is required for reassign")
            booking.assigned_to = assignee
            booking.assigned_at = now
            fields_changed = True
            _append_handoff_event(extracted_fields, "reassign", actor, {"assigned_to": assignee})
        elif action == "escalate":
            next_level = payload.get("escalation_level")
            booking.escalation_level = int(next_level) if next_level is not None else int(booking.escalation_level or 0) + 1
            fields_changed = True
            _append_handoff_event(extracted_fields, "escalate", actor, {"escalation_level": booking.escalation_level})
        elif action == "close":
            payload.setdefault("status", "closed")
        else:
            raise HTTPException(status_code=400, detail="Unsupported action")

    note = payload.get("handoff_note")
    if note:
        booking.handoff_notes = f"{booking.handoff_notes}\n[{now.isoformat()}] {actor}: {note}".strip() if booking.handoff_notes else f"[{now.isoformat()}] {actor}: {note}"
        fields_changed = True
        _append_handoff_event(extracted_fields, "note", actor, {"note": note})

    old_status = booking.status
    new_status = old_status
    if "status" in payload and payload.get("status"):
        new_status = payload["status"]
        booking.status = new_status

    status_changed = old_status != new_status
    if status_changed:
        if new_status == "confirmed":
            booking.confirmed_at = now
            booking.cancelled_at = None
        elif new_status == "cancelled":
            booking.cancelled_at = now
        elif new_status == "tentative":
            booking.confirmed_at = None
            booking.cancelled_at = None
            booking.resolved_at = None
        elif new_status == "closed":
            booking.resolved_at = now

        _append_handoff_event(
            extracted_fields,
            "status_changed",
            actor,
            {"from": old_status, "to": new_status},
        )

    if fields_changed or status_changed:
        extracted_fields["manual_override"] = {
            "updated_at": now.isoformat(),
            "updated_by": actor,
            "status_changed": status_changed,
            "fields_changed": fields_changed,
        }
        booking.extracted_fields = extracted_fields

    return {
        "old_status": old_status,
        "new_status": new_status,
        "status_changed": status_changed,
        "fields_changed": fields_changed,
    }


def _build_crm_payload(
    booking: WhatsAppTentativeBooking,
    tenant: Optional[Tenant],
    contact: Optional[WhatsAppContact],
) -> Dict[str, Any]:
    return {
        "event": "booking_confirmed",
        "tenant": {
            "id": tenant.id if tenant else booking.tenant_id,
            "name": tenant.name if tenant else None,
            "slug": tenant.slug if tenant else None,
            "industry": tenant.industry if tenant else None,
        },
        "customer": {
            "contact_id": contact.id if contact else booking.contact_id,
            "phone_number": contact.phone_number if contact else None,
            "name": contact.contact_name if contact else None,
        },
        "booking": {
            "id": booking.id,
            "intent_type": booking.intent_type,
            "status": booking.status,
            "requested_date": booking.requested_date,
            "requested_time": booking.requested_time,
            "requested_persons": booking.requested_persons,
            "requested_type": booking.requested_type,
            "google_calendar_event_id": booking.google_calendar_event_id,
            "raw_text": booking.raw_text,
            "extracted_fields": booking.extracted_fields or {},
            "created_at": booking.created_at.isoformat() if booking.created_at else None,
            "confirmed_at": booking.confirmed_at.isoformat() if booking.confirmed_at else None,
        },
    }


def _utc_iso(dt) -> str:
    """Return ISO-8601 string with explicit +00:00 UTC marker for naive datetime objects."""
    if dt is None:
        return None
    iso = dt.isoformat()
    if dt.tzinfo is None and not iso.endswith('+00:00') and not iso.endswith('Z'):
        iso += '+00:00'
    return iso


def _build_unified_conversation_rows(
    db: Session,
    tenant_id: str,
    channel: str = "all",
    limit: int = 500,
) -> List[Dict[str, Any]]:
    from sqlalchemy import func as sqlfunc

    linked_llm_session_ids = {
        row[0]
        for row in db.query(WhatsAppSession.llm_session_id)
        .filter(
            WhatsAppSession.tenant_id == tenant_id,
            WhatsAppSession.llm_session_id.isnot(None),
        )
        .all()
        if row[0]
    }

    web_sessions = []
    if channel in ("all", "web"):
        web_query = (
            db.query(ChatSession)
            .filter(ChatSession.tenant_id == tenant_id)
            .order_by(ChatSession.updated_at.desc())
        )
        if linked_llm_session_ids:
            web_query = web_query.filter(~ChatSession.id.in_(linked_llm_session_ids))
        web_sessions = web_query.limit(limit).all()

    web_session_ids = [session.id for session in web_sessions]
    web_count_map: Dict[str, int] = {}
    web_preview_map: Dict[str, Optional[str]] = {}
    web_last_map: Dict[str, Any] = {}

    if web_session_ids:
        count_rows = (
            db.query(ChatMessage.session_id, sqlfunc.count(ChatMessage.id))
            .filter(ChatMessage.session_id.in_(web_session_ids))
            .group_by(ChatMessage.session_id)
            .all()
        )
        web_count_map = {row[0]: row[1] for row in count_rows}

        last_rows = (
            db.query(ChatMessage.session_id, sqlfunc.max(ChatMessage.created_at))
            .filter(ChatMessage.session_id.in_(web_session_ids))
            .group_by(ChatMessage.session_id)
            .all()
        )
        web_last_map = {row[0]: row[1] for row in last_rows}

        preview_rows = (
            db.query(ChatMessage.session_id, ChatMessage.content)
            .filter(
                ChatMessage.session_id.in_(web_session_ids),
                ChatMessage.role == "user",
            )
            .order_by(ChatMessage.session_id, ChatMessage.created_at.asc())
            .all()
        )
        for row in preview_rows:
            if row[0] not in web_preview_map:
                web_preview_map[row[0]] = row[1]

    rows: List[Dict[str, Any]] = []
    for session in web_sessions:
        rows.append(
            {
                "thread_id": session.id,
                "thread_type": "web",
                "channel": "web_chatbot",
                "contact_label": session.user_id or "Website visitor",
                "thread_status": "active",
                "current_intent": None,
                "message_count": web_count_map.get(session.id, 0),
                "preview": web_preview_map.get(session.id),
                "created_at": _utc_iso(session.created_at),
                "updated_at": _utc_iso(session.updated_at),
                "last_message_at": _utc_iso(web_last_map.get(session.id)),
                "linked_llm_session_id": session.id,
            }
        )

    wa_rows = []
    if channel in ("all", "whatsapp"):
        wa_rows = (
            db.query(WhatsAppSession, WhatsAppContact)
            .join(WhatsAppContact, WhatsAppContact.id == WhatsAppSession.contact_id)
            .filter(WhatsAppSession.tenant_id == tenant_id)
            .order_by(WhatsAppSession.updated_at.desc())
            .limit(limit)
            .all()
        )
    contact_ids = [contact.id for _, contact in wa_rows]
    wa_counts: Dict[str, int] = {}
    wa_last: Dict[str, Any] = {}
    wa_preview: Dict[str, Optional[str]] = {}

    if contact_ids:
        count_rows = (
            db.query(WhatsAppMessage.contact_id, sqlfunc.count(WhatsAppMessage.id))
            .filter(WhatsAppMessage.tenant_id == tenant_id, WhatsAppMessage.contact_id.in_(contact_ids))
            .group_by(WhatsAppMessage.contact_id)
            .all()
        )
        wa_counts = {row[0]: row[1] for row in count_rows}

        last_rows = (
            db.query(WhatsAppMessage.contact_id, sqlfunc.max(WhatsAppMessage.created_at))
            .filter(WhatsAppMessage.tenant_id == tenant_id, WhatsAppMessage.contact_id.in_(contact_ids))
            .group_by(WhatsAppMessage.contact_id)
            .all()
        )
        wa_last = {row[0]: row[1] for row in last_rows}

        preview_rows = (
            db.query(WhatsAppMessage.contact_id, WhatsAppMessage.content)
            .filter(
                WhatsAppMessage.tenant_id == tenant_id,
                WhatsAppMessage.contact_id.in_(contact_ids),
                WhatsAppMessage.direction == "inbound",
            )
            .order_by(WhatsAppMessage.contact_id, WhatsAppMessage.created_at.asc())
            .all()
        )
        for row in preview_rows:
            if row[0] not in wa_preview:
                wa_preview[row[0]] = row[1]

    for wa_session, contact in wa_rows:
        rows.append(
            {
                "thread_id": wa_session.id,
                "thread_type": "whatsapp",
                "channel": "whatsapp",
                "contact_label": contact.contact_name or contact.phone_number,
                "thread_status": wa_session.status,
                "current_intent": wa_session.current_intent,
                "message_count": wa_counts.get(contact.id, wa_session.message_count or 0),
                "preview": wa_preview.get(contact.id),
                "created_at": _utc_iso(wa_session.created_at),
                "updated_at": _utc_iso(wa_session.updated_at),
                "last_message_at": _utc_iso(wa_last.get(contact.id)),
                "linked_llm_session_id": wa_session.llm_session_id,
                "contact_id": contact.id,
                "phone_number": contact.phone_number,
            }
        )

    rows.sort(
        key=lambda item: item.get("last_message_at") or item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )
    return rows


def _build_unified_transcript(
    db: Session,
    tenant_id: str,
    thread_type: str,
    thread_id: str,
) -> Dict[str, Any]:
    if thread_type == "web":
        session = db.query(ChatSession).filter(
            ChatSession.id == thread_id,
            ChatSession.tenant_id == tenant_id,
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = db.query(ChatMessage).filter(
            ChatMessage.session_id == thread_id,
            ChatMessage.tenant_id == tenant_id,
        ).order_by(ChatMessage.created_at.asc()).all()

        return {
            "thread_id": thread_id,
            "thread_type": "web",
            "tenant_id": tenant_id,
            "messages": [
                {
                    "id": msg.id,
                    "role": msg.role,
                    "channel": "web_chatbot",
                    "direction": msg.role,
                    "content": msg.content,
                    "model_used": msg.model_used,
                    "latency_ms": msg.latency_ms,
                    "tokens_used": msg.tokens_used,
                    "provider": (msg.msg_metadata or {}).get("provider") if isinstance(msg.msg_metadata, dict) else None,
                    "created_at": _utc_iso(msg.created_at),
                }
                for msg in messages
            ],
        }

    if thread_type != "whatsapp":
        raise HTTPException(status_code=400, detail="Unsupported thread type")

    wa_session = db.query(WhatsAppSession).filter(
        WhatsAppSession.id == thread_id,
        WhatsAppSession.tenant_id == tenant_id,
    ).first()
    if not wa_session:
        raise HTTPException(status_code=404, detail="WhatsApp thread not found")

    messages = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.tenant_id == tenant_id,
        WhatsAppMessage.contact_id == wa_session.contact_id,
    ).order_by(WhatsAppMessage.created_at.asc()).all()

    return {
        "thread_id": thread_id,
        "thread_type": "whatsapp",
        "tenant_id": tenant_id,
        "messages": [
            {
                "id": msg.id,
                "role": "user" if msg.direction == "inbound" else "assistant",
                "channel": "whatsapp",
                "direction": msg.direction,
                "content": msg.content,
                "model_used": None,
                "latency_ms": None,
                "tokens_used": None,
                "provider": None,
                "delivery_status": msg.delivery_status,
                "created_at": _utc_iso(msg.created_at),
            }
            for msg in messages
        ],
    }


def _compute_self_learning_low_conf_days(
    db: Session,
    tenant_id: str,
    since_dt: datetime,
    confidence_threshold: float,
    min_response_words: int,
):
    """
    Count low-confidence/no-positive-feedback assistant replies by day for one tenant.
    Mirrors self-learning skip signal: low_confidence_no_positive_feedback.
    """
    from app.services.query_analyzer import calculate_confidence_with_feedback

    assistant_rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.tenant_id == tenant_id,
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= since_dt,
        )
        .order_by(ChatMessage.created_at.asc())
        .all()
    )

    daily_counts = {}

    for assistant in assistant_rows:
        # Positive feedback should never trigger a low-confidence learning alert.
        if assistant.feedback_score == 1:
            continue

        response = (assistant.content or "").strip()
        if not response:
            continue
        if len(response.split()) < min_response_words:
            continue

        user_msg = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == assistant.session_id,
                ChatMessage.role == "user",
                ChatMessage.created_at <= assistant.created_at,
            )
            .order_by(ChatMessage.created_at.desc())
            .first()
        )
        if not user_msg or not (user_msg.content or "").strip():
            continue

        confidence = calculate_confidence_with_feedback(
            user_msg.content,
            response,
            assistant.feedback_score,
        )

        if confidence >= confidence_threshold:
            continue

        day_key = assistant.created_at.date().isoformat() if assistant.created_at else "unknown"
        daily_counts[day_key] = daily_counts.get(day_key, 0) + 1

    return daily_counts


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    admin_id: str
    username: str


class AdminUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=100)


class AgreementCreate(BaseModel):
    tenant_id: str = Field(..., max_length=36)
    agreement_name: str = Field(..., min_length=1, max_length=255)
    agreement_type: str = Field(..., max_length=50)
    start_date: datetime
    end_date: datetime
    terms: Optional[str] = Field(default=None, max_length=10000)


class AgreementUpdate(BaseModel):
    agreement_name: Optional[str] = Field(default=None, max_length=255)
    status: Optional[str] = Field(default=None, max_length=50)
    terms: Optional[str] = Field(default=None, max_length=10000)
    end_date: Optional[datetime] = None


class TenantUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=6, max_length=100)
    role: Optional[str] = Field(default="tenant_admin", max_length=50)


class TenantUserLogin(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


class TenantRagProfileUpdate(BaseModel):
    chunk_words: int = Field(default=140, ge=50, le=500)
    chunk_overlap: int = Field(default=30, ge=0, le=100)
    min_heading_chunk_words: int = Field(default=8, ge=4, le=40)


def get_current_admin(token: str = None, db: Session = Depends(get_db)):
    """Verify JWT token and get current admin user"""
    if not token:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    # Extract token from "Bearer {token}"
    if token.startswith("Bearer "):
        token = token[7:]
    
    token_data = decode_token(token)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    admin = db.query(AdminUser).filter(AdminUser.id == token_data.admin_id).first()
    if not admin or not admin.is_active:
        raise HTTPException(status_code=401, detail="Admin user not found or inactive")
    
    return admin


# ============ AUTHENTICATION ============

@router.get("/me")
async def get_me(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Validate admin token and return current admin info. Used for session persistence on page refresh."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")
    token = authorization.split(None, 1)[1].strip()
    token_data = decode_token(token)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    admin = db.query(AdminUser).filter(AdminUser.id == token_data.admin_id).first()
    if not admin or not admin.is_active:
        raise HTTPException(status_code=401, detail="Admin not found or inactive")
    return {"admin_id": admin.id, "username": admin.username}


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Admin login - returns JWT token"""
    import time
    t0 = time.time()

    admin = db.query(AdminUser).filter(AdminUser.username == request.username).first()
    t1 = time.time()

    if not admin or not verify_password(request.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    t2 = time.time()

    if not admin.is_active:
        raise HTTPException(status_code=403, detail="Admin account is inactive")

    # Record last login
    admin.last_login_at = datetime.now(timezone.utc)
    db.commit()

    access_token = create_access_token(admin.id, admin.username)
    t3 = time.time()

    logger.info(f"[ADMIN LOGIN] Query: {(t1-t0)*1000:.0f}ms, Password: {(t2-t1)*1000:.0f}ms, Token: {(t3-t2)*1000:.0f}ms")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "admin_id": admin.id,
        "username": admin.username,
        "last_login_at": admin.last_login_at.isoformat(),
    }


@router.post("/reset-password")
async def reset_admin_password(
    request: dict,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Reset admin password from dashboard - requires login."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")
    
    token = authorization.split(" ", 1)[1]
    token_data = decode_token(token)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    current_password = request.get("current_password")
    new_password = request.get("new_password")
    
    if not current_password or not new_password:
        raise HTTPException(status_code=400, detail="Current and new password required")
    
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    
    admin = db.query(AdminUser).filter(AdminUser.id == token_data["admin_id"]).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    if not verify_password(current_password, admin.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    
    admin.hashed_password = hash_password(new_password)
    db.commit()
    
    return {"message": "Password reset successfully"}


@router.post("/forgot-password")
async def forgot_password(
    request: dict,
    db: Session = Depends(get_db),
):
    """Request password reset - sends email to admin email."""
    email = request.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email required")
    
    admin = db.query(AdminUser).filter(AdminUser.email == email).first()
    if not admin:
        # Don't reveal if email exists or not
        return {"message": "If email exists, reset link will be sent"}
    
    # Generate reset token
    import secrets
    reset_token = secrets.token_urlsafe(32)
    from datetime import datetime, timedelta
    
    admin.password_reset_token = reset_token
    admin.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
    db.commit()
    
    # In production, send email here
    # For now, return the reset link for testing
    api_base_url = (os.getenv('API_BASE_URL') or '').strip().rstrip('/')
    if not api_base_url:
        api_base_url = 'http://localhost:8001'
    reset_link = f"{api_base_url}/admin/reset-password.html?token={reset_token}"
    
    # Log the link (in production, send via email)
    print(f"[PASSWORD RESET] Reset link for {email}: {reset_link}")
    
    return {"message": "If email exists, reset link will be sent", "reset_link": reset_link}


@router.get("/reset-password/{token}")
async def verify_reset_token(
    token: str,
    db: Session = Depends(get_db),
):
    """Verify password reset token is valid."""
    admin = db.query(AdminUser).filter(AdminUser.password_reset_token == token).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Invalid reset token")
    
    if admin.password_reset_expires and admin.password_reset_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Reset token has expired")
    
    return {"message": "Token is valid", "email": admin.email}


@router.post("/reset-password/{token}")
async def set_new_password(
    token: str,
    request: dict,
    db: Session = Depends(get_db),
):
    """Set new password using reset token."""
    new_password = request.get("new_password")
    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    
    admin = db.query(AdminUser).filter(AdminUser.password_reset_token == token).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Invalid reset token")
    
    if admin.password_reset_expires and admin.password_reset_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Reset token has expired")
    
    # Set new password and clear token
    admin.hashed_password = hash_password(new_password)
    admin.password_reset_token = None
    admin.password_reset_expires = None
    db.commit()
    
    return {"message": "Password reset successfully. Please login with new password."}


@router.post("/register", response_model=dict)
async def register(request: AdminUserCreate, db: Session = Depends(get_db)):
    """Register new admin user (first-time setup)"""
    # Check if admin already exists (for security, only allow first registration)
    existing = db.query(AdminUser).first()
    if existing:
        raise HTTPException(status_code=403, detail="Admin already registered. Use login.")
    
    # Check for duplicates
    if db.query(AdminUser).filter(AdminUser.username == request.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    
    if db.query(AdminUser).filter(AdminUser.email == request.email).first():
        raise HTTPException(status_code=400, detail="Email already exists")
    
    # Create new admin
    admin = AdminUser(
        username=request.username,
        email=request.email,
        hashed_password=hash_password(request.password)
    )
    
    db.add(admin)
    db.commit()
    db.refresh(admin)
    
    return {"message": "Admin registered successfully", "admin_id": admin.id}


# ============ TENANT MANAGEMENT ============

@router.get("/tenants")
async def list_all_tenants(
    db: Session = Depends(get_db),
):
    """List all tenants for platform owner dashboard."""
    from sqlalchemy import func as sa_func
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    since_7d = now - timedelta(days=7)

    tenants = db.query(Tenant).all()
    result = []
    for t in tenants:
        doc_count = db.query(Document).filter(
            Document.tenant_id == t.id,
            Document.is_active == True
        ).count()

        result.append({
            "id": t.id,
            "name": t.name,
            "slug": t.slug,
            "domain": t.domain,
            "website_url": t.website_url,
            "industry": getattr(t, "industry", None),
            "is_active": t.is_active,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "subscription_plan": getattr(t, "subscription_plan", None),
            "trial_ends_at": t.trial_ends_at.isoformat() if t.trial_ends_at else None,
            "crawl_progress_percent": t.crawl_progress_percent or "0",
            "crawl_progress_stage": t.crawl_progress_stage or "",
            "crawl_progress_updated_at": t.crawl_progress_updated_at.isoformat() if t.crawl_progress_updated_at else None,
            "document_count": doc_count,
            "contact_email": getattr(t, "contact_email", None),
        })

    new_tenants_7d = db.query(Tenant).filter(Tenant.created_at >= since_7d).count()

    return {
        "total": len(result),
        "tenants": result,
        "recent_registrations": {
            "new_7d": new_tenants_7d,
        }
    }


@router.post("/tenants")
async def create_tenant_admin(
    tenant_data: dict,
    db: Session = Depends(get_db),
):
    """Create new tenant via admin panel. Cleans up old inactive tenant data if slug was reused."""
    from app.models import Document, DocumentChunk, ChatSession, ChatMessage, UnansweredQuery
    from app.services.vector_knowledge import VectorKnowledgeService

    required_fields = ["name", "slug", "domain"]
    if not all(field in tenant_data for field in required_fields):
        raise HTTPException(status_code=400, detail="Missing required fields: name, slug, domain")

    # Check if an ACTIVE tenant with this slug exists
    active_tenant = db.query(Tenant).filter(
        Tenant.slug == tenant_data["slug"],
        Tenant.is_active == True
    ).first()
    if active_tenant:
        raise HTTPException(status_code=400, detail="Slug already exists")

    # If an INACTIVE tenant with this slug exists, clean up its old data before creating new one
    inactive_tenant = db.query(Tenant).filter(
        Tenant.slug == tenant_data["slug"],
        Tenant.is_active == False
    ).first()
    if inactive_tenant:
        old_tenant_id = inactive_tenant.id
        old_tenant_name = inactive_tenant.name

        # Delete chat messages
        session_ids = [s.id for s in db.query(ChatSession).filter(ChatSession.tenant_id == old_tenant_id).all()]
        if session_ids:
            db.query(ChatMessage).filter(ChatMessage.session_id.in_(session_ids)).delete(synchronize_session=False)

        # Delete chat sessions
        db.query(ChatSession).filter(ChatSession.tenant_id == old_tenant_id).delete(synchronize_session=False)

        # Delete unanswered queries
        db.query(UnansweredQuery).filter(UnansweredQuery.tenant_id == old_tenant_id).delete(synchronize_session=False)

        # Delete document chunks (vectors)
        db.query(DocumentChunk).filter(DocumentChunk.tenant_id == old_tenant_id).delete(synchronize_session=False)

        # Delete documents
        db.query(Document).filter(Document.tenant_id == old_tenant_id).delete(synchronize_session=False)

        # Delete the old tenant record
        db.query(Tenant).filter(Tenant.id == old_tenant_id).delete(synchronize_session=False)

        db.flush()
        print(f"[TenantCreate] Cleaned up old inactive tenant '{old_tenant_name}' ({old_tenant_id}) for slug '{tenant_data['slug']}'")

    tenant = Tenant(
        name=tenant_data["name"],
        slug=tenant_data["slug"],
        domain=tenant_data["domain"],
        industry=tenant_data.get("industry", "other"),
        subscription_tier=tenant_data.get("subscription_tier", "starter"),
        prompt_template=tenant_data.get("prompt_template"),
        knowledge_context=tenant_data.get("knowledge_context", {}),
        welcome_message=tenant_data.get("welcome_message"),
        website_url=tenant_data.get("website_url"),
        model_name=tenant_data.get("model_name", recommended_models(tenant_data.get("industry", "other"), tenant_data.get("subscription_tier", "starter"))[0]),
        allowed_models=tenant_data.get("allowed_models", recommended_models(tenant_data.get("industry", "other"), tenant_data.get("subscription_tier", "starter"))),
        temperature=tenant_data.get("temperature", 0.7),
        max_tokens=tenant_data.get("max_tokens", 1024),
        registration_source="admin",
    )

    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    invalidate_cors_cache()

    return {"message": "Tenant created", "tenant_id": tenant.id}


@router.get("/tenants/{tenant_id}")
async def get_tenant_for_admin(tenant_id: str, db: Session = Depends(get_db)):
    """Get comprehensive tenant details for admin troubleshooting and editing"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Lookup the primary tenant user for login info
    tenant_user = db.query(TenantUser).filter(
        TenantUser.tenant_id == tenant_id,
        TenantUser.role == "tenant_admin"
    ).first()

    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "domain": tenant.domain,
        "website_url": tenant.website_url,
        "industry": tenant.industry,
        "contact_email": tenant.contact_email,
        "business_hours": tenant.business_hours,
        "tone": tenant.tone,
        "compliance_mode": tenant.compliance_mode,
        "out_of_scope_mode": tenant.out_of_scope_mode,
        "subscription_tier": tenant.subscription_tier,
        "subscription_plan": tenant.subscription_plan,
        "subscription_status": tenant.subscription_status,
        "is_active": tenant.is_active,
        "trial_ends_at": tenant.trial_ends_at.isoformat() if tenant.trial_ends_at else None,
        "onboarding_stage": tenant.onboarding_stage,
        "onboarding_notes": tenant.onboarding_notes,
        "prompt_template": tenant.prompt_template,
        "knowledge_context": tenant.knowledge_context,
        "guardrails": tenant.guardrails,
        "welcome_message": tenant.welcome_message,
        "model_name": tenant.model_name,
        "allowed_models": tenant.allowed_models,
        "temperature": tenant.temperature,
        "max_tokens": tenant.max_tokens,
        "escalation_threshold": tenant.escalation_threshold,
        "enable_sentiment_analysis": tenant.enable_sentiment_analysis,
        "enable_conversation_memory": tenant.enable_conversation_memory,
        "enable_function_calling": tenant.enable_function_calling,
        "cta_goals": tenant.cta_goals,
        "enabled_channels": tenant.enabled_channels,
        "external_api_url": tenant.external_api_url,
        "external_api_enabled": tenant.external_api_enabled,
        "daily_report_email": tenant.daily_report_email,
        "daily_report_enabled": tenant.daily_report_enabled,
        "crawl_progress_percent": tenant.crawl_progress_percent,
        "crawl_progress_stage": tenant.crawl_progress_stage,
        "crawl_progress_updated_at": tenant.crawl_progress_updated_at.isoformat() if tenant.crawl_progress_updated_at else None,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None,
        "registration_source": tenant.registration_source,
        "login_email": tenant_user.email if tenant_user else None,
        "login_last_login_at": tenant_user.last_login_at.isoformat() if tenant_user and tenant_user.last_login_at else None,
    }


@router.put("/tenants/{tenant_id}")
async def update_tenant_admin(
    tenant_id: str,
    update_data: dict,
    db: Session = Depends(get_db),
):
    """Update tenant configuration"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Update fields
    if "name" in update_data:
        tenant.name = update_data["name"]
    if "prompt_template" in update_data:
        tenant.prompt_template = update_data["prompt_template"]
    if "knowledge_context" in update_data:
        tenant.knowledge_context = update_data["knowledge_context"]
    if "welcome_message" in update_data:
        tenant.welcome_message = update_data["welcome_message"]
    if "model_name" in update_data:
        tenant.model_name = update_data["model_name"]
    if "temperature" in update_data:
        tenant.temperature = update_data["temperature"]
    if "max_tokens" in update_data:
        tenant.max_tokens = update_data["max_tokens"]
    if "is_active" in update_data:
        tenant.is_active = update_data["is_active"]
    if "subscription_tier" in update_data:
        tenant.subscription_tier = update_data["subscription_tier"]
        if "allowed_models" not in update_data:
            tenant.allowed_models = recommended_models(tenant.industry, tenant.subscription_tier)
    if "industry" in update_data:
        tenant.industry = update_data["industry"]
        if "allowed_models" not in update_data:
            tenant.allowed_models = recommended_models(tenant.industry, tenant.subscription_tier)
    if "allowed_models" in update_data:
        tenant.allowed_models = update_data["allowed_models"]
    if "website_url" in update_data:
        tenant.website_url = update_data["website_url"]
    if "compliance_mode" in update_data:
        tenant.compliance_mode = update_data["compliance_mode"]
    if "guardrails" in update_data:
        tenant.guardrails = update_data["guardrails"]
    if "enabled_channels" in update_data:
        tenant.enabled_channels = update_data["enabled_channels"]
    if "daily_report_email" in update_data:
        tenant.daily_report_email = update_data["daily_report_email"]
    if "daily_report_enabled" in update_data:
        tenant.daily_report_enabled = update_data["daily_report_enabled"]
    if "external_api_url" in update_data:
        tenant.external_api_url = update_data["external_api_url"]
    if "external_api_key" in update_data:
        tenant.external_api_key = update_data["external_api_key"]
    if "external_api_enabled" in update_data:
        tenant.external_api_enabled = update_data["external_api_enabled"]
    if "enable_sentiment_analysis" in update_data:
        if not update_data["enable_sentiment_analysis"]:
            raise HTTPException(status_code=400, detail="Sentiment analysis is mandatory and cannot be disabled")
        tenant.enable_sentiment_analysis = update_data["enable_sentiment_analysis"]
    if "enable_conversation_memory" in update_data:
        if not update_data["enable_conversation_memory"]:
            raise HTTPException(status_code=400, detail="Conversation memory is mandatory and cannot be disabled")
        tenant.enable_conversation_memory = update_data["enable_conversation_memory"]
    if "enable_function_calling" in update_data:
        if not update_data["enable_function_calling"]:
            raise HTTPException(status_code=400, detail="Function calling is mandatory and cannot be disabled")
        tenant.enable_function_calling = update_data["enable_function_calling"]
    if "escalation_threshold" in update_data:
        tenant.escalation_threshold = update_data["escalation_threshold"]
    if "tone" in update_data:
        tenant.tone = update_data["tone"]
    if "business_hours" in update_data:
        tenant.business_hours = update_data["business_hours"]
    if "out_of_scope_mode" in update_data:
        tenant.out_of_scope_mode = update_data["out_of_scope_mode"]
    if "subscription_plan" in update_data:
        tenant.subscription_plan = update_data["subscription_plan"]
    if "subscription_status" in update_data:
        tenant.subscription_status = update_data["subscription_status"]
    if "trial_ends_at" in update_data:
        tenant.trial_ends_at = update_data["trial_ends_at"] or None
    if "cta_goals" in update_data:
        tenant.cta_goals = update_data["cta_goals"]
    if "contact_email" in update_data:
        tenant.contact_email = update_data["contact_email"]
    if "onboarding_stage" in update_data:
        tenant.onboarding_stage = update_data["onboarding_stage"]
    if "onboarding_notes" in update_data:
        tenant.onboarding_notes = update_data["onboarding_notes"]
    if "crawl_progress_percent" in update_data:
        tenant.crawl_progress_percent = update_data["crawl_progress_percent"]
    if "crawl_progress_stage" in update_data:
        tenant.crawl_progress_stage = update_data["crawl_progress_stage"]
    if "prompt_template" in update_data:
        tenant.prompt_template = update_data["prompt_template"]
    if "knowledge_context" in update_data:
        tenant.knowledge_context = update_data["knowledge_context"]
    if "guardrails" in update_data:
        tenant.guardrails = update_data["guardrails"]
     
    db.commit()
    db.refresh(tenant)
    if any(k in update_data for k in ("domain", "website_url", "is_active")):
        invalidate_cors_cache()
    
    return {"message": "Tenant updated", "tenant_id": tenant.id}


@router.get("/tenants/{tenant_id}/model-policy")
async def get_tenant_model_policy(tenant_id: str, db: Session = Depends(get_db)):
    """Get model policy and subscription facilities for a tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    allowed = tenant.allowed_models or recommended_models(tenant.industry, tenant.subscription_tier)
    return {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "industry": tenant.industry,
        "subscription_tier": tenant.subscription_tier,
        "allowed_models": allowed,
        "active_model": tenant.model_name,
        "features": subscription_features(tenant.subscription_tier),
    }


@router.post("/tenant-users/{tenant_id}")
async def create_tenant_user(tenant_id: str, payload: TenantUserCreate, db: Session = Depends(get_db)):
    """Create login user for tenant portal (stats and subscription facilities)."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if db.query(TenantUser).filter(TenantUser.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    if db.query(TenantUser).filter(TenantUser.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already exists")

    user = TenantUser(
        tenant_id=tenant_id,
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role or "tenant_admin",
    )
    db.add(user)
    
    # Auto-set daily report email to user's email and enable by default
    tenant.daily_report_email = payload.email
    tenant.daily_report_enabled = True
    
    db.commit()
    db.refresh(user)

    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "daily_report_enabled": tenant.daily_report_enabled,
    }


@router.get("/tenant-users/{tenant_id}")
async def list_tenant_users(tenant_id: str, db: Session = Depends(get_db)):
    users = db.query(TenantUser).filter(TenantUser.tenant_id == tenant_id).order_by(TenantUser.created_at.desc()).all()
    return {
        "tenant_id": tenant_id,
        "total": len(users),
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
    }


# New Pydantic models for tenant user management

class TenantUserUpdate(BaseModel):
    username: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)


class TenantUserPasswordReset(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=100)


@router.get("/tenant-users/user/{tenant_user_id}")
async def get_tenant_user(tenant_user_id: str, db: Session = Depends(get_db)):
    """Get single tenant user details by ID."""
    user = db.query(TenantUser).filter(TenantUser.id == tenant_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Tenant user not found")
    
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    
    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "tenant_name": tenant.name if tenant else None,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.put("/tenant-users/user/{tenant_user_id}")
async def update_tenant_user(tenant_user_id: str, payload: TenantUserUpdate, db: Session = Depends(get_db)):
    """Update tenant user username and/or email."""
    user = db.query(TenantUser).filter(TenantUser.id == tenant_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Tenant user not found")
    
    if payload.username:
        existing = db.query(TenantUser).filter(TenantUser.username == payload.username, TenantUser.id != tenant_user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")
        user.username = payload.username
    
    if payload.email:
        existing = db.query(TenantUser).filter(TenantUser.email == payload.email, TenantUser.id != tenant_user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already exists")
        user.email = payload.email
    
    db.commit()
    db.refresh(user)
    
    return {
        "message": "Tenant user updated",
        "id": user.id,
        "username": user.username,
        "email": user.email,
    }


@router.post("/tenant-users/user/{tenant_user_id}/reset-password")
async def reset_tenant_user_password(tenant_user_id: str, payload: TenantUserPasswordReset, db: Session = Depends(get_db)):
    """Reset tenant user password."""
    user = db.query(TenantUser).filter(TenantUser.id == tenant_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Tenant user not found")
    
    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    
    return {"message": "Password reset successfully", "tenant_user_id": tenant_user_id}


@router.patch("/tenant-users/user/{tenant_user_id}/toggle-active")
async def toggle_tenant_user_active(tenant_user_id: str, db: Session = Depends(get_db)):
    """Toggle tenant user active status."""
    user = db.query(TenantUser).filter(TenantUser.id == tenant_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Tenant user not found")
    
    user.is_active = not user.is_active
    db.commit()
    
    return {
        "message": f"User {'activated' if user.is_active else 'deactivated'}",
        "tenant_user_id": tenant_user_id,
        "is_active": user.is_active,
    }


@router.delete("/tenant-users/user/{tenant_user_id}")
async def delete_tenant_user(tenant_user_id: str, db: Session = Depends(get_db)):
    user = db.query(TenantUser).filter(TenantUser.id == tenant_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Tenant user not found")
    user.is_active = False
    db.commit()
    return {"message": "Tenant user deactivated", "tenant_user_id": tenant_user_id}


@router.post("/tenant-users/auth/login")
async def tenant_user_login(payload: TenantUserLogin, db: Session = Depends(get_db)):
    """Tenant portal login for per-tenant stats visibility."""
    import time
    t0 = time.time()
    
    user = db.query(TenantUser).filter(TenantUser.username == payload.username).first()
    t1 = time.time()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    t2 = time.time()

    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    t3 = time.time()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    token = create_tenant_user_token(user, tenant)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    t4 = time.time()
    
    logger.info(f"[TENANT LOGIN] Query: {(t1-t0)*1000:.0f}ms, Password: {(t2-t1)*1000:.0f}ms, Tenant: {(t3-t2)*1000:.0f}ms, Commit: {(t4-t3)*1000:.0f}ms")

    return {
        "access_token": token,
        "token_type": "bearer",
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "username": user.username,
    }


@router.post("/tenant-portal/change-password")
async def tenant_portal_change_password(
    request: dict,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Tenant user password change from dashboard."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")
    token = authorization.split(" ", 1)[1]
    data = decode_tenant_user_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    current_password = request.get("current_password")
    new_password = request.get("new_password")
    if not current_password or not new_password:
        raise HTTPException(status_code=400, detail="Current and new password required")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    user = db.query(TenantUser).filter(TenantUser.id == data["tenant_user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    user.hashed_password = hash_password(new_password)
    db.commit()
    return {"message": "Password updated successfully"}


@router.get("/tenant-portal/stats")
async def tenant_portal_stats(authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)):
    """Tenant-facing stats endpoint (for tenant user login sessions)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")

    token = authorization.split(" ", 1)[1]
    data = decode_tenant_user_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    tenant_id = data.get("tenant_id")
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    since_30d = datetime.now(timezone.utc) - timedelta(days=30)
    messages_30d = db.query(ChatMessage).filter(ChatMessage.tenant_id == tenant_id, ChatMessage.created_at >= since_30d).count()
    sessions_30d = db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id, ChatSession.created_at >= since_30d).count()
    unanswered_30d = db.query(UnansweredQuery).filter(UnansweredQuery.tenant_id == tenant_id, UnansweredQuery.created_at >= since_30d).count()
    docs_active = db.query(Document).filter(Document.tenant_id == tenant_id, Document.is_active == True).count()
    chunks = db.query(DocumentChunk).filter(DocumentChunk.tenant_id == tenant_id).count()
    handoff_counts = _auto_escalate_tentative_handoffs(db, tenant_id=tenant_id)
    pending_handoff = handoff_counts["pending"]
    
    # Get total lifetime sessions
    total_sessions = db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id).count()
    total_messages = db.query(ChatMessage).filter(ChatMessage.tenant_id == tenant_id).count()

    return {
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "subscription_tier": tenant.subscription_tier,
            "industry": tenant.industry,
            "allowed_models": tenant.allowed_models or recommended_models(tenant.industry, tenant.subscription_tier),
            "features": subscription_features(tenant.subscription_tier),
        },
        "window_days": 30,
        "stats": {
            "messages": messages_30d,
            "sessions": sessions_30d,
            "unanswered": unanswered_30d,
            "documents": docs_active,
            "vector_chunks": chunks,
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "pending_whatsapp_queue": pending_handoff,
            "overdue_whatsapp_queue": handoff_counts["overdue"],
            "escalated_whatsapp_queue": handoff_counts["escalated"],
            "sla_auto_escalated_now": handoff_counts["auto_escalated_now"],
            "handoff_required": pending_handoff > 0,
        },
    }


@router.get("/tenant-portal/chat-leads")
async def tenant_portal_chat_leads(authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)):
    """Get all chat leads for tenant portal."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    token = authorization.split(" ", 1)[1]
    data = decode_tenant_user_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    tenant_id = data.get("tenant_id")
    
    sessions = db.query(ChatSession).filter(
        ChatSession.tenant_id == tenant_id,
        ChatSession.lead_name.isnot(None)
    ).order_by(ChatSession.lead_collected_at.desc()).all()
    
    leads = [{
        "id": s.id,
        "name": s.lead_name,
        "email": s.lead_email,
        "phone": s.lead_phone,
        "collected_at": s.lead_collected_at.isoformat() if s.lead_collected_at else None,
    } for s in sessions]
    
    since_7d = datetime.now(timezone.utc) - timedelta(days=7)
    leads_7d = sum(1 for s in sessions if s.lead_collected_at and s.lead_collected_at >= since_7d)
    
    return {"leads": leads, "count": len(leads), "this_week": leads_7d}


@router.get("/tenant-portal/chat-analytics")
async def tenant_portal_chat_analytics(
    authorization: Optional[str] = Header(default=None),
    days: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Get chat analytics for tenant portal."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    token = authorization.split(" ", 1)[1]
    data = decode_tenant_user_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    tenant_id = data.get("tenant_id")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    
    total_sessions = db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id, ChatSession.created_at >= since).count()
    total_messages = db.query(ChatMessage).filter(ChatMessage.tenant_id == tenant_id, ChatMessage.role == "user", ChatMessage.created_at >= since).count()
    leads = db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id, ChatSession.lead_name.isnot(None), ChatSession.lead_collected_at >= since).count()
    pos_feedback = db.query(ChatMessage).filter(ChatMessage.tenant_id == tenant_id, ChatMessage.role == "assistant", ChatMessage.feedback_score == 1, ChatMessage.created_at >= since).count()
    neg_feedback = db.query(ChatMessage).filter(ChatMessage.tenant_id == tenant_id, ChatMessage.role == "assistant", ChatMessage.feedback_score == -1, ChatMessage.created_at >= since).count()
    
    return {"period_days": days, "sessions": total_sessions, "messages": total_messages, "leads": leads, "conversion_rate": round(leads / total_sessions * 100, 1) if total_sessions > 0 else 0, "positive_feedback": pos_feedback, "negative_feedback": neg_feedback}


class EmailSettings(BaseModel):
    daily_report_email: Optional[str] = None
    daily_report_enabled: bool = False


@router.get("/tenant-portal/email-settings")
async def get_tenant_email_settings(authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)):
    """Get email settings for daily reports."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    token = authorization.split(" ", 1)[1]
    data = decode_tenant_user_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    tenant_id = data.get("tenant_id")
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    return {"daily_report_email": tenant.daily_report_email or tenant.email, "daily_report_enabled": tenant.daily_report_enabled or False}


@router.put("/tenant-portal/email-settings")
async def update_tenant_email_settings(settings_in: EmailSettings, authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)):
    """Update email settings for daily reports."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    token = authorization.split(" ", 1)[1]
    data = decode_tenant_user_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    tenant_id = data.get("tenant_id")
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    tenant.daily_report_email = settings_in.daily_report_email
    tenant.daily_report_enabled = settings_in.daily_report_enabled
    tenant.updated_at = datetime.now(timezone.utc)
    db.commit()
    
    return {"status": "saved", "daily_report_email": tenant.daily_report_email, "daily_report_enabled": tenant.daily_report_enabled}


@router.post("/reports/send-daily")
async def trigger_daily_reports(db: Session = Depends(get_db)):
    """Trigger daily report emails to all enabled tenants."""
    try:
        from app.services.daily_report import send_daily_reports
        results = await send_daily_reports(db)
        return {"status": "completed", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tenants/{tenant_id}/test-external-api")
async def test_external_api(tenant_id: str, db: Session = Depends(get_db)):
    """Test external API connection for a tenant"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    if not tenant.external_api_url:
        return {"status": "error", "message": "External API URL not configured"}
    
    try:
        from app.services.external_api import ExternalAPIService
        
        # Test product search
        result = ExternalAPIService.search_products(tenant, "test")
        
        if result is not None:
            return {"status": "success", "message": "External API connected successfully", "products_found": len(result)}
        else:
            return {"status": "error", "message": "External API returned no data (may be empty)"}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/whatsapp/handoff-summary")
async def whatsapp_handoff_summary(
    tenant_id: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Step 5: lightweight pending handoff notification payload for dashboards."""
    from sqlalchemy import func as sqlfunc

    handoff_counts = _auto_escalate_tentative_handoffs(db, tenant_id=tenant_id)

    query = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.status == "tentative")
    if tenant_id:
        query = query.filter(WhatsAppTentativeBooking.tenant_id == tenant_id)

    total_pending = query.count()
    tentative_rows = query.all()
    pending_by_tenant: Dict[str, List[WhatsAppTentativeBooking]] = {}
    for row in tentative_rows:
        pending_by_tenant.setdefault(row.tenant_id, []).append(row)

    grouped = (
        db.query(
            WhatsAppTentativeBooking.tenant_id,
            sqlfunc.count(WhatsAppTentativeBooking.id).label("pending_count"),
            sqlfunc.max(WhatsAppTentativeBooking.created_at).label("latest_created_at"),
            Tenant.name,
        )
        .join(Tenant, Tenant.id == WhatsAppTentativeBooking.tenant_id)
        .filter(WhatsAppTentativeBooking.status == "tentative")
    )
    if tenant_id:
        grouped = grouped.filter(WhatsAppTentativeBooking.tenant_id == tenant_id)

    rows = (
        grouped.group_by(WhatsAppTentativeBooking.tenant_id, Tenant.name)
        .order_by(sqlfunc.max(WhatsAppTentativeBooking.created_at).desc())
        .limit(limit)
        .all()
    )

    return {
        "total_pending": total_pending,
        "overdue_pending": handoff_counts["overdue"],
        "escalated_pending": handoff_counts["escalated"],
        "sla_auto_escalated_now": handoff_counts["auto_escalated_now"],
        "requires_handoff": total_pending > 0,
        "tenants": [
            {
                "tenant_id": row.tenant_id,
                "tenant_name": row.name,
                "pending_count": int(row.pending_count or 0),
                "overdue_count": _compute_handoff_counts(pending_by_tenant.get(row.tenant_id, []))["overdue"],
                "escalated_count": _compute_handoff_counts(pending_by_tenant.get(row.tenant_id, []))["escalated"],
                "latest_created_at": row.latest_created_at.isoformat() if row.latest_created_at else None,
            }
            for row in rows
        ],
    }


@router.get("/crm/admin-stats")
async def admin_crm_stats(
    db: Session = Depends(get_db),
):
    """Admin overview: system-wide CRM metrics across all tenants."""
    from sqlalchemy import func as sqlfunc

    total_contacts = db.query(sqlfunc.count(WhatsAppContact.id)).scalar() or 0
    total_leads = db.query(sqlfunc.count(WhatsAppTentativeBooking.id)).scalar() or 0

    tentative = db.query(sqlfunc.count(WhatsAppTentativeBooking.id)).filter(
        WhatsAppTentativeBooking.status == "tentative"
    ).scalar() or 0
    confirmed = db.query(sqlfunc.count(WhatsAppTentativeBooking.id)).filter(
        WhatsAppTentativeBooking.status == "confirmed"
    ).scalar() or 0

    leads_today = db.query(sqlfunc.count(WhatsAppTentativeBooking.id)).filter(
        WhatsAppTentativeBooking.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    ).scalar() or 0

    top_tenants = db.query(
        WhatsAppTentativeBooking.tenant_id,
        sqlfunc.count(WhatsAppTentativeBooking.id).label("lead_count")
    ).filter(
        WhatsAppTentativeBooking.status == "confirmed"
    ).group_by(WhatsAppTentativeBooking.tenant_id).order_by(
        sqlfunc.count(WhatsAppTentativeBooking.id).desc()
    ).limit(10).all()

    from app.services.followup_scheduler import dispatch_pending_messages
    from app.models.whatsapp import ScheduledMessage
    pending_followups = db.query(sqlfunc.count(ScheduledMessage.id)).filter(
        ScheduledMessage.status == "pending"
    ).scalar() or 0

    return {
        "total_contacts": total_contacts,
        "total_leads": total_leads,
        "tentative_leads": tentative,
        "confirmed_leads": confirmed,
        "leads_today": leads_today,
        "pending_followups": pending_followups,
        "top_tenants": [
            {"tenant_id": t.tenant_id, "confirmed_leads": t.lead_count}
            for t in top_tenants
        ],
    }


@router.get("/whatsapp/tentative-bookings")
async def list_whatsapp_tentative_bookings(
    tenant_id: Optional[str] = Query(default=None),
    intent: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default="tentative"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Admin view: list tentative WhatsApp booking/callback/demo leads."""
    _auto_escalate_tentative_handoffs(db, tenant_id=tenant_id)

    query = (
        db.query(WhatsAppTentativeBooking, Tenant, WhatsAppContact)
        .join(Tenant, Tenant.id == WhatsAppTentativeBooking.tenant_id)
        .join(WhatsAppContact, WhatsAppContact.id == WhatsAppTentativeBooking.contact_id)
    )

    if tenant_id:
        query = query.filter(WhatsAppTentativeBooking.tenant_id == tenant_id)
    if intent:
        query = query.filter(WhatsAppTentativeBooking.intent_type == intent)
    if status and status.lower() != "all":
        query = query.filter(WhatsAppTentativeBooking.status == status)

    total = query.count()
    rows = (
        query.order_by(WhatsAppTentativeBooking.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "leads": [
            _serialize_whatsapp_booking(booking, contact=contact, tenant=tenant)
            for booking, tenant, contact in rows
        ],
    }


@router.patch("/whatsapp/tentative-bookings/{lead_id}")
async def admin_update_whatsapp_tentative_booking(
    lead_id: str,
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Admin Step 4 queue controls: confirm, edit, or reject WhatsApp leads."""
    booking = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.id == lead_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = _apply_booking_update(booking, payload, actor="admin")
    if result["status_changed"]:
        _event = BOOKING_CONFIRMED if result["new_status"] == "confirmed" else (
            BOOKING_CANCELLED if result["new_status"] == "cancelled" else None
        )
        if _event:
            log_analytics_event(
                db,
                tenant_id=booking.tenant_id,
                event_type=_event,
                booking_id=booking.id,
                contact_id=booking.contact_id,
            )
    db.commit()
    db.refresh(booking)

    should_run_side_effects = result["status_changed"] or (booking.status == "confirmed" and result["fields_changed"])
    if should_run_side_effects:
        background_tasks.add_task(
            _handle_lead_status_side_effects,
            lead_id=lead_id,
            tenant_id=booking.tenant_id,
            new_status=result["new_status"],
            old_status=result["old_status"],
            db_factory=lambda: next(get_db()),
            calendar_refresh=result["fields_changed"],
            crm_refresh=result["fields_changed"],
        )

    contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == booking.contact_id).first()
    tenant = db.query(Tenant).filter(Tenant.id == booking.tenant_id).first()
    response = _serialize_whatsapp_booking(booking, contact=contact, tenant=tenant)
    response["calendar_sync"] = "queued" if should_run_side_effects and booking.status in {"confirmed", "cancelled"} else "not_required"
    response["crm_sync_status"] = "queued" if should_run_side_effects and booking.status == "confirmed" else "not_required"
    response["calendar_integration_configured"] = bool(get_calendar_service(_calendar_settings(tenant)))
    response["crm_integration_configured"] = bool(get_crm_sync_service(_crm_settings(tenant)))
    response["whatsapp_delivery_configured"] = _has_active_whatsapp_config(db, booking.tenant_id)
    return response


@router.post("/whatsapp/tentative-bookings/{lead_id}/claim")
async def admin_claim_whatsapp_lead(
    lead_id: str,
    payload: Optional[dict] = None,
    db: Session = Depends(get_db),
):
    booking = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.id == lead_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Lead not found")

    _apply_booking_update(
        booking,
        {
            "action": "claim",
            "assigned_to": (payload or {}).get("assigned_to") or "admin",
            "handoff_note": (payload or {}).get("note"),
        },
        actor="admin",
    )
    log_analytics_event(
        db,
        tenant_id=booking.tenant_id,
        event_type=HUMAN_INTERVENTION,
        booking_id=booking.id,
        contact_id=booking.contact_id,
        sub_type="claim",
    )
    db.commit()
    db.refresh(booking)
    contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == booking.contact_id).first()
    tenant = db.query(Tenant).filter(Tenant.id == booking.tenant_id).first()
    return _with_readiness(_serialize_whatsapp_booking(booking, contact=contact, tenant=tenant), tenant, db, booking.tenant_id)


@router.post("/whatsapp/tentative-bookings/{lead_id}/reassign")
async def admin_reassign_whatsapp_lead(
    lead_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    booking = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.id == lead_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Lead not found")

    _apply_booking_update(
        booking,
        {
            "action": "reassign",
            "assigned_to": payload.get("assigned_to"),
            "handoff_note": payload.get("note"),
        },
        actor="admin",
    )
    log_analytics_event(
        db,
        tenant_id=booking.tenant_id,
        event_type=HUMAN_INTERVENTION,
        booking_id=booking.id,
        contact_id=booking.contact_id,
        sub_type="reassign",
    )
    db.commit()
    db.refresh(booking)
    contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == booking.contact_id).first()
    tenant = db.query(Tenant).filter(Tenant.id == booking.tenant_id).first()
    return _with_readiness(_serialize_whatsapp_booking(booking, contact=contact, tenant=tenant), tenant, db, booking.tenant_id)


@router.post("/whatsapp/tentative-bookings/{lead_id}/note")
async def admin_note_whatsapp_lead(
    lead_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    booking = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.id == lead_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Lead not found")

    _apply_booking_update(booking, {"handoff_note": payload.get("note")}, actor="admin")
    db.commit()
    db.refresh(booking)
    contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == booking.contact_id).first()
    tenant = db.query(Tenant).filter(Tenant.id == booking.tenant_id).first()
    return _with_readiness(_serialize_whatsapp_booking(booking, contact=contact, tenant=tenant), tenant, db, booking.tenant_id)


@router.post("/whatsapp/tentative-bookings/{lead_id}/escalate")
async def admin_escalate_whatsapp_lead(
    lead_id: str,
    payload: Optional[dict] = None,
    db: Session = Depends(get_db),
):
    booking = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.id == lead_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Lead not found")

    _apply_booking_update(
        booking,
        {
            "action": "escalate",
            "escalation_level": (payload or {}).get("escalation_level"),
            "handoff_note": (payload or {}).get("note"),
            "priority": (payload or {}).get("priority"),
        },
        actor="admin",
    )
    log_analytics_event(
        db,
        tenant_id=booking.tenant_id,
        event_type=HUMAN_INTERVENTION,
        booking_id=booking.id,
        contact_id=booking.contact_id,
        sub_type="escalate",
    )
    db.commit()
    db.refresh(booking)
    contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == booking.contact_id).first()
    tenant = db.query(Tenant).filter(Tenant.id == booking.tenant_id).first()
    return _with_readiness(_serialize_whatsapp_booking(booking, contact=contact, tenant=tenant), tenant, db, booking.tenant_id)


@router.post("/whatsapp/tentative-bookings/{lead_id}/close")
async def admin_close_whatsapp_lead(
    lead_id: str,
    payload: Optional[dict] = None,
    db: Session = Depends(get_db),
):
    booking = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.id == lead_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Lead not found")

    _apply_booking_update(
        booking,
        {
            "action": "close",
            "status": "closed",
            "handoff_note": (payload or {}).get("note"),
        },
        actor="admin",
    )
    log_analytics_event(
        db,
        tenant_id=booking.tenant_id,
        event_type=HUMAN_INTERVENTION,
        booking_id=booking.id,
        contact_id=booking.contact_id,
        sub_type="close",
    )
    db.commit()
    db.refresh(booking)
    contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == booking.contact_id).first()
    tenant = db.query(Tenant).filter(Tenant.id == booking.tenant_id).first()
    return _with_readiness(_serialize_whatsapp_booking(booking, contact=contact, tenant=tenant), tenant, db, booking.tenant_id)

@router.get("/tenant-portal/whatsapp-leads")
async def tenant_portal_whatsapp_leads(
    status: Optional[str] = Query(default="all"),
    intent: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Tenant-facing view of Step 2 tentative WhatsApp leads."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")

    token = authorization.split(" ", 1)[1]
    data = decode_tenant_user_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    tenant_id = data.get("tenant_id")
    _auto_escalate_tentative_handoffs(db, tenant_id=tenant_id)

    query = (
        db.query(WhatsAppTentativeBooking, WhatsAppContact)
        .join(WhatsAppContact, WhatsAppContact.id == WhatsAppTentativeBooking.contact_id)
        .filter(WhatsAppTentativeBooking.tenant_id == tenant_id)
    )

    if intent:
        query = query.filter(WhatsAppTentativeBooking.intent_type == intent)
    if status and status.lower() != "all":
        query = query.filter(WhatsAppTentativeBooking.status == status)

    total = query.count()
    rows = (
        query.order_by(WhatsAppTentativeBooking.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "tenant_id": tenant_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "leads": [
            _serialize_whatsapp_booking(booking, contact=contact)
            for booking, contact in rows
        ],
    }


@router.patch("/tenant-portal/whatsapp-leads/{lead_id}")
async def tenant_portal_update_whatsapp_lead(
    lead_id: str,
    payload: dict,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Tenant Step 4 queue controls: confirm, edit, or reject WhatsApp leads."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")

    token = authorization.split(" ", 1)[1]
    data = decode_tenant_user_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    tenant_id = data.get("tenant_id")
    username = data.get("username") or "tenant_user"
    booking = (
        db.query(WhatsAppTentativeBooking)
        .filter(
            WhatsAppTentativeBooking.id == lead_id,
            WhatsAppTentativeBooking.tenant_id == tenant_id,
        )
        .first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = _apply_booking_update(booking, payload, actor=f"tenant:{username}")
    db.commit()
    db.refresh(booking)

    should_run_side_effects = result["status_changed"] or (booking.status == "confirmed" and result["fields_changed"])
    if should_run_side_effects:
        background_tasks.add_task(
            _handle_lead_status_side_effects,
            lead_id=lead_id,
            tenant_id=tenant_id,
            new_status=result["new_status"],
            old_status=result["old_status"],
            db_factory=lambda: next(get_db()),
            calendar_refresh=result["fields_changed"],
            crm_refresh=result["fields_changed"],
        )

    contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == booking.contact_id).first()
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    response = _serialize_whatsapp_booking(booking, contact=contact)
    response["calendar_sync"] = "queued" if should_run_side_effects and booking.status in {"confirmed", "cancelled"} else "not_required"
    response["crm_sync_status"] = "queued" if should_run_side_effects and booking.status == "confirmed" else "not_required"
    response["calendar_integration_configured"] = bool(get_calendar_service(_calendar_settings(tenant)))
    response["crm_integration_configured"] = bool(get_crm_sync_service(_crm_settings(tenant)))
    response["whatsapp_delivery_configured"] = _has_active_whatsapp_config(db, tenant_id)
    return response


@router.post("/tenant-portal/whatsapp-leads/{lead_id}/claim")
async def tenant_portal_claim_whatsapp_lead(
    lead_id: str,
    payload: Optional[dict] = None,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")

    token = authorization.split(" ", 1)[1]
    data = decode_tenant_user_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    tenant_id = data.get("tenant_id")
    username = data.get("username") or "tenant_user"
    booking = (
        db.query(WhatsAppTentativeBooking)
        .filter(
            WhatsAppTentativeBooking.id == lead_id,
            WhatsAppTentativeBooking.tenant_id == tenant_id,
        )
        .first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Lead not found")

    _apply_booking_update(
        booking,
        {
            "action": "claim",
            "assigned_to": (payload or {}).get("assigned_to") or username,
            "handoff_note": (payload or {}).get("note"),
        },
        actor=f"tenant:{username}",
    )
    db.commit()
    db.refresh(booking)
    contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == booking.contact_id).first()
    return _serialize_whatsapp_booking(booking, contact=contact)


@router.post("/tenant-portal/whatsapp-leads/{lead_id}/note")
async def tenant_portal_note_whatsapp_lead(
    lead_id: str,
    payload: dict,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")

    token = authorization.split(" ", 1)[1]
    data = decode_tenant_user_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    tenant_id = data.get("tenant_id")
    username = data.get("username") or "tenant_user"
    booking = (
        db.query(WhatsAppTentativeBooking)
        .filter(
            WhatsAppTentativeBooking.id == lead_id,
            WhatsAppTentativeBooking.tenant_id == tenant_id,
        )
        .first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Lead not found")

    _apply_booking_update(booking, {"handoff_note": payload.get("note")}, actor=f"tenant:{username}")
    db.commit()
    db.refresh(booking)
    contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == booking.contact_id).first()
    return _serialize_whatsapp_booking(booking, contact=contact)


@router.patch("/tenant-portal/whatsapp-leads/{lead_id}/status")
async def update_whatsapp_lead_status(
    lead_id: str,
    payload: dict,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Update status of a WhatsApp tentative lead (tentative → confirmed/cancelled)."""
    return await tenant_portal_update_whatsapp_lead(
        lead_id=lead_id,
        payload=payload,
        background_tasks=background_tasks,
        authorization=authorization,
        db=db,
    )


async def _handle_lead_status_side_effects(
    lead_id: str,
    tenant_id: str,
    new_status: str,
    old_status: str,
    db_factory,
    calendar_refresh: bool = False,
    crm_refresh: bool = False,
):
    """
    Background task: sync Google Calendar and send WhatsApp notification
    when a lead is confirmed or cancelled.  Runs after response is sent.
    """
    db = db_factory()
    try:
        booking = db.query(WhatsAppTentativeBooking).filter(
            WhatsAppTentativeBooking.id == lead_id
        ).first()
        if not booking:
            return

        contact = db.query(WhatsAppContact).filter(
            WhatsAppContact.id == booking.contact_id
        ).first()
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()

        tenant_settings = _calendar_settings(tenant)
        crm_settings = _crm_settings(tenant)
        tenant_name = getattr(tenant, "name", "")

        # ── Google Calendar ────────────────────────────────────────────────────
        cal = get_calendar_service(tenant_settings)
        if cal:
            now = datetime.utcnow()
            if new_status == "confirmed":
                if calendar_refresh and booking.google_calendar_event_id:
                    await cal.delete_event(booking.google_calendar_event_id)
                    booking.google_calendar_event_id = None
                    db.commit()

                if booking.google_calendar_event_id:
                    await cal.confirm_event(booking.google_calendar_event_id)
                else:
                    event_id = await cal.create_tentative_event(
                        booking, tenant_name,
                        contact.phone_number if contact else "unknown"
                    )
                    if event_id:
                        booking.google_calendar_event_id = event_id
                        booking.calendar_synced_at = now
                        await cal.confirm_event(event_id)
            elif new_status == "cancelled" and booking.google_calendar_event_id:
                await cal.delete_event(booking.google_calendar_event_id)
                booking.google_calendar_event_id = None
            elif new_status == "tentative" and calendar_refresh and booking.google_calendar_event_id:
                await cal.delete_event(booking.google_calendar_event_id)
                booking.google_calendar_event_id = None
            log_analytics_event(db, tenant_id=tenant_id, event_type=CALENDAR_SYNCED,
                                 booking_id=lead_id, contact_id=booking.contact_id,
                                 metadata={"new_status": new_status})
            db.commit()

        # ── CRM sync for confirmed bookings ───────────────────────────────────
        crm_service = get_crm_sync_service(crm_settings)
        if crm_service and new_status == "confirmed" and (old_status != "confirmed" or crm_refresh):
            crm_result = await crm_service.push_booking(_build_crm_payload(booking, tenant, contact))
            extracted_fields = dict(booking.extracted_fields or {})
            extracted_fields["crm_sync"] = {
                "status": "synced" if crm_result.get("success") else "failed",
                "last_attempt_at": datetime.utcnow().isoformat(),
                "status_code": crm_result.get("status_code"),
                "error": crm_result.get("error"),
            }
            booking.extracted_fields = extracted_fields
            if crm_result.get("success"):
                log_analytics_event(db, tenant_id=tenant_id, event_type=CRM_SYNCED,
                                     booking_id=lead_id, contact_id=booking.contact_id)
            db.commit()

        # ── CRM follow-up scheduling ─────────────────────────────────────────
        if contact and new_status != old_status:
            from app.services.followup_scheduler import schedule_follow_up
            if new_status == "confirmed":
                schedule_follow_up(db, tenant_id, booking.contact_id, "lead_confirmed", booking)
            elif new_status == "cancelled":
                pass  # No follow-up for cancellations

        # ── WhatsApp confirmation message ─────────────────────────────────────
        if contact and new_status in ("confirmed", "cancelled"):
            wa_config = db.query(WhatsAppConfiguration).filter(
                WhatsAppConfiguration.tenant_id == tenant_id,
                WhatsAppConfiguration.is_active == True,
            ).first()

            if wa_config:
                provider = get_whatsapp_provider(
                    provider_type="cloud_api",
                    phone_number_id=wa_config.phone_number_id,
                    business_account_id=wa_config.business_account_id,
                    access_token=wa_config.access_token,
                    api_version=wa_config.api_version,
                )
                if new_status == "confirmed":
                    msg = (
                        f"✅ Great news! Your {booking.intent_type} has been *confirmed*.\n\n"
                        f"📅 Date: *{booking.requested_date or '—'}*\n"
                        f"🕐 Time: *{booking.requested_time or '—'}*\n"
                        f"👥 Persons: *{booking.requested_persons or '—'}*\n\n"
                        f"We look forward to seeing you! 🙏"
                    )
                else:
                    msg = (
                        f"We're sorry, your {booking.intent_type} request has been *cancelled*.\n"
                        f"Feel free to reach out if you'd like to rebook. 😊"
                    )
                try:
                    await provider.send_message(contact.phone_number, msg)
                    booking.confirmation_sent_at = datetime.utcnow()
                    db.commit()
                except Exception as e:
                    logging.getLogger(__name__).warning(f"[Step3] WhatsApp notify failed: {e}")

    except Exception as e:
        logging.getLogger(__name__).error(f"[Step3] Side-effect task error: {e}")
    finally:
        db.close()


@router.get("/conversations-unified/{tenant_id}")
async def get_unified_tenant_conversations(
    tenant_id: str,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    channel: str = Query(default="all"),
    db: Session = Depends(get_db),
):
    """Step 4 admin view: unified web chatbot and WhatsApp thread summaries."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Fetch only enough rows to satisfy offset + limit, then slice
    fetch_limit = offset + limit
    rows = _build_unified_conversation_rows(db, tenant_id, channel=channel, limit=fetch_limit + 25)
    total = len(rows)
    sliced = rows[offset: offset + limit]
    return {
        "tenant_id": tenant_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "conversations": sliced,
    }


@router.get("/conversations-unified/{thread_type}/{thread_id}/transcript")
async def get_unified_conversation_transcript(
    thread_type: str,
    thread_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
):
    """Step 4 admin transcript view for unified thread records."""
    return _build_unified_transcript(db, tenant_id=tenant_id, thread_type=thread_type, thread_id=thread_id)


@router.get("/tenant-portal/conversations")
async def tenant_portal_unified_conversations(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    channel: str = Query(default="all"),
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Step 4 tenant view: unified web chatbot and WhatsApp thread summaries."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")

    token = authorization.split(" ", 1)[1]
    data = decode_tenant_user_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    tenant_id = data.get("tenant_id")
    rows = _build_unified_conversation_rows(db, tenant_id)

    # Apply channel filter server-side
    if channel == "web":
        rows = [r for r in rows if r.get("thread_type") == "web"]
    elif channel == "whatsapp":
        rows = [r for r in rows if r.get("thread_type") == "whatsapp"]

    total = len(rows)
    return {
        "tenant_id": tenant_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "conversations": rows[offset: offset + limit],
    }


@router.get("/tenant-portal/conversations/{thread_type}/{thread_id}")
async def tenant_portal_unified_conversation_transcript(
    thread_type: str,
    thread_id: str,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Step 4 tenant transcript view for unified thread records."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")

    token = authorization.split(" ", 1)[1]
    data = decode_tenant_user_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return _build_unified_transcript(
        db,
        tenant_id=data.get("tenant_id"),
        thread_type=thread_type,
        thread_id=thread_id,
    )


@router.get("/tenants/{tenant_id}/widget-code")
async def generate_widget_code(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    """Generate embeddable widget integration snippet for tenant websites."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    api_key = db.query(APIKey).filter(APIKey.tenant_id == tenant_id, APIKey.is_active == True, APIKey.key_type == "widget").first()
    if not api_key:
        # Persist allowed_domains as a bare hostname so the per-request domain
        # check in chat.py and the dynamic CORS layer match cleanly. Tenant.domain
        # is sometimes saved as a full URL (e.g. "https://www.foo.com/"), so we
        # normalize to "www.foo.com" before storing.
        from urllib.parse import urlparse as _urlparse
        _raw_domain = (tenant.domain or "").strip()
        _parsed = _urlparse(_raw_domain if "://" in _raw_domain else f"//{_raw_domain}")
        _domain_host = (_parsed.netloc or _parsed.path or _raw_domain).strip("/").lower() or _raw_domain
        api_key = APIKey(
            tenant_id=tenant_id, 
            name="Website Widget",
            key_type="widget",
            allowed_domains=_domain_host,  # Restrict to tenant's domain by default
            rate_limit_per_minute=30,
            rate_limit_per_hour=500,
        )
        db.add(api_key)
        db.commit()
        db.refresh(api_key)
        invalidate_cors_cache()  # new widget key -> refresh CORS allowlist


    # Always use https for widget code generation
    url_obj = request.base_url
    https_base_url = "https://" + url_obj.hostname
    if url_obj.port and url_obj.port not in (80, 443):
        https_base_url += f":{url_obj.port}"

    widget_file = Path(__file__).resolve().parents[2] / "static" / "widget.js"
    widget_version = str(int(widget_file.stat().st_mtime)) if widget_file.exists() else settings.api_version
    # Use a stable URL without ?v= — the server already sends no-cache headers for widget.js
    # so browsers always fetch the latest version without tenants ever changing their embed code.
    widget_script_url = f"{https_base_url}/static/widget.js"
    snippet = (
        '<!-- 💬 SCUBE AI Chatbot Widget - Paste this before </body> on every page -->\n'
        f'<script src="{widget_script_url}"></script>\n'
        '<script>\n'
        f'  LLMChatbot.init({{\n'
        f"    apiUrl: '{https_base_url}',\n"
        f"    tenantId: '{tenant_id}',\n"
        "    tokenRefreshUrl: '/get-chatbot-token',\n"
        '    // --- Position options (uncomment one pair, comment the defaults) ---\n'
        '    // Default: bottom-right\n'
        '    position: { bottom: "20px", right: "20px", left: "auto", top: "auto" },\n'
        '    // Bottom-left:\n'
        '    // position: { bottom: "20px", left: "20px", right: "auto", top: "auto" },\n'
        '    // Top-right:\n'
        '    // position: { top: "20px", right: "20px", bottom: "auto", left: "auto" },\n'
        '    // Top-left:\n'
        '    // position: { top: "20px", left: "20px", bottom: "auto", right: "auto" },\n'
        '  });\n'
        '</script>'
    )

    return {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "api_url": https_base_url,
        "widget_script_url": widget_script_url,
        "integration_snippet": snippet,
        "api_key": api_key.key,
        "token_endpoint": f"{https_base_url}/api/chat/token/{tenant_id}",
        "wordpress_hint": "Paste the script snippet in your theme footer or via a custom HTML block.",
        "integration_note": "Customer implements /get-chatbot-token endpoint on their backend that calls the token endpoint above. Permanent API key never leaves their server.",
        "backend_integration_example": f'curl -X POST "{https_base_url}/api/chat/token/{tenant_id}" -H "X-API-Key: {api_key.key}" -d \'{{"origin": "https://{tenant.domain if tenant.domain else "customer-website.com"}"}}\''
    }


@router.post("/api-keys/{api_key_id}/rotate")
async def rotate_api_key(
    api_key_id: str,
    db: Session = Depends(get_db),
):
    """
    Rotate/regenerate an API key.
    
    This will:
    1. Deactivate the old key immediately
    2. Generate a new key
    3. Return the new key for the customer to update their widget code
    
    Use this when an API key is compromised or as routine security hygiene.
    """
    api_key = db.query(APIKey).filter(APIKey.id == api_key_id).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    
    # Get tenant info for the response
    tenant = db.query(Tenant).filter(Tenant.id == api_key.tenant_id).first()
    
    # Deactivate old key
    api_key.is_active = False
    api_key.name = f"{api_key.name} (rotated)"
    
    # Generate new key
    import secrets
    new_key_value = secrets.token_urlsafe(32)
    
    # Create new key with same settings
    new_api_key = APIKey(
        tenant_id=api_key.tenant_id,
        name=api_key.name.replace(" (rotated)", ""),
        key=api_key.key,  # Keep same key until new one is used
        key_type=api_key.key_type,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
        rate_limit_per_hour=api_key.rate_limit_per_hour,
        is_active=True,
    )
    
    # Actually generate new key value
    new_api_key.key = new_key_value
    
    db.add(new_api_key)
    
    # Reset old key's key value to invalid (can't reuse)
    api_key.key = f"REVOKED_{api_key.key[:8]}"
    
    db.commit()
    db.refresh(new_api_key)
    
    return {
        "status": "rotated",
        "old_key_id": api_key_id,
        "new_key_id": new_api_key.id,
        "new_key": new_api_key.key,
        "warning": "Update your widget code with the new key immediately. The old key is now invalid.",
        "tenant_name": tenant.name if tenant else None,
    }


@router.get("/api-keys/{api_key_id}/usage")
async def get_api_key_usage(
    api_key_id: str,
    db: Session = Depends(get_db),
):
    """Get usage statistics for an API key."""
    from app.services.rate_limiter import RateLimitService
    
    api_key = db.query(APIKey).filter(APIKey.id == api_key_id).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    
    stats = RateLimitService.get_usage_stats(db, api_key_id)
    
    # Get tenant info
    tenant = db.query(Tenant).filter(Tenant.id == api_key.tenant_id).first()
    
    return {
        **stats,
        "tenant_name": tenant.name if tenant else None,
    }


@router.put("/api-keys/{api_key_id}/rate-limits")
async def update_api_key_rate_limits(
    api_key_id: str,
    per_minute: int = Query(..., ge=5, le=1000),
    per_hour: int = Query(..., ge=10, le=50000),
    db: Session = Depends(get_db),
):
    """Update rate limits for an API key."""
    from app.services.rate_limiter import RateLimitService
    
    api_key = db.query(APIKey).filter(APIKey.id == api_key_id).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    
    success = RateLimitService.update_limits(db, api_key_id, per_minute, per_hour)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update rate limits")
    
    return {
        "status": "updated",
        "api_key_id": api_key_id,
        "rate_limit_per_minute": per_minute,
        "rate_limit_per_hour": per_hour,
    }


@router.get("/tenants/{tenant_id}/api-keys")
async def list_tenant_api_keys(
    tenant_id: str,
    db: Session = Depends(get_db),
):
    """List all API keys for a tenant."""
    from app.services.rate_limiter import RateLimitService
    
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    api_keys = db.query(APIKey).filter(APIKey.tenant_id == tenant_id).all()
    
    result = []
    for key in api_keys:
        stats = RateLimitService.get_usage_stats(db, key.id)
        result.append({
            "id": key.id,
            "name": key.name,
            "key_type": key.key_type,
            "is_active": key.is_active,
            "rate_limit_per_minute": key.rate_limit_per_minute,
            "rate_limit_per_hour": key.rate_limit_per_hour,
            "created_at": key.created_at.isoformat() if key.created_at else None,
            "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
            "usage": {
                "minute_remaining": stats.get("minute_remaining") if stats else 0,
                "hour_remaining": stats.get("hour_remaining") if stats else 0,
            }
        })
    
    return {
        "tenant_id": tenant_id,
        "tenant_name": tenant.name,
        "total_keys": len(result),
        "api_keys": result,
    }


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
):
    """Hard delete tenant and all associated data."""
    from app.models import Document, DocumentChunk, ChatSession, ChatMessage, UnansweredQuery, APIKey, TenantUser
    from app.models.billing import Invoice
    from app.models.calendar import CalendarIntegration, TenantAvailability
    from app.models.support import SupportTicket
    from app.models.whatsapp import (
        WhatsAppConfiguration, WhatsAppMessage, WhatsAppSession, WhatsAppMetrics,
        WhatsAppTentativeBooking, WhatsAppAnalyticsEvent, WhatsAppContact,
        ContactActivity, FollowUpTemplate, ScheduledMessage,
    )
    from app.models.quality import QualityScore, FailurePattern, ImprovementCandidate, QualityMetric
    from app.services.vector_knowledge import VectorKnowledgeService

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant_name = tenant.name
    tenant_slug = tenant.slug

    # Delete quality tracking data
    db.query(QualityScore).filter(QualityScore.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(FailurePattern).filter(FailurePattern.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(ImprovementCandidate).filter(ImprovementCandidate.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(QualityMetric).filter(QualityMetric.tenant_id == tenant_id).delete(synchronize_session=False)

    # Delete CRM data
    db.query(ContactActivity).filter(ContactActivity.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(FollowUpTemplate).filter(FollowUpTemplate.tenant_id == tenant_id).delete(synchronize_session=False)

    # Delete scheduled messages
    db.query(ScheduledMessage).filter(ScheduledMessage.tenant_id == tenant_id).delete(synchronize_session=False)

    # Delete WhatsApp contacts
    db.query(WhatsAppContact).filter(WhatsAppContact.tenant_id == tenant_id).delete(synchronize_session=False)

    # Delete billing records
    db.query(Invoice).filter(Invoice.tenant_id == tenant_id).delete(synchronize_session=False)

    # Delete calendar data
    db.query(CalendarIntegration).filter(CalendarIntegration.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(TenantAvailability).filter(TenantAvailability.tenant_id == tenant_id).delete(synchronize_session=False)

    # Delete support tickets
    db.query(SupportTicket).filter(SupportTicket.tenant_id == tenant_id).delete(synchronize_session=False)

    # Delete WhatsApp data
    db.query(WhatsAppAnalyticsEvent).filter(WhatsAppAnalyticsEvent.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(WhatsAppMetrics).filter(WhatsAppMetrics.tenant_id == tenant_id).delete(synchronize_session=False)
    wa_session_ids = [s.id for s in db.query(WhatsAppSession).filter(WhatsAppSession.tenant_id == tenant_id).all()]
    if wa_session_ids:
        db.query(WhatsAppMessage).filter(WhatsAppMessage.session_id.in_(wa_session_ids)).delete(synchronize_session=False)
    db.query(WhatsAppSession).filter(WhatsAppSession.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(WhatsAppConfiguration).filter(WhatsAppConfiguration.tenant_id == tenant_id).delete(synchronize_session=False)

    # Delete unanswered queries (must be before ChatSession due to FK)
    db.query(UnansweredQuery).filter(UnansweredQuery.tenant_id == tenant_id).delete(synchronize_session=False)

    # Delete chat messages and sessions
    session_ids = [s.id for s in db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id).all()]
    if session_ids:
        db.query(ChatMessage).filter(ChatMessage.session_id.in_(session_ids)).delete(synchronize_session=False)
    db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id).delete(synchronize_session=False)

    # Delete document chunks and documents
    db.query(DocumentChunk).filter(DocumentChunk.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(Document).filter(Document.tenant_id == tenant_id).delete(synchronize_session=False)

    # Vector cleanup
    try:
        VectorKnowledgeService.delete_all_vectors_for_tenant(db, tenant_id)
    except Exception:
        pass

    # Delete API keys and tenant users
    db.query(APIKey).filter(APIKey.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(TenantUser).filter(TenantUser.tenant_id == tenant_id).delete(synchronize_session=False)

    # Delete the tenant itself
    db.query(Tenant).filter(Tenant.id == tenant_id).delete(synchronize_session=False)

    db.commit()

    return {
        "status": "deleted",
        "message": f"Tenant '{tenant_name}' ({tenant_slug}) and all associated data permanently deleted",
    }


# ============ AGREEMENT MANAGEMENT ============

@router.post("/agreements")
async def create_agreement(
    agreement: AgreementCreate,
    db: Session = Depends(get_db),
):
    """Create service agreement for tenant"""
    tenant = db.query(Tenant).filter(Tenant.id == agreement.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    new_agreement = Agreement(
        tenant_id=agreement.tenant_id,
        agreement_name=agreement.agreement_name,
        agreement_type=agreement.agreement_type,
        start_date=agreement.start_date,
        end_date=agreement.end_date,
        terms=agreement.terms,
        created_by="system",  # Would be current_admin.id in production
    )
    
    db.add(new_agreement)
    db.commit()
    db.refresh(new_agreement)
    
    return {"message": "Agreement created", "agreement_id": new_agreement.id}


@router.get("/agreements/{tenant_id}")
async def get_tenant_agreements(
    tenant_id: str,
    db: Session = Depends(get_db),
):
    """Get all agreements for a tenant"""
    agreements = db.query(Agreement).filter(Agreement.tenant_id == tenant_id).all()
    
    return {
        "tenant_id": tenant_id,
        "total": len(agreements),
        "agreements": [
            {
                "id": a.id,
                "agreement_name": a.agreement_name,
                "agreement_type": a.agreement_type,
                "start_date": a.start_date,
                "end_date": a.end_date,
                "status": a.status,
                "created_at": a.created_at,
            }
            for a in agreements
        ]
    }


@router.put("/agreements/{agreement_id}")
async def update_agreement(
    agreement_id: str,
    update_data: AgreementUpdate,
    db: Session = Depends(get_db),
):
    """Update agreement"""
    agreement = db.query(Agreement).filter(Agreement.id == agreement_id).first()
    if not agreement:
        raise HTTPException(status_code=404, detail="Agreement not found")
    
    if update_data.agreement_name:
        agreement.agreement_name = update_data.agreement_name
    if update_data.status:
        agreement.status = update_data.status
    if update_data.terms:
        agreement.terms = update_data.terms
    if update_data.end_date:
        agreement.end_date = update_data.end_date
    
    db.commit()
    db.refresh(agreement)
    
    return {"message": "Agreement updated", "agreement_id": agreement.id}


@router.delete("/agreements/{agreement_id}")
async def delete_agreement(
    agreement_id: str,
    db: Session = Depends(get_db),
):
    """Delete agreement"""
    agreement = db.query(Agreement).filter(Agreement.id == agreement_id).first()
    if not agreement:
        raise HTTPException(status_code=404, detail="Agreement not found")
    
    db.delete(agreement)
    db.commit()
    
    return {"message": "Agreement deleted"}


# ============ MAINTENANCE TOOLS ============

@router.post("/maintenance/update-knowledge")
async def update_tenant_knowledge(
    tenant_id: str,
    products: list = None,
    services: list = None,
    faqs: list = None,
    db: Session = Depends(get_db),
):
    """Update tenant knowledge base"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Build new knowledge context
    knowledge = tenant.knowledge_context or {}
    
    if products is not None:
        knowledge["products"] = products
    if services is not None:
        knowledge["services"] = services
    if faqs is not None:
        knowledge["faqs"] = faqs
    
    tenant.knowledge_context = knowledge
    db.commit()
    db.refresh(tenant)
    
    return {"message": "Knowledge base updated", "tenant_id": tenant.id}


@router.get("/maintenance/tenant-health/{tenant_id}")
async def get_tenant_health(
    tenant_id: str,
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Get tenant health and maintenance status"""
    from sqlalchemy import func
    from app.models import Document, DocumentChunk

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    knowledge = tenant.knowledge_context if isinstance(tenant.knowledge_context, dict) else {}
    product_count = len(knowledge.get("products", []) if isinstance(knowledge.get("products"), list) else [])
    service_count = len(knowledge.get("services", []) if isinstance(knowledge.get("services"), list) else [])
    faq_count = len(knowledge.get("faqs", []) if isinstance(knowledge.get("faqs"), list) else [])

    # Crawled docs: tenant business docs excluding auto-learned pairs.
    crawled_docs = int(
        db.query(func.count(Document.id))
        .filter(
            Document.tenant_id == tenant_id,
            Document.is_active == True,
            Document.document_type != "learned",
        )
        .scalar()
        or 0
    )

    indexed_chunks = int(
        db.query(func.count(DocumentChunk.id))
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(
            Document.tenant_id == tenant_id,
            Document.is_active == True,
        )
        .scalar()
        or 0
    )

    indexed_docs = int(
        db.query(func.count(func.distinct(DocumentChunk.document_id)))
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(
            Document.tenant_id == tenant_id,
            Document.is_active == True,
        )
        .scalar()
        or 0
    )

    profile_signals = [tenant.industry, tenant.tone, tenant.compliance_mode, tenant.out_of_scope_mode]
    profile_completed = sum(1 for s in profile_signals if bool((s or "").strip()))
    persona_label = "Aligned" if profile_completed >= 3 else "Unknown"
    persona_details = (
        f"industry={tenant.industry or 'n/a'}, tone={tenant.tone or 'n/a'}, "
        f"compliance={tenant.compliance_mode or 'n/a'}, mode={tenant.out_of_scope_mode or 'n/a'}"
    )

    return {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "status": "healthy" if tenant.is_active else "inactive",
        "knowledge_items": {
            "products": product_count,
            "services": service_count,
            "faqs": faq_count,
        },
        "onboarding_stage": tenant.onboarding_stage or "unknown",
        "crawled_docs": crawled_docs,
        "indexed_docs": indexed_docs,
        "indexed_chunks": indexed_chunks,
        "persona": {
            "label": persona_label,
            "details": persona_details,
        },
        "model": tenant.model_name,
        "created_at": tenant.created_at,
    }


def _get_llm_live_status() -> dict:
    """Get live LLM provider status from health tracker."""
    try:
        tracker = get_provider_health_tracker()
        providers = tracker.get_all_health()

        providers_status = []
        for name, health in providers.items():
            providers_status.append({
                "name": name,
                "status": health.get("status", "unknown"),
                "total_calls": health.get("calls", 0),
                "success_rate": health.get("success_rate", 0),
                "avg_latency_ms": health.get("avg_latency_ms", 0),
                "consecutive_failures": health.get("consecutive_failures", 0),
            })

        return {
            "providers": providers_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(f"Failed to get LLM live status: {e}")
        return {"providers": [], "error": str(e)}


@router.get("/tenants/recent")
async def get_recent_tenants(
    days: int = Query(30, ge=1, le=90, description="Days to look back"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    db: Session = Depends(get_db)
):
    """Get recently registered tenants for sales/marketing follow-up."""
    since_date = datetime.now(timezone.utc) - timedelta(days=days)

    tenants = (
        db.query(Tenant)
        .filter(Tenant.created_at >= since_date)
        .order_by(Tenant.created_at.desc())
        .limit(limit)
        .all()
    )

    results = []
    for tenant in tenants:
        user_count = db.query(TenantUser).filter(TenantUser.tenant_id == tenant.id).count()
        api_keys = db.query(APIKey).filter(APIKey.tenant_id == tenant.id, APIKey.is_active == True).count()

        recent_sessions = (
            db.query(ChatSession)
            .filter(ChatSession.tenant_id == tenant.id)
            .order_by(ChatSession.created_at.desc())
            .first()
        )

        status = "new"
        if tenant.is_active:
            if recent_sessions and (datetime.now(timezone.utc) - recent_sessions.created_at).days < 7:
                status = "active"
            else:
                status = "inactive"
        else:
            status = "suspended"

        results.append({
            "tenant_id": tenant.id,
            "name": tenant.name,
            "domain": tenant.domain,
            "website_url": tenant.website_url,
            "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
            "status": status,
            "users_count": user_count,
            "api_keys_count": api_keys,
            "last_session_at": recent_sessions.created_at.isoformat() if recent_sessions and recent_sessions.created_at else None,
        })

    total_count = db.query(Tenant).filter(Tenant.created_at >= since_date).count()

    return {
        "tenants": results,
        "total_count": total_count,
        "period_days": days,
        "summary": {
            "new": len([t for t in results if t["status"] == "new"]),
            "active": len([t for t in results if t["status"] == "active"]),
            "inactive": len([t for t in results if t["status"] == "inactive"]),
            "suspended": len([t for t in results if t["status"] == "suspended"]),
        }
    }


@router.get("/maintenance/platform-overview")
async def get_platform_overview(db: Session = Depends(get_db)):
    """Platform owner maintenance overview: services, storage, and short-term trends."""
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    since_7d = now - timedelta(days=7)

    db_ready = True
    db_error = None
    db_latency_ms = 0
    try:
        start = datetime.now(timezone.utc)
        db.execute(text("SELECT 1"))
        db_latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    except Exception as exc:
        db_ready = False
        db_error = str(exc)

    db_size_bytes = 0
    db_size_pretty = "n/a"
    try:
        db_size_bytes = int(db.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)
        db_size_pretty = _format_bytes(db_size_bytes)
    except Exception:
        pass

    disk_root = shutil.disk_usage("/")
    disk_used_percent = round((disk_root.used / disk_root.total) * 100, 2) if disk_root.total else 0

    try:
        disk_app = shutil.disk_usage("/app")
    except Exception:
        disk_app = disk_root

    chat_messages_24h = db.query(ChatMessage).filter(ChatMessage.created_at >= since_24h).count()
    chat_messages_7d = db.query(ChatMessage).filter(ChatMessage.created_at >= since_7d).count()
    sessions_24h = db.query(ChatSession).filter(ChatSession.created_at >= since_24h).count()
    sessions_7d = db.query(ChatSession).filter(ChatSession.created_at >= since_7d).count()
    unanswered_24h = db.query(UnansweredQuery).filter(UnansweredQuery.created_at >= since_24h).count()
    unanswered_7d = db.query(UnansweredQuery).filter(UnansweredQuery.created_at >= since_7d).count()
    docs_active = db.query(Document).filter(Document.is_active == True).count()
    chunks_total = db.query(DocumentChunk).count()

    llm_failure_msgs_24h = 0
    llm_exhausted_msgs_24h = 0
    exhausted_provider_counts = Counter()
    provider_failure_counts = Counter()
    provider_last_failure_at = {}
    tenant_exhaustion_rollup = {}

    recent_assistant_msgs = db.query(ChatMessage).filter(
        ChatMessage.role == "assistant",
        ChatMessage.created_at >= since_24h,
    ).all()
    for msg in recent_assistant_msgs:
        metadata = msg.msg_metadata if isinstance(msg.msg_metadata, dict) else {}
        if not metadata.get("llm_failure"):
            continue

        llm_failure_msgs_24h += 1
        provider_failures = metadata.get("provider_failures") if isinstance(metadata.get("provider_failures"), list) else []
        exhausted_in_message = False
        exhausted_providers_in_message = set()
        for failure in provider_failures:
            if not isinstance(failure, dict):
                continue

            provider = (failure.get("provider") or "unknown").strip().lower() or "unknown"
            provider_failure_counts[provider] += 1
            if msg.created_at:
                last_seen = provider_last_failure_at.get(provider)
                if last_seen is None or msg.created_at > last_seen:
                    provider_last_failure_at[provider] = msg.created_at

            kind = (failure.get("error_kind") or "").strip().lower()
            if kind == "insufficient_credits":
                exhausted_provider_counts[provider] += 1
                exhausted_in_message = True
                exhausted_providers_in_message.add(provider)

        if exhausted_in_message:
            llm_exhausted_msgs_24h += 1
            tenant_bucket = tenant_exhaustion_rollup.get(msg.tenant_id)
            if tenant_bucket is None:
                tenant_name = "Unknown Tenant"
                tenant_row = db.query(Tenant).filter(Tenant.id == msg.tenant_id).first()
                if tenant_row and tenant_row.name:
                    tenant_name = tenant_row.name
                tenant_bucket = {
                    "tenant_id": msg.tenant_id,
                    "tenant_name": tenant_name,
                    "incidents": 0,
                    "provider_counts": Counter(),
                    "last_seen_at": None,
                }
                tenant_exhaustion_rollup[msg.tenant_id] = tenant_bucket

            tenant_bucket["incidents"] += 1
            for provider in exhausted_providers_in_message:
                tenant_bucket["provider_counts"][provider] += 1
            if msg.created_at and (
                tenant_bucket["last_seen_at"] is None or msg.created_at > tenant_bucket["last_seen_at"]
            ):
                tenant_bucket["last_seen_at"] = msg.created_at

    active_tenants = db.query(Tenant).filter(Tenant.is_active == True).count()
    total_tenants = db.query(Tenant).count()

    new_tenants_7d = db.query(Tenant).filter(Tenant.created_at >= since_7d).count()
    new_tenants_30d = db.query(Tenant).filter(Tenant.created_at >= (now - timedelta(days=30))).count()

    recent_tenants = (
        db.query(Tenant)
        .filter(Tenant.created_at >= since_7d)
        .order_by(Tenant.created_at.desc())
        .all()
    )

    recent_tenant_list = []
    for tenant in recent_tenants[:10]:
        recent_tenant_list.append({
            "id": tenant.id,
            "name": tenant.name,
            "domain": tenant.domain,
            "website_url": tenant.website_url,
            "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
            "is_active": tenant.is_active,
        })

    # Thresholds for owner-level monitoring.
    thresholds = {
        "disk_warning_percent": 80.0,
        "disk_critical_percent": 90.0,
        "db_latency_warning_ms": 100,
        "db_latency_critical_ms": 250,
        "unanswered_spike_warning_multiplier": 2.0,
        "unanswered_spike_critical_multiplier": 3.0,
        "self_learning_low_conf_days_warning": 3,
        "self_learning_low_conf_hits_per_day_warning": 2,
        "self_learning_low_conf_days_critical": 3,
        "self_learning_low_conf_hits_per_day_critical": 4,
    }

    alerts = []

    if disk_used_percent >= thresholds["disk_critical_percent"]:
        alerts.append({
            "severity": "critical",
            "code": "disk_usage",
            "message": f"Disk usage is at {disk_used_percent}% (critical)",
        })
    elif disk_used_percent >= thresholds["disk_warning_percent"]:
        alerts.append({
            "severity": "warning",
            "code": "disk_usage",
            "message": f"Disk usage is at {disk_used_percent}% (warning)",
        })

    if db_ready:
        if db_latency_ms >= thresholds["db_latency_critical_ms"]:
            alerts.append({
                "severity": "critical",
                "code": "db_latency",
                "message": f"Database latency is {db_latency_ms} ms (critical)",
            })
        elif db_latency_ms >= thresholds["db_latency_warning_ms"]:
            alerts.append({
                "severity": "warning",
                "code": "db_latency",
                "message": f"Database latency is {db_latency_ms} ms (warning)",
            })
    else:
        alerts.append({
            "severity": "critical",
            "code": "database_down",
            "message": "Database health check failed",
        })

    unanswered_daily_avg_7d = round(unanswered_7d / 7.0, 2) if unanswered_7d else 0.0
    unanswered_spike_ratio = round((unanswered_24h / unanswered_daily_avg_7d), 2) if unanswered_daily_avg_7d > 0 else 0.0

    if unanswered_daily_avg_7d > 0 and unanswered_spike_ratio >= thresholds["unanswered_spike_critical_multiplier"]:
        alerts.append({
            "severity": "critical",
            "code": "unanswered_spike",
            "message": f"Unanswered queries spiked: {unanswered_24h} in 24h vs {unanswered_daily_avg_7d}/day baseline",
        })
    elif unanswered_daily_avg_7d > 0 and unanswered_spike_ratio >= thresholds["unanswered_spike_warning_multiplier"]:
        alerts.append({
            "severity": "warning",
            "code": "unanswered_spike",
            "message": f"Unanswered queries increased: {unanswered_24h} in 24h vs {unanswered_daily_avg_7d}/day baseline",
        })

    if llm_exhausted_msgs_24h > 0:
        provider_summary = ", ".join(
            [f"{provider}: {count}" for provider, count in exhausted_provider_counts.items()]
        ) or "unknown provider"
        alerts.append({
            "severity": "critical" if llm_exhausted_msgs_24h >= 3 else "warning",
            "code": "llm_provider_credit_exhaustion",
            "message": (
                f"LLM credit exhaustion detected in {llm_exhausted_msgs_24h} conversation(s) during the last 24h "
                f"({provider_summary})."
            ),
        })
    elif llm_failure_msgs_24h > 0:
        alerts.append({
            "severity": "warning",
            "code": "llm_provider_failures",
            "message": f"LLM provider failures detected in {llm_failure_msgs_24h} conversation(s) during the last 24h.",
        })

    provider_names = set(provider_failure_counts.keys()) | set(exhausted_provider_counts.keys())
    llm_provider_health = []
    for provider in sorted(provider_names):
        total_failures = int(provider_failure_counts.get(provider, 0))
        exhausted = int(exhausted_provider_counts.get(provider, 0))
        if exhausted > 0:
            status = "critical"
        elif total_failures >= 3:
            status = "warning"
        else:
            status = "healthy"

        last_failure_at = provider_last_failure_at.get(provider)
        llm_provider_health.append(
            {
                "provider": provider,
                "status": status,
                "failures_24h": total_failures,
                "credit_exhaustion_24h": exhausted,
                "last_failure_at": last_failure_at.isoformat() if last_failure_at else None,
            }
        )

    llm_exhaustion_by_tenant_24h = []
    for _, row in tenant_exhaustion_rollup.items():
        provider_counts_dict = dict(row["provider_counts"])
        provider_summary = ", ".join([f"{name}: {count}" for name, count in provider_counts_dict.items()]) or "--"
        llm_exhaustion_by_tenant_24h.append(
            {
                "tenant_id": row["tenant_id"],
                "tenant_name": row["tenant_name"],
                "incidents": row["incidents"],
                "provider_counts": provider_counts_dict,
                "provider_summary": provider_summary,
                "last_seen_at": row["last_seen_at"].isoformat() if row["last_seen_at"] else None,
            }
        )

    llm_exhaustion_by_tenant_24h.sort(key=lambda x: x.get("incidents", 0), reverse=True)

    # Enterprise alert: repeated low-confidence/no-positive-feedback trend by tenant (3+ days).
    from app.services.self_learning import CONFIDENCE_THRESHOLD, MIN_RESPONSE_WORDS

    since_3d = now - timedelta(days=3)
    risk_tenants = []
    active_tenant_rows = db.query(Tenant).filter(Tenant.is_active == True).all()
    for tenant in active_tenant_rows:
        day_counts = _compute_self_learning_low_conf_days(
            db=db,
            tenant_id=tenant.id,
            since_dt=since_3d,
            confidence_threshold=CONFIDENCE_THRESHOLD,
            min_response_words=MIN_RESPONSE_WORDS,
        )
        if not day_counts:
            continue

        days_warning = sum(
            1 for c in day_counts.values() if c >= thresholds["self_learning_low_conf_hits_per_day_warning"]
        )
        days_critical = sum(
            1 for c in day_counts.values() if c >= thresholds["self_learning_low_conf_hits_per_day_critical"]
        )

        if days_critical >= thresholds["self_learning_low_conf_days_critical"]:
            alerts.append({
                "severity": "critical",
                "code": "self_learning_low_confidence_trend",
                "message": (
                    f"{tenant.name}: repeated low-confidence/no-positive-feedback responses across "
                    f"{days_critical} day(s)."
                ),
            })
            risk_tenants.append({
                "tenant_id": tenant.id,
                "tenant_name": tenant.name,
                "severity": "critical",
                "days_triggered": days_critical,
                "daily_counts": day_counts,
            })
        elif days_warning >= thresholds["self_learning_low_conf_days_warning"]:
            alerts.append({
                "severity": "warning",
                "code": "self_learning_low_confidence_trend",
                "message": (
                    f"{tenant.name}: persistent low-confidence/no-positive-feedback trend across "
                    f"{days_warning} day(s)."
                ),
            })
            risk_tenants.append({
                "tenant_id": tenant.id,
                "tenant_name": tenant.name,
                "severity": "warning",
                "days_triggered": days_warning,
                "daily_counts": day_counts,
            })

    return {
        "generated_at": now.isoformat(),
        "services": {
            "api": {"status": "up"},
            "database": {
                "status": "up" if db_ready else "down",
                "latency_ms": db_latency_ms,
                "error": db_error,
            },
        },
        "storage": {
            "database": {
                "size_bytes": db_size_bytes,
                "size_pretty": db_size_pretty,
            },
            "disk_root": {
                "total_bytes": disk_root.total,
                "used_bytes": disk_root.used,
                "free_bytes": disk_root.free,
                "used_percent": disk_used_percent,
                "used_pretty": _format_bytes(disk_root.used),
                "total_pretty": _format_bytes(disk_root.total),
                "free_pretty": _format_bytes(disk_root.free),
            },
            "disk_app": {
                "used_pretty": _format_bytes(disk_app.used),
                "total_pretty": _format_bytes(disk_app.total),
                "free_pretty": _format_bytes(disk_app.free),
            },
        },
        "tenants": {
            "active": active_tenants,
            "total": total_tenants,
        },
        "trends": {
            "messages_24h": chat_messages_24h,
            "messages_7d": chat_messages_7d,
            "sessions_24h": sessions_24h,
            "sessions_7d": sessions_7d,
            "unanswered_24h": unanswered_24h,
            "unanswered_7d": unanswered_7d,
            "unanswered_daily_avg_7d": unanswered_daily_avg_7d,
            "unanswered_spike_ratio": unanswered_spike_ratio,
            "llm_failures_24h": llm_failure_msgs_24h,
            "llm_exhausted_messages_24h": llm_exhausted_msgs_24h,
            "llm_exhausted_provider_counts": dict(exhausted_provider_counts),
            "active_documents": docs_active,
            "vector_chunks": chunks_total,
            "self_learning_risk_tenants": risk_tenants,
        },
        "thresholds": thresholds,
        "alerts": alerts,
        "llm_provider_health": llm_provider_health,
        "llm_exhaustion_by_tenant_24h": llm_exhaustion_by_tenant_24h,
        "canary_monitor": get_canary_state(),
        "llm_config": {
            "routing_mode": os.getenv("LLM_ROUTING_MODE", "fallback"),
            "primary": os.getenv("LLM_PRIMARY", "groq"),
            "secondary": os.getenv("LLM_SECONDARY", "gemini"),
            "tertiary": os.getenv("LLM_TERTIARY", "openrouter"),
            "groq_model": os.getenv("LLM_GROQ_MODEL", "llama-3.3-70b-versatile"),
            "gemini_model": os.getenv("LLM_GEMINI_MODEL", "gemini-2.5-flash-lite"),
        },
        "llm_live_status": _get_llm_live_status(),
        "llm_provider_stats": get_llm_stats(),
        "recent_registrations": {
            "new_7d": new_tenants_7d,
            "new_30d": new_tenants_30d,
            "total_active": active_tenants,
            "tenants": recent_tenant_list,
        },
    }


@router.get("/maintenance/canary/status")
async def canary_status():
    """Get current canary monitor status and recent run history."""
    return get_canary_state()


@router.post("/maintenance/canary/activate")
async def canary_activate():
    """Enable scheduled canary checks."""
    state = set_canary_enabled(True)
    return {
        "status": "enabled",
        "message": "Canary monitor enabled",
        "state": state,
    }


@router.post("/maintenance/canary/deactivate")
async def canary_deactivate():
    """Disable scheduled canary checks."""
    state = set_canary_enabled(False)
    return {
        "status": "disabled",
        "message": "Canary monitor disabled",
        "state": state,
    }


@router.post("/maintenance/canary/run")
async def canary_run_now():
    """Run one ad-hoc canary check immediately."""
    state = await asyncio.to_thread(run_canary_check, "adhoc")
    return {
        "status": "success",
        "message": "Canary check executed",
        "state": state,
    }


# ============ CONVERSATION VIEWING ============

@router.get("/conversations/{tenant_id}")
async def get_tenant_conversations(
    tenant_id: str,
    limit: int = Query(default=25, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Get conversations for a tenant – optimised with batch queries (no N+1)"""
    from app.models import ChatSession, ChatMessage
    from sqlalchemy import func as sqlfunc

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Total sessions count (1 query)
    total = db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id).count()

    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.tenant_id == tenant_id)
        .order_by(ChatSession.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    if not sessions:
        return {
            "tenant_id": tenant_id,
            "total": total,
            "limit": limit,
            "offset": offset,
            "conversations": [],
        }

    session_ids = [s.id for s in sessions]

    # Batch: message counts per session (1 query instead of N)
    count_rows = (
        db.query(ChatMessage.session_id, sqlfunc.count(ChatMessage.id).label("cnt"))
        .filter(ChatMessage.session_id.in_(session_ids))
        .group_by(ChatMessage.session_id)
        .all()
    )
    count_map = {r.session_id: r.cnt for r in count_rows}

    # Batch: first user message per session (1 query instead of N)
    first_user_rows = (
        db.query(ChatMessage.session_id, ChatMessage.content)
        .filter(
            ChatMessage.session_id.in_(session_ids),
            ChatMessage.role == "user",
        )
        .order_by(ChatMessage.session_id, ChatMessage.created_at.asc())
        .all()
    )
    first_user_map: dict = {}
    for r in first_user_rows:
        if r.session_id not in first_user_map:
            first_user_map[r.session_id] = r.content

    # Batch: last message timestamp per session (1 query instead of N)
    last_msg_rows = (
        db.query(
            ChatMessage.session_id,
            sqlfunc.max(ChatMessage.created_at).label("last_at"),
        )
        .filter(ChatMessage.session_id.in_(session_ids))
        .group_by(ChatMessage.session_id)
        .all()
    )
    last_msg_map = {r.session_id: r.last_at for r in last_msg_rows}

    conversations = []
    for session in sessions:
        last_at = last_msg_map.get(session.id)
        conversations.append(
            {
                "session_id": session.id,
                "user_id": session.user_id,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "message_count": count_map.get(session.id, 0),
                "first_query": first_user_map.get(session.id),
                "last_message_at": last_at.isoformat() if last_at else None,
            }
        )

    return {
        "tenant_id": tenant_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "conversations": conversations,
    }


@router.get("/conversations/session/{session_id}")
async def get_conversation_transcript(
    session_id: str,
    db: Session = Depends(get_db),
):
    """Get full conversation transcript with all messages"""
    from app.models import ChatSession, ChatMessage
    
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at).all()
    
    return {
        "session_id": session.id,
        "tenant_id": session.tenant_id,
        "user_id": session.user_id,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "message_count": len(messages),
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "model_used": msg.model_used,
                "latency_ms": msg.latency_ms,
                "tokens_used": msg.tokens_used,
                "provider": (msg.msg_metadata or {}).get("provider") if isinstance(msg.msg_metadata, dict) else None,
                "created_at": msg.created_at.isoformat() if msg.created_at else None
            }
            for msg in messages
        ]
    }


# ============ UNANSWERED QUERY TRACKING ============

@router.get("/unanswered-queries/{tenant_id}")
async def get_unanswered_queries(
    tenant_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    resolved_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """Get unanswered queries for a tenant"""
    from app.models import UnansweredQuery

    stopwords = {
        "a", "an", "the", "is", "are", "am", "to", "for", "of", "in", "on", "at",
        "what", "which", "how", "can", "could", "would", "please", "i", "we", "you",
        "your", "my", "our", "all", "do", "does", "did", "me", "about"
    }
    token_alias = {
        "services": "service",
        "offered": "service",
        "offer": "service",
        "offering": "service",
        "products": "product",
        "pricing": "price",
        "cost": "price",
        "costs": "price",
        "charges": "price",
        "fees": "price",
    }

    def _cluster_key(text: str) -> str:
        tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
        filtered = [token_alias.get(t, t) for t in tokens if t not in stopwords]
        if not filtered:
            return ""
        return " ".join(sorted(set(filtered))[:6])
    
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    query_obj = db.query(UnansweredQuery).filter(
        UnansweredQuery.tenant_id == tenant_id
    )
    
    if not resolved_only:
        query_obj = query_obj.filter(UnansweredQuery.is_resolved == False)
    
    queries = query_obj.order_by(UnansweredQuery.created_at.desc()).limit(limit).all()
    
    serialized_queries = [
        {
            "id": q.id,
            "query": q.query,
            "response": q.response,
            "confidence_score": q.confidence_score,
            "reason": q.reason,
            "is_resolved": q.is_resolved,
            "is_used_for_training": q.is_used_for_training,
            "created_at": q.created_at.isoformat() if q.created_at else None
        }
        for q in queries
    ]

    clusters_map = {}
    for q in serialized_queries:
        key = _cluster_key(q.get("query") or "")
        if not key:
            continue
        bucket = clusters_map.get(key)
        if not bucket:
            bucket = {
                "cluster_key": key,
                "count": 0,
                "sample_query": q.get("query") or "",
                "avg_confidence": 0.0,
                "latest_created_at": q.get("created_at"),
                "query_ids": [],
            }
            clusters_map[key] = bucket
        bucket["count"] += 1
        bucket["query_ids"].append(q.get("id"))
        conf = float(q.get("confidence_score") or 0.0)
        bucket["avg_confidence"] += conf
        if (q.get("created_at") or "") > (bucket.get("latest_created_at") or ""):
            bucket["latest_created_at"] = q.get("created_at")

    clusters = []
    for c in clusters_map.values():
        c["avg_confidence"] = round(c["avg_confidence"] / max(1, c["count"]), 2)
        clusters.append(c)
    clusters.sort(key=lambda c: (-c.get("count", 0), c.get("avg_confidence", 1.0)))

    return {
        "tenant_id": tenant_id,
        "total": len(queries),
        "queries": serialized_queries,
        "clusters": clusters[:12],
    }


@router.patch("/unanswered-queries/{query_id}/resolve")
async def resolve_unanswered_query(
    query_id: str,
    resolution_notes: str = None,
    db: Session = Depends(get_db),
):
    """Mark unanswered query as resolved"""
    from app.models import UnansweredQuery
    
    query_obj = db.query(UnansweredQuery).filter(UnansweredQuery.id == query_id).first()
    if not query_obj:
        raise HTTPException(status_code=404, detail="Query not found")
    
    query_obj.is_resolved = True
    query_obj.resolution_notes = resolution_notes
    db.commit()
    
    return {"id": query_id, "status": "resolved"}


@router.post("/unanswered-queries/{query_id}/mark-for-training")
async def mark_query_for_training(
    query_id: str,
    db: Session = Depends(get_db),
):
    """Mark unanswered query for LLM fine-tuning"""
    from app.models import UnansweredQuery
    
    query_obj = db.query(UnansweredQuery).filter(UnansweredQuery.id == query_id).first()
    if not query_obj:
        raise HTTPException(status_code=404, detail="Query not found")
    
    query_obj.is_used_for_training = True
    db.commit()
    
    return {"id": query_id, "status": "marked_for_training"}


@router.post("/unanswered-queries/scan")
async def trigger_manual_scan(
    days_lookback: int = Query(7, ge=1, le=30, description="Days to look back"),
    confidence_threshold: float = Query(0.7, ge=0.0, le=1.0, description="Confidence threshold"),
    db: Session = Depends(get_db),
):
    """
    Manually trigger a scan of conversations to populate unanswered queries.
    This is useful for immediate analysis without waiting for the scheduled job.
    """
    from app.services.query_analyzer import scan_and_populate_unanswered_queries
    
    try:
        stats = await scan_and_populate_unanswered_queries(
            days_lookback=days_lookback,
            confidence_threshold=confidence_threshold,
            db=db
        )
        
        return {
            "status": "success",
            "message": f"Scan completed successfully",
            "stats": stats,
            "parameters": {
                "days_lookback": days_lookback,
                "confidence_threshold": confidence_threshold
            }
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Scan failed: {str(e)}"
        )


# ============ SELF-LEARNING ============

@router.post("/self-learning/run")
async def trigger_self_learning(db: Session = Depends(get_db)):
    """
    Manually trigger the self-learning job.
    Reads recent conversations, extracts high-quality Q&A pairs, and
    indexes them into each tenant's vector knowledge base.
    """
    from app.services.self_learning import run_daily_learning_job
    try:
        stats = run_daily_learning_job()
        return {"status": "success", "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Self-learning job failed: {str(e)}")


@router.get("/self-learning/learned-documents")
async def list_learned_documents(
    tenant_id: str = Query(None, description="Filter by tenant ID"),
    db: Session = Depends(get_db),
):
    """
    List all auto-learned documents across tenants (or for a specific tenant).
    Shows what the system has learned from real conversations.
    """
    from app.models import Document, Tenant

    query = db.query(Document).filter(Document.document_type == "learned", Document.is_active == True)
    if tenant_id:
        query = query.filter(Document.tenant_id == tenant_id)

    docs = query.order_by(Document.created_at.desc()).limit(200).all()

    tenant_names: dict = {}
    for doc in docs:
        if doc.tenant_id not in tenant_names:
            t = db.query(Tenant).filter(Tenant.id == doc.tenant_id).first()
            tenant_names[doc.tenant_id] = t.name if t else doc.tenant_id

    return [
        {
            "id": doc.id,
            "tenant_id": doc.tenant_id,
            "tenant_name": tenant_names.get(doc.tenant_id, doc.tenant_id),
            "name": doc.name,
            "content_preview": (doc.content or "")[:300],
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        }
        for doc in docs
    ]


@router.get("/self-learning/stats")
async def self_learning_stats(db: Session = Depends(get_db)):
    """Summary of how many Q&A pairs have been auto-learned per tenant."""
    from sqlalchemy import func
    from app.models import Document, Tenant

    rows = (
        db.query(Document.tenant_id, func.count(Document.id).label("count"))
        .filter(Document.document_type == "learned", Document.is_active == True)
        .group_by(Document.tenant_id)
        .all()
    )

    result = []
    for tenant_id, count in rows:
        t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        # Detect repeated answers: same answer text used for different queries (generic fallback risk)
        docs = (
            db.query(Document)
            .filter(
                Document.tenant_id == tenant_id,
                Document.document_type == "learned",
                Document.is_active == True,
            )
            .all()
        )
        answer_freq: dict = {}
        for doc in docs:
            content = doc.content or ""
            if "\nA:" in content:
                answer_text = content.split("\nA:", 1)[1].strip()[:200].lower()
                answer_freq[answer_text] = answer_freq.get(answer_text, 0) + 1
        repeated_answer_count = sum(1 for v in answer_freq.values() if v > 1)
        result.append({
            "tenant_id": tenant_id,
            "tenant_name": t.name if t else tenant_id,
            "learned_documents": count,
            "repeated_answer_count": repeated_answer_count,
        })

    return {
        "tenants": result,
        "total_learned": sum(r["learned_documents"] for r in result),
        "total_repeated_answers": sum(r["repeated_answer_count"] for r in result),
    }


# ============ DOCUMENT MANAGEMENT & RAG ============

@router.post("/documents/{tenant_id}/upload")
async def upload_document(
    tenant_id: str,
    file: UploadFile = File(None),
    name: str = Form(None),
    content: str = Form(None),
    document_type: str = Form("document"),
    category: str = Form(None),
    db: Session = Depends(get_db),
):
    """Upload document to knowledge base for RAG — supports .txt, .pdf, .docx, .md"""
    from app.models import Document
    from app.services.vector_knowledge import VectorKnowledgeService

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Get content from file or text
    if file:
        file_bytes = await file.read()
        doc_content = parse_document(file.filename, file_bytes)
        doc_name = name or file.filename
    elif content:
        doc_content = content
        doc_name = name or f"Document_{datetime.now().isoformat()}"
    else:
        raise HTTPException(status_code=400, detail="Either file or content is required")

    if not doc_content.strip():
        raise HTTPException(status_code=422, detail="Document appears to be empty or could not be parsed")

    document = Document(
        tenant_id=tenant_id,
        name=doc_name,
        content=doc_content,
        document_type=document_type,
        category=category
    )

    db.add(document)
    db.flush()
    chunks_indexed = VectorKnowledgeService.index_document(db, document)
    db.commit()
    db.refresh(document)

    return {
        "id": document.id,
        "name": document.name,
        "tenant_id": document.tenant_id,
        "status": "uploaded",
        "chunks_indexed": chunks_indexed,
        "created_at": document.created_at.isoformat() if document.created_at else None
    }


@router.get("/documents/{tenant_id}")
async def get_tenant_documents(
    tenant_id: str,
    active_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    """Get all documents for a tenant"""
    from app.models import Document
    
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    query_obj = db.query(Document).filter(Document.tenant_id == tenant_id)
    
    if active_only:
        query_obj = query_obj.filter(Document.is_active == True)
    
    documents = query_obj.all()
    
    return {
        "tenant_id": tenant_id,
        "total": len(documents),
        "documents": [
            {
                "id": doc.id,
                "name": doc.name,
                "document_type": doc.document_type,
                "category": doc.category,
                "is_processed": doc.is_processed,
                "is_active": doc.is_active,
                "created_at": doc.created_at.isoformat() if doc.created_at else None
            }
            for doc in documents
        ]
    }


@router.get("/documents/{tenant_id}/{document_id}")
async def get_document_detail(
    tenant_id: str,
    document_id: str,
    db: Session = Depends(get_db),
):
    """Get a specific document with full content"""
    from app.models import Document
    
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.tenant_id == tenant_id
    ).first()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return {
        "id": doc.id,
        "name": doc.name,
        "content": doc.content,
        "document_type": doc.document_type,
        "category": doc.category,
        "is_processed": doc.is_processed,
        "is_active": doc.is_active,
        "created_at": doc.created_at.isoformat() if doc.created_at else None
    }


@router.delete("/documents/{tenant_id}/{document_id}")
async def delete_document(
    tenant_id: str,
    document_id: str,
    db: Session = Depends(get_db),
):
    """Delete (soft delete) a document"""
    from app.models import Document
    
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.tenant_id == tenant_id
    ).first()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc.is_active = False
    db.commit()
    
    return {"status": "deleted", "document_id": document_id}


@router.post("/documents/{tenant_id}/{document_id}/process")
async def process_document_rag(
    tenant_id: str,
    document_id: str,
    db: Session = Depends(get_db),
):
    """Process one document into vector chunks and mark it ready for RAG retrieval."""
    from app.models import Document
    from app.services.vector_knowledge import VectorKnowledgeService
    
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.tenant_id == tenant_id
    ).first()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    chunks_indexed = VectorKnowledgeService.index_document(db, doc)
    db.commit()

    return {
        "status": "processed",
        "document_id": document_id,
        "chunks_indexed": chunks_indexed,
    }


@router.get("/documents-search/{tenant_id}")
async def search_tenant_documents(
    tenant_id: str,
    q: str = Query(..., min_length=2, description="Search query"),
    db: Session = Depends(get_db),
):
    """Hybrid document search endpoint (semantic + keyword)."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    results = DocumentService.search_documents(db=db, tenant_id=tenant_id, query=q)
    return {
        "tenant_id": tenant_id,
        "query": q,
        "total": len(results),
        "results": results,
    }


@router.get("/rag-profile/{tenant_id}")
async def get_tenant_rag_profile(
    tenant_id: str,
    db: Session = Depends(get_db),
):
    """Get effective tenant RAG profile used for chunking/indexing."""
    from app.services.vector_knowledge import VectorKnowledgeService

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    effective = VectorKnowledgeService.get_tenant_rag_config(db, tenant_id)
    knowledge = tenant.knowledge_context if isinstance(tenant.knowledge_context, dict) else {}
    stored = knowledge.get("rag_profile") if isinstance(knowledge.get("rag_profile"), dict) else {}

    return {
        "tenant_id": tenant_id,
        "stored": {
            "chunk_words": stored.get("chunk_words"),
            "chunk_overlap": stored.get("chunk_overlap"),
            "min_heading_chunk_words": stored.get("min_heading_chunk_words"),
        },
        "effective": effective,
        "limits": {
            "chunk_words": {"min": VectorKnowledgeService.CHUNK_WORDS_MIN, "max": VectorKnowledgeService.CHUNK_WORDS_MAX},
            "chunk_overlap": {"min": VectorKnowledgeService.CHUNK_OVERLAP_MIN, "max": VectorKnowledgeService.CHUNK_OVERLAP_MAX},
            "min_heading_chunk_words": {"min": VectorKnowledgeService.MIN_HEADING_WORDS_MIN, "max": VectorKnowledgeService.MIN_HEADING_WORDS_MAX},
        },
    }


@router.put("/rag-profile/{tenant_id}")
async def update_tenant_rag_profile(
    tenant_id: str,
    payload: TenantRagProfileUpdate,
    db: Session = Depends(get_db),
):
    """Update tenant RAG profile for chunking behavior on future indexing/reindexing."""
    from app.services.vector_knowledge import VectorKnowledgeService

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Clamp with the same bounds used by vector service for consistency.
    chunk_words = VectorKnowledgeService._clamp_int(
        payload.chunk_words,
        VectorKnowledgeService.CHUNK_WORDS,
        VectorKnowledgeService.CHUNK_WORDS_MIN,
        VectorKnowledgeService.CHUNK_WORDS_MAX,
    )
    chunk_overlap = VectorKnowledgeService._clamp_int(
        payload.chunk_overlap,
        VectorKnowledgeService.CHUNK_OVERLAP,
        VectorKnowledgeService.CHUNK_OVERLAP_MIN,
        VectorKnowledgeService.CHUNK_OVERLAP_MAX,
    )
    min_heading_chunk_words = VectorKnowledgeService._clamp_int(
        payload.min_heading_chunk_words,
        VectorKnowledgeService.MIN_HEADING_CHUNK_WORDS,
        VectorKnowledgeService.MIN_HEADING_WORDS_MIN,
        VectorKnowledgeService.MIN_HEADING_WORDS_MAX,
    )

    chunk_overlap = min(chunk_overlap, max(1, chunk_words - 5))

    knowledge = dict(tenant.knowledge_context) if isinstance(tenant.knowledge_context, dict) else {}
    knowledge["rag_profile"] = {
        "chunk_words": chunk_words,
        "chunk_overlap": chunk_overlap,
        "min_heading_chunk_words": min_heading_chunk_words,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    tenant.knowledge_context = knowledge
    db.commit()

    effective = VectorKnowledgeService.get_tenant_rag_config(db, tenant_id)
    return {
        "status": "updated",
        "tenant_id": tenant_id,
        "effective": effective,
        "message": "RAG profile saved. Reindex vectors to apply to existing documents.",
    }


# ============ WEBSITE CRAWL (Admin-triggered) ============


from fastapi import Body

@router.post("/crawl/{tenant_id}")
async def admin_trigger_crawl(
    tenant_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    website_url: Optional[str] = None,
    include_footer: bool = Body(False, embed=True),
):
    """Trigger a website crawl for a tenant (admin panel action)."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    url = website_url or tenant.website_url
    if not url:
        raise HTTPException(status_code=422, detail="No website URL configured for this tenant")
    
    # Security: Validate URL matches tenant's domain to prevent crawling wrong sites
    from urllib.parse import urlparse
    parsed = urlparse(url)
    crawl_domain = parsed.netloc.lower().replace("www.", "")
    
    # Extract just the domain name from tenant.domain (handle full URLs like "https://example.com/")
    tenant_parsed = urlparse(tenant.domain or "")
    tenant_domain = (tenant_parsed.netloc or tenant_parsed.path or tenant.domain or "").lower().replace("www.", "")
    
    if crawl_domain != tenant_domain:
        raise HTTPException(
            status_code=422, 
            detail=f"URL domain '{crawl_domain}' does not match tenant domain '{tenant_domain}'. Cannot crawl external sites."
        )

    WebsiteCrawlerService.queue_crawl(background_tasks, tenant.id, url, include_footer=include_footer)
    return {
        "status": "crawl_queued",
        "tenant_id": tenant_id,
        "website_url": url,
        "include_footer": include_footer,
        "message": "Crawl started in background. Check crawl-status for progress.",
    }


@router.get("/crawl-status/{tenant_id}")
async def admin_get_crawl_status(
    tenant_id: str,
    db: Session = Depends(get_db),
):
    """Get current website crawl status for a tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return WebsiteCrawlerService.get_crawl_status(db, tenant_id)


# ── Onboarding Request API ─────────────────────────────────────────

class OnboardingSubmit(BaseModel):
    business_name: str
    contact_name: str = ""
    contact_email: str
    contact_phone: str = ""
    website_url: str = ""
    industry: str = "services"
    services_list: str = ""
    faqs: str = ""
    welcome_message: str = ""
    business_hours: str = ""
    want_chat_widget: bool = True
    want_whatsapp: bool = False
    wa_phone_number_id: str = ""
    wa_business_account_id: str = ""
    wa_access_token: str = ""


class VerifyOTP(BaseModel):
    request_id: str
    otp: str


import random
from datetime import datetime, timedelta, timezone
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr


def _send_otp_email(to_email: str, otp: str, business_name: str):
    """Send OTP verification email. Falls back to console log if SMTP not configured."""
    if not settings.smtp_host or not settings.smtp_user:
        logger.warning(f"[OTP Email] SMTP not configured. OTP for {to_email}: {otp}")
        return False
    try:
        msg = MIMEText(
            f"""Hi {business_name},

Thank you for your interest in SCUBE AI Chatbot.

Your verification code is: {otp}

Please enter this 6-digit code on the onboarding form to complete your submission.
This code will expire in 15 minutes.

If you did not request this, please ignore this email.

Best regards,
SCUBE Infotech AI Team
"""
        )
        msg['Subject'] = f'Your SCUBE AI Onboarding Verification Code: {otp}'
        msg['From'] = formataddr((settings.smtp_from_name, settings.smtp_from_email))
        msg['To'] = to_email

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_tls:
                server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        logger.info(f"[OTP Email] Sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"[OTP Email] Failed to send to {to_email}: {e}")
        return False


@router.post("/onboarding-requests", response_model=dict)
def create_onboarding_request(
    payload: OnboardingSubmit,
    db: Session = Depends(get_db),
):
    """Step 1: Public endpoint — submit onboarding request + receive OTP via email."""
    otp = f"{random.randint(100000, 999999)}"
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)

    req = OnboardingRequest(
        business_name=payload.business_name,
        contact_name=payload.contact_name,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
        website_url=payload.website_url,
        industry=payload.industry,
        services_list=payload.services_list,
        faqs=payload.faqs,
        welcome_message=payload.welcome_message,
        business_hours=payload.business_hours,
        want_chat_widget=payload.want_chat_widget,
        want_whatsapp=payload.want_whatsapp,
        wa_phone_number_id=payload.wa_phone_number_id or None,
        wa_business_account_id=payload.wa_business_account_id or None,
        wa_access_token=payload.wa_access_token or None,
        status="awaiting_otp",
        otp_code=otp,
        otp_verified=False,
        otp_expires_at=expires,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    email_sent = _send_otp_email(payload.contact_email, otp, payload.business_name)
    logger.info(f"[Onboarding] OTP request from {payload.business_name} <{payload.contact_email}> — OTP: {otp}")

    return {
        "status": "awaiting_otp",
        "request_id": req.id,
        "email_sent": email_sent,
        "message": "A 6-digit verification code has been sent to your email. Please enter it below to confirm."
    }


@router.post("/onboarding-requests/verify-otp", response_model=dict)
def verify_onboarding_otp(
    payload: VerifyOTP,
    db: Session = Depends(get_db),
):
    """Step 2: Verify OTP → move request to pending status."""
    req = db.query(OnboardingRequest).filter(OnboardingRequest.id == payload.request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != "awaiting_otp":
        raise HTTPException(status_code=400, detail="This request has already been processed")
    if req.otp_expires_at:
        # Handle naive vs offset-aware datetime comparison
        expires = req.otp_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires:
            raise HTTPException(status_code=400, detail="Verification code has expired. Please submit again.")
    if req.otp_code != payload.otp.strip():
        raise HTTPException(status_code=400, detail="Invalid verification code. Please try again.")

    req.otp_verified = True
    req.status = "pending"
    db.commit()
    logger.info(f"[Onboarding] OTP verified for {req.business_name} ({req.contact_email})")
    return {
        "status": "verified",
        "request_id": req.id,
        "message": "Email verified! Your onboarding request is now submitted and our team will review it shortly."
    }


@router.get("/onboarding-requests")
def list_onboarding_requests(
    status: str = Query("pending", description="Filter by status: pending, approved, rejected, all"),
    db: Session = Depends(get_db),
):
    """Admin-only — list onboarding requests."""
    q = db.query(OnboardingRequest)
    if status != "all":
        q = q.filter(OnboardingRequest.status == status)
    else:
        # Never show awaiting_otp in admin list — they're not real submissions yet
        q = q.filter(OnboardingRequest.status != "awaiting_otp")
    requests = q.order_by(OnboardingRequest.created_at.desc()).all()
    return [{
        "id": r.id,
        "business_name": r.business_name,
        "contact_name": r.contact_name,
        "contact_email": r.contact_email,
        "contact_phone": r.contact_phone,
        "website_url": r.website_url,
        "industry": r.industry,
        "services_list": r.services_list,
        "want_chat_widget": r.want_chat_widget,
        "want_whatsapp": r.want_whatsapp,
        "status": r.status,
        "admin_notes": r.admin_notes,
        "created_tenant_id": r.created_tenant_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in requests]


class OnboardingApprove(BaseModel):
    admin_notes: str = ""


@router.post("/onboarding-requests/{request_id}/approve", response_model=dict)
def approve_onboarding_request(
    request_id: str,
    payload: OnboardingApprove,
    db: Session = Depends(get_db),
):
    """Admin approves an onboarding request → creates tenant + optional WA config."""
    req = db.query(OnboardingRequest).filter(OnboardingRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Onboarding request not found")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request already {req.status}")

    # Duplicate prevention: ensure domain/website_url is unique if provided
    if req.website_url:
        existing_domain = db.query(Tenant).filter(Tenant.website_url == req.website_url).first()
        if existing_domain:
            raise HTTPException(
                status_code=409,
                detail=f"Tenant with website {req.website_url} already exists (slug: {existing_domain.slug})"
            )

    slug_base = re.sub(r'[^a-z0-9]+', '-', req.business_name.lower()).strip('-')[:30]
    slug = slug_base
    counter = 1
    while db.query(Tenant).filter(Tenant.slug == slug).first():
        slug = f"{slug_base}-{counter}"
        counter += 1

    tenant = Tenant(
        id=str(uuid.uuid4()),
        name=req.business_name,
        slug=slug,
        domain=req.website_url or f"{slug}.com",
        website_url=req.website_url or None,
        industry=req.industry or None,
        contact_email=req.contact_email or None,
        business_hours=req.business_hours or None,
        welcome_message=req.welcome_message or None,
        subscription_tier="starter",
        knowledge_context={
            "services": [{
                "name": s.strip(),
                "description": ""
            } for s in (req.services_list or "").split("\n") if s.strip()],
            "faqs": req.faqs,
        },
        enabled_channels={
            "chat": req.want_chat_widget,
            "whatsapp": req.want_whatsapp,
        },
        is_active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    # Configure WhatsApp if credentials were provided — use model directly
    wa_configured = False
    if req.want_whatsapp and req.wa_phone_number_id and req.wa_business_account_id and req.wa_access_token:
        try:
            wa = WhatsAppConfiguration(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                phone_number_id=req.wa_phone_number_id,
                business_account_id=req.wa_business_account_id,
                access_token=req.wa_access_token,
                webhook_verify_token=f"{tenant.slug}_wa_verify_2024",
                is_active=True,
            )
            db.add(wa)
            db.commit()
            wa_configured = True
        except Exception as e:
            logger.warning(f"[Onboarding] WhatsApp config failed for {tenant.id}: {e}")
            db.rollback()

    # Generate API key for the tenant
    api_key = APIKey(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        key="tk_" + uuid.uuid4().hex[:24],
        name="auto-generated",
        is_active=True,
    )
    db.add(api_key)

    req.status = "approved"
    req.admin_notes = payload.admin_notes or req.admin_notes or ""
    req.created_tenant_id = tenant.id
    db.commit()

    logger.info(f"[Onboarding] Approved request {request_id} → tenant {tenant.id} ({tenant.slug})")
    return {
        "status": "approved",
        "tenant_id": tenant.id,
        "tenant_slug": tenant.slug,
        "api_key": api_key.key,
        "webhook_url": f"{settings.api_base_url or ''}/api/whatsapp/webhook/{tenant.id}",
        "verify_token": f"{tenant.slug}_wa_verify_2024",
        "whatsapp_configured": wa_configured,
        "message": f"Tenant '{tenant.name}' created successfully."
    }


@router.post("/onboarding-requests/{request_id}/reject")
def reject_onboarding_request(
    request_id: str,
    payload: OnboardingApprove,
    db: Session = Depends(get_db),
):
    """Admin rejects an onboarding request."""
    req = db.query(OnboardingRequest).filter(OnboardingRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Onboarding request not found")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request already {req.status}")
    req.status = "rejected"
    req.admin_notes = payload.admin_notes or req.admin_notes or ""
    db.commit()
    return {"status": "rejected", "request_id": request_id}


# --------------------------------------------------------------------------- #
# Trial Extension & Plan Management (Phase 4)
# --------------------------------------------------------------------------- #

class TrialExtensionRequest(BaseModel):
    """Extend trial days for a tenant."""
    days: int = Field(ge=1, le=30, description="Number of days to extend (1-30)")
    reason: Optional[str] = ""


class PlanCreateRequest(BaseModel):
    """Create a new subscription plan."""
    name: str
    display_name: str
    description: Optional[str] = ""
    price_monthly: float
    price_annual: Optional[float] = None
    trial_days: int = 7
    includes_chatbot: bool = True
    includes_whatsapp: bool = False
    monthly_message_limit: int = 1000
    max_documents: int = 50
    priority_support: bool = False
    features: Optional[str] = ""


class PlanUpdateRequest(BaseModel):
    """Update an existing subscription plan."""
    display_name: Optional[str] = None
    description: Optional[str] = None
    price_monthly: Optional[float] = None
    price_annual: Optional[float] = None
    trial_days: Optional[int] = None
    includes_chatbot: Optional[bool] = None
    includes_whatsapp: Optional[bool] = None
    monthly_message_limit: Optional[int] = None
    max_documents: Optional[int] = None
    priority_support: Optional[bool] = None
    features: Optional[str] = None
    is_active: Optional[bool] = None


@router.post("/tenants/{tenant_id}/extend-trial")
def extend_tenant_trial(
    tenant_id: str,
    payload: TrialExtensionRequest,
    db: Session = Depends(get_db),
):
    """Extend a tenant's trial period. Admin action."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    from datetime import timedelta

    # If trial already expired, start from now
    now = datetime.now(timezone.utc)
    trial_end = tenant.trial_ends_at
    if trial_end and trial_end.tzinfo is None:
        trial_end = trial_end.replace(tzinfo=timezone.utc)

    if trial_end and trial_end > now:
        tenant.trial_ends_at = trial_end + timedelta(days=payload.days)
    else:
        tenant.trial_ends_at = now + timedelta(days=payload.days)

    tenant.subscription_status = "active"
    db.commit()

    logger.info(
        f"[Admin] Trial extended for tenant {tenant_id} by {payload.days} days. "
        f"Reason: {payload.reason}"
    )

    return {
        "status": "success",
        "tenant_id": tenant_id,
        "new_trial_ends_at": tenant.trial_ends_at.isoformat(),
        "days_extended": payload.days,
    }


@router.get("/plans")
def list_plans(db: Session = Depends(get_db)):
    """List all subscription plans (admin view)."""
    plans = db.query(SubscriptionPlan).order_by(SubscriptionPlan.price_monthly).all()
    return {
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "price_monthly": p.price_monthly,
                "price_annual": p.price_annual,
                "trial_days": p.trial_days,
                "includes_chatbot": p.includes_chatbot,
                "includes_whatsapp": p.includes_whatsapp,
                "monthly_message_limit": p.monthly_message_limit,
                "max_documents": p.max_documents,
                "priority_support": p.priority_support,
                "features": p.features,
                "is_active": p.is_active,
                "is_default": p.is_default,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in plans
        ]
    }


@router.post("/plans")
def create_plan(payload: PlanCreateRequest, db: Session = Depends(get_db)):
    """Create a new subscription plan."""
    # Check for duplicate name
    existing = db.query(SubscriptionPlan).filter(SubscriptionPlan.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Plan '{payload.name}' already exists")

    plan = SubscriptionPlan(
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        price_monthly=payload.price_monthly,
        price_annual=payload.price_annual,
        trial_days=payload.trial_days,
        includes_chatbot=payload.includes_chatbot,
        includes_whatsapp=payload.includes_whatsapp,
        monthly_message_limit=payload.monthly_message_limit,
        max_documents=payload.max_documents,
        priority_support=payload.priority_support,
        features=payload.features,
        is_active=True,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    logger.info(f"[Admin] New plan created: {plan.name}")
    return {"status": "success", "plan": {"id": plan.id, "name": plan.name}}


@router.put("/plans/{plan_id}")
def update_plan(plan_id: str, payload: PlanUpdateRequest, db: Session = Depends(get_db)):
    """Update an existing subscription plan."""
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(plan, key, value)

    db.commit()
    db.refresh(plan)

    logger.info(f"[Admin] Plan updated: {plan.name}")
    return {"status": "success", "plan": {"id": plan.id, "name": plan.name}}


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: str, db: Session = Depends(get_db)):
    """Soft-delete a subscription plan (set is_active=False)."""
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan.is_active = False
    db.commit()

    logger.info(f"[Admin] Plan deactivated: {plan.name}")
    return {"status": "success", "message": f"Plan '{plan.name}' deactivated"}


# ── Dashboard Analytics & Crawl Monitoring ─────────────────────────

@router.get("/analytics/overview")
async def admin_analytics_overview(
    db: Session = Depends(get_db),
):
    """Platform overview stats for the new admin dashboard."""
    from sqlalchemy import func as sa_func

    all_tenants = db.query(Tenant).all()
    now = datetime.now(timezone.utc)

    total_tenants = len(all_tenants)
    active_tenants = [t for t in all_tenants if t.is_active]
    active_count = len(active_tenants)

    # Trial tenants with valid trial period
    trial_tenants = [
        t for t in active_tenants
        if t.subscription_plan == "trial"
        and t.trial_ends_at
        and t.trial_ends_at.replace(tzinfo=timezone.utc) > now
    ]
    active_trials = len(trial_tenants)

    # Paid subscriptions (non-trial, active)
    paid_tenants = [
        t for t in active_tenants
        if t.subscription_plan and t.subscription_plan != "trial"
    ]
    paid_subscriptions = len(paid_tenants)

    # Crawl stats
    crawled_ok = [t for t in active_tenants if t.crawl_progress_percent == "100"]
    crawl_failed = [t for t in active_tenants if t.crawl_progress_percent == "0" and t.crawl_progress_stage and "fail" in t.crawl_progress_stage.lower()]
    crawl_never_run = [t for t in active_tenants if t.crawl_progress_percent == "0" and (not t.crawl_progress_stage or t.crawl_progress_stage.strip() == "")]
    crawl_in_progress = [t for t in active_tenants if t.crawl_progress_percent not in ("0", "100")]

    # Unanswered queries count
    total_unanswered = db.query(UnansweredQuery).count()

    # Total documents
    total_docs = db.query(Document).filter(Document.is_active == True).count()

    # Today's chat sessions
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_sessions = db.query(ChatSession).filter(
        ChatSession.created_at >= today_start
    ).count()

    return {
        "total_tenants": total_tenants,
        "active_tenants": active_count,
        "active_trials": active_trials,
        "paid_subscriptions": paid_subscriptions,
        "crawl_completed": len(crawled_ok),
        "crawl_failed": len(crawl_failed),
        "crawl_never_run": len(crawl_never_run),
        "crawl_in_progress": len(crawl_in_progress),
        "total_unanswered_queries": total_unanswered,
        "total_documents": total_docs,
        "today_sessions": today_sessions,
        "last_crawl_errors": [
            {
                "tenant_id": t.id,
                "tenant_name": t.name,
                "slug": t.slug,
                "error": t.crawl_progress_stage or "Unknown error",
                "domain": t.domain,
            }
            for t in crawl_failed[:10]
        ],
        "never_crawled": [
            {
                "tenant_id": t.id,
                "tenant_name": t.name,
                "slug": t.slug,
                "domain": t.domain,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in crawl_never_run[:10]
        ],
    }


@router.get("/crawl/summary")
async def admin_crawl_summary(
    db: Session = Depends(get_db),
):
    """Full crawl status for all tenants — used for monitoring daily 3AM job."""
    from sqlalchemy import func as sa_func

    all_tenants = db.query(Tenant).filter(Tenant.is_active == True).all()

    results = []
    for t in all_tenants:
        doc_count = db.query(Document).filter(
            Document.tenant_id == t.id,
            Document.is_active == True
        ).count()

        percent = int(t.crawl_progress_percent or 0)
        stage = t.crawl_progress_stage or ""
        updated_at = t.crawl_progress_updated_at

        if percent == 100:
            status = "completed"
        elif percent == 0 and stage and ("fail" in stage.lower() or "error" in stage.lower()):
            status = "failed"
        elif percent == 0 and (not stage or stage.strip() == ""):
            status = "never_run"
        elif 0 < percent < 100:
            status = "in_progress"
        else:
            status = "unknown"

        results.append({
            "tenant_id": t.id,
            "tenant_name": t.name,
            "slug": t.slug,
            "domain": t.domain,
            "crawl_status": status,
            "crawl_progress": percent,
            "crawl_stage": stage,
            "crawl_updated_at": updated_at.isoformat() if updated_at else None,
            "document_count": doc_count,
            "website_url": t.website_url or t.domain,
        })

    return {
        "total_active_tenants": len(all_tenants),
        "tenants": results,
        "summary": {
            "completed": sum(1 for r in results if r["crawl_status"] == "completed"),
            "failed": sum(1 for r in results if r["crawl_status"] == "failed"),
            "never_run": sum(1 for r in results if r["crawl_status"] == "never_run"),
            "in_progress": sum(1 for r in results if r["crawl_status"] == "in_progress"),
        },
    }


# =============================================================================
# QUALITY & SELF-LEARNING ENGINE — DASHBOARD ENDPOINTS
# =============================================================================


@router.get("/quality/overview")
async def quality_overview(
    tenant_id: Optional[str] = Query(default=None),
    days: int = Query(default=14, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """
    Quality score trends over time. Returns daily aggregated metrics
    for dashboard charting (line charts for each dimension).
    """
    from sqlalchemy import func as sa_func

    since = date.today() - timedelta(days=days)

    query = db.query(QualityMetric).filter(
        QualityMetric.metric_date >= since,
        QualityMetric.period == "day",
    )
    if tenant_id:
        query = query.filter(QualityMetric.tenant_id == tenant_id)

    metrics = query.order_by(QualityMetric.metric_date.asc()).all()

    if not metrics:
        return {
            "period_days": days,
            "tenant_id": tenant_id or "all",
            "data_points": 0,
            "trends": {
                "dates": [],
                "overall": [],
                "relevance": [],
                "accuracy": [],
                "completeness": [],
                "conciseness": [],
                "tone": [],
                "low_score_count": [],
                "high_score_count": [],
                "feedback_positive": [],
                "feedback_negative": [],
            },
            "summary": {
                "current_avg": 0,
                "best_day": None,
                "worst_day": None,
                "trend_direction": "stable",
            },
        }

    current_avg = metrics[-1].avg_overall_score or 0.0
    prev_avg = (metrics[-2].avg_overall_score or 0.0) if len(metrics) > 1 else current_avg

    if current_avg > prev_avg + 0.02:
        trend = "improving"
    elif current_avg < prev_avg - 0.02:
        trend = "declining"
    else:
        trend = "stable"

    best = max(metrics, key=lambda m: m.avg_overall_score or 0)
    worst = min(metrics, key=lambda m: m.avg_overall_score or 1)

    return {
        "period_days": days,
        "tenant_id": tenant_id or "all",
        "data_points": len(metrics),
        "trends": {
            "dates": [m.metric_date.isoformat() for m in metrics],
            "overall": [m.avg_overall_score or 0 for m in metrics],
            "relevance": [m.avg_relevance or 0 for m in metrics],
            "accuracy": [m.avg_accuracy or 0 for m in metrics],
            "completeness": [m.avg_completeness or 0 for m in metrics],
            "conciseness": [m.avg_conciseness or 0 for m in metrics],
            "tone": [m.avg_tone or 0 for m in metrics],
            "low_score_count": [m.low_score_count for m in metrics],
            "high_score_count": [m.high_score_count for m in metrics],
            "feedback_positive": [m.feedback_positive for m in metrics],
            "feedback_negative": [m.feedback_negative for m in metrics],
        },
        "summary": {
            "current_avg": round(current_avg, 4),
            "previous_avg": round(prev_avg, 4),
            "best_day": {
                "date": best.metric_date.isoformat(),
                "score": best.avg_overall_score,
            },
            "worst_day": {
                "date": worst.metric_date.isoformat(),
                "score": worst.avg_overall_score,
            },
            "trend_direction": trend,
        },
    }


@router.get("/quality/failure-patterns")
async def quality_failure_patterns(
    tenant_id: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Get clustered failure patterns sorted by impact score (highest first).
    Each pattern shows the failure type, sample queries, and message count.
    """
    query = db.query(FailurePattern).filter(FailurePattern.message_count > 0)
    if tenant_id:
        query = query.filter(FailurePattern.tenant_id == tenant_id)

    patterns = query.order_by(FailurePattern.impact_score.desc().nullslast()).limit(limit).all()

    return {
        "total": len(patterns),
        "patterns": [
            {
                "id": p.id,
                "tenant_id": p.tenant_id,
                "channel": p.channel or "web",
                "pattern_name": p.pattern_name,
                "pattern_type": p.pattern_type,
                "description": p.description,
                "cluster_keywords": p.cluster_keywords or [],
                "sample_queries": p.sample_queries or [],
                "message_ids": p.message_ids or [],
                "message_count": p.message_count,
                "avg_score": p.avg_score,
                "impact_score": p.impact_score,
                "is_actionable": p.is_actionable,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }
            for p in patterns
        ],
    }


@router.get("/quality/failure-patterns/{pattern_id}/messages")
async def quality_failure_pattern_messages(
    pattern_id: str,
    db: Session = Depends(get_db),
):
    """
    Get the actual messages behind a failure pattern for admin review.
    Returns user query + bot response pairs with quality scores.
    Supports both web chat and WhatsApp messages.
    """
    from app.models.quality import FailurePattern, QualityScore
    from app.models.chat import ChatMessage
    from app.models.whatsapp import WhatsAppMessage

    pattern = db.query(FailurePattern).filter(FailurePattern.id == pattern_id).first()
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    msg_ids = pattern.message_ids or []
    if not msg_ids:
        return {"pattern_id": pattern_id, "messages": []}

    # Load scores to know which channel each message belongs to
    scores_map = {
        s.message_id: s
        for s in db.query(QualityScore).filter(QualityScore.message_id.in_(msg_ids)).all()
    }

    # Separate message IDs by channel
    web_ids = [mid for mid in msg_ids if scores_map.get(mid) and scores_map[mid].channel in (None, "", "web_chatbot", "web")]
    wa_ids = [mid for mid in msg_ids if scores_map.get(mid) and scores_map[mid].channel == "whatsapp"]

    # Load messages from both tables
    messages = {}
    if web_ids:
        for m in db.query(ChatMessage).filter(ChatMessage.id.in_(web_ids)).all():
            messages[m.id] = ("web", m)
    if wa_ids:
        for m in db.query(WhatsAppMessage).filter(WhatsAppMessage.id.in_(wa_ids)).all():
            messages[m.id] = ("whatsapp", m)

    results = []
    for mid in msg_ids:
        entry = messages.get(mid)
        if not entry:
            continue
        channel, msg = entry
        score = scores_map.get(mid)

        # Find preceding user query based on channel
        if channel == "whatsapp":
            user_msg = db.query(WhatsAppMessage).filter(
                WhatsAppMessage.contact_id == msg.contact_id,
                WhatsAppMessage.direction == "inbound",
                WhatsAppMessage.created_at < msg.created_at,
            ).order_by(WhatsAppMessage.created_at.desc()).first()
        else:
            user_msg = db.query(ChatMessage).filter(
                ChatMessage.session_id == msg.session_id,
                ChatMessage.role == "user",
                ChatMessage.created_at < msg.created_at,
            ).order_by(ChatMessage.created_at.desc()).first()

        results.append({
            "message_id": mid,
            "source": channel,
            "user_query": user_msg.content if user_msg else "",
            "bot_response": msg.content or "",
            "overall_score": score.overall_score if score else None,
            "dimensions": {
                "relevance": score.relevance if score else None,
                "accuracy": score.accuracy if score else None,
                "completeness": score.completeness if score else None,
                "conciseness": score.conciseness if score else None,
                "tone": score.tone if score else None,
            } if score else None,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        })

    return {
        "pattern_id": pattern_id,
        "pattern_name": pattern.pattern_name,
        "pattern_type": pattern.pattern_type,
        "channel": pattern.channel,
        "total_messages": len(results),
        "messages": results,
    }


@router.get("/quality/improvement-candidates")
async def quality_improvement_candidates(
    tenant_id: Optional[str] = Query(default=None),
    status: str = Query(default="pending"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Get improvement candidates for admin review.
    Defaults to pending candidates sorted by improvement delta (highest first).
    """
    from app.services.before_after_generator import get_pending_candidates, get_candidate_history

    if status == "pending":
        candidates = get_pending_candidates(db, tenant_id, limit, offset)
    else:
        candidates = get_candidate_history(db, tenant_id, limit, offset)

    total = db.query(ImprovementCandidate).count()
    if tenant_id:
        total = db.query(ImprovementCandidate).filter(
            ImprovementCandidate.tenant_id == tenant_id
        ).count()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "status_filter": status,
        "candidates": candidates,
    }


class CandidateReviewRequest(BaseModel):
    reviewed_by: str = Field(..., min_length=1)
    review_notes: Optional[str] = None


@router.post("/quality/improvement-candidates/{candidate_id}/approve")
async def approve_improvement_candidate(
    candidate_id: str,
    payload: CandidateReviewRequest,
    db: Session = Depends(get_db),
):
    """
    Approve an improvement candidate. It will be deployed in the next
    self-learning cycle.
    """
    from app.services.before_after_generator import approve_candidate

    result = approve_candidate(
        db=db,
        candidate_id=candidate_id,
        reviewed_by=payload.reviewed_by,
        review_notes=payload.review_notes,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return result


@router.post("/quality/improvement-candidates/{candidate_id}/reject")
async def reject_improvement_candidate(
    candidate_id: str,
    payload: CandidateReviewRequest,
    db: Session = Depends(get_db),
):
    """
    Reject an improvement candidate.
    """
    from app.services.before_after_generator import reject_candidate

    result = reject_candidate(
        db=db,
        candidate_id=candidate_id,
        reviewed_by=payload.reviewed_by,
        review_notes=payload.review_notes,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return result


@router.get("/quality/candidate-summary")
async def quality_candidate_summary(
    tenant_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Summary counts of improvement candidates by status.
    """
    from app.services.before_after_generator import get_candidate_summary

    return get_candidate_summary(db, tenant_id)


@router.post("/quality/pipeline/run")
async def trigger_quality_pipeline(
    background_tasks: BackgroundTasks,
    tenant_id: Optional[str] = Query(default=None),
):
    """
    Manually trigger the full learning pipeline for all tenants or one tenant.
    Runs in the background: scoring → pattern detection → shadow evaluation → quality rollup.
    Returns immediately; pipeline progress is logged server-side.
    """
    from app.services.learning_pipeline import run_full_pipeline_for_tenant, run_full_daily_pipeline

    async def _run():
        if tenant_id:
            await run_full_pipeline_for_tenant(tenant_id)
        else:
            await run_full_daily_pipeline()

    background_tasks.add_task(_run)

    return {
        "status": "triggered",
        "tenant_id": tenant_id or "all",
    }


@router.get("/quality/pipeline/status")
async def quality_pipeline_status():
    """Get current pipeline status (idle/running/completed/failed)."""
    from app.services.pipeline_status import get_status
    return get_status()


@router.get("/quality/live-scores")
async def quality_live_scores(
    tenant_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    min_score: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    max_score: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    """
    Get individual quality scores for recent messages.
    Used for drilling into specific conversations.
    """
    query = db.query(QualityScore)
    if tenant_id:
        query = query.filter(QualityScore.tenant_id == tenant_id)
    if min_score is not None:
        query = query.filter(QualityScore.overall_score >= min_score)
    if max_score is not None:
        query = query.filter(QualityScore.overall_score <= max_score)

    total = query.count()
    scores = query.order_by(QualityScore.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "scores": [
            {
                "id": s.id,
                "tenant_id": s.tenant_id,
                "message_id": s.message_id,
                "channel": s.channel,
                "relevance": s.relevance,
                "accuracy": s.accuracy,
                "completeness": s.completeness,
                "conciseness": s.conciseness,
                "tone": s.tone,
                "overall_score": s.overall_score,
                "flaws": s.flaws or [],
                "judge_model": s.judge_model,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in scores
        ],
    }
