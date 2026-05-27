"""
Document model for knowledge base and RAG
"""
from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, Boolean, Float, JSON
from sqlalchemy.sql import func
from app.database import Base
import uuid


class Document(Base):
    """
    Knowledge base document for tenant RAG
    """
    __tablename__ = "documents"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    
    # Document info
    name = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=True)
    content = Column(Text, nullable=False)
    
    # Metadata
    document_type = Column(String(50), default="document")  # document, faq, guide, etc
    category = Column(String(255), nullable=True)
    
    # Status
    is_processed = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<Document(id={self.id}, tenant_id={self.tenant_id}, name={self.name})>"


class DocumentChunk(Base):
    """
    Chunked document vectors for semantic retrieval.
    Embeddings are stored as JSON arrays for portability.
    """
    __tablename__ = "document_chunks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=False)

    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(JSON, nullable=False)
    source_name = Column(String(255), nullable=True)
    source_url = Column(String(512), nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<DocumentChunk(id={self.id}, tenant_id={self.tenant_id}, document_id={self.document_id})>"


class UnansweredQuery(Base):
    """
    Tracks queries that couldn't be answered by LLM
    """
    __tablename__ = "unanswered_queries"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=True)
    
    # Query details
    query = Column(Text, nullable=False)
    response = Column(Text, nullable=True)
    
    # Confidence/reasoning
    confidence_score = Column(Float, nullable=True)  # 0-1, low = likely unanswered
    reason = Column(String(255), nullable=True)  # why marked as unanswered
    
    # Resolution
    is_resolved = Column(Boolean, default=False)
    resolution_notes = Column(Text, nullable=True)
    
    # Training
    is_used_for_training = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<UnansweredQuery(id={self.id}, tenant_id={self.tenant_id})>"
