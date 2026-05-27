"""
Public API endpoints — self-service tenant registration and login.
No admin intervention required. Zero changes to existing chatbot code.
"""
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session
from typing import Optional

import jwt as pyjwt

from app.database import get_db
from app.services.auth_service import SECRET_KEY, ALGORITHM
from app.models import Tenant, TenantUser, APIKey, SubscriptionPlan
from app.services.auth_service import hash_password, verify_password, create_access_token
from app.services.website_crawler import WebsiteCrawlerService
from app.services.email_service import send_email
import jwt

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["Public"])


# --------------------------------------------------------------------------- #
# Request / Response schemas
# --------------------------------------------------------------------------- #

class RegisterRequest(BaseModel):
    business_name: str
    contact_email: str
    website_url: str
    password: str
    industry: Optional[str] = "other"

    @field_validator("business_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Business name is required")
        return v.strip()

    @field_validator("contact_email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", v):
            raise ValueError("Invalid email address")
        return v.strip().lower()

    @field_validator("website_url")
    @classmethod
    def valid_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v


class RegisterResponse(BaseModel):
    status: str
    tenant_id: str
    tenant_slug: str
    message: str
    dashboard_url: str
    widget_snippet: str
    email_verification_sent: bool = True


class LoginTenantInfo(BaseModel):
    tenant_id: str
    tenant_name: str
    tenant_slug: str
    subscription_plan: str
    trial_ends_at: Optional[str]
    dashboard_url: str


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    email: str
    tenants: list[LoginTenantInfo]


class ForgotPasswordRequest(BaseModel):
    email: str


class VerifyEmailResponse(BaseModel):
    status: str
    message: str


class SwitchTenantRequest(BaseModel):
    tenant_id: str


class SwitchTenantResponse(BaseModel):
    token: str
    tenant_id: str
    tenant_name: str
    tenant_slug: str
    dashboard_url: str


class PlansResponse(BaseModel):
    plans: list[dict]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _generate_slug(business_name: str, db: Session) -> str:
    """Generate a unique slug from business name."""
    slug = re.sub(r"[^a-z0-9]+", "-", business_name.lower().strip()).strip("-")
    if not slug:
        slug = f"tenant-{uuid.uuid4().hex[:8]}"

    # If slug exists, append a number
    base = slug
    counter = 1
    while db.query(Tenant).filter(Tenant.slug == slug).first():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _get_default_trial_days(db: Session) -> int:
    """Get trial days from the default plan (configurable from admin panel)."""
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.name == "trial",
        SubscriptionPlan.is_active == True
    ).first()
    return plan.trial_days if plan else 7


