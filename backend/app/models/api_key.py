"""
API Key model for tenant authentication
"""
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer
from sqlalchemy.sql import func
from app.database import Base
import uuid
import secrets


class APIKey(Base):
    """
    API Key for tenant authentication with rate limiting support
    """
    __tablename__ = "api_keys"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    
    # Key info
    key = Column(String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(32))
    name = Column(String(255), nullable=False)  # e.g., "Production", "Testing", "Widget"
    key_type = Column(String(50), default="chat")  # "chat", "admin", "widget"
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Rate limiting
    rate_limit_per_minute = Column(Integer, default=60)  # Max requests per minute
    rate_limit_per_hour = Column(Integer, default=1000)  # Max requests per hour
    current_minute_count = Column(Integer, default=0)  # Sliding window tracking
    current_hour_count = Column(Integer, default=0)
    minute_reset_at = Column(DateTime, nullable=True)  # When minute window resets
    hour_reset_at = Column(DateTime, nullable=True)  # When hour window resets
    
    # Domain restrictions - comma-separated list of allowed domains
    allowed_domains = Column(String(500), nullable=True)  # e.g., "sdsfoodz.com,www.sdsfoodz.com"
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    last_used_at = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<APIKey(id={self.id}, tenant_id={self.tenant_id}, name={self.name})>"
