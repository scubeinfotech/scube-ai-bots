# Centralized LLM Chatbot Architecture Proposal
## Multi-Tenant AI Service for Multiple Customer Websites

**Prepared for**: Rapas Engineering & Future Clients  
**Date**: March 8, 2026  
**Current Status**: Basic keyword-matching chatbot (needs AI upgrade)

---

## 🎯 Executive Summary

**Problem**: Current chatbot uses hardcoded responses, limited to keyword matching, not scalable.

**Solution**: Build centralized LLM container service that:
- Serves multiple customer websites (multi-tenant)
- Provides intelligent conversational AI
- Reduces per-customer costs through shared infrastructure
- Enables easy customization per client
- Scales horizontally

**Business Model**: SaaS - Centralized AI service with per-customer/per-message pricing

---

## 📊 Current vs Proposed Architecture

### Current State (As-Is)
```
┌─────────────────────────────────────┐
│   Browser (rapas.com.sg)   │
│  ┌──────────────────────────────┐  │
│  │   Hardcoded AI Responses     │  │
│  │   - if (msg.includes('quote'))│  │
│  │   - if (msg.includes('service'))│ │
│  │   - Simple keyword matching   │  │
│  └──────────────────────────────┘  │
└─────────────────────────────────────┘

❌ Problems:
- Not intelligent (keyword matching only)
- Can't understand context
- Requires code changes for new responses
- Not scalable to multiple customers
```

### Proposed Architecture (To-Be)

```
┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐
│  Customer Website 1      │  │  Customer Website 2      │  │  Customer Website 3      │
│  (rapas.com.sg)  │  │  (marinetech.com)        │  │  (shipservices.com)      │
│  ┌────────────────────┐  │  │  ┌────────────────────┐  │  │  ┌────────────────────┐  │
│  │  Chatbot Widget    │  │  │  │  Chatbot Widget    │  │  │  │  Chatbot Widget    │  │
│  │  (JavaScript SDK)  │──┼──┼──│  (JavaScript SDK)  │──┼──┼──│  (JavaScript SDK)  │  │
│  └────────────────────┘  │  │  └────────────────────┘  │  │  └────────────────────┘  │
└──────────────────────────┘  └──────────────────────────┘  └──────────────────────────┘
              │                            │                            │
              └────────────────────────────┼────────────────────────────┘
                                           │
                                 HTTPS / WebSocket / REST API
                                           │
              ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
              ┃   CENTRALIZED LLM SERVICE (Docker Container)         ┃
              ┃   (llm.yourdomain.com or llm-api.rapas.com)          ┃
              ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                           │
         ┌─────────────────────────────────┼─────────────────────────────────┐
         │                                 │                                 │
    ┌────▼─────┐                  ┌───────▼────────┐              ┌─────────▼────────┐
    │  API     │                  │  LLM Engine    │              │  Context Store   │
    │  Gateway │                  │  (Ollama/GPT-4)│              │  (Per Customer)  │
    │  + Auth  │                  │  + Fine-tuning │              │  + Knowledge Base│
    └──────────┘                  └────────────────┘              └──────────────────┘
         │                                 │                                 │
    ┌────▼─────────────────────────────────▼─────────────────────────────────▼────┐
    │                     MULTI-TENANT DATABASE                                   │
    │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
    │  │  Customer 1  │  │  Customer 2  │  │  Customer 3  │  │  Chat Logs   │   │
    │  │  Settings    │  │  Settings    │  │  Settings    │  │  Analytics   │   │
    │  │  - API Key   │  │  - API Key   │  │  - API Key   │  │  - Usage     │   │
    │  │  - Brand     │  │  - Brand     │  │  - Brand     │  │  - Feedback  │   │
    │  │  - Context   │  │  - Context   │  │  - Context   │  │              │   │
    │  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
    └─────────────────────────────────────────────────────────────────────────────┘

✅ Benefits:
- Intelligent AI conversations
- Context-aware responses
- One infrastructure serves all customers
- Easy to add new customers
- Scales horizontally
- Pay per usage
```

---

## 🏗️ Detailed Architecture Components

