"""
Health check endpoints
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
import time
import os

router = APIRouter(prefix="/api/health", tags=["Health"])


class ProviderHealthTracker:
    """Track health status of LLM providers"""
    _instance = None
    _providers = {}

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def record_call(self, provider: str, success: bool, latency_ms: int):
        if provider not in self._providers:
            self._providers[provider] = {
                "total_calls": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "total_latency_ms": 0,
                "last_success": None,
                "last_failure": None,
                "consecutive_failures": 0,
            }
        p = self._providers[provider]
        p["total_calls"] += 1
        p["total_latency_ms"] += latency_ms
        if success:
            p["successful_calls"] += 1
            p["consecutive_failures"] = 0
            p["last_success"] = time.time()
        else:
            p["failed_calls"] += 1
            p["consecutive_failures"] += 1
            p["last_failure"] = time.time()

    def get_health(self, provider: str) -> dict:
        p = self._providers.get(provider, {})
        if not p:
            return {"status": "unknown", "calls": 0}

        avg_latency = p["total_latency_ms"] / max(p["total_calls"], 1)
        success_rate = (p["successful_calls"] / max(p["total_calls"], 1)) * 100

        status = "healthy"
        if p.get("consecutive_failures", 0) >= 3:
            status = "circuit_open"
        elif success_rate < 50:
            status = "degraded"

        return {
            "status": status,
            "calls": p.get("total_calls", 0),
            "success_rate": round(success_rate, 1),
            "avg_latency_ms": round(avg_latency),
            "consecutive_failures": p.get("consecutive_failures", 0),
            "last_success": p.get("last_success"),
            "last_failure": p.get("last_failure"),
        }

    def get_all_health(self) -> dict:
        return {
            "groq": self.get_health("groq"),
            "gemini": self.get_health("gemini"),
            "openrouter": self.get_health("openrouter"),
        }


_provider_health = ProviderHealthTracker.get_instance()


def get_provider_health_tracker():
    return _provider_health


@router.get("")
async def health(db: Session = Depends(get_db)):
    """Platform health status with component checks"""
    start = time.time()
    
    # Check database
    db_status = "ok"
    db_latency_ms = 0
    try:
        db_start = time.time()
        db.execute(text("SELECT 1"))
        db_latency_ms = int((time.time() - db_start) * 1000)
    except Exception as e:
        db_status = f"error: {str(e)[:50]}"
    
    total_ms = int((time.time() - start) * 1000)
    
    return {
        "status": "healthy" if db_status == "ok" else "degraded",
        "version": "1.0.0",
        "latency_ms": total_ms,
        "components": {
            "api": "ok",
            "database": db_status,
            "database_latency_ms": db_latency_ms,
            "llm": "ok"
        }
    }


@router.get("/providers")
async def health_providers():
    """Check health status of all LLM providers"""
    tracker = get_provider_health_tracker()

    providers = tracker.get_all_health()

    overall_status = "healthy"
    for name, health in providers.items():
        if health.get("status") == "circuit_open":
            overall_status = "degraded"
            break
        if health.get("status") == "degraded":
            overall_status = "degraded"

    return {
        "status": overall_status,
        "providers": providers,
        "config": {
            "primary": os.getenv("LLM_PRIMARY", "groq"),
            "secondary": os.getenv("LLM_SECONDARY", "gemini"),
            "tertiary": os.getenv("LLM_TERTIARY", "openrouter"),
            "routing_mode": os.getenv("LLM_ROUTING_MODE", "fallback"),
            "gemini_model": os.getenv("LLM_GEMINI_MODEL", "gemini-2.5-flash-lite"),
            "groq_model": os.getenv("LLM_GROQ_MODEL", "llama-3.3-70b-versatile"),
            "gemini_percent": os.getenv("LLM_GEMINI_PERCENT", "30"),
        },
        "gemini_quota": {
            "daily_limit": 1000,
            "note": "Auto-fallback to Groq when limit reached"
        }
    }
