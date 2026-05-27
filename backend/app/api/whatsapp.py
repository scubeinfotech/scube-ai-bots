"""
WhatsApp API endpoints - webhook and configuration management
"""
import logging
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Tenant
from app.models.whatsapp import WhatsAppConfiguration, WhatsAppContact, WhatsAppMessage
from app.services.whatsapp_service import WhatsAppService
from app.services.whatsapp_validator import WhatsAppConfigValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])


class WhatsAppConfigRequest(BaseModel):
    """Configuration request model"""
    phone_number_id: str = ""
    business_account_id: str = ""
    access_token: str = ""
    webhook_url: str = ""
    webhook_verify_token: str = ""
    enable_booking_flow: bool = False
    enable_interactive_responses: bool = True
    auto_response_enabled: bool = True
    short_response_mode: bool = True
    rate_limit_max_per_minute: int = 5
    cooldown_seconds: int = 2
    response_target_chars: int = 300
    config_metadata: dict = {}


class WhatsAppConfigResponse(BaseModel):
    """Configuration response model"""
    id: str
    tenant_id: str
    phone_number_id: str
    business_account_id: str
    is_active: bool
    enable_booking_flow: bool
    enable_interactive_responses: bool
    auto_response_enabled: bool
    short_response_mode: bool
    rate_limit_max_per_minute: int = 5
    cooldown_seconds: int = 2
    response_target_chars: int = 300
    config_metadata: dict = {}
    
    class Config:
        from_attributes = True


class WhatsAppWebhookRequest(BaseModel):
    """Webhook payload from WhatsApp"""
    object: str
    entry: list


@router.post("/configure/{tenant_id}")
async def configure_whatsapp(
    tenant_id: str,
    config: WhatsAppConfigRequest,
    db: Session = Depends(get_db)
) -> WhatsAppConfigResponse:
    """
    Configure WhatsApp for a tenant
    
    Args:
        tenant_id: Tenant ID
        config: WhatsApp configuration
        db: Database session
        
    Returns:
        Configuration response
    """
    # Verify tenant exists
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    try:
        # Validate configuration before saving
        config_data = {
            'phone_number_id': config.phone_number_id,
            'business_account_id': config.business_account_id,
            'access_token': config.access_token,
            'webhook_url': config.webhook_url,
            'webhook_verify_token': config.webhook_verify_token,
            'auto_response_enabled': config.auto_response_enabled,
            'enable_booking_flow': config.enable_booking_flow,
            'enable_interactive_responses': config.enable_interactive_responses,
            'short_response_mode': config.short_response_mode,
            'rate_limit_max_per_minute': config.rate_limit_max_per_minute,
            'cooldown_seconds': config.cooldown_seconds,
            'response_target_chars': config.response_target_chars,
            'config_metadata': config.config_metadata if config.config_metadata else None
        }
        
        validation = WhatsAppConfigValidator.validate_config_before_save(db, tenant_id, config_data)
        
        if not validation['valid']:
            logger.error(f"[WhatsApp] Configuration validation failed: {validation['errors']}")
            raise HTTPException(
                status_code=400, 
                detail={
                    "message": "Configuration validation failed",
                    "errors": validation['errors']
                }
            )
        
        # Log warnings
        if validation['warnings']:
            logger.warning(f"[WhatsApp] Configuration warnings: {validation['warnings']}")
        
        # Check if config already exists
        existing_config = db.query(WhatsAppConfiguration).filter(
            WhatsAppConfiguration.tenant_id == tenant_id
        ).first()
        
        if existing_config:
            # Update existing configuration
            existing_config.phone_number_id = config.phone_number_id
            existing_config.business_account_id = config.business_account_id
            existing_config.access_token = config.access_token  # Should encrypt in production
            existing_config.webhook_url = config.webhook_url
            existing_config.webhook_verify_token = config.webhook_verify_token
            existing_config.enable_booking_flow = config.enable_booking_flow
            existing_config.enable_interactive_responses = config.enable_interactive_responses
            existing_config.auto_response_enabled = config.auto_response_enabled
            existing_config.short_response_mode = config.short_response_mode
            existing_config.rate_limit_max_per_minute = config.rate_limit_max_per_minute
            existing_config.cooldown_seconds = config.cooldown_seconds
            existing_config.response_target_chars = config.response_target_chars
            if config.config_metadata:
                existing_config.config_metadata = config.config_metadata
            existing_config.is_active = True
            
            db.commit()
            db.refresh(existing_config)
            
            logger.info(f"[WhatsApp] Configuration updated for tenant {tenant_id}")
        else:
            # Create new configuration
            wa_config = WhatsAppConfiguration(
                tenant_id=tenant_id,
                phone_number_id=config.phone_number_id,
                business_account_id=config.business_account_id,
                access_token=config.access_token,
                webhook_url=config.webhook_url,
                webhook_verify_token=config.webhook_verify_token,
                enable_booking_flow=config.enable_booking_flow,
                enable_interactive_responses=config.enable_interactive_responses,
                auto_response_enabled=config.auto_response_enabled,
                short_response_mode=config.short_response_mode,
                rate_limit_max_per_minute=config.rate_limit_max_per_minute,
                cooldown_seconds=config.cooldown_seconds,
                response_target_chars=config.response_target_chars,
                config_metadata=config.config_metadata if config.config_metadata else None
            )
            db.add(wa_config)
            db.commit()
            db.refresh(wa_config)
            
            logger.info(f"[WhatsApp] Configuration created for tenant {tenant_id}")
            existing_config = wa_config
        
        return WhatsAppConfigResponse.from_orm(existing_config)
    
    except Exception as e:
        logger.exception(f"[WhatsApp] Configuration failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/configure/{tenant_id}")
