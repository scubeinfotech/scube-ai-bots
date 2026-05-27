-- Migration: Add quality tracking tables for self-learning engine
-- Date: 2026-05-27
-- Description: Creates quality_scores, failure_patterns, improvement_candidates, quality_metrics
-- Run: psql -U llmuser -d llm_chatbot -f migrations/025_add_quality_tracking.sql

-- 1. quality_scores — per-message LLM-as-judge scores
CREATE TABLE IF NOT EXISTS quality_scores (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id),
    conversation_id VARCHAR(36) NOT NULL,
    message_id VARCHAR(36),
    user_query TEXT,
    assistant_response TEXT,
    relevance_score FLOAT CHECK (relevance_score >= 0 AND relevance_score <= 1),
    accuracy_score FLOAT CHECK (accuracy_score >= 0 AND accuracy_score <= 1),
    completeness_score FLOAT CHECK (completeness_score >= 0 AND completeness_score <= 1),
    conciseness_score FLOAT CHECK (conciseness_score >= 0 AND conciseness_score <= 1),
    tone_score FLOAT CHECK (tone_score >= 0 AND tone_score <= 1),
    overall_score FLOAT CHECK (overall_score >= 0 AND overall_score <= 1),
    scoring_method VARCHAR(20) DEFAULT 'llm',
    judge_model VARCHAR(100),
    score_metadata TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_scores_tenant ON quality_scores(tenant_id);
CREATE INDEX IF NOT EXISTS idx_quality_scores_created ON quality_scores(created_at);
CREATE INDEX IF NOT EXISTS idx_quality_scores_overall ON quality_scores(overall_score);

-- 2. failure_patterns — clustered low-quality response patterns
CREATE TABLE IF NOT EXISTS failure_patterns (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id),
    failure_type VARCHAR(30) NOT NULL,
    failure_pattern TEXT NOT NULL,
    insight_preview TEXT,
    key_terms TEXT,
    affected_count INTEGER DEFAULT 0,
    impact_score FLOAT DEFAULT 0,
    sample_conversation_ids TEXT,
    first_detected_at TIMESTAMP DEFAULT NOW(),
    last_detected_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_failure_patterns_tenant ON failure_patterns(tenant_id);
CREATE INDEX IF NOT EXISTS idx_failure_patterns_type ON failure_patterns(failure_type);
CREATE INDEX IF NOT EXISTS idx_failure_patterns_impact ON failure_patterns(impact_score DESC);
CREATE INDEX IF NOT EXISTS idx_failure_patterns_active ON failure_patterns(is_active);

-- 3. improvement_candidates — prompt variants that outperformed production
CREATE TABLE IF NOT EXISTS improvement_candidates (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id),
    conversation_id VARCHAR(36) NOT NULL,
    variant_name VARCHAR(50) NOT NULL,
    original_prompt TEXT,
    variant_prompt TEXT,
    original_response TEXT,
    improved_response TEXT,
    original_score FLOAT,
    variant_score FLOAT,
    score_delta FLOAT,
    status VARCHAR(20) DEFAULT 'pending',
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMP,
    rejection_reason TEXT,
    applied_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_improvement_candidates_tenant ON improvement_candidates(tenant_id);
CREATE INDEX IF NOT EXISTS idx_improvement_candidates_status ON improvement_candidates(status);
CREATE INDEX IF NOT EXISTS idx_improvement_candidates_delta ON improvement_candidates(score_delta DESC);

-- 4. quality_metrics — daily aggregated quality rollups
CREATE TABLE IF NOT EXISTS quality_metrics (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id),
    metric_date DATE NOT NULL,
    avg_overall_score FLOAT,
    avg_relevance FLOAT,
    avg_accuracy FLOAT,
    avg_completeness FLOAT,
    avg_conciseness FLOAT,
    avg_tone FLOAT,
    total_scores INTEGER DEFAULT 0,
    low_score_count INTEGER DEFAULT 0,
    failure_pattern_count INTEGER DEFAULT 0,
    improvement_candidate_count INTEGER DEFAULT 0,
    metric_metadata TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_quality_metrics_unique ON quality_metrics(tenant_id, metric_date);
CREATE INDEX IF NOT EXISTS idx_quality_metrics_date ON quality_metrics(metric_date);

