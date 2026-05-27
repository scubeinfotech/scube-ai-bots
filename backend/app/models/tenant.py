"""
Tenant model - represents a customer/website
"""
from sqlalchemy import Column, String, DateTime, JSON, Boolean
from sqlalchemy.sql import func
from app.database import Base
import uuid


class Tenant(Base):
    """
    Tenant model representing a customer website
    """
    __tablename__ = "tenants"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False)  # e.g., 'rapas', 'sdsfoodz'
    domain = Column(String(255), nullable=False)
    
    # Configuration
    prompt_template = Column(String(2000), nullable=True)  # Tenant-specific prompt
    knowledge_context = Column(JSON, nullable=True)  # Domain knowledge
    guardrails = Column(JSON, nullable=True)  # Safety constraints
    welcome_message = Column(String(500), nullable=True)  # Auto-greeting for chat widget
    
    # Business Profile (Phase 1A - Multi-Industry Support)
    industry = Column(String(50), nullable=True)  # food, services, retail, accounting, insurance, non-profit, other
    contact_email = Column(String(255), nullable=True)  # Admin contact for this tenant
    business_hours = Column(String(100), nullable=True)  # e.g., "Mon-Sat 9AM-6PM"
    tone = Column(String(50), default="friendly")  # friendly, formal, consultative
    compliance_mode = Column(String(50), default="normal")  # normal, high-regulation
    out_of_scope_mode = Column(String(50), default="strict_business")  # strict_business, assistive_general
    subscription_tier = Column(String(50), default="starter")  # starter, growth, enterprise
    allowed_models = Column(JSON, nullable=True)  # model policy resolved per subscription + industry
    cta_goals = Column(JSON, nullable=True)  # allowed CTA types: lead, booking, quote, support
    website_url = Column(String(500), nullable=True)  # Primary website for crawl/extract
    onboarding_stage = Column(String(50), default="discovering")  # discovering, processing, ready
    onboarding_notes = Column(String(1000), nullable=True)  # Admin notes during onboarding
    
    # Crawl Progress Tracking
    crawl_progress_percent = Column(String(3), nullable=True, default='0')  # 0-100 integer as string
    crawl_progress_stage = Column(String(100), nullable=True, default='')  # Current crawl operation description
    crawl_progress_updated_at = Column(DateTime, nullable=True)  # Last progress update time
    
    # Settings
    model_name = Column(String(255), default="llama-3.3-70b-versatile")
    temperature = Column(String(10), default="0.7")
    max_tokens = Column(String(10), default="512")
    
    # Daily Report Settings
    daily_report_email = Column(String(255), nullable=True)  # Email for daily reports
    daily_report_enabled = Column(Boolean, default=False)  # Enable daily email reports
    
    # Booking/Callback Notification Settings
    notification_email = Column(String(255), nullable=True)  # Email for booking/callback notifications (defaults to daily_report_email)
    notify_on_booking = Column(Boolean, default=True)  # Email tenant when new booking/callback requested
    
    # Timezone Settings
    timezone = Column(String(50), default="Asia/Singapore")  # Tenant's timezone (e.g., Asia/Singapore, America/New_York)
    
    # Phase 2 Features - AI Agent Capabilities (Mandatory)
    enable_sentiment_analysis = Column(Boolean, default=True, nullable=False)  # Detect customer sentiment - MANDATORY
    enable_conversation_memory = Column(Boolean, default=True, nullable=False)  # Long-term memory - MANDATORY
    enable_function_calling = Column(Boolean, default=True, nullable=False)  # Book appointments, create leads - MANDATORY
    escalation_threshold = Column(String(10), default="-0.5")  # Sentiment score to trigger escalation
    
    # E-commerce API Integration (for retail tenants)
    external_api_url = Column(String(500), nullable=True)  # Their platform API URL
    external_api_key = Column(String(255), nullable=True)  # API key for their platform
    external_api_enabled = Column(Boolean, default=False)  # Enable external API calls
    
    # Multi-channel support (extensible for future channels like SMS, Messenger, etc.)
    enabled_channels = Column(JSON, default=lambda: {"chat": False, "whatsapp": False})
    
    # Status
    is_active = Column(Boolean, default=True)

    # Trial & Subscription (Phase 1 — Self-Service Onboarding)
    trial_ends_at = Column(DateTime, nullable=True)  # When free trial expires
    subscription_plan = Column(String(50), default="trial")  # trial, starter, growth, enterprise
    subscription_status = Column(String(20), default="active")  # active, expired, suspended
    stripe_customer_id = Column(String(255), nullable=True)  # For future Stripe billing

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Registration source tracking
    registration_source = Column(String(20), default="self")  # "self" = online registration, "admin" = created by admin team
    
    def __repr__(self):
        return f"<Tenant(id={self.id}, name={self.name}, slug={self.slug})>"
