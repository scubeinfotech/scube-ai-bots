# SCUBE AI Platform — Business Workflow Document

**Version:** 1.0  
**Date:** 2026-05-18  
**Owner:** SCUBE Infotech  
**Platform:** Centralized LLM Chatbot Platform

---

## 1. Platform Overview

SCUBE AI is a multi-tenant AI chatbot platform that enables businesses to deploy intelligent chatbots on their websites and WhatsApp — without any technical expertise. Each tenant gets their own isolated chatbot, trained on their website content, with lead capture, appointment booking, and analytics.

---

## 2. User Roles

| Role | Description | Access |
|------|-------------|--------|
| **Super Admin** | Platform owner (SCUBE Infotech) | Full system control, all tenants, billing, plans |
| **Tenant Admin** | Business owner who registers for the platform | Own chatbot, settings, leads, calendar, billing |
| **End User** | Website visitor who chats with the chatbot | Chat widget on tenant website |
| **WhatsApp User** | Customer who interacts via WhatsApp | WhatsApp messages to tenant's business number |

---

## 3. Business Workflow

### 3.1 Customer Registration → Activation Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    NEW CUSTOMER JOURNEY                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Visit Pricing Page                                          │
│     → /public/pricing                                           │
│     → View plans: Starter ($29), Growth ($59), Enterprise ($149)│
│     → All plans include 7-day free trial                        │
│                                                                 │
│  2. Click "Start Free Trial"                                    │
│     → Redirected to /public/register                            │
│                                                                 │
│  3. Fill Registration Form                                      │
│     → Business Name (required)                                  │
│     → Work Email (required)                                     │
│     → Website URL (required)                                    │
│     → Industry (optional)                                       │
│     → Password (min 6 chars)                                    │
│     → NO credit card required                                   │
│                                                                 │
│  4. Instant Account Creation                                    │
│     → Tenant ID auto-generated                                  │
│     → Unique slug created (e.g., "rapas-engineering")           │
│     → API key generated for widget                              │
│     → 7-day free trial activated                                │
│     → Welcome email sent                                        │
│     → Website crawl queued (auto-build knowledge base)          │
│                                                                 │
│  5. Redirect to Tenant Dashboard                                │
│     → /tenant/dashboard                                         │
│     → 6 tabs available immediately:                             │
│       • Overview (metrics, quick actions)                       │
│       • Channels (embed code, WhatsApp setup)                   │
│       • Conversations (chat history)                            │
│       • Calendar (availability, Google Calendar connect)        │
│       • Billing (upgrade plans, Stripe/PayNow)                  │
│       • Settings (business profile, tone)                       │
│                                                                 │
│  6. Deploy Chatbot                                              │
│     → Copy embed code from Channels tab                         │
│     → Paste into website HTML                                   │
│     → Chatbot goes live immediately                             │
│                                                                 │
│  7. (Optional) Connect WhatsApp                                 │
│     → Enter Meta WhatsApp Business API credentials              │
│     → Phone Number ID, Business Account ID, Access Token        │
│     → WhatsApp channel activated                                │
│                                                                 │
│  8. (Optional) Set Calendar Availability                        │
│     → Toggle days/hours when customers can book                 │
│     → Connect Google Calendar for auto-meeting links            │
│     → Chatbot can now check availability & book appointments    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Trial → Paid Subscription Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                  TRIAL TO PAID CONVERSION                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Day 1-7: Free Trial Active                                     │
│     → Full platform access                                      │
│     → Chatbot live on website                                   │
│     → Leads captured, conversations tracked                     │
│     → Trial countdown visible in dashboard                      │
│                                                                 │
│  Day 5-6: Trial Expiry Warning                                  │
│     → Dashboard shows trial days remaining                      │
│     → Billing tab highlights upgrade options                    │
│     → Email notification sent (if configured)                   │
│                                                                 │
│  Day 7: Trial Expires                                           │
│     → Chatbot continues working (grace period)                  │
│     → Dashboard prompts upgrade                                 │
│     → Admin can extend trial if needed                          │
│                                                                 │
│  Upgrade Options:                                               │
│     → Tenant clicks "Upgrade" in Billing tab                    │
│     → Selects plan: Starter / Growth / Enterprise               │
│     → Chooses payment method:                                   │
│       • Stripe (Credit/Debit Card) → Redirects to Stripe Checkout│
│       • PayNow (Singapore) → Shows QR code + UEN + Reference    │
│                                                                 │
│  Payment Processing:                                            │
│     → Stripe: Automatic activation on successful payment        │
│     → PayNow: Admin verifies via bank statement → clicks Verify │
│     → Subscription activated, trial extended 30 days            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 Admin Management Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                    ADMIN MANAGEMENT FLOW                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Admin Login: /admin/dashboard                                  │
│  Credentials: admin / admin123                                  │
│                                                                 │
│  4 Admin Tabs:                                                  │
│                                                                 │
│  ┌─ Overview ─────────────────────────────────────────────────┐ │
│  │ • Total tenants count                                      │ │
│  │ • Active trials count                                      │ │
│  │ • Paid subscriptions count                                 │ │
│  │ • Pending PayNow payments                                  │ │
│  │ • Recent tenants table                                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ Tenants ──────────────────────────────────────────────────┐ │
│  │ • Search tenants by name, slug, industry                   │ │
│  │ • Extend trial (1-30 days, with reason)                    │ │
│  │ • Activate / Deactivate tenant                             │ │
│  │ • View tenant details                                      │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ Billing ──────────────────────────────────────────────────┐ │
│  │ • Pending PayNow payments list                             │ │
│  │ • Verify PayNow payments (admin action)                    │ │
│  │ • Subscription plan management                             │ │
│  │   - Create new plans                                       │ │
│  │   - Edit existing plans (price, features, limits)          │ │
│  │   - Deactivate plans                                       │ │
│  │ • Revenue overview                                         │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ Settings ─────────────────────────────────────────────────┐ │
│  │ • System configuration                                     │ │
│  │ • API endpoints reference                                  │ │
│  │ • Default trial days                                       │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.4 Chatbot Conversation Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                 CHATBOT CONVERSATION FLOW                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. User visits tenant website                                  │
│  2. Chatbot widget appears (bottom-right)                       │
│  3. Auto-greeting: "Hi! How can I help you today?"              │
│  4. User asks question                                          │
│  5. System processes:                                           │
│     a. Detect language (auto)                                   │
│     b. Check lead gate (collect name/email/phone if needed)     │
│     c. Search knowledge base (RAG)                              │
│     d. Check calendar availability (if booking intent)          │
│     e. Analyze sentiment                                        │
│     f. Apply guardrails (no hallucinated pricing, etc.)         │
│     g. Generate response                                        │
│  6. Response delivered to user                                  │
│  7. Conversation logged for analytics                           │
│  8. Lead captured if applicable                                 │
│                                                                 │
│  Special Flows:                                                 │
│  • Booking: "Can I book an appointment?" → Check calendar →     │
│    Show slots → Confirm → Create event → Send Google Meet link  │
│  • Lead Capture: Collect name → email → phone → store in DB     │
│  • Escalation: Negative sentiment → Offer human handoff         │
│  • Out-of-scope: "I don't know, but our team can help"          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.5 WhatsApp Integration Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                  WHATSAPP INTEGRATION FLOW                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Prerequisites:                                                 │
│  • Meta Business Account                                        │
│  • WhatsApp Business API access                                 │
│  • Phone number not linked to personal WhatsApp                 │
│                                                                 │
│  Setup Steps (via Tenant Dashboard → Channels tab):             │
│  1. Enter Phone Number ID (from Meta Developer Console)         │
│  2. Enter Business Account ID                                   │
│  3. Enter Access Token (System User token)                      │
│  4. Click "Connect WhatsApp"                                    │
│  5. System configures webhook URL                               │
│  6. WhatsApp channel activated                                  │
│                                                                 │
│  Message Flow:                                                  │
│  Customer → WhatsApp → Meta API → Webhook → Platform → LLM →    │
│  Response → Meta API → Customer WhatsApp                        │
│                                                                 │
│  Features:                                                      │
│  • Same AI responses as website chatbot                         │
│  • Lead capture via WhatsApp                                    │
│  • Appointment booking                                          │
│  • Session tracking                                             │
│  • Analytics                                                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Subscription Plans

