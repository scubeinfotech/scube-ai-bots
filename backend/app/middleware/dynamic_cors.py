"""
Dynamic CORS middleware.

Why this exists
---------------
The original setup used Starlette's CORSMiddleware with a hard-coded
``ALLOWED_ORIGINS`` env list. Every time a new tenant was onboarded,
someone had to remember to add the tenant's domain to that env var
and restart the container. When that step was missed, the embedded
chat widget on the tenant's site failed with a generic
"Failed to fetch" (CORS rejection) — which is exactly what happened
for the Nutech Solution onboarding.

This middleware replaces the static list with a DB-driven allowlist:

  * Reads ``Tenant.domain`` and ``Tenant.website_url`` for every active tenant.
  * Reads ``APIKey.allowed_domains`` (comma-separated) for every active key.
  * Merges those with the static base list (admin/dev origins).
  * Caches the merged set for ``cache_ttl`` seconds (default 60s).
  * Exposes ``invalidate_cors_cache()`` so admin write-paths can refresh
    immediately when a tenant or API key is created/updated.

Each entry is normalized to ``https://{host}`` and ``https://www.{host}`` so
admins can save the value with or without a scheme, port, path, or ``www.``
prefix and still get a working allowlist.

Wildcard ``*`` in the static base list is honored: when present, all origins
are allowed (with credentials disabled per CORS spec).
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Iterable, Set

from starlette.requests import Request
from starlette.responses import Response, PlainTextResponse
from starlette.types import ASGIApp


logger = logging.getLogger(__name__)


_CACHE_LOCK = threading.Lock()
_CACHE_EXPIRY: float = 0.0
_CACHE_VALUE: Set[str] = set()


def invalidate_cors_cache() -> None:
    """Mark the cached origin set as stale so the next request rebuilds it.

    Call this from admin endpoints that create or modify tenants / API keys
    so newly-onboarded sites work immediately without waiting for TTL.
    """
    global _CACHE_EXPIRY
    with _CACHE_LOCK:
        _CACHE_EXPIRY = 0.0


def _strip_to_host(raw: str) -> str:
    """Normalize an admin-entered domain string to a bare hostname.

    Accepts ``"https://www.foo.com/"``, ``"foo.com:8080"``, ``"www.foo.com"``,
    etc. and returns ``"www.foo.com"`` (preserving the ``www.`` if present so
    the caller can decide whether to add both variants).
    """
    if not raw:
        return ""
    s = raw.strip().lower()
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)   # drop scheme
    s = s.split("/", 1)[0]                         # drop path
    s = s.split("?", 1)[0]                         # drop query
    s = s.split("#", 1)[0]                         # drop fragment
    s = s.split(":", 1)[0]                         # drop port
    return s.strip(". ")


def _expand_host_to_origins(host: str) -> Set[str]:
    """Given a bare host, produce the origin variants we want to allow.

    For tenant-supplied hosts we always allow both ``https://host`` and
    ``https://www.host`` so admins don't need to think about the ``www.``
    prefix. We do NOT auto-allow ``http://`` for public hosts — that's a
    deliberate security choice; production sites must use TLS.
    """
    if not host or "." not in host:
        return set()
    bare = host[4:] if host.startswith("www.") else host
    if not bare or "." not in bare:
        return set()
    return {f"https://{bare}", f"https://www.{bare}"}


def _build_origins_from_db(static_origins: Iterable[str]) -> Set[str]:
    """Build the full allowed-origin set from the static base + the DB."""
    origins: Set[str] = set()

    # Static entries are taken as-is (covers localhost / dev IPs / admin host).
    for raw in static_origins:
        if not raw:
            continue
        if raw.strip() == "*":
            origins.add("*")
            continue
        origins.add(raw.strip())

    # Lazy import to avoid circulars at module import time.
    try:
        from app.database import SessionLocal
        from app.models.tenant import Tenant
        from app.models.api_key import APIKey
    except Exception as exc:
        logger.exception("Dynamic CORS: failed to import DB models: %s", exc)
        return origins

    db = SessionLocal()
    try:
        try:
            tenants = db.query(Tenant).filter(Tenant.is_active == True).all()  # noqa: E712
        except Exception as exc:
            logger.exception("Dynamic CORS: tenant query failed: %s", exc)
            tenants = []

        for t in tenants:
            for raw in (getattr(t, "domain", None), getattr(t, "website_url", None)):
                origins |= _expand_host_to_origins(_strip_to_host(raw or ""))

        try:
            keys = (
                db.query(APIKey)
                .filter(APIKey.is_active == True)  # noqa: E712
                .filter(APIKey.allowed_domains.isnot(None))
                .all()
            )
        except Exception as exc:
            logger.exception("Dynamic CORS: api_key query failed: %s", exc)
            keys = []

        for k in keys:
            for piece in (getattr(k, "allowed_domains", "") or "").split(","):
                origins |= _expand_host_to_origins(_strip_to_host(piece))
    finally:
        db.close()

    return origins


class DynamicCORSMiddleware:
    """ASGI middleware that adds CORS headers based on a DB-driven allowlist.

    Designed as a pure ASGI middleware (not BaseHTTPMiddleware) so it does
    not consume / re-buffer response bodies — important for streaming and
    large LLM responses.
    """

    DEFAULT_ALLOW_HEADERS = "Content-Type, Authorization, X-API-Key, X-Requested-With"
    DEFAULT_ALLOW_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD"

    def __init__(
        self,
        app: ASGIApp,
        static_origins: Iterable[str],
        cache_ttl: int = 60,
        allow_credentials: bool = True,
        max_age: int = 600,
    ) -> None:
        self.app = app
        self.static_origins = list(static_origins or [])
        self.cache_ttl = max(5, int(cache_ttl))
        self.allow_credentials = allow_credentials
        self.max_age = max_age

    # ---- public helpers ---------------------------------------------------

    def get_allowed_origins(self) -> Set[str]:
        """Return the cached allowlist, refreshing if the TTL has expired."""
        global _CACHE_EXPIRY, _CACHE_VALUE
        now = time.time()
        with _CACHE_LOCK:
            if now < _CACHE_EXPIRY and _CACHE_VALUE:
                return _CACHE_VALUE

        # Build outside the lock to avoid blocking other requests on DB I/O.
        new_value = _build_origins_from_db(self.static_origins)

        with _CACHE_LOCK:
            _CACHE_VALUE = new_value
            _CACHE_EXPIRY = time.time() + self.cache_ttl
            logger.info(
                "Dynamic CORS: refreshed allowlist (%d origins, ttl=%ds)",
                len(new_value),
                self.cache_ttl,
            )
            return _CACHE_VALUE

    def is_origin_allowed(self, origin: str) -> bool:
        if not origin:
            return False
        allowed = self.get_allowed_origins()
        if "*" in allowed:
            return True
        return origin in allowed

    # ---- ASGI entry point -------------------------------------------------

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        origin = request.headers.get("origin", "")
        method = request.method.upper()
        is_preflight = (
            method == "OPTIONS"
            and "access-control-request-method" in request.headers
        )

        if is_preflight:
            response = self._build_preflight_response(request, origin)
            await response(scope, receive, send)
            return

        # For real requests, wrap `send` so we can inject CORS headers onto
        # whatever response the app returns (including 4xx/5xx and streaming).
        origin_allowed = bool(origin) and self.is_origin_allowed(origin)
        cors_headers = self._actual_response_headers(origin) if origin_allowed else {}

        async def send_with_cors(message):
            if message["type"] == "http.response.start" and cors_headers:
                headers = list(message.get("headers", []))
                # Drop any pre-existing CORS headers added downstream.
                headers = [
                    (k, v) for (k, v) in headers
                    if not k.lower().startswith(b"access-control-")
                    and k.lower() != b"vary"
                ]
                for key, value in cors_headers.items():
                    headers.append((key.encode("latin-1"), value.encode("latin-1")))
                # Keep / merge Vary header for caches.
                headers.append((b"vary", b"Origin"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cors)

    # ---- helpers ----------------------------------------------------------

    def _build_preflight_response(self, request: Request, origin: str) -> Response:
        if not origin or not self.is_origin_allowed(origin):
            logger.info("Dynamic CORS: rejected preflight from origin=%r", origin)
            return PlainTextResponse(
                "CORS origin not allowed", status_code=400,
                headers={"Vary": "Origin"},
            )

        req_headers = request.headers.get(
            "access-control-request-headers", self.DEFAULT_ALLOW_HEADERS
        )
        resp_headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": self.DEFAULT_ALLOW_METHODS,
            "Access-Control-Allow-Headers": req_headers,
            "Access-Control-Max-Age": str(self.max_age),
            "Vary": "Origin",
        }
        if self.allow_credentials:
            resp_headers["Access-Control-Allow-Credentials"] = "true"
        return PlainTextResponse("", status_code=200, headers=resp_headers)

    def _actual_response_headers(self, origin: str) -> dict:
        headers = {"Access-Control-Allow-Origin": origin}
        if self.allow_credentials:
            headers["Access-Control-Allow-Credentials"] = "true"
        return headers
