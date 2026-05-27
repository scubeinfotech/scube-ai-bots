# Pending Items & Next Steps Tracker

**Last Updated:** 2026-05-19

---

## ✅ COMPLETED THIS SESSION

- [x] Fixed Admin Dashboard View/Edit Modal (6 bugs)
- [x] Added missing backend field handlers (prompt_template, knowledge_context, guardrails)
- [x] Cleaned up test tenants (11 removed, 7 real tenants remain)
- [x] Added analytics overview endpoint with crawl status
- [x] Added crawl monitoring to admin dashboard

---

## 🔴 HIGH PRIORITY

### 1. Browser Testing - Admin & Tenant Dashboards
- [ ] Open `http://127.0.0.1:8001/admin/dashboard`
- [ ] Login: `admin` / `admin123`
- [ ] Test: Overview tab shows correct stats
- [ ] Test: Tenants tab → click "View/Edit" on any tenant
- [ ] Test: Edit fields → Save → verify changes persisted
- [ ] Test: Open `http://127.0.0.1:8001/tenant/dashboard` with a test tenant login
- [ ] Test: All 6 tabs (Overview, Channels, Conversations, Calendar, Billing, Settings)

### 2. Real Embeddings (Fixes Response Delay)
- **Current state:** Using hashed fallback embeddings (slow/poor quality)
- **Fix needed:** Integrate OpenAI `text-embedding-3-small` or local `sentence-transformers`
- **Impact:** Major improvement in chatbot response speed and answer quality

---

## 🟡 MEDIUM PRIORITY

### 3. Stripe/PayNow Real Integration
**Currently:** Mock flow (no real payments)

**How to enable real Stripe:**
1. Create Stripe account at https://dashboard.stripe.com
2. Get API keys (Test mode first):
   - `sk_test_...` for secret key
   - `pk_test_...` for publishable key
3. Add to `backend/.env`:
   ```
   STRIPE_SECRET_KEY=sk_test_...
   STRIPE_PUBLISHABLE_KEY=pk_test_...
   STRIPE_WEBHOOK_SECRET=whsec_...
   ```
4. Install Stripe SDK: `pip install stripe`
5. Replace mock in `backend/app/services/stripe_service.py` with real SDK calls

**How to enable real PayNow:**
1. Get PayNow QR from your bank (DBS/OCBC/UOB business account)
2. Integrate with Stripe (Stripe supports PayNow in Singapore)
3. Replace mock QR in `backend/app/services/paynow_service.py`

**Test with:** Use Stripe test cards (e.g., `4242424242424242`)

### 4. Google Calendar OAuth Real Integration
**Currently:** Mock flow (no real calendar sync)

**How to enable real OAuth:**
1. Go to https://console.cloud.google.com
2. Create project → enable "Google Calendar API"
3. Create OAuth 2.0 credentials:
   - Application type: Web application
   - Authorized redirect URIs: `http://127.0.0.1:8001/api/calendar/oauth/callback`
4. Download `credentials.json`
5. Add to `backend/.env`:
   ```
   GOOGLE_OAUTH_CLIENT_ID=...
   GOOGLE_OAUTH_CLIENT_SECRET=...
   ```
6. Implement OAuth flow in `backend/app/services/calendar_service.py`

---

## 🟢 LOW PRIORITY / ONGOING

### 5. Answer Quality Improvements
- Multi-step/numerical reasoning
- Source citations in responses
- Out-of-scope handling ("I don't know" for low confidence)
- Tone/length consistency enforcement
- Negative-case test suite

### 6. Conversational Memory
- Session facts (store extracted user context)
- Cross-session memory
- Lead memory regression test

### 7. Crawling & Data
- Semantic chunking + real embeddings
- Manual override (admin upload)
- Data store hygiene

---

## 📋 QUICK REFERENCE

| Item | URL / Command |
|------|---------------|
| Admin Dashboard | `http://127.0.0.1:8001/admin/dashboard` |
| Tenant Dashboard | `http://127.0.0.1:8001/tenant/dashboard` |
| Public Register | `http://127.0.0.1:8001/public/register` |
| API Docs | `http://127.0.0.1:8001/docs` |
| Restart Server | `docker-compose restart api` |
| Run Tests | `cd backend && ../.venv/bin/python -m pytest ../tests/ -v` |

**Admin Credentials:** `admin` / `admin123`

**Active Tenants (7):**
- Rapas Engineering, Scube Infotech, SDS Foodz, Jamiyah Singapore, Nivra-Studios, Nutech Solution, Seven Hills Impex

---

## 📞 SUPPORT

- **Email:** `sales@scubeinfotech.com.sg`
- **Admin:** `admin@llmplatform.local`
- **Alerts:** `alerts@scubeinfotech.com.sg`

---