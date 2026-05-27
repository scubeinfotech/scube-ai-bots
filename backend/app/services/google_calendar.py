"""
Step 3 – Google Calendar Integration Service

Handles creating, confirming, and deleting calendar events when
WhatsApp leads move through the tentative → confirmed → cancelled lifecycle.

Setup (per tenant)
──────────────────
1. Go to https://console.cloud.google.com → Create a project
2. Enable "Google Calendar API"
3. Create OAuth 2.0 credentials (Desktop app) → Download JSON
4. Run: python -c "from app.services.google_calendar import get_oauth_tokens; get_oauth_tokens()"
5. Store the returned refresh_token in tenant settings via:
   PATCH /api/admin/tenants/{id}/settings
   {"google_calendar_refresh_token": "<token>", "google_calendar_id": "primary"}

Environment variables (global defaults, override per-tenant)
─────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID      - OAuth2 client ID
GOOGLE_CLIENT_SECRET  - OAuth2 client secret
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Google API scopes needed
SCOPES = ["https://www.googleapis.com/auth/calendar"]

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
TOKEN_URI            = "https://oauth2.googleapis.com/token"
CALENDAR_API_BASE    = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarService:
    """
    Lightweight Google Calendar client using raw HTTPS (no google-auth SDK
    dependency) so it works without adding packages to requirements.txt.
    Falls back gracefully when credentials are not configured.
    """

    def __init__(self, refresh_token: str, calendar_id: str = "primary"):
        self.refresh_token = refresh_token
        self.calendar_id   = calendar_id
        self._access_token: Optional[str] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def create_tentative_event(
        self,
        booking,          # WhatsAppTentativeBooking ORM object
        tenant_name: str,
        contact_phone: str,
    ) -> Optional[str]:
        """
        Create a *tentative* calendar event for a new booking lead.
        Returns the Google event ID, or None on failure.
        """
        start_dt, end_dt = self._parse_booking_datetime(booking)
        if not start_dt:
            logger.warning("[GCal] Cannot create event – could not parse date/time from booking")
            return None

        summary = f"[Tentative] {booking.intent_type.title()} – {contact_phone}"
        description = (
            f"WhatsApp booking request\n"
            f"Contact: {contact_phone}\n"
            f"Persons: {booking.requested_persons or '—'}\n"
            f"Type: {booking.requested_type or '—'}\n"
            f"Raw request: {booking.raw_text}\n"
            f"Tenant: {tenant_name}\n"
            f"Lead ID: {booking.id}"
        )

        event_body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Singapore"},
            "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "Asia/Singapore"},
            "status": "tentative",
            "colorId": "5",  # banana yellow = tentative
            "reminders": {"useDefault": False},
        }
        return await self._create_event(event_body)

    async def confirm_event(self, event_id: str) -> bool:
        """Update event status to confirmed (green)."""
        patch = {"status": "confirmed", "colorId": "2"}  # sage green
        return await self._patch_event(event_id, patch)

    async def delete_event(self, event_id: str) -> bool:
        """Delete a cancelled booking from calendar."""
        return await self._delete_event(event_id)

    # ── HTTP helpers ───────────────────────────────────────────────────────────

    async def _get_access_token(self) -> Optional[str]:
        """Exchange refresh_token for a short-lived access token."""
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not self.refresh_token:
            logger.warning("[GCal] Google credentials not configured – skipping calendar operation")
            return None
        try:
            import httpx
            resp = await httpx.AsyncClient().post(TOKEN_URI, data={
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": self.refresh_token,
                "grant_type":    "refresh_token",
            })
            if resp.status_code == 200:
                return resp.json().get("access_token")
            logger.error(f"[GCal] Token refresh failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"[GCal] Token refresh error: {e}")
        return None

    async def _create_event(self, body: dict) -> Optional[str]:
        token = await self._get_access_token()
        if not token:
            return None
        try:
            import httpx
            url = f"{CALENDAR_API_BASE}/calendars/{self.calendar_id}/events"
            resp = await httpx.AsyncClient().post(
                url, json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code in (200, 201):
                event_id = resp.json().get("id")
                logger.info(f"[GCal] Created event {event_id}")
                return event_id
            logger.error(f"[GCal] Create event failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"[GCal] Create event error: {e}")
        return None

    async def _patch_event(self, event_id: str, patch: dict) -> bool:
        token = await self._get_access_token()
        if not token:
            return False
        try:
            import httpx
            url = f"{CALENDAR_API_BASE}/calendars/{self.calendar_id}/events/{event_id}"
            resp = await httpx.AsyncClient().patch(
                url, json=patch,
                headers={"Authorization": f"Bearer {token}"},
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"[GCal] Patch event error: {e}")
        return False

    async def _delete_event(self, event_id: str) -> bool:
        token = await self._get_access_token()
        if not token:
            return False
        try:
            import httpx
            url = f"{CALENDAR_API_BASE}/calendars/{self.calendar_id}/events/{event_id}"
            resp = await httpx.AsyncClient().delete(
                url, headers={"Authorization": f"Bearer {token}"},
            )
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.error(f"[GCal] Delete event error: {e}")
        return False

    # ── Date parsing ───────────────────────────────────────────────────────────

    def _parse_booking_datetime(self, booking) -> tuple[Optional[datetime], Optional[datetime]]:
        """
        Convert booking.requested_date + requested_time into start/end datetimes.
        Duration defaults to 2 hours.
        Returns (None, None) if parsing fails.
        """
        try:
            from dateutil import parser as dateutil_parser
            import re

            raw_date = (booking.requested_date or "").strip()
            raw_time = (booking.requested_time or "").strip()

            if not raw_date or not raw_time:
                return None, None

            # Normalise "tomorrow" / "today"
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            if raw_date.lower() == "tomorrow":
                base_date = today + timedelta(days=1)
            elif raw_date.lower() in ("today", "tonight"):
                base_date = today
            else:
                base_date = dateutil_parser.parse(raw_date, default=today)

            # Normalise "8 pm" → "20:00"
            time_str = re.sub(r"\s+", "", raw_time.lower())
            start_dt = dateutil_parser.parse(
                f"{base_date.strftime('%Y-%m-%d')} {time_str}"
            )
            end_dt = start_dt + timedelta(hours=2)
            return start_dt, end_dt
        except Exception as e:
            logger.warning(f"[GCal] Date parse failed ({booking.requested_date!r}, {booking.requested_time!r}): {e}")
            return None, None


def get_calendar_service(tenant_settings: Dict[str, Any]) -> Optional[GoogleCalendarService]:
    """
    Factory – returns a configured GoogleCalendarService if the tenant has
    connected their Google Calendar, otherwise None (silent no-op).
    """
    refresh_token = tenant_settings.get("google_calendar_refresh_token", "")
    calendar_id   = tenant_settings.get("google_calendar_id", "primary")
    if not refresh_token:
        return None
    return GoogleCalendarService(refresh_token=refresh_token, calendar_id=calendar_id)


# ── One-time OAuth helper (run locally to get refresh token) ──────────────────

def get_oauth_tokens():  # pragma: no cover
    """
    Interactive helper to obtain OAuth tokens for the first time.
    Run once on your local machine:
        python -c "from app.services.google_calendar import get_oauth_tokens; get_oauth_tokens()"
    """
    import json, webbrowser, urllib.parse, http.server, threading

    auth_code_holder = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            auth_code_holder["code"] = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query
            ).get("code", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h1>Auth complete - you can close this tab.</h1>")
        def log_message(self, *a): pass

    redirect_uri = "http://localhost:8080"
    params = urllib.parse.urlencode({
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         " ".join(SCOPES),
        "access_type":   "offline",
        "prompt":        "consent",
    })
    url = f"https://accounts.google.com/o/oauth2/auth?{params}"
    print(f"\nOpening browser for Google OAuth...\n{url}\n")
    webbrowser.open(url)

    server = http.server.HTTPServer(("localhost", 8080), _Handler)
    t = threading.Thread(target=server.handle_request)
    t.start(); t.join(timeout=120)

    code = auth_code_holder.get("code")
    if not code:
        print("No code received – timed out.")
        return

    import urllib.request
    data = urllib.parse.urlencode({
        "code": code, "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN_URI, data=data, method="POST")
    with urllib.request.urlopen(req) as r:
        tokens = json.loads(r.read())

    print("\n=== Save these in your tenant settings ===")
    print(f"refresh_token : {tokens.get('refresh_token')}")
    print(f"calendar_id   : primary  (or get from https://calendar.google.com/calendar/r/settings)")
