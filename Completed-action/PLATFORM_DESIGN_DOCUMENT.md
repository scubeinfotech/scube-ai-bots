# Centralized LLM Platform - Design Document

---

## 1. Login Credentials

### Admin Login
| Field | Value |
|-------|-------|
| URL | `http://localhost:8000/admin` |
| Username | `admin` |
| Password | `admin123` |

> ⚠️ **Change password immediately in production!**

### Admin API Authentication
```bash
# Login to get JWT token
curl -X POST http://localhost:8000/api/admin/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'

# Response includes access_token for subsequent API calls
```

### Tenant Access
- Each tenant gets a unique API key for widget embedding
- Widget code generated from Admin Dashboard → Tenant → "Get Widget Code"
- Tenant ID: Unique UUID per tenant

---

## 2. LLM & Embedding Models Used

### LLM Providers (Primary → Fallback Chain)

| Priority | Provider | Model | Env Variable |
|----------|----------|-------|--------------|
| 1 (Primary) | Groq | `llama-3.3-70b-versatile` | `LLM_PRIMARY=groq` |
| 2 (Secondary) | Google Gemini | `gemini-1.5-flash` | `LLM_SECONDARY=gemini` |
| 3 (Tertiary) | OpenRouter | `openai/gpt-4o-mini` | `LLM_TERTIARY=openrouter` |
| 4 (Fallback) | Mock | N/A | `LLM_PROVIDER=mock` |

**Configuration in `.env`:**
```
LLM_PROVIDER=router        # Router mode (tries 1→2→3→4 on failure)
LLM_PRIMARY=groq
LLM_GROQ_MODEL=llama-3.3-70b-versatile
LLM_PROVIDER_TIMEOUT_MS=30000
```

### Embedding Models

| Priority | Provider | Model | Purpose |
|----------|----------|-------|---------|
| 1 | Sentence Transformers | `BAAI/bge-m3` | Semantic search (best quality) |
| 2 | OpenAI | `text-embedding-3-small` | Fallback semantic |
| 3 | OpenRouter | `openai/text-embedding-3-small` | Fallback semantic |
| 4 | Ollama | Local embeddings | Offline fallback |
| 5 | Hash-based | MD5 fallback | Last resort (low quality) |

**Embedding Config:**
```
EMBEDDING_PRIMARY=sentence-transformers
EMBEDDING_MODEL=BAAI/bge-m3
```

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CLIENT WEBSITES                          │
│  (Nutech, Scube, Rapas, Jamiyah, SDS Foodz, Novafarms)     │
└──────────────────────┬──────────────────────────────────────┘
                       │ Widget Embedding (JS)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  BACKEND (FastAPI)                          │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │  Chat API   │  │ Admin API    │  │  Tenant API     │   │
