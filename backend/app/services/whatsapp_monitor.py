"""
WhatsApp Configuration Monitor
Monitors WhatsApp bot health and detects issues
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.whatsapp import WhatsAppMessage, WhatsAppConfiguration

logger = logging.getLogger(__name__)

class WhatsAppMonitor:
    """Monitors WhatsApp bot health and configuration"""
    
    @staticmethod
    def check_response_rate(
        db: Session, 
        tenant_id: str, 
        hours: int = 1
    ) -> Dict[str, Any]:
        """
        Check response rate for the last N hours
        
        Returns:
            Dict with response rate statistics
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        
        # Count inbound and outbound messages
        inbound = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.tenant_id == tenant_id,
            WhatsAppMessage.direction == 'inbound',
            WhatsAppMessage.created_at >= since
        ).count()
        
        outbound = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.tenant_id == tenant_id,
            WhatsAppMessage.direction == 'outbound',
            WhatsAppMessage.created_at >= since
        ).count()
        
        response_rate = (outbound / inbound * 100) if inbound > 0 else 100
        
        return {
            'inbound_count': inbound,
            'outbound_count': outbound,
            'response_rate': response_rate,
            'period_hours': hours,
            'healthy': response_rate >= 50  # At least 50% response rate
        }
    
    @staticmethod
    def detect_configuration_issues(
        db: Session,
        tenant_id: str
    ) -> Dict[str, Any]:
        """
        Detect configuration issues
        
        Returns:
            Dict with detected issues
        """
        issues = []
        warnings = []
        
        config = db.query(WhatsAppConfiguration).filter(
            WhatsAppConfiguration.tenant_id == tenant_id
        ).first()
        
        if not config:
            issues.append("No WhatsApp configuration found")
            return {'issues': issues, 'warnings': warnings}
        
        # Check critical settings
        if not config.is_active:
            warnings.append("WhatsApp is disabled")
        
        if not config.auto_response_enabled:
            warnings.append("Auto-response is disabled - bot will not reply")
        
        # Check MSG91 configuration
        msg91_key = config.config_metadata.get('msg91_auth_key') if config.config_metadata else None
        if not msg91_key:
            issues.append(
                "MSG91 not configured - may have delivery issues with Meta API restrictions"
            )
        
        # Check webhook URL
        if not config.webhook_url:
            issues.append("Webhook URL not configured")
        
        # Check rate limits
        if config.rate_limit_max_per_minute < 1:
            issues.append("Invalid rate limit setting")
        
        return {
            'issues': issues,
            'warnings': warnings,
            'config_healthy': len(issues) == 0
        }
    
    @staticmethod
    def get_health_report(
        db: Session,
        tenant_id: str
    ) -> Dict[str, Any]:
        """
        Get complete health report
        
        Returns:
            Dict with health status
        """
        # Check response rate
        response_1h = WhatsAppMonitor.check_response_rate(db, tenant_id, 1)
        response_24h = WhatsAppMonitor.check_response_rate(db, tenant_id, 24)
        
        # Check configuration
        config_check = WhatsAppMonitor.detect_configuration_issues(db, tenant_id)
        
        # Overall health
        overall_healthy = (
            response_1h['healthy'] and 
            response_24h['healthy'] and 
            config_check['config_healthy']
        )
        
        return {
            'overall_healthy': overall_healthy,
            'response_rate_1h': response_1h,
            'response_rate_24h': response_24h,
            'configuration': config_check,
            'timestamp': datetime.utcnow().isoformat()
        }
    
    @staticmethod
    def log_health_status(db: Session, tenant_id: str):
        """Log health status for monitoring"""
        health = WhatsAppMonitor.get_health_report(db, tenant_id)
        
        if health['overall_healthy']:
            logger.info(f"[WhatsApp Monitor] Tenant {tenant_id}: Healthy")
        else:
            logger.error(f"[WhatsApp Monitor] Tenant {tenant_id}: UNHEALTHY")
            if not health['response_rate_1h']['healthy']:
                logger.error(
                    f"  Low response rate: {health['response_rate_1h']['response_rate']:.1f}% "
                    f"({health['response_rate_1h']['outbound_count']}/{health['response_rate_1h']['inbound_count']})"
                )
            
            for issue in health['configuration']['issues']:
                logger.error(f"  Config issue: {issue}")
            
            for warning in health['configuration']['warnings']:
                logger.warning(f"  Config warning: {warning}")