### 1. **Frontend Layer (Customer Websites)**

**Lightweight JavaScript SDK** embedded in customer sites:

```html
<!-- Customer embeds this ONE LINE in their website -->
<script src="https://llm-api.rapas.com/widget.js" 
        data-customer-id="rapas-eng-001" 
        data-api-key="sk_live_abc123xyz"></script>
```

**Widget Features:**
- Floating chat button
- Expandable chat window
- Real-time message display
- Typing indicators
- File upload support
- Mobile responsive
- Customizable colors/branding per customer

---

### 2. **API Gateway Layer**

**Technology**: FastAPI (Python) or Express.js (Node.js)

**Responsibilities:**
- Authentication (API key validation)
- Rate limiting per customer
- Request routing
- Load balancing
- Caching frequent queries
- CORS handling
- WebSocket connection management

**API Endpoints:**

```
POST   /api/v1/chat/message          → Send user message
GET    /api/v1/chat/history/:id      → Get conversation history
POST   /api/v1/chat/feedback          → Report good/bad response
GET    /api/v1/customer/settings     → Get customer config
WS     /api/v1/chat/stream            → WebSocket for real-time
POST   /api/v1/admin/customer         → Add new customer (admin)
GET    /api/v1/analytics/usage        → Usage metrics (admin)
```

**Sample Request:**
```json
POST /api/v1/chat/message
Headers: {
  "Authorization": "Bearer sk_live_abc123xyz",
  "Content-Type": "application/json"
}
Body: {
  "customer_id": "rapas-eng-001",
  "session_id": "sess_xyz789",
  "message": "What marine engineering services do you offer?",
  "context": {
    "page_url": "https://rapas.com.sg/services",
    "user_name": "John Doe",
    "customer_type": "returning"
  }
}
```

**Sample Response:**
```json
{
  "response": "Rapas Engineering offers comprehensive marine engineering services across the APAC region:\n\n1. **Piping & Fabrication** - Pipe spool fabrication, repairs, pressure testing with DNV-GL approved WPS\n2. **Structures & Steel Works** - Hatch covers, bow repairs, steel decks\n3. **Insulation & Fire Protection** - A60/A30/A15 ratings\n4. **Engine Parts Reconditioning** - State-of-the-art workshop\n5. **Electrical & Instrumentation**\n6. **Staging & Scaffolding**\n\nWhich service interests you most?",
  "confidence": 0.95,
  "sources": ["services_page", "knowledge_base"],
  "suggested_actions": [
    {"type": "button", "text": "Request Quote", "action": "open_form"},
    {"type": "button", "text": "Contact Sales", "action": "open_contact"}
  ],
  "metadata": {
    "response_time_ms": 234,
    "model_used": "gpt-4",
    "tokens_used": 156
  }
}
```

---

### 3. **LLM Engine Layer**

**Option A: Self-Hosted (Cost-Effective)**

**Technology Stack:**
- **Ollama** (open-source LLM runtime)
- **Models**: Llama 3.1, Mistral 7B, Phi-3
- **GPU**: NVIDIA T4 / A10G (AWS/GCP/Azure)

```dockerfile
# Dockerfile for LLM Service
FROM ollama/ollama:latest

# Install Python dependencies
RUN apt-get update && apt-get install -y python3 python3-pip
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# Copy models and fine-tuned weights
COPY models/ /models/
COPY customer_contexts/ /contexts/

# Expose API port
EXPOSE 8000

# Start service
CMD ["python3", "llm_service.py"]
```

**Estimated Costs (AWS):**
- g4dn.xlarge (1x NVIDIA T4): ~$0.526/hour = $380/month
- Can serve 100-200 concurrent users
- ~$3.80 per customer if serving 100 customers

**Option B: Managed Service (Faster Setup)**

**Providers:**
- **OpenAI API** (GPT-4 Turbo): $10/1M input tokens, $30/1M output
- **Anthropic Claude 3**: $15/1M tokens
- **Google Gemini Pro**: $0.50/1M tokens (cheapest)

**Hybrid Approach (Recommended):**
- Use **Ollama** for simple queries (80% of traffic)
- Fall back to **GPT-4** for complex questions (20%)
- Saves ~70% on API costs

