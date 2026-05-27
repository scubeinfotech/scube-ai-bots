# Cost and Capacity Plan

## Cost Drivers
- LLM token usage
- Embedding and vector storage
- Compute for retrieval and orchestration
- Monitoring and logging retention

## Cost Controls
- Tiered model routing (cheap model first)
- Response caching for frequent intents
- Token caps per tenant and per request
- Monthly quota alerts and auto-throttle

## Capacity Baseline
- Start capacity for current portfolio only
- Target: P95 under 2.5 seconds
- Autoscale trigger: CPU/queue/latency thresholds

## Capacity Reviews
- Weekly during rollout
- Monthly after stabilization
- Re-forecast when new tenants are added

## Business KPI Targets
- Cost per conversation trend down month over month
- Onboarding time under 1 business day
- Uptime at or above 99.9%