│  │  - /message │  │ - /admin/*   │  │  - /tenants/*   │   │
│  │  - /session │  │ - Dashboard  │  │  - /crawl/*     │   │
│  └──────┬──────┘  └──────┬───────┘  └────────┬────────┘   │
│         │                │                    │             │
│  ┌──────▼────────────────▼────────────────────▼────────┐  │
│  │              ChatService (Core Logic)                 │  │
│  │  - Prompt building      - Lead extraction            │  │
│  │  - Language detection  - RAG retrieval               │  │
│  │  - Post-processing     - Memory management           │  │
│  └────────────────────────┬───────────────────────────────┘  │
│                           │                                  │
│  ┌──────────────┬─────────┴─────────┬──────────────┐       │
│  │              │                   │              │         │
│  ▼              ▼                   ▼              ▼         │
│ ┌────────┐  ┌──────────┐    ┌──────────┐  ┌──────────┐    │
│ │  LLM   │  │Embedding│    │  Vector  │  │  Rate    │    │
│ │ Router │  │ Provider│    │   Store  │  │ Limiter  │    │
│ └────────┘  └──────────┘    └──────────┘  └──────────┘    │
└────────────────────────────┬────────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
     ┌─────────────────┐          ┌─────────────────┐
     │   SQLite DB     │          │  Self-Learning  │
     │  (llm_platform) │          │  (APScheduler)  │
     │  - tenants      │          │  - Q&A extract  │
     │  - sessions     │          │  - Unanswered   │
     │  - messages     │          │    query scan   │
     │  - api_keys     │          └─────────────────┘
     │  - documents    │
     └─────────────────┘
```

---

## 4. Core Features & Functionality

### 4.1 Chat Widget
- Embeddable JavaScript widget
- Customizable position (bottom-right, bottom-left, top-right, top-left)
- Theme customization (colors, fonts)
- Session persistence (localStorage)
- Lead collection form (after 3 messages)
- JWT token refresh

### 4.2 Multi-Tenant Isolation
- Tenant-scoped API keys
- Domain allowlist validation
- CORS origin checking
- Widget JWT origin binding

### 4.3 Conversational Memory
- Per-session message history
- Lead info extraction (name, email, phone)
- Session facts storage
- Cross-session memory (optional per tenant)

### 4.4 Knowledge & RAG
- Website crawling (scheduled daily 3AM)
- Content extraction (readability)
- Semantic chunking with BM25 + cosine hybrid scoring
- MIN_SCORE threshold: 0.15
- Auto-learned Q&A from conversations

### 4.5 Response Quality
- System prompt with 6 sections (IDENTITY, SCOPE, KNOWLEDGE, RETRIEVED, POLICY, STYLE)
- Language detection (English, Singlish, Malay, Tamil, Chinese)
- Callback intent detection
- Hallucination guards (no invented pricing/URLs)

### 4.6 Admin Dashboard
- Tenant management (create, edit, delete)
- API key management
- Widget code generation
- Chat analytics
- Lead collection tracking

---

## 5. API Endpoints

### Chat API
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat/message/{tenant_id}` | POST | Send message |
| `/api/chat/session/{session_id}` | GET | Get session messages |
| `/api/chat/token/{tenant_id}` | POST | Get widget JWT |

### Admin API
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/tenants` | GET/POST | List/Create tenants |
| `/admin/tenants/{id}` | GET/PUT/DELETE | Manage tenant |
| `/admin/tenants/{id}/widget-code` | GET | Get embed code |
| `/admin/api-keys` | GET/POST | Manage API keys |
| `/admin/analytics` | GET | Chat statistics |

### Tenant API
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tenants` | GET | List tenants |
| `/api/tenants/{id}` | GET | Get tenant config |

---

## 6. Database Schema

### Key Tables
- **tenants** - Tenant configuration (name, domain, theme, prompt_template)
- **users** - Admin users
- **api_keys** - Widget/API keys with rate limits and domain restrictions
- **chat_sessions** - Conversation sessions with lead info
- **chat_messages** - Individual messages
- **documents** - Crawled content metadata
- **document_chunks** - Chunked content for RAG
- **crawl_runs** - Crawl history
- **unanswered_queries** - Self-learning Q&A storage

---

## 7. Scheduled Jobs (APScheduler)

| Job | Schedule | Description |
|-----|----------|-------------|
| Website Crawl | Daily 3:00 AM | Auto-update knowledge base |
| Self-Learning | Daily 2:00 AM | Extract Q&A from conversations |
| Unanswered Query Scan | Every 15 min | Populate unanswered queries |
| Canary Monitor | Every 10 min | Detect chat leak issues |

---

## 8. Security Features

- API key authentication
- Widget JWT with origin binding
- Per-key rate limiting
- Domain allowlist enforcement
- CORS origin validation
- Private IP bypass control (ALLOW_LOCAL_ORIGINS)

---

## 9. Environment Variables

```bash
# Server
HOST=0.0.0.0
PORT=8000

# Database
DATABASE_URL=postgresql://...

# LLM
LLM_PROVIDER=router
LLM_PRIMARY=groq
LLM_GROQ_MODEL=llama-3.3-70b-versatile
LLM_PROVIDER_TIMEOUT_MS=30000

# Embedding
EMBEDDING_PRIMARY=sentence-transformers
EMBEDDING_MODEL=BAAI/bge-m3

# Security
ALLOW_LOCAL_ORIGINS=false
API_SECRET_KEY=your-secret-key

# Scheduler
CRAWL_ENABLED=true
SELF_LEARNING_ENABLED=true
```

---

## 10. Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI (Python 3.11) |
| Database | SQLite (dev) / PostgreSQL (prod) |
| LLM | Groq, Gemini, OpenRouter |
| Embeddings | Sentence Transformers, OpenAI |
| UI | Admin Dashboard (HTML/JS) |
| Task Scheduling | APScheduler |
| Crawling | Trafilatura, BeautifulSoup |

---

*Document generated: 2026-05-15*