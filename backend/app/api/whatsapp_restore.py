"""
WhatsApp Configuration Restoration API
Emergency restore endpoint for broken configurations
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.whatsapp import WhatsAppConfiguration
from app.services.whatsapp_validator import WhatsAppConfigValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp Restore"])

class RestoreRequest(BaseModel):
    """Restore request model"""
    confirm: bool = False
    reason: str = ""

@router.post("/restore/{tenant_id}")
async def restore_working_config(
    tenant_id: str,
    request: RestoreRequest,
    db: Session = Depends(get_db)
):
    """
    Emergency restore of working WhatsApp configuration
    
    Args:
        tenant_id: Tenant ID
        request: Restore request with confirmation
        db: Database session
        
    Returns:
        Restore result
    """
    if not request.confirm:
        raise HTTPException(
            status_code=400, 
            detail="Must confirm restore by setting confirm=true"
        )
    
    # Get working configuration
    working_config = WhatsAppConfigValidator.get_working_config_backup()
    
    # Get current config
    current_config = db.query(WhatsAppConfiguration).filter(
        WhatsAppConfiguration.tenant_id == tenant_id
    ).first()
    
    if current_config:
        # Backup current config before restore
        backup_data = {
            'phone_number_id': current_config.phone_number_id,
            'business_account_id': current_config.business_account_id,
            'access_token': current_config.access_token,
            'webhook_url': current_config.webhook_url,
            'webhook_verify_token': current_config.webhook_verify_token,
            'is_active': current_config.is_active,
            'auto_response_enabled': current_config.auto_response_enabled,
            'enable_booking_flow': current_config.enable_booking_flow,
            'enable_interactive_responses': current_config.enable_interactive_responses,
            'short_response_mode': current_config.short_response_mode,
            'rate_limit_max_per_minute': current_config.rate_limit_max_per_minute,
            'cooldown_seconds': current_config.cooldown_seconds,
            'response_target_chars': current_config.response_target_chars,
            'config_metadata': current_config.config_metadata
        }
        
        logger.warning(f"[WhatsApp Restore] Backing up current config for tenant {tenant_id}: {backup_data}")
        
        # Restore working configuration
        current_config.phone_number_id = working_config['phone_number_id']
        current_config.business_account_id = working_config['business_account_id']
        current_config.access_token = working_config['access_token']
        current_config.webhook_url = working_config['webhook_url']
        current_config.webhook_verify_token = working_config['webhook_verify_token']
        current_config.is_active = working_config['is_active']
        current_config.auto_response_enabled = working_config['auto_response_enabled']
        current_config.enable_booking_flow = working_config['enable_booking_flow']
        current_config.enable_interactive_responses = working_config['enable_interactive_responses']
        current_config.short_response_mode = working_config['short_response_mode']
        current_config.rate_limit_max_per_minute = working_config['rate_limit_max_per_minute']
        current_config.cooldown_seconds = working_config['cooldown_seconds']
        current_config.response_target_chars = working_config['response_target_chars']
        current_config.config_metadata = working_config['config_metadata']
        
        db.commit()
        
        logger.info(f"[WhatsApp Restore] Restored working config for tenant {tenant_id}")
        
        return {
            "success": True,
            "message": "Working configuration restored",
            "restored_config": working_config,
            "reason": request.reason
        }
    else:
        raise HTTPException(status_code=404, detail="No configuration found to restore")

@router.get("/health/{tenant_id}")
async def get_whatsapp_health(
    tenant_id: str,
    db: Session = Depends(get_db)
):
    """Get WhatsApp health status"""
    from app.services.whatsapp_monitor import WhatsAppMonitor
    
    health = WhatsAppMonitor.get_health_report(db, tenant_id)
    return health
