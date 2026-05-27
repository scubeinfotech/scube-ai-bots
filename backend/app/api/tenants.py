"""
Tenant management endpoints
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Tenant
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from app.services.website_crawler import WebsiteCrawlerService
from app.services.vector_knowledge import VectorKnowledgeService
from app.middleware import invalidate_cors_cache


def _require_tenant_token(authorization: Optional[str]) -> dict:
    """Validate ``Authorization: Bearer <jwt>`` for tenant-portal endpoints.

    The tenant portal logs users in via /api/admin/tenant-users/auth/login and
    stores the resulting JWT in localStorage. Read endpoints that expose a
    tenant's chat transcripts must require that token to prevent cross-tenant
    data leaks.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")
    # Lazy import to avoid circular dependency between admin <-> tenants modules.
    from app.api.admin import decode_tenant_user_token
    payload = decode_tenant_user_token(authorization.split(None, 1)[1].strip())
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload

router = APIRouter(prefix="/api/tenants", tags=["Tenants"])


def build_default_guardrails(industry: str, compliance_mode: str) -> dict:
    """Return guardrails that match the tenant profile exactly."""
    if compliance_mode != "high-regulation":
        return {}

    if industry in {"accounting", "insurance"}:
        base = {
            "require_disclaimer": True,
            "prohibited_response_types": ["professional legal advice", "professional financial advice"],
            "escalation_triggers": ["complex case", "legal question", "financial planning", "claims dispute"],
            "audit_all_responses": True,
        }
        if industry == "insurance":
            base.update({
                "enabled": True,
                "disclaimer_text": (
                    "This is general information only, not official insurance advice. "
                    "Please consult your licensed agent for your specific policy details."
                ),
                "disclaimer_trigger_keywords": [
                    "cover", "coverage", "covers", "covered",
                    "policy", "policies", "claim", "claims",
                    "premium", "deductible", "exclusion", "pre-existing",
                    "benefit", "benefits", "reimbursement", "payout",
                ],
            })
        return base

    return {
        "require_disclaimer": True,
        "audit_all_responses": True,
        "escalation_triggers": ["regulated request", "contract risk", "compliance issue"],
    }


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=60, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    domain: str = Field(..., min_length=3, max_length=253)
    website_url: Optional[str] = Field(default=None, max_length=500)
    prompt_template: Optional[str] = Field(default=None, max_length=5000)
    knowledge_context: Optional[dict] = Field(default=None, max_length=100000)  # 100KB max
    guardrails: Optional[dict] = Field(default=None, max_length=10000)
    welcome_message: Optional[str] = Field(default=None, max_length=1000)
    out_of_scope_mode: Optional[str] = Field(default="strict_business", max_length=50)
    subscription_tier: Optional[str] = Field(default="starter", max_length=50)
    allowed_models: Optional[list] = Field(default=None, max_length=20)
    industry: Optional[str] = Field(default=None, max_length=50)
    tone: Optional[str] = Field(default="friendly", max_length=50)
    cta_goals: Optional[list] = Field(default=None, max_length=10)
    
    @field_validator('slug')
    @classmethod
    def validate_slug(cls, v: str) -> str:
        import re
        if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$', v):
            raise ValueError('Slug must be lowercase alphanumeric with hyphens (no leading/trailing hyphens)')
        return v
    
    @field_validator('knowledge_context')
    @classmethod
    def validate_knowledge_context(cls, v: Optional[dict]) -> Optional[dict]:
        if v is None:
            return v
        # Allowed keys for knowledge_context
        ALLOWED_KEYS = {
            'company_overview', 'about', 'services', 'products', 'faqs',
            'contact_info', 'official_contact', 'business_hours', 'pricing',
            'pricing_info', 'access_policy', 'trial_policy', 'ctas', 'next_steps',
            'business_facts', 'website_pages', 'rag_profile'
        }
        for key in v.keys():
            if key not in ALLOWED_KEYS:
                raise ValueError(f'Invalid knowledge_context key: {key}. Allowed: {", ".join(sorted(ALLOWED_KEYS))}')
        return v


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    domain: str
    industry: Optional[str] = None
    tone: Optional[str] = None
    compliance_mode: Optional[str] = None
    out_of_scope_mode: Optional[str] = None
    subscription_tier: Optional[str] = None
    allowed_models: Optional[list] = None
    cta_goals: Optional[list] = None
    website_url: Optional[str] = None
    onboarding_stage: Optional[str] = None
    onboarding_notes: Optional[str] = None
    prompt_template: Optional[str] = None
    guardrails: Optional[dict] = None
    welcome_message: Optional[str] = None
    enabled_channels: Optional[dict] = None  # {"chat": bool, "whatsapp": bool, ...}
    is_active: bool
    
    # Timezone
    timezone: str = "Asia/Singapore"
    
    # Phase 2: AI Agent capabilities (all mandatory)
    enable_sentiment_analysis: bool = True
    enable_conversation_memory: bool = True
    enable_function_calling: bool = True
    escalation_threshold: Optional[str] = "-0.5"
    
    # Daily Report Settings
    daily_report_email: Optional[str] = None
    daily_report_enabled: Optional[bool] = False
    
    # External API (Reply Back)
    external_api_url: Optional[str] = None
    external_api_key: Optional[str] = None
    external_api_enabled: Optional[bool] = False
    
    # Notification Settings
    notification_email: Optional[str] = None
    notify_on_booking: bool = True
    
    class Config:
        from_attributes = True


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    domain: Optional[str] = Field(default=None, max_length=253)
    website_url: Optional[str] = Field(default=None, max_length=500)
    prompt_template: Optional[str] = Field(default=None, max_length=5000)
    knowledge_context: Optional[dict] = Field(default=None, max_length=100000)
    guardrails: Optional[dict] = Field(default=None, max_length=10000)
    welcome_message: Optional[str] = Field(default=None, max_length=1000)
    out_of_scope_mode: Optional[str] = Field(default=None, max_length=50)
    subscription_tier: Optional[str] = Field(default=None, max_length=50)
    allowed_models: Optional[list] = Field(default=None, max_length=20)
    industry: Optional[str] = Field(default=None, max_length=50)
    tone: Optional[str] = Field(default=None, max_length=50)
    cta_goals: Optional[list] = Field(default=None, max_length=10)
    enabled_channels: Optional[dict] = Field(default=None, max_length=20)
    is_active: Optional[bool] = None
    
    # Phase 2: AI Agent capabilities
    enable_sentiment_analysis: Optional[bool] = None
    enable_conversation_memory: Optional[bool] = None
    enable_function_calling: Optional[bool] = None
    escalation_threshold: Optional[str] = Field(default=None, max_length=20)
    
    # External API (Reply Back)
    external_api_url: Optional[str] = Field(default=None, max_length=500)
    external_api_key: Optional[str] = Field(default=None, max_length=255)
    external_api_enabled: Optional[bool] = None
    
    # Notification Settings
    notification_email: Optional[str] = Field(default=None, max_length=255)
    notify_on_booking: Optional[bool] = None
    
    # Timezone Settings
    timezone: Optional[str] = Field(default=None, max_length=50)
    
    @field_validator('knowledge_context')
    @classmethod
    def validate_knowledge_context(cls, v: Optional[dict]) -> Optional[dict]:
        if v is None:
            return v
        ALLOWED_KEYS = {
            'company_overview', 'about', 'services', 'products', 'faqs',
            'contact_info', 'official_contact', 'business_hours', 'pricing',
            'pricing_info', 'access_policy', 'trial_policy', 'ctas', 'next_steps',
            'business_facts', 'website_pages', 'rag_profile'
        }
        for key in v.keys():
            if key not in ALLOWED_KEYS:
                raise ValueError(f'Invalid knowledge_context key: {key}. Allowed: {", ".join(sorted(ALLOWED_KEYS))}')
        return v


