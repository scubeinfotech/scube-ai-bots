# Centralized LLM Platform

This folder contains the complete project plan and execution structure for building a shared, multi-tenant LLM platform that powers chatbot experiences across multiple customer websites.

## 🚀 Current Status (March 10, 2026)
- ✅ **Sprint 01 Complete:** Backend API, database, LLM adapters, widget SDK, tests
- ✅ **Admin Dashboard:** Conversation viewing, analytics, document management
- ✅ **Query Training Feature:** Click-to-view query details with training options
- 🔄 **POC Testing:** Ready for validation

## 📊 Admin Features Available
1. **View Conversations** - See actual chat sessions and responses
2. **Track Unanswered Queries** - Monitor low-confidence responses (e.g., Scube's 10.3%)
3. **Auto-Training System** - Mark queries for LLM fine-tuning
4. **Document Upload** - Manually upload training documents for RAG
5. **Analytics Dashboard** - Portfolio-wide metrics and per-tenant insights

## Program Goals
- Build one centralized LLM service for all managed websites.
- Keep tenant data and behavior isolated per website.
- Support current portfolio and future onboarding with minimal code changes.
- Reduce operating cost through shared infrastructure and model routing.

## Current Tenant Portfolio
- `rapas`
- `sdsfoodz`
- `insurance-a`
- `insurance-b`
- `technology`

## 📁 Key Files
- **Admin UI:** `backend/static/admin-dashboard.html` - Interactive admin interface served at `/admin`
- **API Setup:** `setup.sh` - Initial environment setup
- **Service Control:** `service-control.sh` - Start/stop/restart services
- **Validation:** `validate-and-test.sh` - Comprehensive testing
- **Quick Reference:** `QUICK-REFERENCE.md` - All commands and ports
- **Query Training Guide:** `QUICK_START_QUERY_TRAINING.md` - Feature walkthrough

## Folder Structure
- `planning/`: charter, roadmap, WBS, risks
- `implementation/`: technical module plan and build boundaries
- `integrations/`: tenant onboarding plan and current portfolio rollout
- `operations/`: cost, capacity, security, compliance, SRE
- `execution/`: sprint backlog and delivery checklists
- `backend/`: FastAPI application with multi-tenant support
- `tests/`: POC tests and validation scripts

## Delivery Horizon
- Phase 1 (Weeks 1-4): MVP for 1 tenant (`rapas`) ✅ **COMPLETE**
- Phase 2 (Weeks 5-8): Multi-tenant foundation + 2 more tenants
- Phase 3 (Weeks 9-12): Full current portfolio onboarding
- Phase 4 (Weeks 13-16): Scale, automation, and client-ready onboarding

## Success Criteria
- P95 chatbot response latency under 2.5s
- 99.9% uptime
- Tenant data isolation enforced
- All current websites integrated
- New tenant onboarding time under 1 day

## 🚀 Quick Start
```bash
# Start services
./service-control.sh start

# Validate everything
./validate-and-test.sh

# Open live admin dashboard
open http://localhost:8001/admin

# Access API docs
open http://localhost:8001/docs
```

## 🔧 Service Ports
- **API:** http://localhost:8001
- **Admin UI:** http://localhost:8001/admin
- **Database:** localhost:5432
- **API Docs:** http://localhost:8001/docs