---

### 4. **Multi-Tenant Database**

**Technology**: PostgreSQL with row-level security

**Schema Design:**

```sql
-- Customers Table
CREATE TABLE customers (
    customer_id VARCHAR(50) PRIMARY KEY,
    company_name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) NOT NULL,
    api_key VARCHAR(100) UNIQUE NOT NULL,
    plan_tier VARCHAR(20) DEFAULT 'basic', -- basic, pro, enterprise
    monthly_quota INT DEFAULT 10000, -- messages per month
    context_data JSONB, -- Custom knowledge base
    branding JSONB, -- Colors, logo, etc.
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Conversations Table
CREATE TABLE conversations (
    conversation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id VARCHAR(50) REFERENCES customers(customer_id),
    session_id VARCHAR(100),
    user_identifier VARCHAR(255), -- Email, IP, or anonymous ID
    started_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    total_messages INT DEFAULT 0,
    satisfaction_score INT, -- 1-5 rating
    metadata JSONB
);

-- Messages Table
CREATE TABLE messages (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(conversation_id),
    role VARCHAR(20) NOT NULL, -- 'user' or 'assistant'
    content TEXT NOT NULL,
    tokens_used INT,
    response_time_ms INT,
    model_used VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB
);

-- Customer Context/Knowledge Base
CREATE TABLE knowledge_base (
    kb_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id VARCHAR(50) REFERENCES customers(customer_id),
    content_type VARCHAR(50), -- 'faq', 'product', 'service', 'policy'
    title VARCHAR(255),
    content TEXT,
    embedding VECTOR(1536), -- For semantic search
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Usage Analytics
CREATE TABLE usage_stats (
    stat_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id VARCHAR(50) REFERENCES customers(customer_id),
    date DATE NOT NULL,
    total_messages INT DEFAULT 0,
    total_tokens INT DEFAULT 0,
    total_cost DECIMAL(10, 4) DEFAULT 0.00,
    avg_response_time_ms INT,
    satisfaction_avg DECIMAL(3, 2),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_customer_conversations ON conversations(customer_id, started_at DESC);
CREATE INDEX idx_conversation_messages ON messages(conversation_id, created_at);
CREATE INDEX idx_knowledge_customer ON knowledge_base(customer_id);
CREATE INDEX idx_usage_customer_date ON usage_stats(customer_id, date);
```

---

### 5. **Context Management System**

**Per-Customer Customization:**

```json
{
  "customer_id": "rapas-eng-001",
  "company_name": "Rapas Engineering Services Pte Ltd",
  "domain": "rapas.com.sg",
  "system_prompt": "You are a helpful marine engineering expert representing Rapas Engineering. You have 18+ years of experience in APAC marine services. You are knowledgeable, professional, and focused on providing value to shipowners and operators. Always mention contact details when relevant: +65 6710 7052, sales@rapas.com.sg",
  "context": {
    "industry": "Marine Engineering",
    "services": [
      "Piping & Fabrication",
      "Steel Works & Structures", 
      "Insulation & Fire Protection",
      "Engine Parts Reconditioning",
      "Electrical & Instrumentation",
      "Scaffolding Solutions"
    ],
    "regions": ["Singapore", "Malaysia", "Indonesia", "Thailand", "Philippines"],
    "certifications": ["ISO 9001:2015", "BizSafe Level 3", "DNV-GL Approved"],
    "contact": {
      "phone": "+65 6710 7052",
      "mobile": "+65 9763 0029",
      "email": "sales@rapas.com.sg",
      "workshop": "2 Fan Yoong Road, Singapore 629780",
      "office": "462 Crawford Lane, Singapore 190462"
    },
    "business_hours": "Mon-Fri 8am-8pm, Sat 8am-4pm, Sun on-call"
  },
  "faq": [
    {
      "question": "What are your service areas?",
      "answer": "We serve the entire APAC region including Singapore, Malaysia, Indonesia, Thailand, Philippines, and beyond."
    },
    {
      "question": "Do you have emergency services?",
      "answer": "Yes, we offer 24/7 emergency response for critical marine engineering situations. Call +65 9763 0029."
    }
  ],
  "branding": {
    "primary_color": "#00c1d4",
    "secondary_color": "#0a1e3c",
    "logo_url": "https://rapas.com.sg/assets/images/logo.png",
    "chat_header": "Rapas Engineering AI Assistant"
  },
  "features": {
    "file_upload": true,
    "voice_input": false,
    "email_transcript": true,
    "live_agent_handoff": true
  },
  "rate_limits": {
    "messages_per_minute": 60,
    "messages_per_month": 50000
  }
}
```

