# Master Roadmap (16 Weeks)

## Phase 1: Foundation + MVP (Weeks 1-4)
### Outcomes
- Platform architecture finalized
- Core API, tenant model, and widget contract defined
- `rapas` MVP live

### Workstreams
- Architecture: API gateway, LLM router, tenant config model
- Platform: auth, session, message API, logs
- RAG: basic tenant knowledge ingestion and retrieval
- Integration: replace local keyword chatbot in `rapas`

## Phase 2: Multi-Tenant Core (Weeks 5-8)
### Outcomes
- Tenant onboarding workflow stable
- Admin controls for tenant config
- `sdsfoodz` and `insurance-a` onboarded

### Workstreams
- Tenant management APIs
- Prompt, policy, and retrieval profiles per tenant
- Quotas, rate limits, and cost tagging
- Basic analytics dashboard

## Phase 3: Portfolio Completion (Weeks 9-12)
### Outcomes
- `insurance-b` and `technology` onboarded
- Full portfolio on centralized LLM
- Guardrails and quality checks hardened

### Workstreams
- Domain-specific response constraints (insurance)
- Regression suite for each tenant
- SLA monitoring and alerting

## Phase 4: Scale + Productization (Weeks 13-16)
### Outcomes
- New tenant onboarding in under 1 day
- Operational readiness for growth
- Commercially reusable model for additional clients

### Workstreams
- Self-serve onboarding templates
- Runbooks and incident process
- Cost optimization and caching strategy
- Capacity planning and scale tests
