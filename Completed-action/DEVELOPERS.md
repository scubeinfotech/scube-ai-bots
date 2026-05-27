# Centralized LLM Platform - Development Setup

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- Git

### Installation

1. **Clone and Setup**
```bash
cd centralized-llm-platform
chmod +x setup.sh
./setup.sh
```

2. **Access Services**
- API: http://localhost:8001
- API Docs: http://localhost:8001/docs
- PostgreSQL: localhost:5432
- Redis: localhost:6379

### Manual Setup

**Without Docker:**
```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
cd backend
pip install -r requirements.txt

# 3. Setup database
# Create PostgreSQL database (or use SQLite for testing)
export DATABASE_URL="postgresql://llmuser:changeme123@localhost:5432/llm_chatbot"

# 4. Run server
uvicorn app.main:app --reload

# 5. In another terminal, run tests
cd ..
pytest tests/
```

**With Docker:**
```bash
# Start all services
docker-compose up

# In another terminal, run migrations
docker-compose exec api alembic upgrade head

# Run tests
docker-compose exec api pytest tests/
```

## Project Structure

```
centralized-llm-platform/
├── backend/
│   ├── app/
│   │   ├── api/              # API endpoints
│   │   ├── models/           # Database models
│   │   ├── adapters/         # LLM adapters (Ollama, Mock, etc)
│   │   ├── services/         # Business logic
│   │   ├── config.py         # Configuration
│   │   ├── database.py       # Database setup
│   │   └── main.py           # FastAPI app
│   ├── requirements.txt
│   └── Dockerfile
├── widget/
│   ├── src/widget.js         # JavaScript SDK
│   └── test.html             # Widget test page
├── tests/
│   ├── test_tenants.py       # Tenant API tests
│   ├── test_chat.py          # Chat API tests
│   ├── test_adapters.py      # LLM adapter tests
│   └── conftest.py           # Test configuration
├── docker-compose.yml        # Docker services
├── .github/workflows/ci.yml  # CI/CD pipeline
└── setup.sh                  # Development setup script
```

## API Endpoints

### Tenants
- `POST /api/tenants/` - Create tenant
- `GET /api/tenants/{id}` - Get tenant by ID
- `GET /api/tenants/slug/{slug}` - Get tenant by slug
- `GET /api/tenants/` - List all tenants

### Chat
- `POST /api/chat/message/{tenant_id}` - Send message
- `GET /api/chat/session/{session_id}` - Get session messages

### Health
- `GET /health` - API health check
- `GET /api/health` - Detailed health status

## Development Workflow

1. **Create a feature branch**
```bash
git checkout -b feature/my-feature
```

2. **Make changes and test**
```bash
pytest tests/ -v
docker-compose up  # or run backend locally
```

3. **Commit and push**
```bash
git add .
git commit -m "feat: add new feature"
git push origin feature/my-feature
```

4. **Create pull request**

## Sprint 01 Checklist (Phase 1 - Weeks 1-2)

- [x] Platform repo and CI scaffold
  - [x] Main repository structure
  - [x] GitHub Actions CI/CD pipeline
  - [x] Lint/test automation
- [x] Tenant config schema and seed data
  - [x] Tenant model with configuration fields
  - [x] API endpoints for tenant management
- [x] Chat message API v1
  - [x] ChatMessage and ChatSession models
  - [x] Message send endpoint
  - [x] Session retrieval endpoint
- [x] LLM adapter abstraction
  - [x] Base LLMAdapter class
  - [x] OllamaAdapter implementation
  - [x] MockAdapter for testing
- [x] Widget SDK basic integration
  - [x] JavaScript widget.js SDK
  - [x] HTML test page
  - [x] Basic UI with theme customization
- [x] Logging and metrics baseline
  - [x] Request/response logging
  - [x] Token usage tracking
  - [x] Latency measurement
- [x] QA smoke tests
  - [x] 15+ test cases for critical flows
  - [x] Tenant CRUD operations
  - [x] Chat message flow
  - [x] LLM adapter testing

## Environment Variables

```bash
# Backend
DATABASE_URL=postgresql://llmuser:changeme123@localhost:5432/llm_chatbot
OLLAMA_URL=http://localhost:11434
API_SECRET_KEY=dev-secret-key-change-in-prod
ENVIRONMENT=development
DEFAULT_MODEL=llama3.1:8b
```

## Troubleshooting

**Docker containers not starting:**
```bash
docker-compose down
docker-compose up --build
```

**PostgreSQL connection error:**
```bash
# Wait for PostgreSQL to be ready
sleep 10
docker-compose exec api alembic upgrade head
```

**Tests failing:**
```bash
# Run with verbose output
pytest tests/ -v -s

# Run specific test
pytest tests/test_tenants.py::test_create_tenant -v
```

## Next Steps (Phase 2 - Weeks 5-8)

1. **Tenant onboarding workflow**
   - Automated tenant registration flow
   - Admin controls for configuration

2. **Multi-tenant isolation**
   - Enhanced permission model
   - Data boundary enforcement

3. **Additional portfolios**
   - Onboard SDSFoodz
   - Onboard Insurance-A

4. **Analytics dashboard**
   - Usage metrics visualization
   - Performance monitoring

## Support

For issues or questions, check:
1. GitHub Issues
2. Project documentation in `/planning` and `/execution`
3. API documentation at http://localhost:8001/docs

---

**Version:** 0.1.0 (MVP - Phase 1)  
**Last Updated:** March 8, 2026
