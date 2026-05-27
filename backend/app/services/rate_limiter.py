"""
Rate limiting service for API key usage control.
Implements sliding window rate limiting per API key.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from sqlalchemy.orm import Session

from app.models.api_key import APIKey

logger = logging.getLogger(__name__)


class RateLimitService:
    """
    Rate limiter that tracks API key usage and enforces limits.
    Uses a simple sliding window approach with reset timestamps.
    """
    
    @classmethod
    def check_rate_limit(cls, db: Session, api_key_record: APIKey) -> Tuple[bool, Optional[str], Optional[dict]]:
        """
        Check if the API key is within rate limits.
        
        Returns:
            Tuple of (allowed, reason, headers)
            - allowed: True if request is allowed, False if rate limited
            - reason: Error message if not allowed, None if allowed
            - headers: Rate limit headers for response
        """
        now = datetime.now(timezone.utc)
        
        # Convert database datetime to timezone-aware for comparison
        def to_aware(dt):
            if dt is None:
                return None
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        
        minute_reset = to_aware(api_key_record.minute_reset_at)
        hour_reset = to_aware(api_key_record.hour_reset_at)
        
        # Reset minute counter if window expired
        if minute_reset and now >= minute_reset:
            api_key_record.current_minute_count = 0
            api_key_record.minute_reset_at = now + timedelta(minutes=1)
        
        # Reset hour counter if window expired  
        if hour_reset and now >= hour_reset:
            api_key_record.current_hour_count = 0
            api_key_record.hour_reset_at = now + timedelta(hours=1)
        
        # Check minute limit
        if api_key_record.current_minute_count >= api_key_record.rate_limit_per_minute:
            reset_in = (api_key_record.minute_reset_at - now).seconds if api_key_record.minute_reset_at else 60
            headers = cls._build_headers(
                api_key_record.rate_limit_per_minute,
                api_key_record.current_minute_count,
                reset_in
            )
            return False, f"Rate limit exceeded: {api_key_record.rate_limit_per_minute} requests per minute", headers
        
        # Check hour limit
        if api_key_record.current_hour_count >= api_key_record.rate_limit_per_hour:
            reset_in = (api_key_record.hour_reset_at - now).seconds if api_key_record.hour_reset_at else 3600
            headers = cls._build_headers(
                api_key_record.rate_limit_per_hour,
                api_key_record.current_hour_count,
                reset_in
            )
            return False, f"Rate limit exceeded: {api_key_record.rate_limit_per_hour} requests per hour", headers
        
        # Atomic increment to prevent race conditions
        from sqlalchemy import func
        db.query(APIKey).filter(APIKey.id == api_key_record.id).update({
            "current_minute_count": APIKey.current_minute_count + 1,
            "current_hour_count": APIKey.current_hour_count + 1,
            "last_used_at": now,
            "minute_reset_at": func.coalesce(APIKey.minute_reset_at, now + timedelta(minutes=1)),
            "hour_reset_at": func.coalesce(APIKey.hour_reset_at, now + timedelta(hours=1))
        }, synchronize_session=False)
        
        db.commit()
        
        # Refresh record to get updated values
        db.refresh(api_key_record)
        
        # Return headers with remaining quota
        remaining_min = api_key_record.rate_limit_per_minute - api_key_record.current_minute_count
        remaining_hour = api_key_record.rate_limit_per_hour - api_key_record.current_hour_count
        
        headers = {
            "X-RateLimit-Limit-Minute": str(api_key_record.rate_limit_per_minute),
            "X-RateLimit-Remaining-Minute": str(max(0, remaining_min)),
            "X-RateLimit-Limit-Hour": str(api_key_record.rate_limit_per_hour),
            "X-RateLimit-Remaining-Hour": str(max(0, remaining_hour)),
        }
        
        return True, None, headers
    
    @classmethod
    def _build_headers(cls, limit: int, current: int, reset_in_seconds: int) -> dict:
        """Build rate limit response headers."""
        return {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(reset_in_seconds),
            "Retry-After": str(reset_in_seconds),
        }
    
    @classmethod
    def get_usage_stats(cls, db: Session, api_key_id: str) -> Optional[dict]:
        """Get current usage statistics for an API key."""
        record = db.query(APIKey).filter(APIKey.id == api_key_id).first()
        if not record:
            return None
        
        now = datetime.now(timezone.utc)

        def _to_aware(dt):
            """Make a naive datetime timezone-aware (assume UTC) or return as-is if already aware."""
            if dt is None:
                return None
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        # Calculate remaining quota
        minute_remaining = 0
        hour_remaining = 0

        minute_reset = _to_aware(record.minute_reset_at)
        hour_reset = _to_aware(record.hour_reset_at)

        if minute_reset and now < minute_reset:
            minute_remaining = record.rate_limit_per_minute - record.current_minute_count

        if hour_reset and now < hour_reset:
            hour_remaining = record.rate_limit_per_hour - record.current_hour_count
        
        return {
            "api_key_id": record.id,
            "api_key_name": record.name,
            "key_type": record.key_type,
            "is_active": record.is_active,
            "rate_limit_per_minute": record.rate_limit_per_minute,
            "rate_limit_per_hour": record.rate_limit_per_hour,
            "current_minute_usage": record.current_minute_count,
            "current_hour_usage": record.current_hour_count,
            "minute_remaining": max(0, minute_remaining),
            "hour_remaining": max(0, hour_remaining),
            "last_used_at": record.last_used_at.isoformat() if record.last_used_at else None,
        }
    
    @classmethod
    def reset_usage(cls, db: Session, api_key_id: str) -> bool:
        """Reset usage counters for an API key."""
        record = db.query(APIKey).filter(APIKey.id == api_key_id).first()
        if not record:
            return False
        
        record.current_minute_count = 0
        record.current_hour_count = 0
        record.minute_reset_at = None
        record.hour_reset_at = None
        db.commit()
        
        return True
    
    @classmethod
    def update_limits(cls, db: Session, api_key_id: str, per_minute: int, per_hour: int) -> bool:
        """Update rate limits for an API key."""
        record = db.query(APIKey).filter(APIKey.id == api_key_id).first()
        if not record:
            return False
        
        record.rate_limit_per_minute = per_minute
        record.rate_limit_per_hour = per_hour
        db.commit()
        
        return True