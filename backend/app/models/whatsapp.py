"""
WhatsApp models - database models for WhatsApp integration
Tracks incoming messages, conversation state, and delivery status
"""
from sqlalchemy import Column, String, DateTime, Text, Integer, JSON, ForeignKey, Boolean, Float
from sqlalchemy.sql import func
from app.database import Base
import uuid


class WhatsAppContact(Base):
    """
    WhatsApp contact - represents a user/customer on WhatsApp
    """
    __tablename__ = "whatsapp_contacts"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    
    # WhatsApp identifiers
    phone_number = Column(String(20), nullable=False)  # E.164 format: +country_code...
    whatsapp_contact_id = Column(String(255), nullable=True)  # WhatsApp's internal ID
    
    # Contact info
    contact_name = Column(String(255), nullable=True)
    profile_picture_url = Column(String(500), nullable=True)
    
    # Interaction tracking
    first_message_at = Column(DateTime, nullable=True)
    last_message_at = Column(DateTime, nullable=True)
    total_messages = Column(Integer, default=0)
    
    # Status
    is_active = Column(Boolean, default=True)
    opted_out = Column(Boolean, default=False)  # For GDPR/privacy
    
    # Metadata
    contact_metadata = Column(JSON, nullable=True)  # Custom fields
    
    # CRM enrichment fields
    company = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    job_title = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)  # ["vip", "repeat", "hot_lead"]
    source_channel = Column(String(50), default="whatsapp")  # whatsapp, chat, imported
    last_lead_status = Column(String(50), nullable=True)  # tentative, confirmed, cancelled, none
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<WhatsAppContact(id={self.id}, phone={self.phone_number})>"


class ContactActivity(Base):
    """
    Unified activity timeline for contacts across all channels
    """
    __tablename__ = "contact_activities"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    contact_id = Column(String(36), ForeignKey("whatsapp_contacts.id"), nullable=False)

    activity_type = Column(String(50), nullable=False)  # message_in, message_out, lead_created, lead_confirmed, lead_cancelled, note_added, tag_added, followup_sent
    description = Column(Text, nullable=True)

    # Optional refs
    ref_type = Column(String(50), nullable=True)  # whatsapp_message, tentative_booking, scheduled_message
    ref_id = Column(String(36), nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<ContactActivity(id={self.id}, type={self.activity_type})>"


class WhatsAppMessage(Base):
    """
    WhatsApp message - incoming and outgoing WhatsApp messages
    """
    __tablename__ = "whatsapp_messages"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    contact_id = Column(String(36), ForeignKey("whatsapp_contacts.id"), nullable=False)
    
    # Reference to internal chat session (if applicable)
    chat_session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=True)
    
    # Message identifiers
    whatsapp_message_id = Column(String(255), nullable=True, unique=True)  # WhatsApp's message ID
    
    # Message content
    direction = Column(String(10), nullable=False)  # "inbound" or "outbound"
    message_type = Column(String(50), default="text")  # text, image, video, document, interactive
    content = Column(Text, nullable=False)
    
    # Metadata
    msg_metadata = Column(JSON, nullable=True)
    
    # Status tracking
    delivery_status = Column(String(50), default="pending")  # pending, sent, delivered, read, failed
    delivery_timestamp = Column(DateTime, nullable=True)
    read_timestamp = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Processing
    processed = Column(Boolean, default=False)  # Whether message was processed
    processing_error = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<WhatsAppMessage(id={self.id}, direction={self.direction})>"


class WhatsAppSession(Base):
    """
    WhatsApp session - tracks conversation context between contact and tenant
    """
    __tablename__ = "whatsapp_sessions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    contact_id = Column(String(36), ForeignKey("whatsapp_contacts.id"), nullable=False)
    
    # Reference to LLM chat session (for RAG context)
    llm_session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=True)
    
    # Session state
    status = Column(String(50), default="active")  # active, paused, closed
    current_intent = Column(String(100), nullable=True)  # e.g., booking, support, inquiry
    
    # Business context
    booking_flow_state = Column(String(50), nullable=True)  # For booking flows
    booking_data = Column(JSON, nullable=True)  # Accumulated booking form data
    
    # Message tracking
    message_count = Column(Integer, default=0)
    last_user_message_at = Column(DateTime, nullable=True)
    last_ai_message_at = Column(DateTime, nullable=True)
    
    # Session metadata
    session_metadata = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<WhatsAppSession(id={self.id}, status={self.status})>"


class WhatsAppConfiguration(Base):
    """
    WhatsApp configuration - per-tenant WhatsApp settings
    """
    __tablename__ = "whatsapp_configurations"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, unique=True)
    
    # WhatsApp Business API credentials
    phone_number_id = Column(String(255), nullable=False)
    business_account_id = Column(String(255), nullable=False)
    access_token = Column(String(500), nullable=False)  # Should be encrypted in production
    
    # Configuration
    api_version = Column(String(20), default="v18.0")
    webhook_url = Column(String(500), nullable=True)
    webhook_verify_token = Column(String(255), nullable=True)
    
    # Features
    enable_message_forwarding = Column(Boolean, default=True)  # Forward to LLM
    enable_booking_flow = Column(Boolean, default=False)
    enable_interactive_responses = Column(Boolean, default=True)  # Buttons/lists
    
    # Response settings
    auto_response_enabled = Column(Boolean, default=True)
    response_timeout_seconds = Column(Integer, default=30)
    short_response_mode = Column(Boolean, default=True)  # Keep responses short
    rate_limit_max_per_minute = Column(Integer, default=5)  # Max outbound/contact/min
    cooldown_seconds = Column(Integer, default=2)  # Min gap between outbound msgs
    response_target_chars = Column(Integer, default=300)  # Target reply length
    
    # Metadata
    config_metadata = Column(JSON, nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True)
    last_health_check = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<WhatsAppConfiguration(tenant_id={self.tenant_id})>"


