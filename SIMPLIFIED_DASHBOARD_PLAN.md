# Simplified Admin + Tenant Portal + Billing Plan

**Created:** 2026-05-18
**Goal:** Replace cumbersome 4709-line admin dashboard with simplified 4-menu admin + self-service tenant portal + Stripe/PayNow billing

---

## Guiding Principle
**Zero impact on existing chatbot.** All new code is additive — new files, new routes, new dashboards. The current `admin-dashboard.html` stays untouched until we're ready to switch over.

---

## Architecture

```
Public Facing:
  /public/register   → Registration page (business name, email, phone, website)
  /public/pricing    → Plans page (7-day free, then Stripe/PayNow)
  /public/login      → Unified login (admin + tenant)
  /payment/success   → Payment confirmation
  /payment/cancel    → Payment cancelled

Tenant Portal (after login):
  /tenant/dashboard  → 4 tabs: Overview, Channels, Conversations, Settings

Admin Dashboard (after admin login):
  /admin/dashboard   → 4 tabs: Overview, Tenants, Billing, Settings
```

---

## Phase 1: Registration + Tenant Portal ✅ DONE

### Status: COMPLETE (2026-05-17 night)

### What Was Built
- [x] Registration page (`static/public/register.html`)
- [x] Login page (`static/public/login.html`)
- [x] Pricing page (`static/public/pricing.html`)
- [x] Tenant dashboard (`static/tenant/dashboard.html`) — 4 tabs
- [x] Backend: `/api/public/register` endpoint (already existed)
- [x] Backend: `/api/public/login` endpoint (already existed)
- [x] Backend: `/api/public/plans` endpoint (already existed)
- [x] Backend: `/api/public/trial/status/{tenant_id}` endpoint (already existed)
- [x] Auto 7-day trial on registration
- [x] Welcome email on registration
- [x] Website crawl queued on registration
- [x] Embed code generation in tenant dashboard

### Tests
- [x] Registration flow test (valid input, duplicate email, duplicate website)
- [x] Login flow test (valid, invalid password, deactivated account)
- [x] Trial status endpoint test
- [x] Plans endpoint test
- [x] Forgot password test
- **All 20 tests passing** (2026-05-18)

---

## Phase 2: Calendar + Meeting Automation ✅ DONE

### Status: COMPLETE (2026-05-18)

### What Was Built
- [x] Calendar Integration model (`app/models/calendar.py`)
- [x] TenantAvailability model
- [x] Calendar service (`app/services/calendar_service.py`)
- [x] Calendar API routes (`app/api/calendar.py`)
- [x] OAuth URL generation (Google)
- [x] Availability management (CRUD)
- [x] Date availability checking
- [x] Appointment booking with Google Meet link generation
- [x] Default availability initialization (Mon-Fri 9AM-5PM)
- [x] Disconnect calendar integration
- [x] Registered calendar router in main.py

### Files Created
- `backend/app/models/calendar.py`
- `backend/app/services/calendar_service.py`
- `backend/app/api/calendar.py`
- `tests/test_phase2_calendar.py`

### Files Modified
- `backend/app/models/__init__.py` — added CalendarIntegration, TenantAvailability
- `backend/app/main.py` — added calendar router

### Tests
- [x] Calendar status tests (2 tests)
- [x] Availability CRUD tests (5 tests)
- [x] Check availability tests (4 tests)
- [x] Booking tests (3 tests)
- [x] Disconnect tests (1 test)
- [x] Initialize defaults tests (2 tests)
- **All 18 tests passing** (2026-05-18)

---

## Phase 3: Billing — Stripe + PayNow ✅ DONE

### Status: COMPLETE (2026-05-18)

### What Was Built
- [x] Stripe service (`app/services/stripe_service.py`)
- [x] PayNow service (`app/services/paynow_service.py`)
- [x] Billing API routes (`app/api/billing.py`)
- [x] Stripe checkout session creation
- [x] Stripe webhook handler (payment success/failure)
- [x] PayNow QR code generation
- [x] PayNow payment reference tracking
- [x] PayNow manual verification (admin action)
- [x] Auto-activate subscription on payment
- [x] Pending payments list for admin review
- [x] Invoice details endpoint
- [x] Subscription cancellation endpoint
- [x] Registered billing router in main.py

### Files Created
- `backend/app/services/stripe_service.py`
- `backend/app/services/paynow_service.py`
- `backend/app/api/billing.py`
- `tests/test_phase3_billing.py`

### Files Modified
- `backend/app/main.py` — added billing router

### Tests
- [x] Stripe checkout tests (3 tests)
- [x] PayNow invoice creation tests (2 tests)
- [x] Invoice retrieval tests (2 tests)
- [x] PayNow verification tests (3 tests)
- [x] Pending payments test (1 test)
- [x] Unsupported payment method test (1 test)
- [x] Webhook test (1 test)
- **All 13 tests passing** (2026-05-18)