class TenantOnboarding(BaseModel):
    """Comprehensive tenant onboarding profile for multi-industry support."""
    industry: str = Field(description="food, services, accounting, insurance, other")
    tone: str = Field(default="friendly", description="friendly, formal, consultative")
    compliance_mode: str = Field(default="normal", description="normal or high-regulation")
    out_of_scope_mode: str = Field(default="strict_business", description="strict_business or assistive_general")
    cta_goals: List[str] = Field(default=["lead"], description="Allowed CTA types: lead, booking, quote, support")
    website_url: str = Field(description="Website URL for crawling and content extraction")
    business_description: str = Field(description="Brief description of the business (100-500 chars)")
    onboarding_notes: Optional[str] = Field(default=None, description="Admin notes")


class TenantConfigResponse(BaseModel):
    """Public tenant configuration for widget"""
    welcome_message: Optional[str] = None
    name: str
    
    class Config:
        from_attributes = True


class TenantCrawlStatusResponse(BaseModel):
    tenant_id: str
    website_url: Optional[str] = None
    onboarding_stage: Optional[str] = None
    document_count: int
    onboarding_notes: Optional[str] = None


class TenantVectorStatusResponse(BaseModel):
    tenant_id: str
    indexed_documents: int
    indexed_chunks: int


class TenantVectorSearchResult(BaseModel):
    score: float
    content: str
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    document_id: str


