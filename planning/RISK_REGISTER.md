# Risk Register

## High Risks
1. Cross-tenant data leakage
- Impact: Critical
- Mitigation: strict tenant IDs in data layer, row-level controls, automated isolation tests

2. Insurance domain compliance breaches
- Impact: Critical
- Mitigation: policy prompts, response filters, legal disclaimers, restricted answer modes

3. Cost escalation due to token usage
- Impact: High
- Mitigation: caching, model routing, max token limits, quota alerts

4. Latency degradation at scale
- Impact: High
- Mitigation: autoscaling, request queueing, regional deployment strategy

5. Hallucinated responses
- Impact: High
- Mitigation: RAG grounding, confidence thresholds, fallback messaging

## Medium Risks
1. Slow onboarding due to manual tenant setup
- Mitigation: onboarding templates and automation scripts

2. Integration drift across websites
- Mitigation: single widget SDK, versioned API contracts

3. Operational dependency on one model/provider
- Mitigation: multi-provider abstraction and fallback routing

## Risk Review Cadence
- Weekly risk review
- Monthly control validation
- Pre-go-live checkpoint per tenant
