"""
WhatsApp Connection Testing API
Tests WhatsApp configuration and displays status
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any

from app.database import get_db
from app.models.whatsapp import WhatsAppConfiguration
from app.services.whatsapp_service import WhatsAppService
from app.services.whatsapp_monitor import WhatsAppMonitor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp Test"])

class TestResponse(BaseModel):
    """WhatsApp connection test response"""
    success: bool
    status: str  # "connected", "disconnected", "error"
    message: str
    details: Dict[str, Any] = {}
    test_message_id: str = None

class StatusResponse(BaseModel):
    """WhatsApp status response"""
    connection_status: str  # "connected", "disconnected", "error"
    last_test: str = None
    webhook_active: bool
    messages_today: int
    response_rate: float
    provider: str
    phone_number: str

@router.post("/test/{tenant_id}", response_model=TestResponse)
async def test_whatsapp_connection(
    tenant_id: str,
    db: Session = Depends(get_db)
) -> TestResponse:
    """
    Test WhatsApp connection for tenant
    
    Args:
        tenant_id: Tenant ID
        db: Database session
        
    Returns:
        Test results with status and details
    """
    try:
        # Get configuration
        config = db.query(WhatsAppConfiguration).filter(
            WhatsAppConfiguration.tenant_id == tenant_id
        ).first()
        
        if not config:
            return TestResponse(
                success=False,
                status="error",
                message="No WhatsApp configuration found"
            )
        
        # Determine provider
        provider = "msg91" if config.config_metadata and config.config_metadata.get("msg91_auth_key") else "meta"
        
        # Test by sending a message
        service = WhatsAppService(db)
        
        # Use a test number (you can make this configurable)
        test_number = "6594561045"  # Known working number
        test_message = "Connection test - please ignore"
        
        try:
            result = await service._send_whatsapp_message(
                wa_config=config,
                recipient_phone=test_number,
                message_text=test_message
            )
            
            if result.get('success'):
                # Update last health check
                from datetime import datetime
                config.last_health_check = datetime.utcnow()
                db.commit()
                
                return TestResponse(
                    success=True,
                    status="connected",
                    message="WhatsApp connection successful",
                    details={
                        "provider": provider,
                        "test_number": test_number,
                        "latency_ms": result.get('latency_ms', 0),
                        "message_id": result.get('message_id')
                    },
                    test_message_id=result.get('message_id')
                )
            else:
                return TestResponse(
                    success=False,
                    status="error",
                    message=f"Failed to send test message: {result.get('error', 'Unknown error')}",
                    details={
                        "provider": provider,
                        "error": result.get('error')
                    }
                )
                
        except Exception as e:
            logger.exception(f"[WhatsApp Test] Connection test failed: {str(e)}")
            return TestResponse(
                success=False,
                status="error",
                message=f"Connection test failed: {str(e)}",
                details={
                    "provider": provider,
                    "error": str(e)
                }
            )
            
    except Exception as e:
        logger.exception(f"[WhatsApp Test] Test failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status/{tenant_id}", response_model=StatusResponse)
async def get_whatsapp_status(
    tenant_id: str,
    db: Session = Depends(get_db)
) -> StatusResponse:
    """
    Get WhatsApp status for tenant
    
    Args:
        tenant_id: Tenant ID
        db: Database session
        
    Returns:
        Current WhatsApp status
    """
    try:
        # Get configuration
        config = db.query(WhatsAppConfiguration).filter(
            WhatsAppConfiguration.tenant_id == tenant_id
        ).first()
        
        if not config:
            return StatusResponse(
                connection_status="disconnected",
                webhook_active=False,
                messages_today=0,
                response_rate=0.0,
                provider="none",
                phone_number="-"
            )
        
        # Get health report
        health = WhatsAppMonitor.get_health_report(db, tenant_id)
        
        # Determine provider
        provider = "msg91" if config.config_metadata and config.config_metadata.get("msg91_auth_key") else "meta"
        
        # Get phone number
        phone_number = config.config_metadata.get("msg91_integrated_number") if provider == "msg91" else config.phone_number_id
        
        # Determine connection status
        if health['overall_healthy']:
            connection_status = "connected"
        elif health['configuration']['config_healthy']:
            connection_status = "disconnected"
        else:
            connection_status = "error"
        
        return StatusResponse(
            connection_status=connection_status,
            last_test=config.last_health_check.isoformat() if config.last_health_check else None,
            webhook_active=config.is_active,
            messages_today=health['response_rate_1h']['inbound_count'],
            response_rate=health['response_rate_1h']['response_rate'],
            provider=provider,
            phone_number=phone_number or "-"
        )
        
    except Exception as e:
        logger.exception(f"[WhatsApp Status] Status check failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/activate/{tenant_id}")
async def activate_whatsapp(
    tenant_id: str,
    db: Session = Depends(get_db)
):
    """
    Activate WhatsApp for tenant (go-live)
    
    Args:
        tenant_id: Tenant ID
        db: Database session
        
    Returns:
        Activation result
    """
    try:
        # First test connection
        test_result = await test_whatsapp_connection(tenant_id, db)
        
        if not test_result.success:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot activate - connection test failed: {test_result.message}"
            )
        
        # Get configuration
        config = db.query(WhatsAppConfiguration).filter(
            WhatsAppConfiguration.tenant_id == tenant_id
        ).first()
        
        if config:
            # Ensure it's active
            config.is_active = True
            db.commit()
            
            return {
                "success": True,
                "message": "WhatsApp activated successfully",
                "activated_at": config.last_health_check.isoformat(),
                "webhook_url": config.webhook_url,
                "phone_number": config.config_metadata.get("msg91_integrated_number") or config.phone_number_id
            }
        
        raise HTTPException(status_code=404, detail="Configuration not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[WhatsApp Activate] Activation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