class TenantVectorSearchResponse(BaseModel):
    tenant_id: str
    query: str
    total_hits: int
    results: List[TenantVectorSearchResult]


@router.post("/", response_model=TenantResponse, status_code=201)
async def create_tenant(tenant_in: TenantCreate, db: Session = Depends(get_db)):
    """Create a new tenant"""
    # Check if slug already exists
    existing = db.query(Tenant).filter(Tenant.slug == tenant_in.slug).first()
    if existing:
        raise HTTPException(status_code=400, detail="Slug already exists")
    
    tenant = Tenant(**tenant_in.model_dump())
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    invalidate_cors_cache()  # new tenant domain may need to be CORS-allowed
    return tenant


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: str, db: Session = Depends(get_db)):
    """Get tenant by ID"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/{tenant_id}/api-keys")
async def list_tenant_api_keys(
    tenant_id: str,
    db: Session = Depends(get_db),
):
    """List API keys for a tenant (used by tenant dashboard)."""
    from app.models import APIKey

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    api_keys = db.query(APIKey).filter(APIKey.tenant_id == tenant_id, APIKey.is_active == True).all()
    return {
        "api_keys": [
            {
                "id": key.id,
                "name": key.name,
                "key": key.key,
                "key_type": key.key_type,
                "is_active": key.is_active,
            }
            for key in api_keys
        ]
    }


@router.post("/{tenant_id}/api-keys")
async def regenerate_tenant_api_key(
    tenant_id: str,
    db: Session = Depends(get_db),
):
    """Regenerate the first active widget API key for a tenant."""
    from app.models import APIKey

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    api_key = db.query(APIKey).filter(
        APIKey.tenant_id == tenant_id,
        APIKey.is_active == True,
    ).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="No active API key found to rotate")

    old_key_id = api_key.id

    api_key.is_active = False
    api_key.name = f"{api_key.name} (rotated)"

    import secrets
    new_key_value = secrets.token_urlsafe(32)

    new_api_key = APIKey(
        tenant_id=api_key.tenant_id,
        name=api_key.name.replace(" (rotated)", ""),
        key=new_key_value,
        key_type=api_key.key_type,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
        rate_limit_per_hour=api_key.rate_limit_per_hour,
        is_active=True,
    )

    db.add(new_api_key)
    api_key.key = f"REVOKED_{api_key.key[:8]}"
    db.commit()
    db.refresh(new_api_key)

    return {
        "status": "rotated",
        "old_key_id": old_key_id,
        "new_key_id": new_api_key.id,
        "new_key": new_api_key.key,
        "warning": "Update your widget code with the new key immediately. The old key is now invalid.",
    }


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(tenant_id: str, tenant_in: TenantUpdate, db: Session = Depends(get_db)):
    """Update tenant configuration dynamically for onboarding and tuning."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    update_data = tenant_in.model_dump(exclude_unset=True)
    if not update_data:
        return tenant

    # Mandatory Phase 2 AI features - cannot be disabled
    MANDATORY_AI_FEATURES = ['enable_sentiment_analysis', 'enable_conversation_memory', 'enable_function_calling']
    for feature in MANDATORY_AI_FEATURES:
        if feature in update_data and not update_data[feature]:
            raise HTTPException(
                status_code=400, 
                detail=f"{feature.replace('_', ' ').title()} is mandatory and cannot be disabled"
            )
    
    if "out_of_scope_mode" in update_data:
        valid_modes = ["strict_business", "assistive_general"]
        if update_data["out_of_scope_mode"] not in valid_modes:
            raise HTTPException(status_code=400, detail=f"out_of_scope_mode must be one of: {valid_modes}")

    if "subscription_tier" in update_data:
        valid_tiers = ["starter", "growth", "enterprise"]
        if update_data["subscription_tier"] not in valid_tiers:
            raise HTTPException(status_code=400, detail=f"subscription_tier must be one of: {valid_tiers}")

    for key, value in update_data.items():
        setattr(tenant, key, value)

    # Auto-derive domain from website_url
    if "website_url" in update_data and update_data["website_url"]:
        bare_host = update_data["website_url"].lower().replace("http://", "").replace("https://", "").split("/")[0].replace("www.", "")
        if bare_host:
            tenant.domain = bare_host

    db.commit()
    db.refresh(tenant)
    if any(k in update_data for k in ("domain", "website_url", "is_active")):
        invalidate_cors_cache()
    return tenant


