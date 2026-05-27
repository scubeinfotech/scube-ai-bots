# 🚀 Centralized LLM Platform - Quick Reference

## ✅ **PORT CONFIGURATION - VALIDATED**

| Service | Host Port | Container Port | Access URL |
|---------|-----------|----------------|------------|
| **FastAPI** | **8001** | 8000 | http://localhost:**8001** |
| **PostgreSQL** | **5432** | 5432 | localhost:**5432** |
| **API Docs** | **8001** | - | http://localhost:**8001/docs** |

⚠️ **IMPORTANT:** Always use port **8001** when accessing the API from your browser/curl

---

## 📋 **MANAGEMENT SCRIPTS**

### 1. **Service Control** (Primary)
```bash
./service-control.sh start     # Start all services
./service-control.sh stop      # Stop all services
./service-control.sh restart   # Restart all services
./service-control.sh status    # Check status & health
./service-control.sh logs      # View live logs
./service-control.sh clean     # Remove all data & restart
```

### 2. **Validation & Testing**
```bash
./validate-and-test.sh         # Comprehensive validation
                               # - Validates all configurations
                               # - Tests API endpoints
                               # - Runs functional tests
```

### 3. **Initial Setup**
```bash
./setup.sh                     # First-time setup
                               # - Creates .env
                               # - Installs dependencies
                               # - Starts services
```

---

## 🔧 **DIRECT DOCKER COMMANDS**

### Start/Stop
```bash
docker-compose up -d           # Start in background
docker-compose down            # Stop services
docker-compose down -v         # Stop & remove data
docker-compose restart         # Restart all
docker restart llm-api         # Restart API only
```

### Monitor
```bash
docker-compose ps              # Check status
docker-compose logs -f         # Follow all logs
docker-compose logs -f api     # API logs only
docker-compose logs --tail 50 api  # Last 50 lines
```

### Troubleshoot
```bash
docker exec -it llm-api bash   # Shell into API container
docker exec llm-postgres psql -U llmuser -d llm_chatbot  # Database shell
```

---

## 🧪 **QUICK HEALTH CHECKS**

### 1. API Health
```bash
curl http://localhost:8001/health
# Expected: {"status":"healthy","version":"1.0.0"}
```

### 2. Database Health
```bash
docker exec llm-postgres pg_isready -U llmuser
# Expected: llm-postgres:5432 - accepting connections
```

### 3. Service Status
```bash
docker-compose ps
# Expected: llm-api and llm-postgres both "Up"
```

---

## 📊 **API TESTING COMMANDS**

### Create a Tenant
```bash
curl -X POST http://localhost:8001/api/tenants/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Company",
    "slug": "test-company",
    "domain": "testcompany.com"
  }'
```

### List Tenants
```bash
curl http://localhost:8001/api/tenants/
```

### Send a Chat Message
```bash
# Replace <TENANT_ID> with actual ID
curl -X POST http://localhost:8001/api/chat/message/<TENANT_ID> \
  -H "Content-Type: application/json" \
  -d '{"content": "Hello, how can you help me?"}'
```

### View Conversations (Admin)
```bash
# Replace <TENANT_ID> with actual ID
curl http://localhost:8001/api/admin/conversations/<TENANT_ID>
```

### Upload Document
```bash
# Replace <TENANT_ID> with actual ID
curl -X POST http://localhost:8001/api/admin/documents/<TENANT_ID>/upload \
  -F "name=FAQ Document" \
  -F "content=Q: How to deploy? A: Follow these steps..." \
  -F "document_type=faq"
```

### View Unanswered Queries
```bash
# Replace <TENANT_ID> with actual ID
curl http://localhost:8001/api/admin/unanswered-queries/<TENANT_ID>
```

---

## 🎯 **ADMIN FEATURES AVAILABLE**

### 1. View Conversations
- Endpoint: `GET /api/admin/conversations/{tenant_id}`
- View all chat sessions for a tenant

### 2. View Detailed Transcript
- Endpoint: `GET /api/admin/conversations/session/{session_id}`
- Get full conversation with all messages

### 3. Document Management
- Upload: `POST /api/admin/documents/{tenant_id}/upload`
- List: `GET /api/admin/documents/{tenant_id}`
- Delete: `DELETE /api/admin/documents/{tenant_id}/{doc_id}`
- Process for RAG: `POST /api/admin/documents/{tenant_id}/{doc_id}/process`

### 4. Unanswered Query Tracking
- List: `GET /api/admin/unanswered-queries/{tenant_id}`
- Resolve: `PATCH /api/admin/unanswered-queries/{query_id}/resolve`
- Mark for training: `POST /api/admin/unanswered-queries/{query_id}/mark-for-training`

### 5. Analytics
- Portfolio: `GET /api/analytics/portfolio`
- Tenant specific: `GET /api/analytics/tenant/{tenant_id}/dashboard?days=7`

---

## 🔍 **TROUBLESHOOTING GUIDE**

### Problem: API not responding on port 8001
```bash
# Check if services are running
docker-compose ps

# Check API logs
docker logs llm-api --tail 50

# Restart API
docker restart llm-api

# Wait and test
sleep 5
curl http://localhost:8001/health
```

### Problem: Database connection error
```bash
# Check database status
docker exec llm-postgres pg_isready -U llmuser

# Restart database
docker restart llm-postgres

# Wait for health check
sleep 10
```

### Problem: Port 6379 already in use (Redis)
```bash
# Redis is commented out in docker-compose.yml
# If you see this error, it's from a local Redis instance
# This is OK - we're not using Redis in POC

# To confirm:
grep -A5 "redis:" docker-compose.yml
# Should show commented out lines
```

### Problem: Changes not reflecting
```bash
# Restart with rebuild
docker-compose down
docker-compose up -d --build

# Or restart just API
docker restart llm-api
```

---

## 📁 **FILE LOCATIONS**

### Configuration
- Main config: `docker-compose.yml`
- Environment: `backend/.env`
- Database: Docker volume `postgres_data`

### Logs
- API logs: `docker logs llm-api`
- DB logs: `docker logs llm-postgres`
- All logs: `docker-compose logs`

### Code
- Backend: `backend/app/`
- Models: `backend/app/models/`
- API endpoints: `backend/app/api/`
- Services: `backend/app/services/`

---

## ✅ **VALIDATION CHECKLIST**

Run this before testing:
```bash
# 1. Check scripts are executable
ls -l *.sh | grep rwx

# 2. Validate configuration
./validate-and-test.sh

# 3. Check services
./service-control.sh status

# 4. Test API
curl http://localhost:8001/health

# 5. View docs
# Open: http://localhost:8001/docs
```

---

## 🎯 **READY TO TEST?**

### Quick Start Sequence:
```bash
# 1. Start services
./service-control.sh start

# 2. Validate everything
./validate-and-test.sh

# 3. Open API docs in browser
# http://localhost:8001/docs

# 4. Open live admin dashboard
# http://localhost:8001/admin
```

---

## 🆘 **NEED HELP?**

### View Full Documentation
```bash
cat DEVELOPERS.md              # Developer guide
cat README.md                  # Project overview
cat CHATBOT_LLM_ARCHITECTURE.md  # Architecture details
```

### Quick Support Commands
```bash
# View all running containers
docker ps -a

# View container resource usage
docker stats

# Clean slate restart
docker-compose down -v
docker-compose up -d

# Rebuild everything
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

---

**Last Updated:** March 10, 2026  
**POC Status:** ✅ Ready for Testing  
**API Port:** 8001 (VALIDATED)
