"""
Centralized WhatsApp Configuration Manager
Single source of truth for all WhatsApp configuration
"""
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.whatsapp import WhatsAppConfiguration
from app.models import Tenant

logger = logging.getLogger(__name__)

class WhatsAppConfigManager:
    """Centralized WhatsApp configuration management"""
    
    @staticmethod
    def get_config(db: Session, tenant_id: str) -> Optional[WhatsAppConfiguration]:
        """Get WhatsApp configuration for tenant"""
        return db.query(WhatsAppConfiguration).filter(
            WhatsAppConfiguration.tenant_id == tenant_id
        ).first()
    
    @staticmethod
    def create_config(
        db: Session,
        tenant_id: str,
        config_data: Dict[str, Any]
    ) -> WhatsAppConfiguration:
        """Create new WhatsApp configuration"""
        # Auto-generate webhook URL and verify token
        config_data['webhook_url'] = f"https://chat.scubeinfotech.com.sg/api/whatsapp/webhook/{tenant_id}"
        config_data['webhook_verify_token'] = "scube_wa_verify_2024"
        
        config = WhatsAppConfiguration(
            tenant_id=tenant_id,
            phone_number_id=config_data.get('phone_number_id', ''),
            business_account_id=config_data.get('business_account_id', ''),
            access_token=config_data.get('access_token', ''),
            webhook_url=config_data['webhook_url'],
            webhook_verify_token=config_data['webhook_verify_token'],
            is_active=config_data.get('is_active', True),
            auto_response_enabled=config_data.get('auto_response_enabled', True),
            enable_booking_flow=config_data.get('enable_booking_flow', False),
            enable_interactive_responses=config_data.get('enable_interactive_responses', True),
            short_response_mode=config_data.get('short_response_mode', True),
            rate_limit_max_per_minute=config_data.get('rate_limit_max_per_minute', 5),
            cooldown_seconds=config_data.get('cooldown_seconds', 2),
            response_target_chars=config_data.get('response_target_chars', 300),
            config_metadata=config_data.get('config_metadata', {}),
            api_version=config_data.get('api_version', 'v18.0')
        )
        
        db.add(config)
        db.commit()
        db.refresh(config)
        
        logger.info(f"[WhatsApp Config] Created configuration for tenant {tenant_id}")
        return config
    
    @staticmethod
    def update_config(
        db: Session,
        tenant_id: str,
        config_data: Dict[str, Any]
    ) -> WhatsAppConfiguration:
        """Update existing WhatsApp configuration"""
        config = WhatsAppConfigManager.get_config(db, tenant_id)
        if not config:
            raise ValueError(f"No configuration found for tenant {tenant_id}")
        
        # Update fields
        for key, value in config_data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        
        db.commit()
        db.refresh(config)
        
        logger.info(f"[WhatsApp Config] Updated configuration for tenant {tenant_id}")
        return config
    
    @staticmethod
    def get_msg91_config(config: WhatsAppConfiguration) -> Dict[str, str]:
        """Extract MSG91 configuration"""
        if not config.config_metadata:
            return {}
        
        return {
            'auth_key': config.config_metadata.get('msg91_auth_key', ''),
            'integrated_number': config.config_metadata.get('msg91_integrated_number', ''),
            'api_endpoint': config.config_metadata.get('msg91_api_endpoint', 
                'https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/')
        }
    
    @staticmethod
    def get_provider_type(config: WhatsAppConfiguration) -> str:
        """Determine provider type from configuration"""
        if config.config_metadata and config.config_metadata.get('msg91_auth_key'):
            return 'msg91'
        elif config.access_token and config.phone_number_id:
            return 'meta'
        else:
            return 'none'
    
    @staticmethod
    def validate_provider_config(config_data: Dict[str, Any], provider_type: str) -> Dict[str, Any]:
        """Validate provider-specific configuration"""
        errors = []
        
        if provider_type == 'msg91':
            if not config_data.get('config_metadata', {}).get('msg91_auth_key'):
                errors.append("MSG91 auth key is required")
            if not config_data.get('config_metadata', {}).get('msg91_integrated_number'):
                errors.append("MSG91 integrated number is required")
        
        elif provider_type == 'meta':
            if not config_data.get('phone_number_id'):
                errors.append("Phone Number ID is required for Meta API")
            if not config_data.get('business_account_id'):
                errors.append("Business Account ID is required for Meta API")
            if not config_data.get('access_token'):
                errors.append("Access Token is required for Meta API")
        
        return {'valid': len(errors) == 0, 'errors': errors}
    
    @staticmethod
    def get_onboarding_template() -> Dict[str, Any]:
        """Get template for new tenant onboarding"""
        return {
            'phone_number_id': '',
            'business_account_id': '',
            'access_token': '',
            'is_active': True,
            'auto_response_enabled': True,
            'enable_booking_flow': False,
            'enable_interactive_responses': True,
            'short_response_mode': True,
            'rate_limit_max_per_minute': 5,
            'cooldown_seconds': 2,
            'response_target_chars': 300,
            'config_metadata': {
                'msg91_auth_key': '',
                'msg91_integrated_number': '',
                'msg91_api_endpoint': 'https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/'
            },
            'api_version': 'v18.0'
        }
    
    @staticmethod
    def migrate_from_env(db: Session, tenant_id: str) -> Dict[str, Any]:
        """Migrate configuration from environment variables to database"""
        import os
        from dotenv import load_dotenv
        
        load_dotenv('.env')
        
        config = WhatsAppConfigManager.get_config(db, tenant_id)
        if not config:
            return {'success': False, 'message': 'No configuration found'}
        
        migrated = False
        changes = []
        
        # Migrate MSG91_AUTH_KEY from env if not in config
        msg91_env_key = os.getenv('MSG91_AUTH_KEY')
        if msg91_env_key and not config.config_metadata.get('msg91_auth_key'):
            if not config.config_metadata:
                config.config_metadata = {}
            config.config_metadata['msg91_auth_key'] = msg91_env_key
            changes.append('Migrated MSG91_AUTH_KEY from .env')
            migrated = True
        
        # Migrate WHATSAPP_ACCESS_TOKEN from env if not in config
        wa_env_token = os.getenv('WHATSAPP_ACCESS_TOKEN')
        if wa_env_token and not config.access_token:
            config.access_token = wa_env_token
            changes.append('Migrated WHATSAPP_ACCESS_TOKEN from .env')
            migrated = True
        
        if migrated:
            db.commit()
            logger.info(f"[WhatsApp Config] Migrated configuration for tenant {tenant_id}")
            return {'success': True, 'changes': changes}
        
        return {'success': True, 'message': 'No migration needed'}