@router.get("/slug/{slug}", response_model=TenantResponse)
async def get_tenant_by_slug(slug: str, db: Session = Depends(get_db)):
    """Get tenant by slug"""
    tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/", response_model=List[TenantResponse])
async def list_tenants(db: Session = Depends(get_db)):
    """List all tenants"""
    return db.query(Tenant).filter(Tenant.is_active == True).all()


@router.get("/{tenant_id}/config", response_model=TenantConfigResponse)
async def get_tenant_config(tenant_id: str, db: Session = Depends(get_db)):
    """Get public tenant configuration for widget initialization"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.is_active == True).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"welcome_message": tenant.welcome_message, "name": tenant.name}


@router.post("/{tenant_id}/onboard", response_model=TenantResponse, status_code=200)
async def onboard_tenant(
    tenant_id: str,
    onboarding: TenantOnboarding,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Complete tenant business profile onboarding for multi-industry support.
    Sets up industry-specific prompt, compliance rules, and CTA goals.
    Triggers website crawl and document processing.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Validate inputs
    valid_industries = ["food", "services", "accounting", "insurance", "marine", "non-profit", "other"]
    if onboarding.industry not in valid_industries:
        raise HTTPException(status_code=400, detail=f"Industry must be one of: {valid_industries}")
    
    valid_tones = ["friendly", "formal", "consultative"]
    if onboarding.tone not in valid_tones:
        raise HTTPException(status_code=400, detail=f"Tone must be one of: {valid_tones}")
    
    valid_compliance = ["normal", "high-regulation"]
    if onboarding.compliance_mode not in valid_compliance:
        raise HTTPException(status_code=400, detail=f"Compliance mode must be one of: {valid_compliance}")

    valid_out_of_scope = ["strict_business", "assistive_general"]
    if onboarding.out_of_scope_mode not in valid_out_of_scope:
        raise HTTPException(status_code=400, detail=f"out_of_scope_mode must be one of: {valid_out_of_scope}")
    
    valid_ctas = ["lead", "booking", "quote", "support"]

    for cta in onboarding.cta_goals:
        if cta not in valid_ctas:
            raise HTTPException(status_code=400, detail=f"CTA goal must be one of: {valid_ctas}")
    
    # Build industry-specific prompt template
    # IMPORTANT: Use user-friendly terms - avoid "business" unless detected as for-profit
    # The system will auto-detect org type from website content
    # Industry is now auto-detected from crawler, no hardcoded prompts needed
    industry_prompts = {
        # Default fallback - LLM will adapt based on website content
        "other": "You are a helpful assistant. Adapt your language based on the organization's type. Use 'organization', 'charity', or 'company' appropriately. When describing yourself, represent the organization - never use internal system terms like 'tenant'."
    }
    
    # Build guardrails deterministically so stale settings do not survive profile changes.
    guardrails = build_default_guardrails(onboarding.industry, onboarding.compliance_mode)
    
    # Update tenant
    tenant.industry = onboarding.industry
    tenant.tone = onboarding.tone
    tenant.compliance_mode = onboarding.compliance_mode
    tenant.out_of_scope_mode = onboarding.out_of_scope_mode
    tenant.cta_goals = onboarding.cta_goals
    tenant.website_url = onboarding.website_url
    tenant.onboarding_stage = "processing"  # Mark as processing, will be 'ready' after crawl completes
    tenant.onboarding_notes = onboarding.onboarding_notes or ""
    
    # Set prompt template based on industry + tone
    base_prompt = industry_prompts.get(onboarding.industry, industry_prompts["other"])
    tone_suffix = {
        "friendly": " Keep responses warm and approachable.",
        "formal": " Keep responses professional and concise.",
        "consultative": " Ask clarifying questions to provide the best guidance."
    }
    tenant.prompt_template = base_prompt + tone_suffix.get(onboarding.tone, "")
    
    # Always overwrite guardrails so old industry-specific rules do not leak across onboarding updates.
    tenant.guardrails = guardrails
    
    db.commit()
    db.refresh(tenant)
    invalidate_cors_cache()  # onboarding may have set/changed website_url

    if onboarding.website_url:
        WebsiteCrawlerService.queue_crawl(background_tasks, tenant.id, onboarding.website_url)
    
    return tenant


@router.post("/{tenant_id}/crawl-website", response_model=TenantCrawlStatusResponse)
async def trigger_tenant_website_crawl(
    tenant_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Manually trigger website crawl for a tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not tenant.website_url:
        raise HTTPException(status_code=400, detail="Tenant website_url is not configured")

    tenant.onboarding_stage = "processing"
    db.commit()

    WebsiteCrawlerService.queue_crawl(background_tasks, tenant.id, tenant.website_url)
    return WebsiteCrawlerService.get_crawl_status(db, tenant.id)


@router.get("/{tenant_id}/crawl-status", response_model=TenantCrawlStatusResponse)
async def get_tenant_crawl_status(tenant_id: str, db: Session = Depends(get_db)):
    """Get website crawl status for a tenant."""
    status = WebsiteCrawlerService.get_crawl_status(db, tenant_id)
    if not status:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return status


@router.post("/{tenant_id}/reindex-vectors", response_model=TenantVectorStatusResponse)
async def reindex_tenant_vectors(tenant_id: str, db: Session = Depends(get_db)):
    """Manually rebuild vector index for all active tenant documents."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    stats = VectorKnowledgeService.index_tenant_documents(db, tenant_id)
    return {
        "tenant_id": tenant_id,
        "indexed_documents": stats["documents"],
        "indexed_chunks": stats["chunks"],
    }


