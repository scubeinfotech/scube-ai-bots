-- Migration: Add business profile columns for multi-industry tenant support (Phase 1A)
-- Date: 2026-03-12
-- Description: Enables tenant onboarding with industry, tone, compliance, and CTA configuration

ALTER TABLE tenants ADD COLUMN industry VARCHAR(50);
ALTER TABLE tenants ADD COLUMN tone VARCHAR(50) DEFAULT 'friendly';
ALTER TABLE tenants ADD COLUMN compliance_mode VARCHAR(50) DEFAULT 'normal';
ALTER TABLE tenants ADD COLUMN cta_goals JSONB;
ALTER TABLE tenants ADD COLUMN website_url VARCHAR(500);
ALTER TABLE tenants ADD COLUMN onboarding_stage VARCHAR(50) DEFAULT 'discovering';
ALTER TABLE tenants ADD COLUMN onboarding_notes VARCHAR(1000);

-- Create index on onboarding_stage for filtering during crawl processing
CREATE INDEX idx_tenants_onboarding_stage ON tenants(onboarding_stage);
CREATE INDEX idx_tenants_industry ON tenants(industry);
