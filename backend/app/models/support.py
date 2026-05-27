"""
Support ticket model for tenant support requests
"""
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.sql import func
from app.database import Base
import uuid


class SupportTicket(Base):
    """Support ticket raised by tenant users"""
    __tablename__ = "support_tickets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    tenant_user_id = Column(String(36), ForeignKey("tenant_users.id"), nullable=True)

    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(50), default="general")  # onboarding, billing, technical, feature_request, other
    status = Column(String(20), default="open")  # open, in_progress, resolved, closed
    priority = Column(String(20), default="normal")  # low, normal, high, urgent

    admin_notes = Column(Text, nullable=True)
    assigned_to = Column(String(255), nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    resolved_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<SupportTicket(id={self.id}, tenant_id={self.tenant_id}, status={self.status})>"