@router.get("/{tenant_id}/vector-status", response_model=TenantVectorStatusResponse)
async def get_tenant_vector_status(tenant_id: str, db: Session = Depends(get_db)):
    """Get current vector index status for a tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    stats = VectorKnowledgeService.get_index_stats(db, tenant_id)
    return {
        "tenant_id": tenant_id,
        "indexed_documents": stats["documents"],
        "indexed_chunks": stats["chunks"],
    }


@router.get("/{tenant_id}/vector-search", response_model=TenantVectorSearchResponse)
async def tenant_vector_search(
    tenant_id: str,
    q: str = Query(..., min_length=2, description="Search query"),
    top_k: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """Run semantic search on tenant vector index."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    results = VectorKnowledgeService.search(db=db, tenant_id=tenant_id, query=q, top_k=top_k)
    return {
        "tenant_id": tenant_id,
        "query": q,
        "total_hits": len(results),
        "results": results,
    }


class ConversationSummary(BaseModel):
    """Summary of a chat session"""
    session_id: str
    created_at: Optional[str]
    updated_at: Optional[str]
    message_count: int
    last_message_preview: Optional[str] = None


class TenantConversationsResponse(BaseModel):
    """Response with list of tenant conversations"""
    tenant_id: str
    total: int
    limit: int
    offset: int
    conversations: List[ConversationSummary]


class ChatMessageSummary(BaseModel):
    """Summary of a chat message"""
    id: str
    role: str
    content: str
    created_at: Optional[str]
    model_used: Optional[str] = None
    feedback_score: Optional[int] = None


class SessionTranscriptResponse(BaseModel):
    """Response with session transcript"""
    session_id: str
    tenant_id: str
    messages: List[ChatMessageSummary]


class TenantChatRequest(BaseModel):
    """Chat request for tenant test mode"""
    content: str
    session_id: Optional[str] = None


