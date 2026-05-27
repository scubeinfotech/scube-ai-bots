"""
FastAPI application entry point
"""
import json
import logging
import os
from pathlib import Path
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from app.middleware import DynamicCORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.database import Base, engine
from app.api import tenants, chat, health, analytics, admin, whatsapp, public, calendar, billing, crm, whatsapp_restore, whatsapp_onboarding, whatsapp_test, ics
from app.services.query_analyzer import run_background_scan
from app.services.self_learning import run_daily_learning_job
from app.services.canary_monitor import run_scheduled_canary_job, DEFAULT_INTERVAL_MINUTES
from app.services.followup_scheduler import dispatch_pending_messages
from app.services.website_crawler import WebsiteCrawlerService
from app.services.learning_pipeline import run_full_daily_pipeline


def run_learning_pipeline_job():
    """Run the full self-learning pipeline (scoring → patterns → shadow → rollup → learn).
    Runs daily at 3:00 AM. This is a synchronous wrapper for APScheduler."""
    import asyncio
    try:
        result = asyncio.run(run_full_daily_pipeline())
        logger.info(f"[Scheduler] Learning pipeline completed: {result.get('status')}")
    except Exception as e:
        logger.error(f"[Scheduler] Learning pipeline failed: {e}")


def run_crm_followup_job():
    """Dispatch pending CRM follow-up messages (runs every 5 minutes)."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        sent = dispatch_pending_messages(db)
        if sent:
            logger.info(f"[CRM] Dispatched {sent} follow-up messages")
    except Exception as e:
        logger.error(f"[CRM] Follow-up dispatch error: {e}")
    finally:
        db.close()


async def run_daily_website_crawl():
    """Daily scheduled crawl - updates all active tenants' knowledge base from their websites."""
    from app.database import SessionLocal
    from app.models.tenant import Tenant
    
    logger.info("Starting daily website crawl...")
    db = SessionLocal()
    
    try:
        tenants = db.query(Tenant).filter(
            Tenant.is_active == True,
            Tenant.website_url.isnot(None)
        ).all()
        
        for tenant in tenants:
            try:
                logger.info(f"Crawling {tenant.name} ({tenant.website_url})")
                WebsiteCrawlerService.crawl_and_ingest(
                    tenant.id, 
                    tenant.website_url,
                    include_footer=True  # Include footer contact info
                )
                logger.info(f"✓ Crawled {tenant.name}")
            except Exception as e:
                logger.error(f"✗ Crawl failed for {tenant.name}: {e}")
        
        logger.info("Daily website crawl completed")
    finally:
        db.close()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = None

