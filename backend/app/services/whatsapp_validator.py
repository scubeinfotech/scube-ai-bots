"""
WhatsApp Configuration Validator
Prevents silent failures by validating configuration before saving
"""
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.whatsapp import WhatsAppConfiguration

logger = logging.getLogger(__name__)

class WhatsAppConfigValidator:
    """Validates WhatsApp configuration to prevent silent failures"""
    
    @staticmethod
    def validate_config_before_save(
        db: Session,
        tenant_id: str,
        config_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate configuration before saving
        
        Returns:
            Dict with 'valid' boolean and 'errors' list
        """
        errors = []
        warnings = []
        
        # Get current config for comparison
        current_config = db.query(WhatsAppConfiguration).filter(
            WhatsAppConfiguration.tenant_id == tenant_id
        ).first()
        
        # Critical validation: MSG91 metadata
        msg91_auth_key = config_data.get('config_metadata', {}).get('msg91_auth_key')
        msg91_integrated_number = config_data.get('config_metadata', {}).get('msg91_integrated_number')
        
        if current_config and current_config.config_metadata.get('msg91_auth_key'):
            # Currently using MSG91
            if not msg91_auth_key:
                errors.append(
                    "CRITICAL: Removing MSG91 configuration will break bot responses! "
                    "MSG91 allows sending to any user, Meta API has restrictions."
                )
                return {'valid': False, 'errors': errors, 'warnings': warnings}
            
            if msg91_auth_key != current_config.config_metadata.get('msg91_auth_key'):
                warnings.append("MSG91 auth key changed - this may affect message delivery")
            
            if not msg91_integrated_number:
                errors.append("MSG91 integrated number is required when using MSG91")
        
        # Validate required fields
        if not config_data.get('phone_number_id'):
            errors.append("Phone Number ID is required")
        
        if not config_data.get('webhook_url'):
            errors.append("Webhook URL is required")
        
        if config_data.get('auto_response_enabled') is None:
            errors.append("Auto Response setting must be specified")
        
        # Validate rate limits
        rate_limit = config_data.get('rate_limit_max_per_minute', 5)
        if rate_limit < 1 or rate_limit > 100:
            errors.append("Rate limit must be between 1 and 100 messages per minute")
        
        cooldown = config_data.get('cooldown_seconds', 2)
        if cooldown < 0 or cooldown > 60:
            errors.append("Cooldown must be between 0 and 60 seconds")
        
        # Check for potential breaking changes
        if current_config:
            if current_config.auto_response_enabled and not config_data.get('auto_response_enabled'):
                warnings.append("Disabling auto-response will stop bot from replying to messages")
            
            if current_config.is_active and not config_data.get('is_active'):
                warnings.append("Disabling WhatsApp will stop all message processing")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }
    
    @staticmethod
    def test_configuration(
        db: Session,
        tenant_id: str,
        config: WhatsAppConfiguration
    ) -> Dict[str, Any]:
        """
        Test if configuration can send messages
        
        Returns:
            Dict with test results
        """
        try:
            from app.services.whatsapp_service import WhatsAppService
            import asyncio
            
            async def run_test():
                service = WhatsAppService(db)
                # Test with a safe test message
                result = await service._send_whatsapp_message(
                    wa_config=config,
                    recipient_phone='6594561045',  # Known working number
                    message_text='Configuration test - please ignore'
                )
                return result
            
            result = asyncio.run(run_test())
            
            if result.get('success'):
                return {
                    'test_passed': True,
                    'message': 'Configuration test successful'
                }
            else:
                return {
                    'test_passed': False,
                    'message': f'Configuration test failed: {result.get("error", "Unknown error")}'
                }
                
        except Exception as e:
            logger.exception(f"Configuration test failed: {str(e)}")
            return {
                'test_passed': False,
                'message': f'Configuration test error: {str(e)}'
            }
    
    @staticmethod
    def get_working_config_backup() -> Dict[str, Any]:
        """Get the known working configuration for restoration"""
        return {
            'phone_number_id': '1069501506253151',
            'business_account_id': '2025919281614311',
            'access_token': 'EAAdPhtILTHEBRv8SZBr0FEmFsTlCo...',
            'webhook_url': 'https://chat.scubeinfotech.com.sg/api/whatsapp/webhook/fb8a4ec0-e463-4678-8178-32b8332db73a',
            'webhook_verify_token': 'scube_wa_verify_2024',
            'is_active': True,
            'auto_response_enabled': True,
            'enable_booking_flow': False,
            'enable_interactive_responses': True,
            'short_response_mode': True,
            'rate_limit_max_per_minute': 5,
            'cooldown_seconds': 2,
            'response_target_chars': 300,
            'config_metadata': {
                'msg91_auth_key': '516065A2X1NLCv6a1167dcP1',
                'msg91_integrated_number': '6580786788',
                'msg91_api_endpoint': 'https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/'
            },
            'api_version': 'v18.0'
        }
