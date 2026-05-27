https://g1y5m4ak4bm0-d.space-z.ai/  refere this website , 
https://manychat.com/
SKILLS.md — Incident Tracker Frontend Simplification
1. Dashboard Restructure
Collapse sidebar into 4 core items:

Overview → Tenant status, active channels

Channels → Chatbot + WhatsApp integration

Tickets → Queries/issues raised by users

Settings → Tenant info, API keys

Remove cluttered menus; use collapsible sections inside each tab.

2. Tenant Auto-Onboarding
On registration:

Generate Tenant ID automatically.

Produce two code snippets:

Chatbot embed script

WhatsApp integration link/button

Redirect tenant to backend activation system.

No manual admin intervention required.c

3. Code Generator Module
Service outputs pre-filled snippets:

html
<!-- Chatbot -->
<script src="https://yourdomain.com/chatbot.js" data-tenant="TENANT_ID"></script>

<!-- WhatsApp -->
<a href="https://wa.me/PHONE?text=Hello" target="_blank">Chat on WhatsApp</a>
Snippets tied to Tenant ID for isolation.

4. Ticket Workflow
Simplify ticket lifecycle:

Raise Issue → auto-capture via chatbot/WhatsApp

Track Status → dashboard shows Open, In Progress, Resolved

Resolve/Close → admin marks completion

Minimal UI, no nested menus.

5. Role-Based Views
Tenant View: onboarding, snippets, ticket status.

Admin View: analytics, system-wide controls, tenant management.

Prevent tenants from seeing irrelevant system menus.

6. Scalable Modules
Each feature (Chatbot, WhatsApp, Ticketing) is a pluggable module.

Future channels (e.g., Email, Telegram) can be added without redesign.

Maintain modularity to avoid rigid, non-scalable solutions.

7. Compliance & Redirects
Auto-onboarding must enforce compliance checks (basic validation).

Redirects ensure tenants land in your existing backend system for activation.

No duplication of backend logic.