async def _send_verification_email(email: str, business_name: str, token: str, base_url: str):
    """Send verification email with verification link."""
    verify_url = f"{base_url}/api/public/verify-email?token={token}"
    try:
        await send_email(
            to=email,
            subject=f"Verify your email — SCUBE AI, {business_name}!",
            html_body=f"""
            <h2>Welcome to SCUBE AI! 🎉</h2>
            <p>Your AI chatbot account for <strong>{business_name}</strong> is almost ready.</p>
            <p>Please verify your email address by clicking the button below:</p>
            <p><a href="{verify_url}" style="display:inline-block;padding:12px 24px;background:#667eea;color:#fff;text-decoration:none;border-radius:8px;">Verify Email Address</a></p>
            <p>If the button does not work, copy and paste this link into your browser:</p>
            <p style="word-break:break-all;font-size:13px;color:#667eea;">{verify_url}</p>
            <p>Once verified, you can log in and access your dashboard.</p>
            <p>Your 7-day free trial starts after verification. No payment required!</p>
            <hr>
            <p style="color:#999;font-size:12px;">SCUBE AI — Intelligent Chatbots for Every Business</p>
            """,
        )
        logger.info(f"[Public] Verification email sent to {email}")
    except Exception as e:
        logger.warning(f"[Public] Failed to send verification email to {email}: {e}")


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@router.post("/register", response_model=RegisterResponse)
async def register_tenant(request: Request, payload: RegisterRequest, db: Session = Depends(get_db), background_tasks: BackgroundTasks = None):
    """
    Self-service tenant registration.
    Auto-creates tenant, user, API key, starts website crawl, sends welcome email, and returns widget snippet.
    """
    # Check if email is already registered
    existing_user = db.query(TenantUser).filter(
        TenantUser.email == payload.contact_email.lower().strip()
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="This email is already registered. Please log in instead.")

    # Check if website already belongs to a tenant
    bare_host = payload.website_url.lower().replace("http://", "").replace("https://", "").split("/")[0].replace("www.", "")
    existing_tenant = db.query(Tenant).filter(
        Tenant.domain == bare_host
    ).first()
    if existing_tenant:
        raise HTTPException(status_code=400, detail="This website is already registered. Please contact support.")

    # Soft-check website reachability — warn but don't block registration
    import requests
    try:
        resp = requests.get(payload.website_url, timeout=6)
        if resp.status_code >= 400:
            logger.warning(f"[Public] Website {payload.website_url} returned status {resp.status_code}")
    except Exception as e:
        logger.warning(f"[Public] Could not reach website {payload.website_url}: {e}")

    # Generate unique slug
    slug = _generate_slug(payload.business_name, db)

    # Get trial days from admin-configurable plan
    trial_days = _get_default_trial_days(db)
    trial_ends = datetime.now(timezone.utc) + timedelta(days=trial_days)

    # Create tenant
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name=payload.business_name,
        slug=slug,
        domain=bare_host,
        website_url=payload.website_url,
        contact_email=payload.contact_email,
        industry=payload.industry or "other",
        subscription_tier="starter",
        subscription_plan="trial",
        subscription_status="active",
        trial_ends_at=trial_ends,
        model_name="llama-3.3-70b-versatile",
        temperature="0.7",
        max_tokens="1024",
        onboarding_stage="discovering",
        is_active=True,
    )
    db.add(tenant)
    db.flush()

    # Create tenant user
    username = payload.contact_email.split("@")[0]
    # Ensure username uniqueness
    base_username = username
    counter = 1
    while db.query(TenantUser).filter(TenantUser.username == username).first():
        username = f"{base_username}{counter}"
        counter += 1

    # Generate verification token
    verification_token = secrets.token_urlsafe(32)

    user = TenantUser(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        username=username,
        email=payload.contact_email,
        hashed_password=hash_password(payload.password),
        role="tenant_admin",
        is_active=True,
        email_verified=False,
        verification_token=verification_token,
    )
    db.add(user)
    db.flush()

    # Create API key for widget
    api_key = APIKey(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        key=f"sk_{tenant.slug}_{uuid.uuid4().hex[:24]}",
        name="Default Widget Key",
        is_active=True,
        allowed_domains=bare_host,
    )
    db.add(api_key)
    db.commit()

    # Queue website crawl in background
    if background_tasks is not None:
        try:
            WebsiteCrawlerService.queue_crawl(
                background_tasks, tenant.id, payload.website_url, include_footer=True
            )
            logger.info(f"[Public] Crawl queued for {tenant.name} ({payload.website_url})")
        except Exception as e:
            logger.warning(f"[Public] Failed to queue crawl for {tenant.id}: {e}")

    # Send verification email
    base_url = str(request.base_url).rstrip("/")
    await _send_verification_email(payload.contact_email, payload.business_name, verification_token, base_url)


    logger.info(f"[Public] New tenant registered: {tenant.name} ({tenant.slug}) by {payload.contact_email}")


    # Build widget snippet with placement comments
    widget_url = f"{base_url}/static/widget.js"
    widget_snippet = (
        f'<!-- 💬 SCUBE AI Chatbot Widget - Paste this before </body> on every page -->\n'
        f'<script id="scube-widget"\n'
        f'    src="{widget_url}"\n'
        f'    data-tenant-id="{tenant.id}"\n'
        f'    data-api-key="{api_key.key}"\n'
        f'    data-domain="{bare_host}"\n'
        f'    async></script>\n'
        f'<!--\n'
        f'  🔧 To change widget position (default: bottom-right):\n'
        f'     data-position="left"       → bottom-left\n'
        f'     data-position="top-right"   → top-right\n'
        f'     data-position="top-left"    → top-left\n'
        f'  Example:\n'
        f'  <script id="scube-widget" ... data-position="left"></script>\n'
        f'-->'
    )

    return RegisterResponse(
        status="success",
        tenant_id=tenant.id,
        tenant_slug=slug,
        message=f"Registration successful! Please check your email ({payload.contact_email}) to verify your account before logging in.",
        dashboard_url="/public/login",
        widget_snippet=widget_snippet,
        email_verification_sent=True,
    )


