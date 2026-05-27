"""
Chat endpoints - message API v1
"""
from datetime import datetime, timezone, timedelta
import logging
import jwt

from fastapi import APIRouter, Depends, HTTPException, Request, Header, Response, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import ChatMessage, Tenant, APIKey, ChatSession
from app.services import ChatService
from app.services.rate_limiter import RateLimitService
from app.config import settings
from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Optional
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["Chat"])


def verify_api_key(db: Session, tenant_id: str, api_key: str = None) -> Optional[APIKey]:
    """Verify that the provided API key is valid for the given tenant. Returns the key record."""
    if not api_key:
        return None
    
    key_record = db.query(APIKey).filter(
        APIKey.tenant_id == tenant_id,
        APIKey.key == api_key,
        APIKey.is_active == True
    ).first()
    
    return key_record


def _origin_to_bare_host(value: str) -> str:
    """Reduce a URL/origin string to its bare hostname (no scheme/port/www)."""
    if not value:
        return ""
    s = value.strip().lower()
    # Drop scheme.
    if "://" in s:
        s = s.split("://", 1)[1]
    # Drop path / query / fragment / port.
    for sep in ("/", "?", "#"):
        s = s.split(sep, 1)[0]
    s = s.split(":", 1)[0]
    if s.startswith("www."):
        s = s[4:]
    return s.strip(". ")


def verify_widget_token(db: Session, token: str, request_origin: Optional[str] = None) -> Optional[dict]:
    """Verify widget JWT token.

    Returns the decoded payload when the signature, expiry, and (optionally)
    the ``origin`` claim all check out. When ``request_origin`` is supplied
    we compare it against the claim *after* normalizing both sides to a bare
    hostname so trailing slashes, ``www.`` prefixes, and ports don't cause
    false rejections. Mismatches return None.
    """
    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            settings.api_secret_key,
            algorithms=["HS256"],
            options={"verify_exp": True}
        )
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

    claim_origin = payload.get("origin")
    if request_origin and claim_origin:
        if _origin_to_bare_host(request_origin) != _origin_to_bare_host(claim_origin):
            logger.warning(
                "[Widget JWT] origin mismatch: request=%r token=%r",
                request_origin, claim_origin,
            )
            return None
    return payload


def verify_chat_authorization(
    db: Session,
    tenant_id: str,
    auth_header: str = None,
    request_origin: Optional[str] = None,
) -> tuple[bool, Optional[str], Optional[APIKey]]:
    """
    Verify chat request authorization.
    Supports both permanent API keys and short-lived widget JWT tokens.
    Returns (authorized, error_message, api_key_record)

    ``request_origin`` is the value of the inbound ``Origin`` header. When
    supplied (and the caller is using a widget JWT), we additionally enforce
    that the JWT's ``origin`` claim matches the request origin, so a token
    leaked to a third-party site cannot be replayed from a different domain.
    """
    # Allow unauthenticated initial widget load - welcome message only
    if not auth_header:
        # Create temporary anonymous access for welcome message
        key_record = db.query(APIKey).filter(
            APIKey.tenant_id == tenant_id,
            APIKey.is_active == True,
            APIKey.key_type == "widget"
        ).first()
        
        if key_record:
            return True, None, key_record
    
    # Try JWT token first
    payload = verify_widget_token(db, auth_header, request_origin=request_origin)
    if payload:
        if payload.get("tenant_id") == tenant_id:
            key_record = db.query(APIKey).filter(APIKey.id == payload["api_key_id"]).first()
            return True, None, key_record
        return False, "Token invalid for this tenant", None

    # If decode failed because of an origin mismatch (signature OK but origin
    # wrong), surface a clear error rather than silently falling through to
    # the API-key path.
    if auth_header and not auth_header.startswith("sk-") and len(auth_header) > 40:
        # Heuristic: looks like a JWT (no "sk-" prefix, long); try decode
        # without origin enforcement to distinguish "expired/invalid" from
        # "origin mismatch".
        plain = verify_widget_token(db, auth_header, request_origin=None)
        if plain:
            return False, "Widget token origin mismatch", None
    
    # Fall back to API key verification
    key_record = verify_api_key(db, tenant_id, auth_header)
    if key_record:
        return True, None, key_record
    
    return False, "Invalid or missing authorization", None

# LLM provider is resolved per-request via os.getenv (see handlers). This
# avoids freezing a stale value at module import time and keeps the boundary
# consistent with other API modules (e.g. tenants.py).


class ChatMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)
    session_id: Optional[str] = Field(default=None, max_length=100)
    user_id: Optional[str] = Field(default=None, max_length=100)
    
    @field_validator('content')
    @classmethod
    def validate_content_length(cls, v: str) -> str:
        MAX_LENGTH = 150  # 150 chars - plenty for chat messages
        if len(v) > MAX_LENGTH:
            import logging
            logging.getLogger(__name__).warning(
                f"Chat message truncated ({len(v)} -> {MAX_LENGTH} chars)"
            )
            return v[:MAX_LENGTH]
        return v


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    content: str
    role: str
    model_used: Optional[str] = None
    latency_ms: Optional[int] = None
    tokens_used: Optional[int] = None
    retrieved_sources: Optional[List[dict]] = None
    feedback_score: Optional[int] = None
    feedback_comment: Optional[str] = None
    timing_breakdown: Optional[Dict[str, int]] = Field(None, alias="_timing_breakdown")
    
    class Config:
        from_attributes = True
        populate_by_name = True


class ChatFeedbackRequest(BaseModel):
    score: int = Field(description="Feedback score: 1 for positive, -1 for negative")
    comment: Optional[str] = Field(default=None, max_length=1000)


class WidgetTokenRequest(BaseModel):
    origin: Optional[str] = None


class WidgetTokenResponse(BaseModel):
    token: str
    expires_at: datetime




@router.post("/message/{tenant_id}", response_model=ChatMessageResponse, status_code=201)
async def send_message(
    tenant_id: str,
    message_in: ChatMessageRequest,
    db: Session = Depends(get_db),
    request: Request = None,
    x_api_key: str = Header(None, description="Tenant API key or widget token for authentication")
):
    """
    Send a chat message and get AI response
    Requires API key authentication with rate limiting.
    """
    # --- Authorization validation ---
    # Pass through the browser Origin so widget JWTs are bound to the domain
    # they were issued for (prevents replay if a token leaks to a third party).
    request_origin = request.headers.get("origin") if request is not None else None
    authorized, error, key_record = verify_chat_authorization(
        db, tenant_id, x_api_key, request_origin=request_origin
    )
    if not authorized:
        raise HTTPException(status_code=401, detail=error)
    
    # --- Rate limiting check ---
    allowed, reason, rate_headers = RateLimitService.check_rate_limit(db, key_record)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=reason,
            headers=rate_headers
        )
    
    # --- Domain/Hostname validation ---
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Check allowed_domains on API key (comma-separated list).
    # Normalize each entry: strip scheme, path, port, and any leading "www." so admins
    # can save values like "https://www.foo.com/" or "foo.com" interchangeably.
    def _normalize_domain(raw: str) -> str:
        import re as _re
        d = (raw or "").strip().lower()
        if not d:
            return ""
        d = _re.sub(r"^[a-z]+://", "", d)        # drop scheme
        d = d.split("/", 1)[0]                    # drop path
        d = d.split(":", 1)[0]                    # drop port
        if d.startswith("www."):
            d = d[4:]
        return d

    allowed_domains_str = key_record.allowed_domains if hasattr(key_record, 'allowed_domains') and key_record.allowed_domains else ""
    raw_allowed = [d for d in allowed_domains_str.split(",") if d.strip()] if allowed_domains_str else []
    allowed_domains = [n for n in (_normalize_domain(d) for d in raw_allowed) if n]

    # Fall back to tenant domain if no specific domains set on key
    if not allowed_domains and tenant.domain:
        normalized_tenant_domain = _normalize_domain(tenant.domain)
        if normalized_tenant_domain:
            allowed_domains = [normalized_tenant_domain]
    
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    
    if origin and allowed_domains:
        import re
        m = re.match(r"https?://([^/]+)", origin.lower())
        if m:
            req_domain = m.group(1)
            req_host = req_domain.split(":")[0]  # strip port for IP checks

            # Allow localhost and private IP ranges — these cannot be reached
            # from the public internet so domain enforcement is not meaningful.
            _private_ip = re.match(
                r"^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|"
                r"172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|192\.168\.\d+\.\d+)$",
                req_host
            )
            if _private_ip and getattr(settings, "allow_local_origins", True):
                # Dev-only convenience: skip the per-key domain check for
                # localhost / RFC1918. In production set ALLOW_LOCAL_ORIGINS=false
                # so leaked widget keys can't be exercised from the admin's LAN.
                logger.warning(
                    "Domain check bypassed for private/local origin %s "
                    "(ALLOW_LOCAL_ORIGINS=true)", req_domain,
                )
            elif _private_ip:
                logger.warning(
                    "Blocked private/local origin %s — ALLOW_LOCAL_ORIGINS is disabled",
                    req_domain,
                )
                raise HTTPException(
                    status_code=403,
                    detail="Requests from local/private origins are not allowed in this environment.",
                )
            else:
                # Compare bare host (no scheme/port/www) on both sides.
                req_bare = req_host[4:] if req_host.startswith("www.") else req_host
                is_allowed = req_bare in allowed_domains
                if not is_allowed:
                    logger.warning(
                        f"Blocked request from unauthorized domain: {req_host} (bare={req_bare}) not in {allowed_domains}"
                    )
                    raise HTTPException(
                        status_code=403,
                        detail=f"Requests not allowed from this domain. Expected: {', '.join(allowed_domains)}"
                    )
    elif not origin and allowed_domains:
        # No origin header - might be server-side call, allow it
        pass

    try:
        chat_service = ChatService(db=db, llm_provider=os.getenv("LLM_PROVIDER", "mock"))
        result = await chat_service.send_message(
            tenant_id=tenant_id,
            content=message_in.content,
            session_id=message_in.session_id,
            user_id=message_in.user_id
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("[Chat API] send_message failed for tenant_id=%s: %s", tenant_id, e)
        raise HTTPException(
            status_code=503,
            detail="We're facing a temporary issue right now. Please try again shortly."
        )


@router.get("/session/{session_id}", response_model=List[ChatMessageResponse])
async def get_session_messages(
    session_id: str, 
    db: Session = Depends(get_db),
    x_api_key: str = Header(None, description="Tenant API key or widget token for authentication")
):
    """
    Get all messages in a session
    Requires API key authentication.
    """
    # First get session to find tenant_id
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Validate authorization with proper tenant ownership check
    authorized, error, _ = verify_chat_authorization(db, session.tenant_id, x_api_key)
    if not authorized:
        raise HTTPException(status_code=401, detail=error)
    
    try:
        chat_service = ChatService(db=db, llm_provider=os.getenv("LLM_PROVIDER", "mock"))
        messages = chat_service.get_session_messages(session_id)
        return messages
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/token/{tenant_id}", response_model=WidgetTokenResponse)
async def get_widget_token(
    tenant_id: str,
    token_request: WidgetTokenRequest,
    db: Session = Depends(get_db),
    x_api_key: str = Header(None, description="Tenant API key for authentication")
):
    """
    Generate short-lived JWT token for widget usage.
    This endpoint should ONLY be called from customer backend servers, never from browser.
    """
    key_record = verify_api_key(db, tenant_id, x_api_key)
    if not key_record:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    
    token = jwt.encode(
        {
            "tenant_id": tenant_id,
            "api_key_id": key_record.id,
            "origin": token_request.origin,
            "type": "widget",
            "exp": expires_at
        },
        settings.api_secret_key,
        algorithm="HS256"
    )
    
    return {
        "token": token,
        "expires_at": expires_at
    }


@router.post("/feedback/{message_id}")
async def submit_feedback(
    message_id: str,
    feedback_in: ChatFeedbackRequest,
    db: Session = Depends(get_db),
    x_api_key: str = Header(None, description="Tenant API key or widget token for authentication")
):
    """Submit thumbs up/down feedback for an assistant message."""
    if feedback_in.score not in (-1, 1):
        raise HTTPException(status_code=400, detail="score must be 1 or -1")

    message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    # Validate authorization
    authorized, error, _ = verify_chat_authorization(db, message.tenant_id, x_api_key)
    if not authorized:
        raise HTTPException(status_code=401, detail=error)

    if message.role != "assistant":
        raise HTTPException(status_code=400, detail="Feedback can only be submitted for assistant messages")

    message.feedback_score = feedback_in.score
    message.feedback_comment = feedback_in.comment.strip() if feedback_in.comment else None
    message.feedback_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "message_id": message_id,
        "feedback_score": message.feedback_score,
        "feedback_comment": message.feedback_comment,
        "status": "saved"
    }


