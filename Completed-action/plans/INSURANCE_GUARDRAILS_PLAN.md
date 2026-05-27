# Insurance Guardrails - Domain-Specific Response Constraints

**Feature:** Insurance Guardrails - Domain-Specific Response Constraints  
**Status:** Planned  
**Start Date:** Tomorrow (2026-04-01)

## Overview

Insurance is a highly regulated industry with strict rules about what can and cannot be said to customers. Insurance Guardrails add special safety checks when responding to insurance-related queries for tenants in the insurance industry.

## Problem

Insurance tenants (`insurance-a`, `insurance-b`) need special content filtering to:
- Comply with insurance regulations
- Prevent giving misleading advice
- Add required disclaimers
- Protect from liability

## Solution

### 1. Disallowed Content Filtering
- Block responses that mention specific insurance premiums or quotes without proper disclaimer
- Prevent giving specific financial advice ("You should invest in...")
- Block promises like "We guarantee coverage"

### 2. Required Disclaimers
- Auto-append "This is general information, not official advice" when discussing policies
- Add "Please consult your agent" when giving recommendations

### 3. Compliance Keywords
- Watch for regulated terms: "pre-existing condition", "exclusion", "deductible", "coverage limit"
- Flag or modify responses containing these terms

## Example Flow

**User asks:** "Does my policy cover diabetes treatment?"

**Without guardrails:**
> "Yes, your policy covers diabetes treatment"

**With guardrails:**
> "Coverage for diabetes treatment depends on your specific policy terms and any pre-existing condition clauses. Please check with your agent for accurate information. This is general information only."

## Implementation Plan

### Phase 1: Basic Guardrails
1. Add guardrail configuration to tenant model
2. Create guardrail service/class
3. Add disclaimer injection
4. Apply to insurance tenants

### Phase 2: Advanced
1. Keyword detection and modification
2. Response template system
3. Admin UI to configure guardrails per tenant

## Files to Modify
- `backend/app/models/tenant.py` - Add guardrail settings
- `backend/app/services/chat_service.py` - Apply guardrails before response
- `backend/static/admin-dashboard.html` - UI to configure guardrails

## Notes
- Current tenants: `rapas`, `sdsfoodz`, `insurance-a`, `insurance-b`, `technology`
- Only `insurance-a` and `insurance-b` need these guardrails
