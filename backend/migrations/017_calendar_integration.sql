-- Migration 017: Calendar Integration Tables
-- Date: 2026-05-18
-- Purpose: Add calendar_integrations and tenant_availability tables

-- Calendar Integration table
CREATE TABLE IF NOT EXISTS calendar_integrations (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    provider VARCHAR(20) DEFAULT 'google',
    provider_email VARCHAR(255),
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at TIMESTAMP,
    calendar_id VARCHAR(255),
    timezone VARCHAR(50) DEFAULT 'Asia/Singapore',
    meeting_provider VARCHAR(20) DEFAULT 'google_meet',
    zoom_api_key VARCHAR(255),
    zoom_api_secret VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    is_connected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_calendar_tenant ON calendar_integrations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_calendar_provider ON calendar_integrations(provider);

-- Tenant Availability table
CREATE TABLE IF NOT EXISTS tenant_availability (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    day_of_week INTEGER NOT NULL,
    start_time VARCHAR(5) NOT NULL,
    end_time VARCHAR(5) NOT NULL,
    timezone VARCHAR(50) DEFAULT 'Asia/Singapore',
    blocked_dates JSON,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_availability_tenant ON tenant_availability(tenant_id);
CREATE INDEX IF NOT EXISTS idx_availability_day ON tenant_availability(day_of_week);