---

## 💡 Key Features of Centralized System

### 1. **Intelligent Routing**
```python
def route_query(message, customer_context):
    # Simple queries → Ollama (fast, cheap)
    if is_simple_query(message):
        return ollama_response(message, customer_context)
    
    # Complex queries → GPT-4 (accurate, expensive)
    elif is_complex_query(message):
        return openai_response(message, customer_context)
    
    # Technical queries → RAG + Vector search
    elif requires_knowledge_base(message):
        return rag_response(message, customer_context)
```

### 2. **RAG (Retrieval-Augmented Generation)**
- Upload customer PDFs, docs, website pages
- Create vector embeddings
- Semantic search before generating response
- Reduces hallucinations, increases accuracy

### 3. **Fine-Tuning per Customer**
```bash
# Train custom model on customer's data
ollama create rapas-model \
  --from llama3.1 \
  --adapter customer_data/rapas-engineering.safetensors
```

### 4. **Multi-Language Support**
- Detect user language automatically
- Respond in same language
- Support: English, Chinese, Malay, Thai, Bahasa

### 5. **Analytics Dashboard**
- Real-time conversations
- Customer satisfaction scores
- Most asked questions
- Response accuracy trends
- Cost per customer
- Token usage

---

## 🚀 Implementation Roadmap

### Phase 1: MVP (4-6 weeks)
**Goal**: Single LLM container serving Rapas Engineering website

- [ ] Week 1-2: Setup Docker + Ollama + FastAPI
- [ ] Week 2-3: Build REST API with authentication
- [ ] Week 3-4: Create JavaScript widget SDK
- [ ] Week 4-5: Integrate with rapas.com.sg
- [ ] Week 5-6: Testing + optimization

**Tech Stack:**
- Backend: Python FastAPI
- LLM: Ollama (Llama 3.1 8B)
- Database: PostgreSQL
- Deployment: Docker Compose
- Frontend: Vanilla JavaScript widget

**Estimated Cost:** $0-50/month (self-hosted)

---

### Phase 2: Multi-Tenant (6-8 weeks)
**Goal**: Support 2-5 customer websites

- [ ] Week 7-8: Multi-tenant database schema
- [ ] Week 9-10: Customer onboarding portal
- [ ] Week 11-12: Per-customer customization
- [ ] Week 13-14: Admin dashboard for management

**Additional Features:**
- API key management
- Usage quotas
- Custom branding
- Knowledge base upload

**Estimated Cost:** $100-300/month (small GPU instance)

---

### Phase 3: Scale & Optimize (8-12 weeks)
**Goal**: Support 10-50 customers, production-ready

- [ ] Week 15-16: Horizontal scaling (Kubernetes)
- [ ] Week 17-18: Caching layer (Redis)
- [ ] Week 19-20: Load balancing + CDN
- [ ] Week 21-22: Advanced analytics
- [ ] Week 23-24: Live agent handoff
- [ ] Week 25-26: Mobile SDK (iOS/Android)

**Infrastructure:**
- Kubernetes cluster
- Redis for caching
- CloudFlare CDN
- Monitoring (Prometheus/Grafana)

**Estimated Cost:** $500-1500/month (production scale)

---

## 💰 Cost Analysis

### Self-Hosted Option

| Component | Monthly Cost | Notes |
|-----------|-------------|-------|
| GPU Instance (g4dn.xlarge) | $380 | 1x NVIDIA T4, can serve 100-200 users |
| Database (PostgreSQL) | $50 | Managed database (AWS RDS) |
| Storage (500GB) | $25 | For logs, models, embeddings |
| Load Balancer | $20 | AWS ALB |
| Monitoring | $25 | Datadog/New Relic basic |
| **Total** | **~$500/month** | Can serve 50-100 customers |