| Feature | Free Trial | Starter | Growth | Enterprise |
|---------|-----------|---------|--------|------------|
| **Price** | Free (7 days) | $29/mo | $59/mo | $149/mo |
| **Messages/month** | Unlimited | 2,000 | 10,000 | 100,000 |
| **Knowledge Documents** | 50 | 50 | 200 | 1,000 |
| **Chatbot Widget** | ✅ | ✅ | ✅ | ✅ |
| **WhatsApp** | ❌ | ❌ | ✅ | ✅ |
| **Calendar Booking** | ✅ | ✅ | ✅ | ✅ |
| **Priority Support** | ❌ | ❌ | ✅ | ✅ |
| **Custom Branding** | ❌ | ❌ | ✅ | ✅ |
| **API Access** | ❌ | ❌ | ✅ | ✅ |

*Plans are configurable by admin from the dashboard.*

---

## 5. Payment Methods

### 5.1 Stripe (International)
- Credit/Debit Cards (Visa, Mastercard, Amex)
- Automatic subscription activation
- Customer portal for self-management
- Webhook-based payment confirmation

### 5.2 PayNow (Singapore)
- Bank transfer via PayNow QR
- UEN: `202600001A`
- Manual verification by admin
- 3-day payment window
- Reference number for tracking

---

## 6. Access URLs & Credentials

| Purpose | URL | Credentials |
|---------|-----|-------------|
| **Public Registration** | `http://<server>:8001/public/register` | Open to all |
| **Public Login** | `http://<server>:8001/public/login` | Tenant email + password |
| **Pricing Page** | `http://<server>:8001/public/pricing` | Open to all |
| **Tenant Dashboard** | `http://<server>:8001/tenant/dashboard` | Tenant credentials |
| **Admin Dashboard** | `http://<server>:8001/admin/dashboard` | `admin` / `admin123` |
| **API Documentation** | `http://<server>:8001/docs` | Open |
| **Health Check** | `http://<server>:8001/health` | Open |

