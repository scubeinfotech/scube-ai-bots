# SCUBE AI Platform — Quick Start & Access Card

**Server Status:** ✅ Running on `http://127.0.0.1:8001`  
**Last Updated:** 2026-05-18

---

## 🔗 All URLs

| Page | URL | Who Can Access |
|------|-----|----------------|
| **Home / API** | `http://127.0.0.1:8001` | Everyone |
| **API Docs** | `http://127.0.0.1:8001/docs` | Everyone |
| **Register (New Account)** | `http://127.0.0.1:8001/public/register` | Everyone |
| **Login** | `http://127.0.0.1:8001/public/login` | Registered tenants |
| **Pricing** | `http://127.0.0.1:8001/public/pricing` | Everyone |
| **Tenant Dashboard** | `http://127.0.0.1:8001/tenant/dashboard` | Logged-in tenants |
| **Admin Dashboard** | `http://127.0.0.1:8001/admin/dashboard` | Admin only |
| **Health Check** | `http://127.0.0.1:8001/health` | Everyone |

---

## 🔑 Login Credentials

### Admin Dashboard
| Field | Value |
|-------|-------|
| **URL** | `http://127.0.0.1:8001/admin/dashboard` |
| **Username** | `admin` |
| **Password** | `admin123` |

### Tenant (Self-Service Registration)
| Field | Value |
|-------|-------|
| **URL** | `http://127.0.0.1:8001/public/register` |
| **Who** | Anyone — no approval needed |
| **Trial** | 7 days free, no credit card |

### Existing Test Tenants
| Tenant | Slug | Email | Password |
|--------|------|-------|----------|
| **RAPAS** | `rapas` | Check DB | Set during registration |
| **SDS Foods** | `sdsfoodz` | Check DB | Set during registration |
| **SCUBE** | `scube` | Check DB | Set during registration |

*To find tenant email: Login to admin dashboard → Tenants tab → view tenant details.*

---

## 📋 Quick Start — New Tenant (30 seconds)

1. **Go to** `http://127.0.0.1:8001/public/register`
2. **Fill in:**
   - Business Name: `My Business`
   - Email: `you@business.com`
   - Website: `https://mybusiness.com`
   - Password: `yourpassword`
3. **Click** "Start Free Trial"
4. **You're in!** Dashboard opens automatically
5. **Copy embed code** from Channels tab
6. **Paste into your website** — chatbot is live

---

## 📋 Quick Start — Admin

1. **Go to** `http://127.0.0.1:8001/admin/dashboard`
2. **Login:** `admin` / `admin123`
3. **Overview tab** — see all tenants, trials, payments
4. **Tenants tab** — search, extend trials, activate/deactivate
5. **Billing tab** — verify PayNow payments, manage plans
6. **Settings tab** — system config

---

## 🚀 Start / Stop Server

```bash
# Start
cd /home/sudhakar/New-Projects/centralized-llm-platform
./start-service.sh

# Stop
./stop-service.sh

# Check status
./service-control.sh
```

---

## 📊 What Each Dashboard Does

### Tenant Dashboard (6 Tabs)
| Tab | What It Does |
|-----|-------------|
| **Overview** | Metrics: messages, sessions, leads, unanswered queries |
| **Channels** | Get embed code, configure WhatsApp Business API |
| **Conversations** | View chat history with customers |
| **Calendar** | Set availability hours, connect Google Calendar, manage bookings |
| **Billing** | See trial status, upgrade plans, pay via Stripe or PayNow |
| **Settings** | Edit business name, industry, chatbot tone, API key |

### Admin Dashboard (4 Tabs)
| Tab | What It Does |
|-----|-------------|
| **Overview** | Total tenants, active trials, paid subscriptions, pending payments |
| **Tenants** | Search, extend trials (1-30 days), activate/deactivate tenants |
| **Billing** | Verify PayNow payments, create/edit/delete subscription plans |
| **Settings** | System info, API endpoints reference |

---

## 💳 Subscription Plans

| Plan | Price | Messages | WhatsApp | Best For |
|------|-------|----------|----------|----------|
| **Free Trial** | $0 (7 days) | Unlimited | ❌ | Testing |
| **Starter** | $29/mo | 2,000 | ❌ | Small business |
| **Growth** | $59/mo | 10,000 | ✅ | Growing business |
| **Enterprise** | $149/mo | 100,000 | ✅ | Large organization |

---

## 📞 Support

| Channel | Contact |
|---------|---------|
| **Email** | `sales@scubeinfotech.com.sg` |
| **Admin Email** | `admin@llmplatform.local` |
| **Alerts** | `alerts@scubeinfotech.com.sg` |

---

*Print this page for quick reference.*