class TenantChatResponse(BaseModel):
    """Chat response"""
    id: str
    session_id: str
    content: str
    role: str
    model_used: Optional[str] = None


@router.post("/{tenant_id}/chat", response_model=TenantChatResponse, status_code=201)
async def tenant_test_chat(
    tenant_id: str,
    chat_in: TenantChatRequest,
    db: Session = Depends(get_db),
):
    """Send a chat message in test mode (for tenant portal testing)
    
    This endpoint uses tenant authentication for testing the chatbot.
    """
    from app.services import ChatService
    import os
    
    # Verify tenant exists
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    try:
        chat_service = ChatService(db=db, llm_provider=os.getenv("LLM_PROVIDER", "mock"))
        result = await chat_service.send_message(
            tenant_id=tenant_id,
            content=chat_in.content,
            session_id=chat_in.session_id,
            user_id="tenant-test"
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail="We're facing a temporary issue right now. Please try again shortly."
        )


@router.get("/{tenant_id}/conversations", response_model=TenantConversationsResponse)
async def get_tenant_conversations(
    tenant_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    """Get all conversations for a tenant (for tenant portal). Requires a
    tenant-user JWT whose ``tenant_id`` claim matches the path parameter.
    """
    from app.models import ChatSession, ChatMessage

    token = _require_tenant_token(authorization)
    if token.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=403, detail="Token does not grant access to this tenant")

    # Verify tenant exists
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Get sessions ordered by most recent
    sessions = db.query(ChatSession).filter(
        ChatSession.tenant_id == tenant_id
    ).order_by(ChatSession.updated_at.desc()).offset(offset).limit(limit).all()
    
    conversations = []
    for session in sessions:
        # Get last message preview
        last_msg = db.query(ChatMessage).filter(
            ChatMessage.session_id == session.id
        ).order_by(ChatMessage.created_at.desc()).first()
        
        # Count messages in session
        msg_count = db.query(ChatMessage).filter(
            ChatMessage.session_id == session.id
        ).count()
        
        preview = None
        if last_msg:
            # Get preview of last user message
            user_msgs = db.query(ChatMessage).filter(
                ChatMessage.session_id == session.id,
                ChatMessage.role == "user"
            ).order_by(ChatMessage.created_at.desc()).first()
            if user_msgs:
                preview = user_msgs.content[:100] + ("..." if len(user_msgs.content) > 100 else "")
        
        conversations.append({
            "session_id": session.id,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            "message_count": msg_count,
            "last_message_preview": preview
        })
    
    total_count = db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id).count()
    
    return {
        "tenant_id": tenant_id,
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "conversations": conversations
    }


@router.get("/conversations/session/{session_id}", response_model=SessionTranscriptResponse)
async def get_session_transcript(
    session_id: str,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    """Get full conversation transcript (for tenant portal). Requires a
    tenant-user JWT whose ``tenant_id`` claim matches the session's tenant.
    """
    from app.models import ChatSession, ChatMessage

    token = _require_tenant_token(authorization)

    # Get session — and confirm it belongs to the caller's tenant before we
    # return any of its content (prevents cross-tenant transcript reads).
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if token.get("tenant_id") != session.tenant_id:
        # Don't leak existence of the session to other tenants.
        raise HTTPException(status_code=404, detail="Session not found")

    # Get all messages in order
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at.asc()).all()
    
    return {
        "session_id": session_id,
        "tenant_id": session.tenant_id,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() + '+00:00' if msg.created_at else None,
                "model_used": msg.model_used,
                "feedback_score": msg.feedback_score
            }
            for msg in messages
        ]
    }


@router.get("/{tenant_id}/analytics")
def tenant_analytics(
    tenant_id: str,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    from app.models import ChatSession, ChatMessage
    from app.models.whatsapp import WhatsAppMessage

    token = _require_tenant_token(authorization)
    if token.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=403, detail="Token does not grant access to this tenant")

    total_sessions = db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id).count()
    total_messages = db.query(ChatMessage).filter(ChatMessage.tenant_id == tenant_id).count()
    wa_messages = db.query(WhatsAppMessage).filter(WhatsAppMessage.tenant_id == tenant_id).count()

    return {
        "total_sessions": total_sessions,
        "total_messages": total_messages + wa_messages,
    }

