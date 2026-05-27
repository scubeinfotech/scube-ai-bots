# Architecture Review & Optimization

**Date:** March 8, 2026  
**Status:** Optimized for Resource-Constrained Start

---

## 🏗️ Current Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLIENT WEBSITES                              │
│         (Rapas, SDSFoodz, Insurance, Technology)                    │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             │ Widget SDK (JavaScript)
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                      API LAYER (FastAPI)                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │   Tenants    │  │    Chat      │  │       Health             │  │
│  │   /tenants/* │  │  /chat/*     │  │      /health             │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                    SERVICE LAYER                                    │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              ChatService (Business Logic)                     │  │
│  │  • Session management    • Context building                   │  │
│  │  • Message orchestration • Error handling                     │  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────┬────────────────────────┬─────────────────────────┘
                   │                        │
         ┌─────────▼───────────┐  ┌─────────▼──────────┐
         │  DATABASE (SQLite)  │  │  LLM ADAPTER LAYER │
         │  • Tenants          │  │  (Pluggable)       │
         │  • Chat Sessions    │  └──────────┬─────────┘
         │  • Messages         │             │
         │  • API Keys         │             │
         └─────────────────────┘   ┌─────────▼─────────────────────┐
                                   │   LLM PROVIDERS (Choose One)  │
                                   │  ┌─────────────────────────┐  │
                                   │  │ Mock (Development)      │  │
                                   │  │ RAM: 100MB  Cost: $0    │  │
                                   │  └─────────────────────────┘  │
                                   │  ┌─────────────────────────┐  │
                                   │  │ Groq (FREE - Recommended) │
                                   │  │ RAM: 200MB  Cost: $0    │  │
                                   │  │ Speed: Very Fast        │  │
                                   │  └─────────────────────────┘  │
                                   │  ┌─────────────────────────┐  │
                                   │  │ Ollama (Future)         │  │
                                   │  │ RAM: 8-16GB  Cost: $0   │  │
                                   │  │ Use: Later when needed  │  │
                                   │  └─────────────────────────┘  │
                                   └───────────────────────────────┘
```

---

## 📊 Resource Comparison

### Current Setup (Mock - Development)
```
Total Resources Required:
├── RAM: ~500 MB
├── CPU: 1 core
├── Disk: ~1 GB
├── Cost: $0
└── Use Case: Development, testing, UI/UX work
```

### Recommended Setup (Groq - Production Ready)
```
Total Resources Required:
├── RAM: ~1 GB
├── CPU: 1 core  
├── Disk: ~1 GB
├── Cost: $0 (free tier: 14,400 requests/day)
├── Setup Time: 5 minutes
└── Use Case: Real production, all 5 tenants
```

### Future Setup (Ollama - When Scaling)
```
Total Resources Required:
├── RAM: 16 GB minimum
├── CPU: 4+ cores
├── Disk: 20-50 GB (multiple models)
├── Cost: Server costs only
└── Use Case: High volume, data privacy, offline
```

---

## 🎯 Optimization Strategy

### **Phase 1: Current (Mock) - ✅ COMPLETE**
- **Goal:** Platform development & testing
- **Provider:** Mock adapter
- **Resources:** Minimal (~500 MB RAM)
- **Status:** All 17 tests passing

### **Phase 2: Groq Free Tier - 🟡 NEXT (TODAY)**
- **Goal:** Real LLM responses for Rapas
- **Provider:** Groq (free, fast)
- **Resources:** ~1 GB RAM total
- **Steps:**
  1. Get free Groq API key
  2. Set environment variables
  3. Run seed script for Rapas
  4. Test real conversations
  5. Deploy widget on Rapas website

### **Phase 3: Multi-Tenant Production (Weeks 3-8)**
- **Goal:** All 5 tenants onboarded
- **Provider:** Groq (still free tier)
- **Resources:** ~1-2 GB RAM
- **Capacity:** 14,400 requests/day (sufficient for 5 sites)

### **Phase 4: Scale Decision (Weeks 9+)**
- **Evaluate:** Request volume, data privacy needs
- **Options:**
  - Stay on Groq free (if under 14K/day)
  - Upgrade to Groq paid (if needed)
  - Move to Ollama (if need self-hosting)

---

## 🔧 Key Design Decisions

### 1. **Adapter Pattern for LLM Providers**
**Why:** Flexibility to switch providers without changing business logic

**Benefits:**
- Start with mock (free, instant)
- Move to Groq (free, fast) 
- Later switch to Ollama (self-hosted) or others
- No code changes in API/service layers

### 2. **Service Layer Separation**
**Why:** Business logic isolated from API and data layers

**Benefits:**
- Easier testing
- Reusable across different API endpoints
- Clear separation of concerns
- Simpler maintenance

### 3. **SQLite → PostgreSQL Path**
**Current:** SQLite (development)
**Future:** PostgreSQL (production)

**Benefits:**
- Start simple with SQLite
- No DB server setup needed initially
- Easy migration path to PostgreSQL
- Same ORM code works for both

### 4. **Tenant-Level Configuration**
**Why:** Each tenant has unique needs

**Features:**
- Custom prompts per industry
- Domain-specific knowledge
- Configurable model parameters
- Guardrails and safety rules

---

## 📈 Scaling Roadmap

### Current Capacity (Groq Free Tier)
```
┌──────────────────────────────────────────────────────┐
│ Groq Free Tier Capacity                              │
├──────────────────────────────────────────────────────┤
│ Daily Limit:     14,400 requests                     │
│ Per Tenant:      ~2,880 requests (5 tenants)         │
│ Per Hour/Tenant: ~120 requests                       │
│ Per User:        ~24 conversations/hour              │
│                                                      │
│ Sufficient for: Small business websites              │
│ Upgrade when:   > 500 conversations/day per tenant   │
└──────────────────────────────────────────────────────┘
```

### When to Consider Ollama
```
Triggers:
├── Request volume > 10K/day consistently
├── Data privacy requirements (can't use cloud)
├── Need offline operation
├── Have server with 16GB+ RAM available
└── Budget for server costs ($50-100/month)

Until then: Groq free tier is perfect! ✓
```

---

## 🚀 Next Immediate Actions

### Step 1: Get Groq API Key (5 minutes)
1. Visit: https://console.groq.com
2. Sign up (free, no credit card)
3. Create API key
4. Copy key

### Step 2: Configure Environment
```bash
cd /home/sudhakar/New-Projects/centralized-llm-platform/backend
cp .env.example .env
nano .env
```

Set:
```bash
LLM_PROVIDER=groq
GROQ_API_KEY=your_actual_key_here
```

### Step 3: Seed Rapas Tenant
```bash
PYTHONPATH=./backend python3 backend/seed_rapas_tenant.py
```

### Step 4: Start Backend
```bash
cd backend
uvicorn app.main:app --reload --port 8001
```

### Step 5: Test Widget
```bash
# Open widget/test.html in browser
# Update tenant_id to Rapas tenant ID
# Test real conversations!
```

---

## 💰 Cost Analysis

### 3-Month Projection (Groq Free Tier)

```
Month 1 (Rapas only):
├── Requests/day: ~500
├── Cost: $0
└── Status: Well under limit ✓

Month 2 (Rapas + SDSFoodz + Insurance-A):
├── Requests/day: ~2,000
├── Cost: $0
└── Status: Well under limit ✓

Month 3 (All 5 tenants):
├── Requests/day: ~4,000-6,000
├── Cost: $0
└── Status: Under limit ✓

Conclusion: Can run all 5 tenants FREE for months!
```

### If Growth Requires Paid Plan
```
Groq Paid Tier (when needed):
├── Cost: ~$0.10 per 1M tokens
├── Average conversation: 500 tokens
├── 10,000 conversations: ~$0.50
├── Very affordable scaling path ✓
```

---

## ✅ Architecture Strengths

1. **Resource Efficient:** Runs on minimal hardware
2. **Cost Effective:** $0 for months with free tier
3. **Scalable:** Easy upgrade path when needed
4. **Flexible:** Swap providers anytime
5. **Production Ready:** Groq is fast & reliable
6. **Well Tested:** 17 tests, all passing
7. **Clean Design:** Service layer, adapters, clear separation

---

## 📝 Summary

**Current State:** ✅ Platform ready, all tests passing

**Recommended Next Step:** 🎯 Switch to Groq (5 min setup, $0 cost)

**Short-term Goal:** Get Rapas live with real LLM (today!)

**Long-term Goal:** All 5 tenants on platform (8 weeks)

**Resource Needs:** ~1-2 GB RAM total (very light!)

**Cost:** $0 for foreseeable future

---

**You made the right call to avoid Ollama initially!** 🎉

Start with Groq free tier → Ship fast → Scale when needed.
