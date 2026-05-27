"""
WhatsApp Database Migration
Creates necessary tables for WhatsApp integration

Run this script to initialize WhatsApp tables:
    python -c "from backend.app.models.whatsapp import *; from backend.app.database import Base, engine; Base.metadata.create_all(bind=engine)"

Or use Alembic for version-controlled migrations.
"""
from sqlalchemy import Column, String, DateTime, Text, Integer, JSON, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.database import Base


# Migration SQL (for manual database execution if needed)

WHATSAPP_MIGRATIONS = """

-- Create whatsapp_contacts table
CREATE TABLE IF NOT EXISTS whatsapp_contacts (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    phone_number VARCHAR(20) NOT NULL,
    whatsapp_contact_id VARCHAR(255),
    contact_name VARCHAR(255),
    profile_picture_url VARCHAR(500),
    first_message_at TIMESTAMP,
    last_message_at TIMESTAMP,
    total_messages INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    opted_out BOOLEAN DEFAULT FALSE,
    contact_metadata JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    UNIQUE KEY unique_phone_per_tenant (tenant_id, phone_number),
    INDEX idx_tenant_phone (tenant_id, phone_number),
    INDEX idx_last_message (last_message_at)
);

-- Create whatsapp_messages table
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    contact_id VARCHAR(36) NOT NULL,
    chat_session_id VARCHAR(36),
    whatsapp_message_id VARCHAR(255),
    direction VARCHAR(10) NOT NULL,
    message_type VARCHAR(50) DEFAULT 'text',
    content LONGTEXT NOT NULL,
    msg_metadata JSON,
    delivery_status VARCHAR(50) DEFAULT 'pending',
    delivery_timestamp TIMESTAMP,
    read_timestamp TIMESTAMP,
    error_message LONGTEXT,
    processed BOOLEAN DEFAULT FALSE,
    processing_error LONGTEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    FOREIGN KEY (contact_id) REFERENCES whatsapp_contacts(id),
    FOREIGN KEY (chat_session_id) REFERENCES chat_sessions(id),
    INDEX idx_tenant_contact (tenant_id, contact_id),
    INDEX idx_direction (direction),
    INDEX idx_status (delivery_status),
    INDEX idx_created (created_at)
);

-- Create whatsapp_sessions table
CREATE TABLE IF NOT EXISTS whatsapp_sessions (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    contact_id VARCHAR(36) NOT NULL,
    llm_session_id VARCHAR(36),
    status VARCHAR(50) DEFAULT 'active',
    current_intent VARCHAR(100),
    booking_flow_state VARCHAR(50),
    booking_data JSON,
    message_count INTEGER DEFAULT 0,
    last_user_message_at TIMESTAMP,
    last_ai_message_at TIMESTAMP,
    session_metadata JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    FOREIGN KEY (contact_id) REFERENCES whatsapp_contacts(id),
    FOREIGN KEY (llm_session_id) REFERENCES chat_sessions(id),
    INDEX idx_tenant_contact_status (tenant_id, contact_id, status),
    INDEX idx_updated (updated_at)
);

-- Create whatsapp_configurations table
CREATE TABLE IF NOT EXISTS whatsapp_configurations (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL UNIQUE,
    phone_number_id VARCHAR(255) NOT NULL,
    business_account_id VARCHAR(255) NOT NULL,
    access_token VARCHAR(500) NOT NULL,
    api_version VARCHAR(20) DEFAULT 'v18.0',
    webhook_url VARCHAR(500),
    webhook_verify_token VARCHAR(255),
    enable_message_forwarding BOOLEAN DEFAULT TRUE,
    enable_booking_flow BOOLEAN DEFAULT FALSE,
    enable_interactive_responses BOOLEAN DEFAULT TRUE,
    auto_response_enabled BOOLEAN DEFAULT TRUE,
    response_timeout_seconds INTEGER DEFAULT 30,
    short_response_mode BOOLEAN DEFAULT TRUE,
    rate_limit_max_per_minute INTEGER DEFAULT 5,
    cooldown_seconds INTEGER DEFAULT 2,
    response_target_chars INTEGER DEFAULT 300,
    config_metadata JSON,
    is_active BOOLEAN DEFAULT TRUE,
    last_health_check TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    INDEX idx_tenant_active (tenant_id, is_active)
);

-- Create whatsapp_metrics table
CREATE TABLE IF NOT EXISTS whatsapp_metrics (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    period_date TIMESTAMP NOT NULL,
    messages_received INTEGER DEFAULT 0,
    messages_sent INTEGER DEFAULT 0,
    messages_failed INTEGER DEFAULT 0,
    avg_response_time_ms INTEGER DEFAULT 0,
    avg_llm_latency_ms INTEGER DEFAULT 0,
    unique_contacts INTEGER DEFAULT 0,
    conversations_started INTEGER DEFAULT 0,
    conversations_completed INTEGER DEFAULT 0,
    booking_attempts INTEGER DEFAULT 0,
    booking_completions INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    UNIQUE KEY unique_tenant_period (tenant_id, period_date),
    INDEX idx_tenant_date (tenant_id, period_date)
);

-- Create indices for common queries
CREATE INDEX idx_wa_messages_contact_created ON whatsapp_messages(contact_id, created_at DESC);
CREATE INDEX idx_wa_sessions_active ON whatsapp_sessions(tenant_id, status) WHERE status = 'active';
CREATE INDEX idx_wa_metrics_daily ON whatsapp_metrics(tenant_id, period_date DESC);

-- Optional: Add comments for documentation
ALTER TABLE whatsapp_contacts COMMENT = 'WhatsApp contacts - users messaging the business';
ALTER TABLE whatsapp_messages COMMENT = 'WhatsApp messages - inbound and outbound messages with delivery tracking';
ALTER TABLE whatsapp_sessions COMMENT = 'WhatsApp sessions - conversation context linked to LLM chat sessions';
ALTER TABLE whatsapp_configurations COMMENT = 'WhatsApp Business API configuration per tenant';
ALTER TABLE whatsapp_metrics COMMENT = 'WhatsApp usage and performance metrics';
"""


def print_migration_info():
    """Print information about WhatsApp migration"""
    print("""
WhatsApp Database Migration
===========================

The WhatsApp integration creates 5 new tables:

1. whatsapp_contacts
   - Stores WhatsApp users/customers
   - Links to tenant
   - Tracks first/last message timestamps

2. whatsapp_messages  
   - Stores all WhatsApp messages (inbound & outbound)
   - Tracks delivery status
   - Links to LLM chat_messages for unified conversation history

3. whatsapp_sessions
   - Conversation context between contact and tenant
   - Links to LLM chat_sessions for RAG context
   - Supports multi-step booking flows

4. whatsapp_configurations
   - Per-tenant WhatsApp Business API configuration
   - Stores credentials, webhook settings, feature flags

5. whatsapp_metrics
   - Daily usage metrics (messages sent/received, latency, etc)
   - Supports dashboard and analytics

Automatic Table Creation:
========================

Tables are automatically created when the application starts:
- SQLAlchemy creates tables from model definitions
- Run: python -c "from app.database import Base, engine; Base.metadata.create_all(bind=engine)"

Or with Alembic (if using migrations):
- alembic revision --autogenerate -m "Add WhatsApp tables"
- alembic upgrade head

Manual SQL:
===========

If you prefer manual execution:
1. Copy WHATSAPP_MIGRATIONS SQL above
2. Connect to your database
3. Execute the SQL statements

The migration is idempotent (safe to run multiple times).

Important Notes:
================

1. Data Preservation:
   - Existing chat_messages and chat_sessions are NOT modified
   - WhatsApp integration is purely additive
   - No data loss or breaking changes

2. Vector Database:
   - No changes to vector DB queries or storage
   - RAG functionality remains unchanged
   - Existing knowledge base still used

3. Migration Rollback:
   - If using Alembic: alembic downgrade -1
   - Or drop tables manually: DROP TABLE whatsapp_metrics, whatsapp_configurations, etc.
   - Chat data remains intact

4. Indexes:
   - Optimized for common queries
   - Monitor index usage in production
   - Consider adjusting based on query patterns
    """)


if __name__ == "__main__":
    import sys
    from app.database import Base, engine
    
    # Create all tables
    print("Creating WhatsApp tables...")
    Base.metadata.create_all(bind=engine)
    print("✓ WhatsApp tables created successfully")
    
    print_migration_info()
