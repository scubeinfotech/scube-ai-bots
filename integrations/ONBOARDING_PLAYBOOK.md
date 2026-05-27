# Tenant Onboarding Playbook

## Step 1: Tenant Registration
- Create tenant ID (slug)
- Set domain allowlist
- Issue API keys and rotate policy

## Step 2: Knowledge Setup
- Ingest website pages, FAQs, docs
- Define retrieval scope and exclusions
- Validate citations and answer grounding

### Dynamic Knowledge Schema (No Hardcoding)
Use `knowledge_context` as structured JSON per tenant so the platform can auto-select relevant content from conversation context.

```json
{
	"company_overview": "One paragraph about the customer business.",
	"services": [
		{"name": "Managed IT", "description": "24/7 support for SMB"},
		{"name": "Cloud Migration", "description": "AWS/Azure onboarding"}
	],
	"products": [
		{
			"name": "ChronoBill",
			"aliases": ["chronobill", "chrono bill"],
			"description": "Cloud billing and invoicing platform",
			"features": ["Invoice automation", "Payment tracking", "Client portal"]
		}
	],
	"faqs": [
		{"question": "Do you offer a free trial?", "answer": "Yes, 14-day trial is available."}
	],
	"ctas": [
		"Offer product demo booking if customer shows interest",
		"Offer pricing consultation for qualified leads"
	]
}
```

Notes:
- Keep product aliases in lowercase and natural variants to improve matching.
- Keep each description concise (1-2 lines) for prompt efficiency.
- Update tenant JSON during onboarding instead of editing backend code.

## Step 3: Prompt and Policy
- Configure system prompt by industry
- Add compliance guardrails (especially insurance)
- Configure fallback response for unknowns

### Prompt Design Rule
- Use behavior rules that generalize across tenants: continue short follow-ups (`yes`, `ok`, `tell me more`) from prior topic, ask one focused clarifying question only when needed.

## Step 4: Widget Integration
- Add SDK script to website
- Apply tenant theme and UX options
- Enable telemetry events

## Step 5: QA and UAT
- Core scenarios pass
- Abuse and policy tests pass
- Response latency and uptime checks pass

## Step 6: Go-live and Hypercare
- Production key enabled
- Monitoring alerts active
- 7-day hypercare with issue triage

## API Onboarding Example

```bash
curl -X POST http://localhost:8000/api/tenants/ \
	-H "Content-Type: application/json" \
	-d '{
		"name": "SCUBE Infotech",
		"slug": "scube",
		"domain": "scubeinfotech.com.sg",
		"prompt_template": "You are the SCUBE customer assistant. Be concise, helpful, and conversion-focused.",
		"knowledge_context": {
			"company_overview": "SCUBE provides enterprise software and IT solutions.",
			"products": [
				{
					"name": "ChronoBill",
					"aliases": ["chronobill", "chrono bill"],
					"description": "Cloud-based billing and invoicing software",
					"features": ["Invoice automation", "Payment tracking", "Reporting"]
				}
			],
			"ctas": ["Offer demo", "Offer pricing call"]
		}
	}'
```
