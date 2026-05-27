"""
OnboardingRequest — tenant self-service onboarding submissions
Admin reviews and clicks "Approve" to create the tenant.
"""
from sqlalchemy import Column, String, DateTime, JSON, Boolean, Text
from sqlalchemy.sql import func
from app.database import Base
import uuid


class OnboardingRequest(Base):
    """
    Stores a prospective tenant's onboarding form submission.
    Status flows:  pending → approved | rejected
    """
    __tablename__ = "onboarding_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Contact
    business_name = Column(String(255), nullable=False)
    contact_name  = Column(String(255), nullable=True)
    contact_email = Column(String(255), nullable=False)
    contact_phone = Column(String(50), nullable=True)

    # Business profile
    website_url   = Column(String(500), nullable=True)
    industry      = Column(String(50), nullable=True, default="services")
    services_list = Column(Text, nullable=True)  # newline-separated or comma-separated
    faqs          = Column(Text, nullable=True)
    welcome_message = Column(String(500), nullable=True)
    business_hours  = Column(String(100), nullable=True)

    # Channels requested
    want_chat_widget = Column(Boolean, default=True)
    want_whatsapp    = Column(Boolean, default=False)

    # WhatsApp details (if provided up-front)
    wa_phone_number_id     = Column(String(50), nullable=True)
    wa_business_account_id = Column(String(50), nullable=True)
    wa_access_token        = Column(String(500), nullable=True)

    # Admin tracking
    status        = Column(String(20), default="pending")   # awaiting_otp, pending, approved, rejected
    admin_notes   = Column(Text, nullable=True)
    created_tenant_id = Column(String(36), nullable=True)

    # OTP verification
    otp_code      = Column(String(10), nullable=True)
    otp_verified  = Column(Boolean, default=False)
    otp_expires_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<OnboardingRequest(id={self.id}, name={self.business_name}, status={self.status})>"
