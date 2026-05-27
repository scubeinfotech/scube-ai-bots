"""
Calendar Integration models — Google Calendar + Zoom + availability slots
"""
from sqlalchemy import Column, String, DateTime, JSON, Boolean, Integer, Text, ForeignKey
from sqlalchemy.sql import func
from app.database import Base
import uuid


class CalendarIntegration(Base):
    """Stores OAuth tokens and settings for a tenant's calendar provider."""
    __tablename__ = "calendar_integrations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)

    provider = Column(String(20), default="google")  # google, zoom
    provider_email = Column(String(255), nullable=True)  # Connected account email

    # OAuth tokens (encrypted at rest in production)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)

    # Calendar-specific settings
    calendar_id = Column(String(255), nullable=True)  # Primary calendar ID
    timezone = Column(String(50), default="Asia/Singapore")

    # Meeting link settings
    meeting_provider = Column(String(20), default="google_meet")  # google_meet, zoom
    zoom_api_key = Column(String(255), nullable=True)
    zoom_api_secret = Column(String(255), nullable=True)

    is_active = Column(Boolean, default=True)
    is_connected = Column(Boolean, default=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<CalendarIntegration(id={self.id}, tenant_id={self.tenant_id}, provider={self.provider})>"


class TenantAvailability(Base):
    """Weekly availability slots for a tenant — used by chatbot for booking."""
    __tablename__ = "tenant_availability"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)

    day_of_week = Column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    start_time = Column(String(5), nullable=False)  # "09:00"
    end_time = Column(String(5), nullable=False)    # "17:00"
    timezone = Column(String(50), default="Asia/Singapore")

    # Optional: block specific dates (holidays, etc.)
    blocked_dates = Column(JSON, nullable=True)  # ["2026-12-25", "2027-01-01"]

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TenantAvailability(id={self.id}, tenant_id={self.tenant_id}, day={self.day_of_week})>"
