# Platform Module Plan

## A. API Gateway
- Tenant auth (API key/JWT)
- Rate limits and quotas
- Request tracing and correlation IDs

## B. Conversation Service
- Session create/restore
- Message pipeline
- Response streaming support (optional)

## C. LLM Orchestration
- Model routing policy (fast/cheap vs high-quality)
- Fallback model chain
- Prompt assembly with tenant policy

## D. RAG Service
- Tenant document ingestion
- Embedding generation
- Top-k retrieval with citations

## E. Tenant Config Service
- Tenant profile CRUD
- Prompt template versioning
- Policy controls and disclaimers

## F. Widget SDK
- Drop-in JS for static websites
- Per-tenant theming
- Error handling and fallback UI

## G. Admin Console
- Tenant onboarding
- Usage dashboards
- Prompt/policy config

## H. Ops Layer
- Logging, metrics, traces
- Alerting and incident hooks
- Backup and restore

## Definition of Done (Module Level)
- Unit tests and integration tests
- API docs updated
- SLO instrumentation added
- Security checklist passed