class LeadFormData(BaseModel):
    session_id: Optional[str] = None
    name: str = Field(..., min_length=1, description="Contact name")
    email: str = Field(..., description="Email address")
    phone: str = Field(..., min_length=1, description="Phone number")


@router.post("/lead/{tenant_id}")
async def submit_lead(
    tenant_id: str,
    lead_data: LeadFormData,
    db: Session = Depends(get_db),
    x_api_key: str = Header(None, description="Tenant API key or widget token for authentication")
):
    """Submit lead contact information from widget form."""
    # Find tenant
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Validate authorization
    authorized, error, _ = verify_chat_authorization(db, tenant_id, x_api_key)
    if not authorized:
        raise HTTPException(status_code=401, detail=error)
    
    # Find or create session. The session_id MUST belong to the tenant in the
    # path; otherwise an attacker could submit a lead under tenant A's path
    # while passing tenant B's session_id and overwrite tenant B's lead fields.
    session = None
    if lead_data.session_id:
        session = db.query(ChatSession).filter(
            ChatSession.id == lead_data.session_id,
            ChatSession.tenant_id == tenant_id,
        ).first()
        if not session:
            # Treat a mismatched / unknown session_id as "no session" rather
            # than leaking whether the id exists for another tenant.
            logger.warning(
                "[Lead] session_id %s did not match tenant %s; creating fresh session",
                lead_data.session_id, tenant_id,
            )

    if not session:
        session = ChatSession(
            tenant_id=tenant_id,
            user_id="widget-lead-form"
        )
        db.add(session)
        db.flush()
    
    # Save lead info
    session.lead_name = lead_data.name
    session.lead_email = lead_data.email
    session.lead_phone = lead_data.phone
    session.lead_collected_at = datetime.now(timezone.utc)
    db.commit()
    
    logger.info(f"[Lead] Saved from widget: name={lead_data.name}, email={lead_data.email}")
    
    return {
        "session_id": session.id,
        "status": "saved",
        "name": lead_data.name
    }