**Per-Customer Cost**: $5-10/month (at 50-100 customers)

### Managed API Option

| Provider | Input Cost | Output Cost | 10K msgs/month | Notes |
|----------|-----------|------------|----------------|-------|
| GPT-4 Turbo | $10/1M tokens | $30/1M tokens | ~$80 | Most accurate |
| Claude 3 Haiku | $0.25/1M | $1.25/1M | ~$3 | Fast & cheap |
| Gemini Pro | $0.50/1M | $1.50/1M | ~$5 | Google's offering |
| Ollama (self) | $0 | $0 | ~$5 | Infrastructure cost only |

**Recommendation**: Hybrid approach saves 60-80% costs

---

### Pricing Model for Customers

**Option A: Subscription Tiers**

| Tier | Messages/Month | Features | Price |
|------|----------------|----------|-------|
| Basic | 1,000 | Basic chatbot, 1 website | $29/month |
| Professional | 10,000 | Advanced AI, 3 websites, Analytics | $99/month |
| Enterprise | 100,000 | Custom models, Unlimited sites, Priority | $499/month |
| Enterprise Plus | Unlimited | Dedicated resources, White-label | Custom |

**Option B: Pay-As-You-Go**

- $0.01 per message (Ollama backend)
- $0.05 per message (GPT-4 backend)
- Volume discounts at 10K, 50K, 100K messages

---

## 🔐 Security Considerations

### 1. **Authentication & Authorization**
```python
# API Key authentication
def verify_api_key(api_key: str):
    customer = db.query(Customer).filter(
        Customer.api_key == api_key,
        Customer.is_active == True
    ).first()
    
    if not customer:
        raise HTTPException(401, "Invalid API key")
    
    if customer.usage_this_month >= customer.monthly_quota:
        raise HTTPException(429, "Quota exceeded")
    
    return customer
```

### 2. **Data Isolation**
- Row-level security in PostgreSQL
- Separate S3 buckets per customer
- Encrypted data at rest

### 3. **Rate Limiting**
```python
# Per customer rate limiting
limiter = RateLimiter(
    key="customer_id",
    rate="60/minute",  # 60 requests per minute
    storage=RedisStorage(redis_client)
)
```

### 4. **Content Filtering**
- Block inappropriate content
- PII detection (emails, phone numbers, SSN)
- Profanity filter
- Prompt injection prevention

### 5. **Compliance**
- GDPR: Right to delete conversations
- Data retention policies
- Audit logs
- SOC 2 compliance (for enterprise)

---

## 📈 Scalability Strategy

### Horizontal Scaling

