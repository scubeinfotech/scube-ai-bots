"""
Chat models - messages and sessions
"""
from sqlalchemy import Column, String, DateTime, Text, Integer, JSON, ForeignKey
from sqlalchemy.sql import func
from app.database import Base
import uuid


class ChatSession(Base):
    """
    Chat session - represents a conversation
    """
    __tablename__ = "chat_sessions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    user_id = Column(String(255), nullable=True)  # Optional user identifier
    
    # Metadata
    title = Column(String(255), nullable=True)
    session_data = Column(JSON, nullable=True)
    
    # Lead collection (for converting chat users to leads)
    lead_name = Column(String(255), nullable=True)
    lead_email = Column(String(255), nullable=True)
    lead_phone = Column(String(50), nullable=True)
    lead_collected_at = Column(DateTime, nullable=True)
    lead_prompt_count = Column(Integer, default=0)  # Track message count for trigger
    
    # Booking link (populated when a booking is created from this chat session)
    booking_id = Column(String(36), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<ChatSession(id={self.id}, tenant_id={self.tenant_id})>"


class ChatMessage(Base):
    """
    Individual chat message
    """
    __tablename__ = "chat_messages"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=False)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    
    # Message content
    role = Column(String(20), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    
    # LLM tracking
    model_used = Column(String(255), nullable=True)
    tokens_used = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    
    # Metadata
    msg_metadata = Column(JSON, nullable=True)

    # User feedback
    feedback_score = Column(Integer, nullable=True)  # -1 = negative, 1 = positive
    feedback_comment = Column(Text, nullable=True)
    feedback_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    
    def __repr__(self):
        return f"<ChatMessage(id={self.id}, session_id={self.session_id}, role={self.role})>"