---

## Phase 4: Simplified Admin Dashboard ✅ DONE

### Status: COMPLETE (2026-05-18)

### What Was Built
- [x] New admin dashboard (`static/admin/dashboard.html`) — 4 tabs
  - **Overview**: Total tenants, active trials, paid subscriptions, pending payments
  - **Tenants**: List, search, extend trials, activate/deactivate
  - **Billing**: Pending PayNow payments, subscription plans management
  - **Settings**: System config, API endpoints reference
- [x] Admin trial extension endpoint (`POST /api/admin/tenants/{id}/extend-trial`)
- [x] Admin plan management endpoints (list, create, update, delete)
- [x] Login form with JWT authentication
- [x] Tenant search functionality
- [x] PayNow payment verification from dashboard
- [x] Subscription plan cards display

### Files Created
- `backend/static/admin/dashboard.html`
- `tests/test_phase4_admin.py`

### Files Modified
- `backend/app/api/admin.py` — added trial extension, plan CRUD endpoints, SubscriptionPlan import
- `backend/app/main.py` — already routes to `/admin/dashboard`

### Tests
- [x] Trial extension tests (3 tests)
- [x] Plan management tests (7 tests)
- **All 10 tests passing** (2026-05-18)

---

## Database Schema Changes

### Already Exists ✅
- `tenants` — has `trial_ends_at`, `subscription_plan`, `stripe_customer_id`
- `subscription_plans` — plan definitions with trial days
- `invoices` — Invoice model with Stripe + PayNow fields
- `onboarding_requests` — self-service onboarding submissions

### New Tables Needed
- `calendar_integrations` — tenant_id, provider, tokens, settings
- `tenant_availability` — tenant_id, day_of_week, start_time, end_time
- `admin_audit_log` — admin_id, action, target, timestamp

---

## Test Strategy

Each phase must have tests before merging:

1. **Unit tests** — service layer logic
2. **API tests** — endpoint behavior with test database
3. **Integration tests** — full flow across services

Tests go in `tests/` directory following existing patterns.

---

## Current Progress Summary

| Phase | Status | Progress | Tests |
|-------|--------|----------|-------|
| Phase 1: Registration + Portal | ✅ Done | 100% | 20 passing |
| Phase 2: Calendar Integration | ✅ Done | 100% | 18 passing |
| Phase 3: Billing (Stripe+PayNow) | ✅ Done | 100% | 13 passing |
| Phase 4: Simplified Admin | ✅ Done | 100% | 10 passing |
| Integration Tests | ✅ Done | 100% | 8 passing |
| **Total Tests** | | | **69 passing** |

---

## Browser Verification Guide

### Prerequisites
1. Start the backend server: `cd backend && python -m uvicorn app.main:app --reload --port 8001`
2. Open browser to `http://127.0.0.1:8001`

### Test Flow

#### 1. Public Registration
- Go to `http://127.0.0.1:8001/public/register`
- Fill in: Business Name, Email, Website, Password
- Click "Start Free Trial"
- Verify: Success screen shows, redirect to dashboard

#### 2. Tenant Portal (6 tabs)
- Go to `http://127.0.0.1:8001/tenant/dashboard`
- **Overview tab**: See metrics, quick actions (embed code, test chatbot)
- **Channels tab**: View/copy embed code, configure WhatsApp
- **Conversations tab**: View recent chat sessions
- **Calendar tab**: 
  - See Google Calendar connection status
  - Set weekly availability (toggle days, set hours)
  - Click "Save Availability" → verify success toast
  - Click "Set Mon-Fri 9-5" → verify slots populated
- **Billing tab**:
  - See trial countdown circle
  - View available plans (Starter, Growth, Enterprise)
  - Click "Upgrade" → select Stripe or PayNow
  - PayNow: Shows QR data, UEN, reference number
- **Settings tab**: Edit business name, industry, tone

#### 3. Admin Dashboard
- Go to `http://127.0.0.1:8001/admin/dashboard`
- Login with: `admin` / `admin123`
- **Overview tab**: Total tenants, active trials, paid subscriptions
- **Tenants tab**:
  - Search tenants by name/slug
  - Click "Extend Trial" → set days → verify
  - Click "Deactivate/Activate" → verify status change
- **Billing tab**:
  - View pending PayNow payments
  - Click "Verify" on a pending payment → confirm → verify subscription activated
  - View subscription plan cards
  - Click "+ New Plan" → create plan → verify appears
- **Settings tab**: System info, API endpoints reference

#### 4. Pricing Page
- Go to `http://127.0.0.1:8001/public/pricing`
- Verify: Plans loaded from database, "Start Free Trial" button

#### 5. Login Page
- Go to `http://127.0.0.1:8001/public/login`
- Login with registered email/password
- Verify: Redirects to tenant dashboard

---

*Last updated: 2026-05-18*
