"""
Chat Leak Canary Monitor

Periodically sends a lightweight chat message through the live API endpoint and
checks whether customer-visible response text accidentally exposes technical
errors (provider names, billing codes, stack traces, etc.).

Control model:
- Enabled/disabled state is persisted in a local JSON state file.
- Scheduler can call run_scheduled_canary_job() at fixed intervals.
- Admin endpoints can trigger an ad-hoc check immediately.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.database import SessionLocal
from app.models import APIKey, Tenant

logger = logging.getLogger(__name__)

STATE_DIR = Path(__file__).resolve().parents[2] / ".runtime"
STATE_FILE = STATE_DIR / "canary_state.json"
MAX_HISTORY = 20
DEFAULT_INTERVAL_MINUTES = int(os.getenv("CANARY_INTERVAL_MINUTES", "10"))
DEFAULT_BASE_URL = os.getenv("CANARY_BASE_URL", "http://127.0.0.1:8001")
DEFAULT_TEST_MESSAGE = os.getenv(
    "CANARY_TEST_MESSAGE",
    "Hello, this is system quality check. Please reply briefly.",
)

LEAK_TOKENS = [
    "insufficient credits",
    "all providers failed",
    "openrouter",
    "groq api returned",
    "openai api returned",
    "gemini api returned",
    "traceback",
    "internal error",
    "status_code",
    "error:",
    "api returned 402",
    "api returned 429",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> Dict[str, Any]:
    return {
        "enabled": False,
        "interval_minutes": DEFAULT_INTERVAL_MINUTES,
        "base_url": DEFAULT_BASE_URL,
        "last_run_at": None,
        "last_status": "never",
        "last_trigger": None,
        "last_issue": None,
        "last_http_status": None,
        "last_tenant_id": None,
        "last_tenant_name": None,
        "last_response_preview": None,
        "run_count": 0,
        "failure_count": 0,
        "leak_count": 0,
        "history": [],
    }


def _read_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return _default_state()
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state = _default_state()
        if isinstance(raw, dict):
            state.update(raw)
        if not isinstance(state.get("history"), list):
            state["history"] = []
        return state
    except Exception as exc:
        logger.warning("[Canary] Failed to read state file, resetting: %s", exc)
        return _default_state()


def _write_state(state: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_canary_state() -> Dict[str, Any]:
    return _read_state()


def set_canary_enabled(enabled: bool) -> Dict[str, Any]:
    state = _read_state()
    state["enabled"] = bool(enabled)
    state["updated_at"] = _now_iso()
    _write_state(state)
    return state


def _append_history(state: Dict[str, Any], item: Dict[str, Any]) -> None:
    history = state.get("history") or []
    history.insert(0, item)
    state["history"] = history[:MAX_HISTORY]


def _pick_active_tenant_api_key(db) -> tuple[APIKey | None, Tenant | None]:
    row = (
        db.query(APIKey, Tenant)
        .join(Tenant, Tenant.id == APIKey.tenant_id)
        .filter(APIKey.is_active == True)
        .filter(Tenant.is_active == True)
        .order_by(APIKey.created_at.desc())
        .first()
    )
    if not row:
        return None, None
    return row[0], row[1]


def _detect_leaks(text: str) -> List[str]:
    lowered = (text or "").lower()
    return [token for token in LEAK_TOKENS if token in lowered]


def run_canary_check(trigger: str = "adhoc") -> Dict[str, Any]:
    """Run one canary check and persist status. Returns latest state payload."""
    state = _read_state()
    db = SessionLocal()

    run_at = _now_iso()
    status = "ok"
    issue = None
    http_status = None
    tenant_id = None
    tenant_name = None
    response_preview = None
    used_base_url = None

    try:
        api_key, tenant = _pick_active_tenant_api_key(db)
        if not api_key or not tenant:
            status = "failed"
            issue = "No active tenant API key found"
        else:
            tenant_id = tenant.id
            tenant_name = tenant.name

            configured_base = state.get("base_url", DEFAULT_BASE_URL)
            candidate_base_urls = []
            for base in [configured_base, DEFAULT_BASE_URL, "http://127.0.0.1:8000", "http://localhost:8000"]:
                if base and base not in candidate_base_urls:
                    candidate_base_urls.append(base)

            body = json.dumps({
                "content": DEFAULT_TEST_MESSAGE,
                "user_id": "canary-monitor",
            }).encode("utf-8")

            raw = ""
            last_network_error = None
            for base_url in candidate_base_urls:
                url = f"{base_url}/api/chat/message/{tenant.id}"
                req = urllib_request.Request(
                    url,
                    data=body,
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "X-API-Key": api_key.key,
                    },
                )
                try:
                    with urllib_request.urlopen(req, timeout=25) as resp:
                        http_status = resp.status
                        raw = resp.read().decode("utf-8", errors="ignore")
                        used_base_url = base_url
                        break
                except urllib_error.HTTPError as err:
                    http_status = err.code
                    raw = err.read().decode("utf-8", errors="ignore")
                    used_base_url = base_url
                    break
                except Exception as exc:
                    last_network_error = exc
                    continue

            if used_base_url is None and last_network_error is not None:
                raise RuntimeError(str(last_network_error))

            response_preview = (raw or "")[:400]
            leaks = _detect_leaks(raw)
            if leaks:
                status = "leak_detected"
                issue = f"Leak tokens found: {', '.join(leaks)}"
            elif http_status is None or int(http_status) >= 500:
                status = "failed"
                issue = f"Canary endpoint returned HTTP {http_status}"

    except Exception as exc:
        status = "failed"
        issue = f"Canary execution error: {exc}"
    finally:
        db.close()

    state["last_run_at"] = run_at
    state["last_status"] = status
    state["last_trigger"] = trigger
    state["last_issue"] = issue
    state["last_http_status"] = http_status
    state["last_tenant_id"] = tenant_id
    state["last_tenant_name"] = tenant_name
    state["last_response_preview"] = response_preview
    state["last_used_base_url"] = used_base_url
    state["run_count"] = int(state.get("run_count", 0)) + 1
    if status != "ok":
        state["failure_count"] = int(state.get("failure_count", 0)) + 1
    if status == "leak_detected":
        state["leak_count"] = int(state.get("leak_count", 0)) + 1

    _append_history(
        state,
        {
            "run_at": run_at,
            "trigger": trigger,
            "status": status,
            "issue": issue,
            "http_status": http_status,
            "tenant_id": tenant_id,
            "tenant_name": tenant_name,
        },
    )
    _write_state(state)

    if status == "ok":
        logger.info("[Canary] Check passed at %s", run_at)
    else:
        logger.warning("[Canary] Check status=%s issue=%s", status, issue)

    return state


def run_scheduled_canary_job() -> None:
    """Scheduler entrypoint: run only if enabled."""
    state = _read_state()
    if not state.get("enabled", False):
        return
    run_canary_check(trigger="scheduled")