async def get_whatsapp_config(
    tenant_id: str,
    db: Session = Depends(get_db)
) -> WhatsAppConfigResponse:
    """
    Get WhatsApp configuration for tenant
    
    Args:
        tenant_id: Tenant ID
        db: Database session
        
    Returns:
        Configuration response
    """
    wa_config = db.query(WhatsAppConfiguration).filter(
        WhatsAppConfiguration.tenant_id == tenant_id
    ).first()
    
    if not wa_config:
        raise HTTPException(status_code=404, detail="WhatsApp not configured")
    
    return WhatsAppConfigResponse.from_orm(wa_config)


@router.delete("/configure/{tenant_id}")
async def disable_whatsapp(
    tenant_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Disable WhatsApp for a tenant
    
    Args:
        tenant_id: Tenant ID
        db: Database session
        
    Returns:
        Status response
    """
    wa_config = db.query(WhatsAppConfiguration).filter(
        WhatsAppConfiguration.tenant_id == tenant_id
    ).first()
    
    if not wa_config:
        raise HTTPException(status_code=404, detail="WhatsApp not configured")
    
    wa_config.is_active = False
    db.commit()
    
    logger.info(f"[WhatsApp] Disabled for tenant {tenant_id}")
    
    return {"success": True, "message": "WhatsApp disabled"}


@router.get("/webhook/{tenant_id}")
async def verify_webhook(
    tenant_id: str,
    request: Request,
    db: Session = Depends(get_db)
) -> PlainTextResponse:
    """
    Verify WhatsApp webhook token (GET request)
    WhatsApp sends dotted params (hub.mode, hub.challenge, hub.verify_token)
    which FastAPI can't bind to Python variables, so we read them from
    request.query_params directly.

    Args:
        tenant_id: Tenant ID
        request: Request object
        db: Database session

    Returns:
        Challenge if verified
    """
    query_params = dict(request.query_params)
    hub_mode = query_params.get("hub.mode")
    hub_challenge = query_params.get("hub.challenge")
    hub_verify_token = (
        query_params.get("hub.verify_token")
        or query_params.get("verify_token")
        or query_params.get("token")
    )

    if hub_mode != "subscribe":
        logger.warning(f"[WhatsApp] Invalid webhook mode: {hub_mode}")
        raise HTTPException(status_code=400, detail="Invalid mode")

    service = WhatsAppService(db)
    challenge = service.verify_webhook(hub_challenge, hub_verify_token, tenant_id)

    if not challenge:
        raise HTTPException(status_code=403, detail="Verification failed")

    logger.info(f"[WhatsApp] Webhook verified for tenant {tenant_id}")
    return PlainTextResponse(str(hub_challenge))


@router.post("/webhook/{tenant_id}")
async def receive_webhook(
    tenant_id: str,
    payload: Dict[str, Any],
    request: Request = None,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Receive incoming WhatsApp messages via webhook

    Args:
        tenant_id: Tenant ID
        payload: Webhook payload
        request: Request object
        db: Database session

    Returns:
        Processing result
    """
    try:
        logger.debug(f"[WhatsApp] Received webhook for tenant {tenant_id}")

        # Check if this is a verification request (POST with hub fields)
        # Support multiple formats: hub.mode, hub_mode, mode
        hub_mode = payload.get("hub.mode") or payload.get("hub_mode") or payload.get("mode")
        hub_challenge = payload.get("hub.challenge") or payload.get("hub_challenge") or payload.get("challenge")
        hub_verify_token = payload.get("hub.verify_token") or payload.get("hub_verify_token") or payload.get("verify_token") or payload.get("token")

        # Also try nested hub object: {"hub": {"mode": "...", "challenge": "...", "verify_token": "..."}}
        if "hub" in payload and isinstance(payload.get("hub"), dict):
            hub = payload.get("hub", {})
            hub_mode = hub_mode or hub.get("mode")
            hub_challenge = hub_challenge or hub.get("challenge")
            hub_verify_token = hub_verify_token or hub.get("verify_token")

        if hub_mode == "subscribe" and hub_challenge and hub_verify_token:
            service = WhatsAppService(db)
            result = service.verify_webhook(hub_challenge, hub_verify_token, tenant_id)
            if result:
                logger.info(f"[WhatsApp] Webhook verified via POST for tenant {tenant_id}")
                return PlainTextResponse(str(hub_challenge))
            else:
                logger.warning(f"[WhatsApp] Verification failed for tenant {tenant_id}")
                raise HTTPException(status_code=403, detail="Verification failed")

        # Create WhatsApp service (processes messages synchronously)
        service = WhatsAppService(db)

        # Process webhook
        result = await service.process_incoming_webhook(tenant_id, payload)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[WhatsApp] Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/verify/{tenant_id}")
async def simple_verify_webhook(
    tenant_id: str,
    challenge: str = None,
    verify_token: str = None
) -> str:
    """
    Simple webhook verification endpoint for API vendors
    Supports: ?challenge=...&verify_token=...
    """
    from app.database import SessionLocal

    logger.info(f"[WhatsApp] Simple verify - tenant: {tenant_id}")

    if not challenge or not verify_token:
        raise HTTPException(status_code=400, detail="Missing parameters")

    db = SessionLocal()
    try:
        service = WhatsAppService(db)
        result = service.verify_webhook(challenge, verify_token, tenant_id)
        if result:
            logger.info(f"[WhatsApp] Simple verify SUCCESS for tenant {tenant_id}")
            return PlainTextResponse(str(challenge))
        else:
            logger.warning(f"[WhatsApp] Simple verify FAILED for tenant {tenant_id}")
            raise HTTPException(status_code=403, detail="Verification failed")
    finally:
        db.close()


@router.get("/tenant/{tenant_id}/messages")
async def list_tenant_whatsapp_messages(
    tenant_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db)
) -> List[dict]:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    contacts = db.query(WhatsAppContact).filter(
        WhatsAppContact.tenant_id == tenant_id
    ).order_by(WhatsAppContact.last_message_at.desc().nullslast()).limit(limit).all()
    result = []
    for c in contacts:
        last_msg = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.contact_id == c.id
        ).order_by(WhatsAppMessage.created_at.desc()).first()
        msg_count = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.contact_id == c.id
        ).count()
        result.append({
            "contact_id": c.id,
            "phone": c.phone_number,
            "name": c.contact_name or c.phone_number,
            "first_message_at": c.first_message_at.isoformat() if c.first_message_at else None,
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
            "message_count": msg_count,
            "last_message": last_msg.content[:200] if last_msg else None,
            "last_message_direction": last_msg.direction if last_msg else None,
            "last_message_time": last_msg.created_at.isoformat() if last_msg else None,
        })
    return result