@router.get("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(token: str, db: Session = Depends(get_db)):
    """Verify tenant email address using verification token."""
    user = db.query(TenantUser).filter(TenantUser.verification_token == token).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link.")

    if user.email_verified:
        return VerifyEmailResponse(
            status="success",
            message="Email already verified. You can now log in."
        )

    user.email_verified = True
    user.verification_token = None
    db.commit()

    logger.info(f"[Public] Email verified for {user.email}")

    return VerifyEmailResponse(
        status="success",
        message="Email verified successfully! You can now log in to your dashboard."
    )


@router.post("/login", response_model=LoginResponse)
async def login_tenant(payload: LoginRequest, db: Session = Depends(get_db)):
    """Tenant login — returns JWT token + list of accessible tenants."""
    email = payload.email.strip().lower()

    # Find all users for this email
    users = db.query(TenantUser).filter(TenantUser.email == email).all()
    if not users:
        raise HTTPException(status_code=401, detail="Invalid email or password. Please check your credentials.")

    # Check at least one user is active
    active_users = [u for u in users if u.is_active]
    if not active_users:
        raise HTTPException(status_code=403, detail="Your account is deactivated. Please contact support or your administrator.")

    # Verify password against the first active user (all share the same password)
    if not verify_password(payload.password, active_users[0].hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password. Please check your credentials.")

    # Check email verification — at least one must be verified to proceed
    verified_users = [u for u in active_users if u.email_verified]
    if not verified_users:
        raise HTTPException(
            status_code=403,
            detail="Your email address is not verified. Please check your inbox (and spam folder) for the verification link."
        )

    # Build tenant list from all verified active users
    tenants_info = []
    for u in verified_users:
        t = db.query(Tenant).filter(Tenant.id == u.tenant_id).first()
        if t and t.is_active:
            trial_ends_str = t.trial_ends_at.isoformat() if t.trial_ends_at else None
            tenants_info.append(LoginTenantInfo(
                tenant_id=t.id,
                tenant_name=t.name,
                tenant_slug=t.slug,
                subscription_plan=t.subscription_plan or "trial",
                trial_ends_at=trial_ends_str,
                dashboard_url=f"/public/dashboard?tenant_id={t.id}",
            ))

    if not tenants_info:
        raise HTTPException(status_code=403, detail="No active tenants found for this account. Please contact support.")

    # Pick the first tenant as the primary context for the JWT
    primary = verified_users[0]
    primary_tenant = db.query(Tenant).filter(Tenant.id == primary.tenant_id).first()

    # Update last login for all verified users
    now = datetime.now(timezone.utc)
    for u in verified_users:
        u.last_login_at = now
    db.commit()

    # Generate JWT token scoped to the primary tenant
    token = create_access_token(
        data={
            "sub": primary.id,
            "tenant_id": primary_tenant.id,
            "tenant_slug": primary_tenant.slug,
            "role": primary.role,
        }
    )

    return LoginResponse(
        token=token,
        email=email,
        tenants=tenants_info,
    )


@router.post("/switch-tenant", response_model=SwitchTenantResponse)
async def switch_tenant(payload: SwitchTenantRequest, authorization: str = Header(default=""), db: Session = Depends(get_db)):
    """Switch to a different tenant under the same email account."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        token_payload = jwt.decode(authorization[7:], SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    current_user_id = token_payload.get("sub")
    if not current_user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload.")

    # Find the current user to get their email
    current_user = db.query(TenantUser).filter(TenantUser.id == current_user_id).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Find the TenantUser record for the target tenant with the same email
    target_user = db.query(TenantUser).filter(
        TenantUser.tenant_id == payload.tenant_id,
        TenantUser.email == current_user.email,
    ).first()
    if not target_user or not target_user.is_active or not target_user.email_verified:
        raise HTTPException(status_code=403, detail="Access denied to this tenant.")

    tenant = db.query(Tenant).filter(Tenant.id == payload.tenant_id).first()
    if not tenant or not tenant.is_active:
        raise HTTPException(status_code=403, detail="Tenant is not active.")

    # Generate new token scoped to this tenant
    token = create_access_token(
        data={
            "sub": target_user.id,
            "tenant_id": tenant.id,
            "tenant_slug": tenant.slug,
            "role": target_user.role,
        }
    )

    return SwitchTenantResponse(
        token=token,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        tenant_slug=tenant.slug,
        dashboard_url=f"/public/dashboard?tenant_id={tenant.id}",
    )


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Send password reset email to tenant user."""
    email = payload.email.strip().lower()
    user = db.query(TenantUser).filter(TenantUser.email == email).first()

    # Always return success to prevent email enumeration
    if user:
        # TODO: Generate reset token and send email
        logger.info(f"[Public] Password reset requested for {email}")

    return {"status": "success", "message": "If an account exists with that email, a reset link has been sent."}


@router.get("/plans", response_model=PlansResponse)
async def get_plans(db: Session = Depends(get_db)):
    """List active subscription plans (for pricing page)."""
    plans = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.is_active == True
    ).order_by(SubscriptionPlan.price_monthly).all()

    return PlansResponse(
        plans=[
            {
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "price_monthly": p.price_monthly,
                "price_annual": p.price_annual,
                "currency": p.currency,
                "trial_days": p.trial_days,
                "includes_chatbot": p.includes_chatbot,
                "includes_whatsapp": p.includes_whatsapp,
                "monthly_message_limit": p.monthly_message_limit,
                "max_documents": p.max_documents,
                "priority_support": p.priority_support,
                "features": p.features,
            }
            for p in plans
        ]
    )


@router.get("/trial/status/{tenant_id}")
async def get_trial_status(tenant_id: str, db: Session = Depends(get_db)):
    """Check remaining trial days for a tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if not tenant.trial_ends_at:
        return {
            "tenant_id": tenant_id,
            "subscription_plan": tenant.subscription_plan or "trial",
            "trial_active": True,
            "days_remaining": None,
            "trial_ends_at": None,
        }

    now = datetime.now(timezone.utc)
    ends = tenant.trial_ends_at
    if ends.tzinfo is None:
        ends = ends.replace(tzinfo=timezone.utc)

    days_remaining = max(0, (ends - now).days)
    trial_active = days_remaining > 0

    return {
        "tenant_id": tenant_id,
        "subscription_plan": tenant.subscription_plan or "trial",
        "trial_active": trial_active,
        "days_remaining": days_remaining,
        "trial_ends_at": tenant.trial_ends_at.isoformat(),
    }


# --------------------------------------------------------------------------- #
# Google OAuth
# --------------------------------------------------------------------------- #

@router.get("/auth/google")
async def google_oauth_redirect():
    """Redirect to Google OAuth consent screen."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    from urllib.parse import urlencode
    google_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"
    return RedirectResponse(url=google_url)


@router.get("/auth/google/callback")
async def google_oauth_callback(
    code: str = None,
    error: str = None,
    db: Session = Depends(get_db),
):
    """Handle Google OAuth callback — create or log in tenant user."""
    if error:
        logger.warning(f"[Google OAuth] Error from Google: {error}")
        return RedirectResponse(url="/public/login?error=" + error)

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")

    # Exchange code for tokens
    import requests
    token_resp = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=10)

    if not token_resp.ok:
        logger.error(f"[Google OAuth] Token exchange failed: {token_resp.text}")
        return RedirectResponse(url="/public/login?error=token_exchange_failed")

    token_data = token_resp.json()
    id_token = token_data.get("id_token")

    if not id_token:
        logger.error("[Google OAuth] No id_token in response")
        return RedirectResponse(url="/public/login?error=no_id_token")

    # Decode id_token to get user info
    import jwt as pyjwt_inner
    user_info = pyjwt_inner.decode(id_token, options={"verify_signature": False})
    google_email = user_info.get("email", "").strip().lower()
    google_name = user_info.get("name", google_email.split("@")[0])

    if not google_email:
        logger.error("[Google OAuth] No email in id_token")
        return RedirectResponse(url="/public/login?error=no_email")

    # Check if user exists by email
    users = db.query(TenantUser).filter(TenantUser.email == google_email).all()

    if users:
        # User exists — log them in
        active_users = [u for u in users if u.is_active]
        if not active_users:
            return RedirectResponse(url="/public/login?error=account_deactivated")

        primary = active_users[0]
        primary_tenant = db.query(Tenant).filter(Tenant.id == primary.tenant_id).first()
        if not primary_tenant or not primary_tenant.is_active:
            return RedirectResponse(url="/public/login?error=tenant_inactive")

        now = datetime.now(timezone.utc)
        for u in active_users:
            u.last_login_at = now
        db.commit()

        token = create_access_token(data={
            "sub": primary.id,
            "tenant_id": primary_tenant.id,
            "tenant_slug": primary_tenant.slug,
            "role": primary.role,
        })

        dashboard_url = f"/public/dashboard?tenant_id={primary_tenant.id}&token={token}"
        return RedirectResponse(url=dashboard_url)
    else:
        # New user — create tenant + user
        slug = _generate_slug(google_name, db)
        trial_days = _get_default_trial_days(db)
        trial_ends = datetime.now(timezone.utc) + timedelta(days=trial_days)

        tenant = Tenant(
            id=str(uuid.uuid4()),
            name=google_name,
            slug=slug,
            domain="",
            website_url="",
            contact_email=google_email,
            industry="other",
            subscription_tier="starter",
            subscription_plan="trial",
            subscription_status="active",
            trial_ends_at=trial_ends,
            model_name="llama-3.3-70b-versatile",
            temperature="0.7",
            max_tokens="1024",
            onboarding_stage="discovering",
            is_active=True,
        )
        db.add(tenant)
        db.flush()

        # Auto-verified since Google verified their email
        user = TenantUser(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            username=google_email.split("@")[0],
            email=google_email,
            hashed_password="",  # No password — Google OAuth only
            role="tenant_admin",
            is_active=True,
            email_verified=True,
        )
        db.add(user)
        db.flush()

        # Create widget API key
        api_key = APIKey(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            key=f"sk_{slug}_{uuid.uuid4().hex[:24]}",
            name="Default Widget Key",
            is_active=True,
            allowed_domains=None,
        )
        db.add(api_key)
        db.commit()

        token = create_access_token(data={
            "sub": user.id,
            "tenant_id": tenant.id,
            "tenant_slug": tenant.slug,
            "role": user.role,
        })

        dashboard_url = f"/public/dashboard?tenant_id={tenant.id}&token={token}"
        return RedirectResponse(url=dashboard_url)
