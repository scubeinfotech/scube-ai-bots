# LLM Platform - Phase 2 Implementation Plan

## 🎯 Vision
Transform from Q&A chatbot to intelligent AI agent that can take actions, remember context, and handle complex workflows.

---

## Phase 1: Foundation (Week 1-2)

### 1.1 Conversation Memory
- Add session persistence beyond single conversation
- Store conversation history per tenant
- Implement summary-based memory (compress old messages)
- Allow tenants to configure memory depth

### 1.2 RAG Improvements  
- Add BM25 keyword search alongside vector search
- Implement hybrid search (combine both)
- Add reranking for better result quality

---

## Phase 2: Intelligence (Week 2-3)

### 2.1 Sentiment Analysis
- Analyze user messages for sentiment
- Track conversation sentiment trend
- Flag negative sentiment to admin
- Auto-escalate if sentiment drops

### 2.2 Smart Escalation
- Define escalation triggers (sentiment, keyword, explicit request)
- Add human handoff workflow
- Notification system for admins
- Handoff context preservation

---

## Phase 3: Action (Week 3-4)

### 3.1 Function Calling Framework
- Define function schema system
- Register built-in functions (calendar, CRM, etc.)
- LLM function calling integration
- Tenant-specific custom functions

### 3.2 Appointment Booking
- Calendar integration (Google Calendar API)
- Check availability
- Create booking
- Send confirmation

---

## Priority Tonight

1. Function Calling Framework - Core infrastructure
2. Calendar Integration - Most requested  
3. Memory System - Foundation

---

## Files to Modify

- backend/app/services/chat_service.py
- backend/app/services/function_caller.py (NEW)
- backend/app/services/memory_service.py (NEW)
- backend/app/services/sentiment_analyzer.py (NEW)
- backend/app/services/rag_service.py
- backend/app/api/chat.py