@router.get("/tenant/{tenant_id}/messages/{contact_id}")
async def get_contact_messages(
    tenant_id: str,
    contact_id: str,
    db: Session = Depends(get_db)
) -> List[dict]:
    msgs = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.contact_id == contact_id,
        WhatsAppMessage.tenant_id == tenant_id
    ).order_by(WhatsAppMessage.created_at.asc()).all()
    return [{
        "id": m.id,
        "direction": m.direction,
        "content": m.content,
        "message_type": m.message_type,
        "created_at": m.created_at.isoformat() + '+00:00' if m.created_at else None,
    } for m in msgs]


@router.get("/health/{tenant_id}")
async def whatsapp_health(
    tenant_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Check WhatsApp integration health
    
    Args:
        tenant_id: Tenant ID
        db: Database session
        
    Returns:
        Health status
    """
    try:
        wa_config = db.query(WhatsAppConfiguration).filter(
            WhatsAppConfiguration.tenant_id == tenant_id
        ).first()
        
        if not wa_config:
            return {
                "status": "not_configured",
                "configured": False
            }
        
        if not wa_config.is_active:
            return {
                "status": "disabled",
                "configured": True,
                "active": False
            }
        
        # Could add actual API health check here
        return {
            "status": "healthy",
            "configured": True,
            "active": True,
            "phone_number_id": wa_config.phone_number_id,
            "features": {
                "booking_flow": wa_config.enable_booking_flow,
                "interactive_responses": wa_config.enable_interactive_responses,
                "auto_response": wa_config.auto_response_enabled,
                "short_response_mode": wa_config.short_response_mode
            }
        }
    
    except Exception as e:
        logger.exception(f"[WhatsApp] Health check failed: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }
