"""
WhatsApp Business API adapter - handles communication with WhatsApp platform
"""
import logging
import json
from typing import Dict, Any, Optional, List
import aiohttp
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class WhatsAppProvider(ABC):
    """Base class for WhatsApp provider implementations"""
    
    @abstractmethod
    async def send_message(
        self,
        recipient_phone: str,
        message_text: str,
        template_name: Optional[str] = None,
        template_params: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Send a message via WhatsApp"""
        pass
    
    @abstractmethod
    async def send_interactive_message(
        self,
        recipient_phone: str,
        interactive_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send interactive message (buttons, lists, etc)"""
        pass


class CloudAPIWhatsAppProvider(WhatsAppProvider):
    """
    WhatsApp Cloud API provider (official Meta/Facebook implementation)
    Supports both on-premises and cloud deployments
    """
    
    def __init__(
        self,
        phone_number_id: str,
        business_account_id: str,
        access_token: str,
        api_version: str = "v18.0",
        base_url: str = "https://graph.facebook.com"
    ):
        """
        Initialize WhatsApp Cloud API provider
        
        Args:
            phone_number_id: Phone number ID from WhatsApp Business
            business_account_id: Business Account ID
            access_token: API access token
            api_version: API version (default v18.0)
            base_url: Base URL for API (default Meta hosted)
        """
        self.phone_number_id = phone_number_id
        self.business_account_id = business_account_id
        self.access_token = access_token
        self.api_version = api_version
        self.base_url = base_url
        self.endpoint = f"{base_url}/{api_version}/{phone_number_id}/messages"
    
    async def send_message(
        self,
        recipient_phone: str,
        message_text: str,
        template_name: Optional[str] = None,
        template_params: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Send a text message or template message
        
        Args:
            recipient_phone: Phone number with country code (e.g., +1234567890)
            message_text: Text content to send
            template_name: Optional template name
            template_params: Optional template parameters
            
        Returns:
            Response dict with message ID and status
        """
        start_time = time.time()
        
        try:
            # Prepare payload
            if template_name:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": recipient_phone,
                    "type": "template",
                    "template": {
                        "name": template_name,
                        "language": {
                            "code": "en_US"
                        }
                    }
                }
                if template_params:
                    payload["template"]["components"] = [{
                        "type": "body",
                        "parameters": [{"type": "text", "text": param} for param in template_params]
                    }]
            else:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": recipient_phone,
                    "type": "text",
                    "text": {
                        "body": message_text
                    }
                }
            
            # Send request
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    latency_ms = int((time.time() - start_time) * 1000)
                    
                    if resp.status in (200, 201):
                        response_data = await resp.json()
                        logger.info(f"[WhatsApp] Message sent to {recipient_phone}, latency: {latency_ms}ms")
                        return {
                            "success": True,
                            "message_id": response_data.get("messages", [{}])[0].get("id"),
                            "status": "sent",
                            "latency_ms": latency_ms
                        }
                    else:
                        error_text = await resp.text()
                        logger.error(f"[WhatsApp] Failed to send message: {resp.status} - {error_text}")
                        return {
                            "success": False,
                            "status": "failed",
                            "error": f"HTTP {resp.status}",
                            "details": error_text,
                            "latency_ms": latency_ms
                        }
        
        except asyncio.TimeoutError:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"[WhatsApp] Request timeout after {latency_ms}ms")
            return {
                "success": False,
                "status": "timeout",
                "error": "Request timeout",
                "latency_ms": latency_ms
            }
        
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.exception(f"[WhatsApp] Unexpected error: {str(e)}")
            return {
                "success": False,
                "status": "error",
                "error": str(e),
                "latency_ms": latency_ms
            }
    
    async def send_interactive_message(
        self,
        recipient_phone: str,
        interactive_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send interactive message (buttons, lists, etc)
        
        Args:
            recipient_phone: Phone number with country code
            interactive_payload: Interactive message payload structure
            
        Returns:
            Response dict with message ID and status
        """
        start_time = time.time()
        
        try:
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient_phone,
                "type": "interactive",
                "interactive": interactive_payload
            }
            
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    latency_ms = int((time.time() - start_time) * 1000)
                    
                    if resp.status in (200, 201):
                        response_data = await resp.json()
                        logger.info(f"[WhatsApp] Interactive message sent to {recipient_phone}")
                        return {
                            "success": True,
                            "message_id": response_data.get("messages", [{}])[0].get("id"),
                            "status": "sent",
                            "latency_ms": latency_ms
                        }
                    else:
                        error_text = await resp.text()
                        logger.error(f"[WhatsApp] Interactive message failed: {resp.status}")
                        return {
                            "success": False,
                            "status": "failed",
                            "error": f"HTTP {resp.status}",
                            "latency_ms": latency_ms
                        }
        
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.exception(f"[WhatsApp] Interactive message error: {str(e)}")
            return {
                "success": False,
                "status": "error",
                "error": str(e),
                "latency_ms": latency_ms
            }


class MSG91WhatsAppProvider(WhatsAppProvider):
    """
    MSG91 WhatsApp provider - sends messages via MSG91 API
    Used when MSG91 is the intermediary between Meta and SCUBE
    """

    def __init__(
        self,
        auth_key: str,
        integrated_number: str,
        base_url: str = "https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/"
    ):
        self.auth_key = auth_key
        self.integrated_number = integrated_number
        self.base_url = base_url

    def _normalize_phone(self, phone: str) -> str:
        """Ensure phone number has + prefix for MSG91"""
        if not phone:
            return phone
        phone = phone.strip()
        if not phone.startswith('+'):
            phone = '+' + phone
        return phone

    async def send_message(
        self,
        recipient_phone: str,
        message_text: str,
        template_name: Optional[str] = None,
        template_params: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        start_time = time.time()
        try:
            # Normalize phone number to ensure + prefix
            normalized_phone = self._normalize_phone(recipient_phone)
            payload = {
                "integrated_number": self.integrated_number,
                "recipient_number": normalized_phone,
                "content_type": "text",
                "text": message_text
            }
            headers = {
                "authkey": self.auth_key,
                "Content-Type": "application/json",
                "accept": "application/json"
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    latency_ms = int((time.time() - start_time) * 1000)
                    response_data = await resp.json()
                    if resp.status in (200, 201) and response_data.get("status") == "success":
                        logger.info(f"[MSG91] Message sent to {recipient_phone}, latency: {latency_ms}ms")
                        return {
                            "success": True,
                            "message_id": response_data.get("data", {}).get("message_uuid"),
                            "status": "sent",
                            "latency_ms": latency_ms
                        }
                    else:
                        logger.error(f"[MSG91] Failed to send: {resp.status} - {response_data}")
                        return {
                            "success": False,
                            "status": "failed",
                            "error": str(response_data),
                            "latency_ms": latency_ms
                        }
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.exception(f"[MSG91] Error: {str(e)}")
            return {"success": False, "status": "error", "error": str(e), "latency_ms": latency_ms}

    async def send_interactive_message(
        self,
        recipient_phone: str,
        interactive_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {"success": False, "error": "Interactive messages not supported via MSG91 yet"}


def get_whatsapp_provider(
    provider_type: str = "cloud_api",
    **kwargs
) -> WhatsAppProvider:
    """
    Factory function to get WhatsApp provider instance
    
    Args:
        provider_type: Type of provider (e.g., "cloud_api", "msg91")
        **kwargs: Provider-specific initialization parameters
        
    Returns:
        Initialized WhatsApp provider instance
    """
    if provider_type == "cloud_api":
        return CloudAPIWhatsAppProvider(**kwargs)
    elif provider_type == "msg91":
        return MSG91WhatsAppProvider(**kwargs)
    else:
        raise ValueError(f"Unknown WhatsApp provider: {provider_type}")