```yaml
# Kubernetes deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-service
spec:
  replicas: 5  # Start with 5 pods
  selector:
    matchLabels:
      app: llm-service
  template:
    metadata:
      labels:
        app: llm-service
    spec:
      containers:
      - name: llm-api
        image: llm-service:v1.0
        resources:
          requests:
            memory: "8Gi"
            cpu: "4"
            nvidia.com/gpu: 1
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: url
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: llm-service-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: llm-service
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### Geographic Distribution
- Deploy in multiple regions (AWS Singapore, Tokyo, Sydney)
- Route requests to nearest region
- Reduce latency for APAC customers

---

## 🎯 Success Metrics

### Technical KPIs
- Response time: < 2 seconds (95th percentile)
- Uptime: 99.9% availability
- Accuracy: > 85% helpful responses
- Token efficiency: < 300 tokens average per response

### Business KPIs
- Customer acquisition: 10 new customers/month
- Retention rate: > 90%
- MRR growth: 20% monthly
- Customer satisfaction: > 4.5/5 average

---

## 🚧 Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| LLM hallucinations | High | RAG + fact-checking + human review |
| Scaling costs exceed revenue | High | Hybrid approach + caching + optimization |
| Customer data breach | Critical | Encryption + isolation + regular audits |
| Model latency issues | Medium | Multiple model tiers + caching |
| Vendor lock-in (OpenAI) | Medium | Multi-provider support + open-source fallback |
| Customer churn | Medium | Excellent support + analytics + value demonstration |

---

## 🎬 Getting Started (Next Steps)

### Immediate Actions (This Week)

1. **Decision**: Self-hosted vs Managed API?
   - Self-hosted: More control, lower long-term cost
   - Managed: Faster setup, less maintenance

2. **Setup Development Environment**
   ```bash
   # Clone starter template
   git clone https://github.com/yourusername/llm-chatbot-service
   cd llm-chatbot-service
   
   # Install dependencies
   docker-compose up -d
   
   # Test local Ollama
   curl http://localhost:11434/api/chat -d '{
     "model": "llama3.1",
     "messages": [{"role": "user", "content": "Hello"}]
   }'
   ```

3. **Create MVP Specification**
   - Define exact features for Rapas Engineering chatbot
   - Design customer context schema
   - Plan integration points

4. **Budget Approval**
   - Phase 1 MVP: $0-50/month (self-hosted)
   - Phase 2 Multi-tenant: $100-300/month
   - Phase 3 Scale: $500-1500/month

### Questions to Answer

1. **Self-hosted or Cloud API?**
   - Do you have GPU infrastructure?
   - What's your budget?
   - Technical expertise available?

2. **Which customers first?**
   - Start with Rapas Engineering only?
   - Or 2-3 pilot customers?

3. **Features priority?**
   - Must-have: Basic chat, context awareness
   - Nice-to-have: Voice input, file upload, live handoff

4. **Timeline?**
   - MVP in 4-6 weeks?
   - Multi-tenant in 3 months?
   - Production in 6 months?

---

## 📚 Technical Resources

### Recommended Stack

**Backend:**
- FastAPI (Python) - Modern, fast API framework
- Ollama - Open-source LLM runtime
- LangChain - LLM orchestration
- pgvector - PostgreSQL extension for embeddings

**Frontend:**
- Vanilla JavaScript SDK (lightweight)
- React dashboard for admin
- TailwindCSS for styling

**Infrastructure:**
- Docker + Docker Compose (development)
- Kubernetes (production)
- Redis (caching)
- PostgreSQL (database)
- CloudFlare (CDN)

### Starter Code Snippets

**1. Basic LLM API Endpoint**
```python
# main.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import ollama

app = FastAPI()

class ChatRequest(BaseModel):
    customer_id: str
    message: str
    session_id: str

class ChatResponse(BaseModel):
    response: str
    confidence: float
    metadata: dict

@app.post("/api/v1/chat/message", response_model=ChatResponse)
async def chat(request: ChatRequest, customer=Depends(verify_customer)):
    # Get customer context
    context = get_customer_context(request.customer_id)
    
    # Build system prompt
    system_prompt = f"""You are {context['company_name']}'s AI assistant.
    {context['system_prompt']}
    
    Services: {', '.join(context['services'])}
    Contact: {context['contact']['phone']}
    """
    
    # Call LLM
    response = ollama.chat(
        model='llama3.1',
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': request.message}
        ]
    )
    
    # Log to database
    log_conversation(request, response)
    
    return ChatResponse(
        response=response['message']['content'],
        confidence=0.9,
        metadata={'model': 'llama3.1', 'tokens': response['eval_count']}
    )
```

**2. JavaScript Widget SDK**
```javascript
// widget.js - Customer embeds this
(function() {
  const LLMAPI = {
    endpoint: 'https://llm-api.rapas.com',
    customerId: document.currentScript.dataset.customerId,
    apiKey: document.currentScript.dataset.apiKey,
    
    async sendMessage(message) {
      const response = await fetch(`${this.endpoint}/api/v1/chat/message`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.apiKey}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          customer_id: this.customerId,
          session_id: this.getSessionId(),
          message: message
        })
      });
      
      return await response.json();
    },
    
    getSessionId() {
      let sessionId = localStorage.getItem('llm_session_id');
      if (!sessionId) {
        sessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('llm_session_id', sessionId);
      }
      return sessionId;
    },
    
    createWidget() {
      // Create floating chat button
      const button = document.createElement('div');
      button.id = 'llm-chat-button';
      button.innerHTML = '💬';
      button.style.cssText = `
        position: fixed; bottom: 20px; right: 20px; 
        width: 60px; height: 60px; border-radius: 50%;
        background: #00c1d4; color: white;
        display: flex; align-items: center; justify-content: center;
        font-size: 28px; cursor: pointer; z-index: 9999;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      `;
      
      // Create chat window (hidden initially)
      const chatWindow = document.createElement('div');
      chatWindow.id = 'llm-chat-window';
      chatWindow.innerHTML = this.getChatWindowHTML();
      chatWindow.style.display = 'none';
      
      document.body.appendChild(button);
      document.body.appendChild(chatWindow);
      
      this.attachEventListeners();
    },
    
    getChatWindowHTML() {
      return `
        <div style="position:fixed; bottom:90px; right:20px; width:380px; height:600px; 
                    background:white; border-radius:16px; box-shadow:0 8px 32px rgba(0,0,0,0.2);
                    display:flex; flex-direction:column; z-index:9999;">
          <div style="background:#00c1d4; color:white; padding:16px; border-radius:16px 16px 0 0;">
            <h3 style="margin:0;">AI Assistant</h3>
            <button id="llm-close-btn" style="position:absolute; top:16px; right:16px; 
                    background:transparent; border:none; color:white; font-size:24px; cursor:pointer;">×</button>
          </div>
          <div id="llm-messages" style="flex:1; overflow-y:auto; padding:16px;"></div>
          <div style="padding:16px; border-top:1px solid #eee;">
            <input id="llm-input" type="text" placeholder="Type your message..." 
                   style="width:100%; padding:12px; border:1px solid #ddd; border-radius:8px;">
          </div>
        </div>
      `;
    },
    
    attachEventListeners() {
      document.getElementById('llm-chat-button').onclick = () => {
        document.getElementById('llm-chat-window').style.display = 'flex';
      };
      
      document.getElementById('llm-close-btn').onclick = () => {
        document.getElementById('llm-chat-window').style.display = 'none';
      };
      
      document.getElementById('llm-input').onkeypress = async (e) => {
        if (e.key === 'Enter') {
          const input = e.target;
          const message = input.value.trim();
          if (!message) return;
          
          this.addMessage('user', message);
          input.value = '';
          
          const response = await this.sendMessage(message);
          this.addMessage('assistant', response.response);
        }
      };
    },
    
    addMessage(role, content) {
      const messagesDiv = document.getElementById('llm-messages');
      const messageDiv = document.createElement('div');
      messageDiv.style.cssText = `
        margin-bottom: 12px; 
        padding: 12px; 
        border-radius: 8px;
        ${role === 'user' ? 'background:#e3f2fd; text-align:right;' : 'background:#f5f5f5;'}
      `;
      messageDiv.textContent = content;
      messagesDiv.appendChild(messageDiv);
      messagesDiv.scrollTop = messagesDiv.scrollHeight;
    },
    
    init() {
      this.createWidget();
      console.log('LLM Chat Widget initialized for customer:', this.customerId);
    }
  };
  
  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => LLMAPI.init());
  } else {
    LLMAPI.init();
  }
})();
```

---

## 🎉 Conclusion

**This architecture enables:**
- ✅ One centralized LLM service
- ✅ Multiple customer websites (multi-tenant)
- ✅ Cost-effective scaling (shared infrastructure)
- ✅ Easy customization per customer
- ✅ Production-ready security & compliance
- ✅ Sustainable business model

**Next Decision Points:**
1. Approve MVP budget ($0-50/month)
2. Choose self-hosted vs managed API
3. Set timeline for Phase 1 (4-6 weeks)
4. Identify pilot customers (Rapas + 2-3 others?)

**Ready to Start?** Let's build the MVP! 🚀

---

**Questions? Let's discuss:**
- Technical architecture choices
- Cost optimization strategies
- Customer onboarding process
- Feature prioritization

I'm ready to help implement this! 💪