class WhatsAppMetrics(Base):
    """
    WhatsApp metrics - usage and performance metrics
    """
    __tablename__ = "whatsapp_metrics"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    
    # Date/time
    period_date = Column(DateTime, nullable=False)  # Day of metrics
    
    # Message counts
    messages_received = Column(Integer, default=0)
    messages_sent = Column(Integer, default=0)
    messages_failed = Column(Integer, default=0)
    
    # Performance
    avg_response_time_ms = Column(Integer, default=0)
    avg_llm_latency_ms = Column(Integer, default=0)
    
    # Engagement
    unique_contacts = Column(Integer, default=0)
    conversations_started = Column(Integer, default=0)
    conversations_completed = Column(Integer, default=0)
    
    # Booking metrics (if enabled)
    booking_attempts = Column(Integer, default=0)
    booking_completions = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<WhatsAppMetrics(tenant_id={self.tenant_id}, date={self.period_date})>"


class WhatsAppTentativeBooking(Base):
    """
    Tentative booking record extracted from inbound WhatsApp intent.
    """
    __tablename__ = "whatsapp_tentative_bookings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    contact_id = Column(String(36), ForeignKey("whatsapp_contacts.id"), nullable=True)
    whatsapp_session_id = Column(String(36), ForeignKey("whatsapp_sessions.id"), nullable=True)
    source_message_id = Column(String(36), ForeignKey("whatsapp_messages.id"), nullable=True)

    # Origin channel – 'whatsapp' (default) or 'chatbot'
    source = Column(String(20), default="whatsapp")

    # Intent context
    intent_type = Column(String(50), nullable=False)  # booking, callback, demo_scheduling
    status = Column(String(50), default="tentative")  # tentative, confirmed, cancelled

    # Extracted structured fields
    requested_date = Column(String(50), nullable=True)
    requested_time = Column(String(50), nullable=True)
    requested_persons = Column(Integer, nullable=True)
    requested_type = Column(String(100), nullable=True)

    # Raw and normalized payload details
    raw_text = Column(Text, nullable=False)
    extracted_fields = Column(JSON, nullable=True)

    # Step 3 – Google Calendar & lifecycle timestamps
    google_calendar_event_id = Column(String(255), nullable=True)
    calendar_synced_at        = Column(DateTime, nullable=True)
    confirmed_at              = Column(DateTime, nullable=True)
    cancelled_at              = Column(DateTime, nullable=True)
    confirmation_sent_at      = Column(DateTime, nullable=True)

    # Step 5 – Human handoff workflow
    assigned_to = Column(String(120), nullable=True)
    assigned_at = Column(DateTime, nullable=True)
    priority = Column(String(20), default="normal")
    due_by = Column(DateTime, nullable=True)
    escalation_level = Column(Integer, default=0)
    handoff_notes = Column(Text, nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return (
            f"<WhatsAppTentativeBooking(id={self.id}, "
            f"tenant_id={self.tenant_id}, intent={self.intent_type})>"
        )


class WhatsAppAnalyticsEvent(Base):
    """
    Step 6 – per-event analytics log.
    Captures intent detection, booking lifecycle, human interventions,
    and automation side-effects (calendar/CRM sync).
    """
    __tablename__ = "whatsapp_analytics_events"

    id               = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id        = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    event_type       = Column(String(50), nullable=False)
    intent           = Column(String(50), nullable=True)
    confidence_score = Column(Float, nullable=True)
    session_id       = Column(String(36), nullable=True)
    contact_id       = Column(String(36), nullable=True)
    booking_id       = Column(String(36), nullable=True)
    sub_type         = Column(String(50), nullable=True)
    event_metadata   = Column(JSON, nullable=True)
    created_at       = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<WhatsAppAnalyticsEvent(tenant={self.tenant_id}, type={self.event_type})>"


class FollowUpTemplate(Base):
    """
    CRM follow-up template — industry-aware, trigger-based message templates
    Templates can be global (tenant_id=NULL) or tenant-specific overrides.
    """
    __tablename__ = "follow_up_templates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True)  # NULL = global
    industry = Column(String(50), nullable=True)  # NULL = all industries
    trigger_event = Column(String(50), nullable=False)  # lead_created, lead_confirmed, abandoned, inactive_7d
    delay_hours = Column(Integer, default=24)

    template_text = Column(Text, nullable=False)  # Supports {{name}}, {{service}}, {{date}}, {{time}}
    conclusive_line = Column(Text, nullable=True)  # Benefit to customer + CTA for business

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<FollowUpTemplate(id={self.id}, event={self.trigger_event})>"


class ScheduledMessage(Base):
    """
    CRM scheduled message — a follow-up message queued for future delivery
    """
    __tablename__ = "scheduled_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    contact_id = Column(String(36), ForeignKey("whatsapp_contacts.id"), nullable=False)
    template_id = Column(String(36), ForeignKey("follow_up_templates.id"), nullable=True)

    trigger_event = Column(String(50), nullable=True)
    scheduled_at = Column(DateTime, nullable=False)
    status = Column(String(20), default="pending")  # pending, sent, cancelled
    message_text = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ScheduledMessage(id={self.id}, status={self.status})>"