NO_CACHE_HTML_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _serve_html_no_cache(path: Path):
    """Serve HTML pages with no-cache headers so dashboard updates appear immediately."""
    return FileResponse(path, media_type="text/html", headers=NO_CACHE_HTML_HEADERS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for the FastAPI application.
    Handles startup and shutdown events.
    """
    # Startup: Initialize background job scheduler
    global scheduler
    scheduler = BackgroundScheduler()
    
    # Schedule the unanswered query scanner
    # Runs every 15 minutes to analyze recent conversations
    scheduler.add_job(
        run_background_scan,
        trigger=IntervalTrigger(minutes=15),
        id="unanswered_query_scanner",
        name="Scan and populate unanswered queries",
        replace_existing=True
    )

    # Schedule daily self-learning job
    # Runs at 2:00 AM every day — reads yesterday's conversations,
    # extracts high-quality Q&A pairs, and indexes them per tenant.
    scheduler.add_job(
        run_daily_learning_job,
        trigger=CronTrigger(hour=2, minute=0),
        id="daily_self_learning",
        name="Daily self-learning: extract Q&A pairs from conversations",
        replace_existing=True
    )

    # Schedule full learning pipeline
    # Runs at 3:00 AM — scores responses, detects patterns, shadows variants,
    # aggregates metrics, and runs the existing self-learning.
    scheduler.add_job(
        run_learning_pipeline_job,
        trigger=CronTrigger(hour=3, minute=0),
        id="learning_pipeline",
        name="Self-learning pipeline: scoring, patterns, shadow eval, rollup",
        replace_existing=True,
    )

    # Schedule daily website crawl
    # Runs at 3:00 AM every day — crawls all tenant websites
    # to auto-update address, services, contact info, etc.
    scheduler.add_job(
        run_daily_website_crawl,
        trigger=CronTrigger(hour=3, minute=0),
        id="daily_website_crawl",
        name="Daily website crawl: auto-update knowledge base",
        replace_existing=True
    )

    # Schedule leak canary monitor (runtime-toggleable from admin API).
    scheduler.add_job(
        run_scheduled_canary_job,
        trigger=IntervalTrigger(minutes=DEFAULT_INTERVAL_MINUTES),
        id="chat_leak_canary",
        name="Chat leak canary monitor",
        replace_existing=True,
    )

    # Schedule CRM follow-up dispatch (runs every 5 minutes).
    scheduler.add_job(
        run_crm_followup_job,
        trigger=IntervalTrigger(minutes=5),
        id="crm_followup_dispatch",
        name="CRM follow-up message dispatch",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("✓ Background scheduler started - scanning for unanswered queries every 15 minutes")
    logger.info("✓ Self-learning job scheduled — runs daily at 02:00 AM")
    logger.info("✓ Learning pipeline scheduled — runs daily at 03:00 AM (scoring, patterns, shadow eval, rollup)")
    logger.info("✓ Website crawl scheduled — runs daily at 04:00 AM (auto-update knowledge base)")
    logger.info("✓ Canary monitor scheduled — runs every %d minute(s) when enabled", DEFAULT_INTERVAL_MINUTES)
    
    # Skip initial scan on startup to speed up server startup
    # The scheduled job will run every 15 minutes anyway
    # try:
    #     logger.info("Running initial unanswered query scan...")
    #     run_background_scan()
    # except Exception as e:
    #     logger.error(f"Initial scan failed (will retry on schedule): {str(e)}")
    logger.info("Skipping initial scan - will run on schedule")

    # Warm up the embedding model on startup so the first chat request
    # doesn't pay the 30-90s sentence-transformers lazy-load cost.
    try:
        from app.services.embedding_provider import EmbeddingService
        logger.info("[Startup] Warming up embedding model (may take a moment)...")
        emb = EmbeddingService.instance()
        vec = emb.embed("warmup initialization vector")
        if vec:
            logger.info("[Startup] Embedding model ready (dim=%d)", len(vec))
        else:
            logger.warning("[Startup] Embedding model returned empty vector")
    except Exception as exc:
        logger.warning("[Startup] Embedding warmup failed (will lazy-load later): %s", exc)

    yield
    
    # Shutdown: Stop the scheduler
    if scheduler:
        scheduler.shutdown()
        logger.info("✓ Background scheduler stopped")


def parse_allowed_origins(raw_value: str):
    """Accept '*', JSON array, or comma-separated origins."""
    if not raw_value:
        return ["*"]
    stripped = raw_value.strip()
    if stripped == "*":
        return ["*"]
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list) and parsed:
                return parsed
        except json.JSONDecodeError:
            pass
    return [item.strip() for item in stripped.split(",") if item.strip()] or ["*"]


allowed_origins = parse_allowed_origins(settings.allowed_origins)

# Create tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    debug=settings.debug,
    lifespan=lifespan
)

# Dynamic CORS — allow each active tenant's domain (and per-API-key
# allowed_domains) automatically, plus the static base list above. This means
# onboarding a new tenant in the admin UI is enough; no .env edit or restart
# is required for the chat widget to work on their site.
app.add_middleware(
    DynamicCORSMiddleware,
    static_origins=allowed_origins,
    cache_ttl=60,
    allow_credentials=True,
)


@app.middleware("http")
async def widget_cache_control(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/static/widget.js", "/static/widget.html"} or request.url.path.startswith("/chat/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.middleware("http")
async def request_size_limit(request: Request, call_next):
    """Limit request body size to prevent DoS attacks.
    
    Default: 2MB (2097152 bytes)
    - Chat messages: typically <1KB
    - Tenant creation: knowledge_context may be up to 100KB (validated by Pydantic)
    - File uploads: handled separately
    
    This is a safety net - won't affect normal usage.
    """
    MAX_SIZE = int(os.getenv("MAX_REQUEST_SIZE", "2097152"))  # 2MB default
    
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_SIZE:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request too large. Maximum size: {MAX_SIZE // 1024}KB"}
                )
        except ValueError:
            pass  # Ignore invalid content-length
    
    return await call_next(request)

# Mount static files for widget hosting
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include routers
routers = [tenants.router, chat.router, health.router, analytics.router, admin.router, whatsapp.router, public.router, calendar.router, billing.router, crm.router, whatsapp_restore.router, whatsapp_onboarding.router, whatsapp_test.router, ics.router]
for router in routers:
    app.include_router(router)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "version": settings.api_version,
        "environment": settings.environment
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Centralized LLM Platform API",
        "version": settings.api_version,
        "docs": "/docs"
    }


@app.get("/dashboard")
async def dashboard():
    """Tenant-facing entrypoint now requires tenant login."""
    return RedirectResponse(url="/tenant/login", status_code=307)



@app.get("/tenant/login")
async def tenant_login_page():
    """Tenant login page alias — delegates to /public/login handler."""
    return await public_login_page()




# Use absolute path for static HTML files
STATIC_DIR = Path(__file__).parent.parent.resolve() / "static"

@app.get("/public/dashboard")
async def public_dashboard_page(tenant_id: str = ""):
    """Serve tenant dashboard page."""
    path = STATIC_DIR / "tenant" / "dashboard.html"
    if path.exists():
        return _serve_html_no_cache(path)
    return {"error": "Tenant dashboard page not found"}

@app.get("/tenant/dashboard")
async def tenant_dashboard_page(tenant_id: str = ""):
    return await public_dashboard_page(tenant_id)





@app.get("/public/conversations")
async def public_conversations_page():
    """Serve tenant conversations page."""
    conversations_path = STATIC_DIR / "tenant-conversations.html"
    if conversations_path.exists():
        return _serve_html_no_cache(conversations_path)
    return {"error": "Conversations page not found"}

@app.get("/tenant/conversations")
async def tenant_conversations_page():
    return await public_conversations_page()





@app.get("/public/leads")
async def public_leads_page():
    """Serve tenant WhatsApp leads page."""
    leads_path = STATIC_DIR / "tenant-leads.html"
    if leads_path.exists():
        return _serve_html_no_cache(leads_path)
    return {"error": "Leads page not found"}

@app.get("/tenant/leads")
async def tenant_leads_page():
    return await public_leads_page()





@app.get("/public/session/{session_id}")
async def public_chat_session_page(session_id: str):
    """Serve chat session transcript page."""
    session_path = STATIC_DIR / "session-transcript.html"
    if session_path.exists():
        return FileResponse(session_path, media_type="text/html")

@app.get("/chat/session/{session_id}")
async def chat_session_page(session_id: str):
    return await public_chat_session_page(session_id)


@app.get("/chat/{slug}")
async def chat_page(slug: str):
    """Serve chat widget page for tenant."""
    widget_path = Path(__file__).parent.parent / "static" / "widget.html"
    if widget_path.exists():
        return FileResponse(widget_path, media_type="text/html")
    return {"error": "Chat widget page not found"}



# Always redirect /admin to the new dashboard
@app.get("/admin")
async def admin_dashboard():
    return RedirectResponse(url="/admin/dashboard", status_code=307)


@app.get("/onboarding")
async def onboarding_page():
    """Serve public onboarding form for new tenants"""
    onboarding_path = Path(__file__).parent.parent / "static" / "onboarding-form.html"
    if onboarding_path.exists():
        return _serve_html_no_cache(onboarding_path)
    return {"error": "Onboarding form not found"}


# ---- New self-service public pages ----

@app.get("/public/register")
async def public_register_page():
    """Self-service tenant registration page"""
    path = Path(__file__).parent.parent / "static" / "public" / "register.html"
    if path.exists():
        return _serve_html_no_cache(path)
    return {"error": "Registration page not found"}


@app.get("/public/login")
async def public_login_page():
    """Tenant login page"""
    path = Path(__file__).parent.parent / "static" / "public" / "login.html"
    if path.exists():
        return _serve_html_no_cache(path)
    return {"error": "Login page not found"}


@app.get("/public/pricing")
async def public_pricing_page():
    """Pricing page"""
    path = Path(__file__).parent.parent / "static" / "public" / "pricing.html"
    if path.exists():
        return _serve_html_no_cache(path)
    return {"error": "Pricing page not found"}


@app.get("/admin/dashboard")
async def new_admin_dashboard_page():
    """Serve new admin dashboard page"""
    path = Path(__file__).parent.parent / "static" / "admin" / "dashboard.html"
    if path.exists():
        return _serve_html_no_cache(path)
    # Fallback to old admin dashboard
    old_path = Path(__file__).parent.parent / "static" / "admin-dashboard.html"
    if old_path.exists():
        return _serve_html_no_cache(old_path)
    return {"error": "Admin dashboard not found"}


@app.get("/SCUBE_AI_PLATFORM.html")
async def scube_ai_platform_page():
    path = Path(__file__).parent.parent / "static" / "SCUBE_AI_PLATFORM.html"
    if path.exists():
        return FileResponse(str(path), media_type="text/html")
    return {"error": "Page not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info" if not settings.debug else "debug"
    )