@router.get("/leads/{tenant_id}")
async def get_leads(
    tenant_id: str,
    db: Session = Depends(get_db),
    x_api_key: str = Header(None, description="API key for authentication")
):
    """Get all leads collected for a tenant."""
    # Find tenant
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Validate authorization
    authorized, error, _ = verify_chat_authorization(db, tenant_id, x_api_key)
    if not authorized:
        raise HTTPException(status_code=401, detail=error)
    
    # Get all sessions with leads
    sessions = db.query(ChatSession).filter(
        ChatSession.tenant_id == tenant_id,
        ChatSession.lead_name.isnot(None)
    ).order_by(ChatSession.lead_collected_at.desc()).all()
    
    leads = []
    for s in sessions:
        leads.append({
            "session_id": s.id,
            "name": s.lead_name,
            "email": s.lead_email,
            "phone": s.lead_phone,
            "collected_at": s.lead_collected_at.isoformat() if s.lead_collected_at else None
        })
    
    return {"tenant": tenant.name, "leads": leads, "count": len(leads)}


@router.get("/analytics/{tenant_id}")
async def get_analytics_summary(
    tenant_id: str,
    days: int = Query(7, ge=1, le=90, description="Days to analyze"),
    db: Session = Depends(get_db),
    x_api_key: str = Header(None, description="API key for authentication")
):
    """Get analytics summary for a tenant."""
    # Find tenant
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Validate authorization
    authorized, error, _ = verify_chat_authorization(db, tenant_id, x_api_key)
    if not authorized:
        raise HTTPException(status_code=401, detail=error)
    
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=days)
    
    # Total sessions
    total_sessions = db.query(ChatSession).filter(
        ChatSession.tenant_id == tenant_id,
        ChatSession.created_at >= since
    ).count()
    
    # Total messages
    total_messages = db.query(ChatMessage).filter(
        ChatMessage.tenant_id == tenant_id,
        ChatMessage.created_at >= since
    ).count()
    
    # Leads collected
    leads_collected = db.query(ChatSession).filter(
        ChatSession.tenant_id == tenant_id,
        ChatSession.lead_name.isnot(None),
        ChatSession.lead_collected_at >= since
    ).count()
    
    # User messages (topic analysis)
    user_msgs = db.query(ChatMessage).filter(
        ChatMessage.tenant_id == tenant_id,
        ChatMessage.role == "user",
        ChatMessage.created_at >= since
    ).all()
    
    # Top topics (simple word frequency)
    topic_words = {}
    stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'i', 'you', 'we', 'they', 'it', 'to', 'of', 'in', 'for', 'on', 'my', 'me', 'and', 'or', 'but', 'how', 'what', 'can', 'do', 'have', 'has', 'hi', 'hello', 'hey', 'thanks', 'please', 'help'}
    for msg in user_msgs:
        words = msg.content.lower().split()
        for w in words:
            if len(w) > 4 and w not in stop_words:
                topic_words[w] = topic_words.get(w, 0) + 1
    
    top_topics = sorted(topic_words.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # Feedback stats
    neg_feedback = db.query(ChatMessage).filter(
        ChatMessage.tenant_id == tenant_id,
        ChatMessage.role == "assistant",
        ChatMessage.feedback_score == -1,
        ChatMessage.created_at >= since
    ).count()
    
    pos_feedback = db.query(ChatMessage).filter(
        ChatMessage.tenant_id == tenant_id,
        ChatMessage.role == "assistant",
        ChatMessage.feedback_score == 1,
        ChatMessage.created_at >= since
    ).count()
    
    return {
        "tenant": tenant.name,
        "period_days": days,
        "summary": {
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "leads_collected": leads_collected,
            "conversion_rate": round(leads_collected / total_sessions * 100, 1) if total_sessions > 0 else 0
        },
        "feedback": {
            "positive": pos_feedback,
            "negative": neg_feedback
        },
        "top_topics": [{"topic": t[0], "count": t[1]} for t in top_topics],
        "insights": {
            "needs_attention": neg_feedback > 0,
            "high_volume": total_messages > 100,
            "good_conversion": leads_collected > 0
        }
    }
