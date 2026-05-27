"""
Step 4 CRM sync service.

Provides a lightweight, webhook-based CRM integration for confirmed bookings.
The integration is intentionally generic so tenants can point it at their CRM
middleware, Zapier/Make, or a custom endpoint without introducing a hard
dependency on a specific CRM vendor.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CRMSyncService:
    """Push confirmed booking payloads to an external CRM webhook."""

    def __init__(
        self,
        endpoint_url: str,
        api_key: Optional[str] = None,
        auth_header: str = "Authorization",
        auth_scheme: str = "Bearer",
        timeout_seconds: int = 10,
    ):
        self.endpoint_url = endpoint_url
        self.api_key = api_key
        self.auth_header = auth_header or "Authorization"
        self.auth_scheme = auth_scheme or "Bearer"
        self.timeout_seconds = timeout_seconds or 10

    async def push_booking(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import httpx

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                if self.auth_scheme:
                    headers[self.auth_header] = f"{self.auth_scheme} {self.api_key}".strip()
                else:
                    headers[self.auth_header] = self.api_key

            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.endpoint_url, json=payload, headers=headers)

            if response.status_code in (200, 201, 202):
                body = {}
                try:
                    body = response.json()
                except Exception:
                    body = {"raw": response.text[:1000]}
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "response": body,
                }

            logger.warning("[CRM] Sync failed: %s %s", response.status_code, response.text[:500])
            return {
                "success": False,
                "status_code": response.status_code,
                "error": response.text[:1000],
            }
        except Exception as exc:
            logger.exception("[CRM] Sync error: %s", exc)
            return {
                "success": False,
                "error": str(exc),
            }


def get_crm_sync_service(config: Optional[Dict[str, Any]]) -> Optional[CRMSyncService]:
    """Build CRM sync service from tenant integration config."""
    if not isinstance(config, dict):
        return None

    if config.get("enabled") is False:
        return None

    endpoint_url = (config.get("webhook_url") or config.get("endpoint_url") or "").strip()
    if not endpoint_url:
        return None

    return CRMSyncService(
        endpoint_url=endpoint_url,
        api_key=(config.get("api_key") or "").strip() or None,
        auth_header=config.get("auth_header") or "Authorization",
        auth_scheme=config.get("auth_scheme") or "Bearer",
        timeout_seconds=int(config.get("timeout_seconds") or 10),
    )
