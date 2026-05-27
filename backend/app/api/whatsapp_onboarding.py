"""
WhatsApp Onboarding API
Simplified endpoint for new tenant WhatsApp setup
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Tenant
from app.services.whatsapp_config_manager import WhatsAppConfigManager
from app.services.whatsapp_validator import WhatsAppConfigValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp Onboarding"])

class OnboardingRequest(BaseModel):
    """WhatsApp onboarding request"""
    tenant_id: str
    provider: str  # 'msg91' or 'meta'
    
    # MSG91 fields
    msg91_auth_key: str = ""
    msg91_integrated_number: str = ""
    
    # Meta fields
    phone_number_id: str = ""
    business_account_id: str = ""
    meta_access_token: str = ""
    
    # Optional settings
    auto_response_enabled: bool = True
    rate_limit_max_per_minute: int = 5
    cooldown_seconds: int = 2

class OnboardingResponse(BaseModel):
    """Onboarding response"""
    success: bool
    message: str
    config_id: str = None
    webhook_url: str = None
    next_steps: list = []

@router.post("/onboard")
async def onboard_whatsapp(
    request: OnboardingRequest,
    db: Session = Depends(get_db)
) -> OnboardingResponse:
    """
    Simplified WhatsApp onboarding for new tenants
    
    Args:
        request: Onboarding request
        db: Database session
        
    Returns:
        Onboarding result with next steps
    """
    try:
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.id == request.tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Prepare configuration based on provider
        config_data = WhatsAppConfigManager.get_onboarding_template()
        config_data['auto_response_enabled'] = request.auto_response_enabled
        config_data['rate_limit_max_per_minute'] = request.rate_limit_max_per_minute
        config_data['cooldown_seconds'] = request.cooldown_seconds
        
        if request.provider.lower() == 'msg91':
            # MSG91 configuration
            if not request.msg91_auth_key or not request.msg91_integrated_number:
                raise HTTPException(
                    status_code=400, 
                    detail="MSG91 auth key and integrated number are required"
                )
            
            config_data['config_metadata'] = {
                'msg91_auth_key': request.msg91_auth_key,
                'msg91_integrated_number': request.msg91_integrated_number,
                'msg91_api_endpoint': 'https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/'
            }
            config_data['phone_number_id'] = request.msg91_integrated_number
            config_data['access_token'] = request.msg91_auth_key
            
        elif request.provider.lower() == 'meta':
            # Meta API configuration
            if not all([request.phone_number_id, request.business_account_id, request.meta_access_token]):
                raise HTTPException(
                    status_code=400,
                    detail="Phone Number ID, Business Account ID, and Access Token are required for Meta API"
                )
            
            config_data['phone_number_id'] = request.phone_number_id
            config_data['business_account_id'] = request.business_account_id
            config_data['access_token'] = request.meta_access_token
            config_data['config_metadata'] = {}  # No MSG91 for Meta
            
        else:
            raise HTTPException(status_code=400, detail="Provider must be 'msg91' or 'meta'")
        
        # Validate configuration
        validation = WhatsAppConfigValidator.validate_config_before_save(
            db, request.tenant_id, config_data
        )
        
        if not validation['valid']:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Configuration validation failed",
                    "errors": validation['errors']
                }
            )
        
        # Create or update configuration
        existing_config = WhatsAppConfigManager.get_config(db, request.tenant_id)
        if existing_config:
            config = WhatsAppConfigManager.update_config(db, request.tenant_id, config_data)
        else:
            config = WhatsAppConfigManager.create_config(db, request.tenant_id, config_data)
        
        # Prepare next steps
        next_steps = []
        if request.provider.lower() == 'meta':
            next_steps = [
                "1. Go to Meta Developer Console",
                f"2. Set webhook URL: {config.webhook_url}",
                "3. Set verify token: scube_wa_verify_2024",
                "4. Subscribe to 'messages' webhook field",
                "5. Test by sending a message"
            ]
        else:
            next_steps = [
                "1. MSG91 configuration is complete",
                "2. Test by sending a message to your WhatsApp number",
                "3. Check if bot responds"
            ]
        
        logger.info(f"[WhatsApp Onboarding] Successfully configured {request.provider} for tenant {request.tenant_id}")
        
        return OnboardingResponse(
            success=True,
            message=f"WhatsApp configured successfully using {request.provider.upper()}",
            config_id=config.id,
            webhook_url=config.webhook_url,
            next_steps=next_steps
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[WhatsApp Onboarding] Failed for tenant {request.tenant_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/onboard/template")
async def get_onboarding_template():
    """Get onboarding template with field descriptions"""
    return {
        "msg91_template": {
            "provider": "msg91",
            "msg91_auth_key": "Get from MSG91 dashboard",
            "msg91_integrated_number": "Your WhatsApp number with country code",
            "auto_response_enabled": True,
            "rate_limit_max_per_minute": 5,
            "cooldown_seconds": 2
        },
        "meta_template": {
            "provider": "meta",
            "phone_number_id": "From Meta Developer Console",
            "business_account_id": "From Meta Developer Console", 
            "meta_access_token": "From Meta Developer Console",
            "auto_response_enabled": True,
            "rate_limit_max_per_minute": 5,
            "cooldown_seconds": 2
        },
        "recommended": "Use MSG91 for easier setup - no webhook configuration required"
    }

@router.post("/migrate/{tenant_id}")
async def migrate_from_env(
    tenant_id: str,
    db: Session = Depends(get_db)
):
    """Migrate configuration from environment variables to database"""
    result = WhatsAppConfigManager.migrate_from_env(db, tenant_id)
    return result