*Replace `<server>` with your server address (e.g., `127.0.0.1:8001` for local, `chat.scubeinfotech.com.sg` for production).*

---

## 7. Key API Endpoints

### Public (No Auth)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/public/register` | Register new tenant (auto 7-day trial) |
| POST | `/api/public/login` | Tenant login |
| GET | `/api/public/plans` | List subscription plans |
| GET | `/api/public/trial/status/{id}` | Check trial status |
| POST | `/api/public/forgot-password` | Request password reset |

### Tenant (JWT Auth)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/calendar/status/{id}` | Calendar connection status |
| POST | `/api/calendar/availability/{id}` | Set weekly availability |
| GET | `/api/calendar/availability/{id}/check` | Check date availability |
| POST | `/api/calendar/book/{id}` | Book appointment |
| POST | `/api/billing/checkout/{id}` | Create payment (Stripe/PayNow) |
| GET | `/api/billing/invoice/{id}` | Get invoice details |

### Admin (Admin JWT Auth)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/admin/login` | Admin login |
| POST | `/api/admin/tenants/{id}/extend-trial` | Extend tenant trial |
| GET | `/api/admin/plans` | List all plans |
| POST | `/api/admin/plans` | Create new plan |
| PUT | `/api/admin/plans/{id}` | Update plan |
| DELETE | `/api/admin/plans/{id}` | Deactivate plan |
| GET | `/api/billing/paynow/pending` | List pending PayNow payments |
| POST | `/api/billing/paynow/verify` | Verify PayNow payment |

---

## 8. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        SCUBE AI PLATFORM                          │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐ │
│  │   Public   │  │   Tenant   │  │    Admin   │  │   Chat     │ │
│  │   Pages    │  │   Portal   │  │  Dashboard │  │   Widget   │ │
│  │            │  │            │  │            │  │            │ │
│  │ Register   │  │ Overview   │  │ Overview   │  │ JS Embed   │ │
│  │ Login      │  │ Channels   │  │ Tenants    │  │ HTML Page  │ │
│  │ Pricing    │  │ Calendar   │  │ Billing    │  │            │ │
│  │            │  │ Billing    │  │ Settings   │  │            │ │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘ │
│        │               │               │               │         │
│        └───────────────┴───────────────┴───────────────┘         │
│                            │                                     │
│                   ┌────────▼────────┐                            │
│                   │   FastAPI API   │                            │
│                   │   Gateway       │                            │
│                   └────────┬────────┘                            │
│                            │                                     │
│        ┌───────────────────┼───────────────────┐                │
│        │                   │                   │                 │
│  ┌─────▼─────┐     ┌──────▼──────┐     ┌──────▼──────┐          │
│  │  Chat     │     │  Calendar   │     │   Billing   │          │
│  │  Service  │     │  Service    │     │   Service   │          │
│  │           │     │             │     │             │          │
│  │ RAG + LLM │     │ Google Cal  │     │ Stripe      │          │
│  │ Lead Gate │     │ Availability│     │ PayNow      │          │
│  │ Sentiment │     │ Booking     │     │ Invoices    │          │
│  └─────┬─────┘     └──────┬──────┘     └──────┬──────┘          │
│        │                  │                   │                  │
│        └──────────────────┼───────────────────┘                  │
│                           │                                      │
│                  ┌────────▼────────┐                             │
│                  │   PostgreSQL    │                             │
│                  │   Database      │                             │
│                  │                 │                             │
│                  │ tenants         │                             │
│                  │ tenant_users    │                             │
│                  │ chat_sessions   │                             │
│                  │ chat_messages   │                             │
│                  │ calendar_integr.│                             │
│                  │ tenant_availab. │                             │
│                  │ invoices        │                             │
│                  │ subscr_plans    │                             │
│                  │ api_keys        │                             │
│                  │ documents       │                             │
│                  └─────────────────┘                             │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 9. Quick Start Checklist

### For New Tenants
- [ ] Register at `/public/register`
- [ ] Login at `/public/login`
- [ ] Copy embed code from Channels tab
- [ ] Paste embed code into website
- [ ] Test chatbot on website
- [ ] (Optional) Set calendar availability
- [ ] (Optional) Connect Google Calendar
- [ ] (Optional) Configure WhatsApp
- [ ] Upgrade before trial expires

### For Admin
- [ ] Login at `/admin/dashboard` (admin / admin123)
- [ ] Monitor tenant registrations
- [ ] Review pending PayNow payments
- [ ] Extend trials as needed
- [ ] Manage subscription plans
- [ ] Monitor system health

---

## 10. Support & Contact

| Channel | Details |
|---------|---------|
| **Email** | `sales@scubeinfotech.com.sg` |
| **Platform** | SCUBE AI — Intelligent Chatbots for Every Business |
| **Admin Email** | `admin@llmplatform.local` |
| **Alerts From** | `alerts@scubeinfotech.com.sg` |

---

*Document generated: 2026-05-18 | Version 1.0*
