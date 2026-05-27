# Quick Start: Centralized LLM Chatbot MVP
## Get Your AI Chatbot Running in 1 Day

**Goal**: Replace current keyword-matching chatbot with intelligent AI

---

## 🎯 MVP Features (Phase 1)

- ✅ Intelligent AI responses (not keyword matching)
- ✅ Context-aware conversations
- ✅ Rapas Engineering knowledge base
- ✅ Mobile responsive chat widget
- ✅ Conversation history
- ✅ Admin dashboard (basic)

**Timeline**: 4-6 weeks  
**Cost**: $0-50/month (self-hosted) or $100-200/month (managed API)

---

## Option 1: Self-Hosted (Recommended for Cost)

### Prerequisites
```bash
# Minimum requirements:
- Linux server (Ubuntu 22.04)
- 16GB RAM
- 4 CPU cores
- NVIDIA GPU (optional but recommended)
- Docker & Docker Compose
```

### Installation Steps

**1. Install Ollama**
```bash
# Install Ollama (LLM runtime)
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model (choose one):
ollama pull llama3.1:8b          # 8B model, 4.7GB, good quality
ollama pull mistral:7b           # 7B model, 4.1GB, fast
ollama pull phi3:mini            # 3.8B model, 2.3GB, very fast (for testing)

# Test it works
ollama run llama3.1:8b "Hello, introduce yourself"
```

**2. Clone Starter Template**
```bash
# Create project directory
mkdir llm-chatbot-service
cd llm-chatbot-service

# Create project structure
mkdir -p {api,frontend,database,docker}
```

**3. Create Docker Compose**
```yaml
# docker-compose.yml
version: '3.8'

services:
  # PostgreSQL Database
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: llm_chatbot
      POSTGRES_USER: llmuser
      POSTGRES_PASSWORD: changeme123
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-QUERY", "pg_isready", "-U", "llmuser"]
      interval: 5s
      timeout: 5s
      retries: 5

  # FastAPI Backend
  api:
    build: ./api
    environment:
      DATABASE_URL: postgresql://llmuser:changeme123@postgres:5432/llm_chatbot
      OLLAMA_URL: http://host.docker.internal:11434
      API_SECRET_KEY: your-secret-key-change-this
    ports:
      - "8001:8000"
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./api:/app
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload

  # Nginx (serves widget.js + frontend)
  nginx:
    image: nginx:alpine
    ports:
      - "8080:80"
    volumes:
      - ./frontend:/usr/share/nginx/html
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - api

volumes:
  postgres_data:
```

**4. Create FastAPI Backend**
```python
# api/main.py
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import ollama
import psycopg2
from datetime import datetime
import os

app = FastAPI(title="LLM Chatbot API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection
def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

# Initialize database
@app.on_event("startup")
async def startup():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id VARCHAR(50) PRIMARY KEY,
            api_key VARCHAR(100) UNIQUE,
            company_name VARCHAR(255),
            system_prompt TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id SERIAL PRIMARY KEY,
            customer_id VARCHAR(50),
            session_id VARCHAR(100),
            user_message TEXT,
            ai_response TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        
        -- Insert Rapas Engineering as first customer
        INSERT INTO customers (customer_id, api_key, company_name, system_prompt)
        VALUES (
            'rapas-eng-001',
            'sk_live_rapas_abc123xyz',
            'Rapas Engineering Services Pte Ltd',
            'You are a helpful marine engineering expert representing Rapas Engineering. You have 18+ years of experience in APAC marine services. Services include: Piping & Fabrication, Steel Works, Insulation, Engine Parts Reconditioning, Electrical & Instrumentation, Scaffolding. Contact: +65 6710 7052, sales@rapas.com.sg. Always be professional and helpful.'
        ) ON CONFLICT DO NOTHING;
    """)
    conn.commit()
    cur.close()
    conn.close()

class ChatRequest(BaseModel):
    customer_id: str
    session_id: str
    message: str

class ChatResponse(BaseModel):
    response: str
    confidence: float
    metadata: dict

@app.post("/api/v1/chat/message", response_model=ChatResponse)
async def chat(request: ChatRequest, authorization: str = Header(None)):
    # Verify API key
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization")
    
    api_key = authorization.replace("Bearer ", "")
    
    # Get customer from database
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT customer_id, system_prompt FROM customers WHERE api_key = %s",
        (api_key,)
    )
    customer = cur.fetchone()
    
    if not customer:
        raise HTTPException(401, "Invalid API key")
    
    customer_id, system_prompt = customer
    
    # Get conversation history (last 10 messages)
    cur.execute("""
        SELECT user_message, ai_response 
        FROM conversations 
        WHERE customer_id = %s AND session_id = %s
        ORDER BY created_at DESC
        LIMIT 10
    """, (customer_id, request.session_id))
    
    history = cur.fetchall()
    
    # Build messages for LLM
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add history (reverse order)
    for user_msg, ai_msg in reversed(history):
        messages.append({"role": "user", "content": user_msg})
        messages.append({"role": "assistant", "content": ai_msg})
    
    # Add current message
    messages.append({"role": "user", "content": request.message})
    
    # Call Ollama
    try:
        response = ollama.chat(
            model='llama3.1:8b',
            messages=messages
        )
        
        ai_response = response['message']['content']
        
        # Save to database
        cur.execute("""
            INSERT INTO conversations (customer_id, session_id, user_message, ai_response)
            VALUES (%s, %s, %s, %s)
        """, (customer_id, request.session_id, request.message, ai_response))
        
        conn.commit()
        
        return ChatResponse(
            response=ai_response,
            confidence=0.9,
            metadata={
                "model": "llama3.1:8b",
                "tokens": response.get('eval_count', 0)
            }
        )
        
    except Exception as e:
        raise HTTPException(500, f"LLM error: {str(e)}")
    
    finally:
        cur.close()
        conn.close()

@app.get("/api/v1/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/")
async def root():
    return {"message": "LLM Chatbot API v1.0", "docs": "/docs"}
```

**5. Create API Dependencies**
```txt
# api/requirements.txt
fastapi==0.109.0
uvicorn[standard]==0.27.0
python-multipart==0.0.9
psycopg2-binary==2.9.9
ollama==0.1.6
pydantic==2.5.3
python-dotenv==1.0.1
```

**6. Create Dockerfile for API**
```dockerfile
# api/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port
EXPOSE 8000

# Start application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**7. Create Frontend Widget**
```javascript
// frontend/widget.js
(function() {
  const LLM_CONFIG = {
    apiUrl: window.location.hostname === 'localhost' 
      ? 'http://localhost:8001' 
      : 'https://llm-api.rapas.com',
    customerId: document.currentScript?.dataset.customerId || 'rapas-eng-001',
    apiKey: document.currentScript?.dataset.apiKey || 'sk_live_rapas_abc123xyz'
  };

  class LLMChatbot {
    constructor() {
      this.sessionId = this.getSessionId();
      this.isOpen = false;
      this.messages = [];
      this.init();
    }

    getSessionId() {
      let sessionId = localStorage.getItem('llm_session_id');
      if (!sessionId) {
        sessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('llm_session_id', sessionId);
      }
      return sessionId;
    }

    async sendMessage(message) {
      try {
        const response = await fetch(`${LLM_CONFIG.apiUrl}/api/v1/chat/message`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${LLM_CONFIG.apiKey}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            customer_id: LLM_CONFIG.customerId,
            session_id: this.sessionId,
            message: message
          })
        });

        if (!response.ok) {
          throw new Error(`API error: ${response.status}`);
        }

        const data = await response.json();
        return data.response;
      } catch (error) {
        console.error('Chat error:', error);
        return "Sorry, I'm having trouble connecting. Please try again or contact us directly at +65 6710 7052.";
      }
    }

    createWidget() {
      // Chat button
      const button = document.createElement('div');
      button.id = 'llm-chat-button';
      button.innerHTML = '💬';
      button.style.cssText = `
        position: fixed;
        bottom: 24px;
        right: 24px;
        width: 64px;
        height: 64px;
        border-radius: 50%;
        background: linear-gradient(135deg, #00c1d4, #0a8a96);
        color: white;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 32px;
        cursor: pointer;
        z-index: 9999;
        box-shadow: 0 6px 24px rgba(0,193,212,0.4);
        transition: transform 0.3s ease;
      `;

      button.addEventListener('mouseenter', () => {
        button.style.transform = 'scale(1.1)';
      });

      button.addEventListener('mouseleave', () => {
        button.style.transform = 'scale(1)';
      });

      button.addEventListener('click', () => this.toggleChat());

      // Chat window
      const chatWindow = document.createElement('div');
      chatWindow.id = 'llm-chat-window';
      chatWindow.style.cssText = `
        position: fixed;
        bottom: 100px;
        right: 24px;
        width: 400px;
        height: 600px;
        background: white;
        border-radius: 16px;
        box-shadow: 0 12px 48px rgba(0,0,0,0.2);
        display: none;
        flex-direction: column;
        z-index: 9999;
        overflow: hidden;
      `;

      chatWindow.innerHTML = `
        <div style="background: linear-gradient(135deg, #00c1d4, #0a8a96); color: white; padding: 20px; display: flex; justify-content: space-between; align-items: center;">
          <div>
            <h3 style="margin: 0; font-size: 18px;">AI Assistant</h3>
            <p style="margin: 4px 0 0 0; font-size: 12px; opacity: 0.9;">Powered by Rapas Engineering</p>
          </div>
          <button id="llm-close-btn" style="background: transparent; border: none; color: white; font-size: 28px; cursor: pointer; padding: 0; width: 32px; height: 32px;">×</button>
        </div>
        <div id="llm-messages" style="flex: 1; overflow-y: auto; padding: 20px; background: #f7f9fb;"></div>
        <div style="padding: 16px; background: white; border-top: 1px solid #e5e7eb;">
          <div style="display: flex; gap: 8px;">
            <input id="llm-input" type="text" placeholder="Type your message..." 
                   style="flex: 1; padding: 12px 16px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px; outline: none;">
            <button id="llm-send-btn" style="padding: 12px 20px; background: #00c1d4; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;">Send</button>
          </div>
          <div id="llm-typing" style="display: none; margin-top: 8px; font-size: 12px; color: #6b7280;">
            <span style="animation: pulse 1.5s ease-in-out infinite;">AI is typing...</span>
          </div>
        </div>
      `;

      document.body.appendChild(button);
      document.body.appendChild(chatWindow);

      // Add welcome message
      this.addMessage('assistant', 'Hello! 👋 I\'m the Rapas Engineering AI assistant. I can help you with information about our marine engineering services. How can I assist you today?');

      this.attachEventListeners();
    }

    attachEventListeners() {
      document.getElementById('llm-close-btn').addEventListener('click', () => this.toggleChat());
      
      const input = document.getElementById('llm-input');
      const sendBtn = document.getElementById('llm-send-btn');

      const handleSend = () => this.handleUserMessage();
      
      sendBtn.addEventListener('click', handleSend);
      input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSend();
      });
    }

    async handleUserMessage() {
      const input = document.getElementById('llm-input');
      const message = input.value.trim();

      if (!message) return;

      // Add user message
      this.addMessage('user', message);
      input.value = '';

      // Show typing indicator
      document.getElementById('llm-typing').style.display = 'block';

      // Get AI response
      const response = await this.sendMessage(message);

      // Hide typing indicator
      document.getElementById('llm-typing').style.display = 'none';

      // Add AI response
      this.addMessage('assistant', response);
    }

    addMessage(role, content) {
      const messagesDiv = document.getElementById('llm-messages');
      
      const messageDiv = document.createElement('div');
      messageDiv.style.cssText = `
        margin-bottom: 16px;
        display: flex;
        gap: 12px;
        ${role === 'user' ? 'flex-direction: row-reverse;' : ''}
      `;

      const avatar = document.createElement('div');
      avatar.style.cssText = `
        width: 36px;
        height: 36px;
        border-radius: 50%;
        ${role === 'user' 
          ? 'background: #00c1d4;' 
          : 'background: linear-gradient(135deg, #00c1d4, #0a8a96);'}
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
        flex-shrink: 0;
      `;
      avatar.textContent = role === 'user' ? '👤' : '🤖';

      const bubble = document.createElement('div');
      bubble.style.cssText = `
        padding: 12px 16px;
        border-radius: 12px;
        max-width: 70%;
        ${role === 'user' 
          ? 'background: #00c1d4; color: white; border-bottom-right-radius: 4px;' 
          : 'background: white; color: #1f2937; border-bottom-left-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);'}
        font-size: 14px;
        line-height: 1.5;
        word-wrap: break-word;
      `;
      bubble.textContent = content;

      messageDiv.appendChild(avatar);
      messageDiv.appendChild(bubble);
      messagesDiv.appendChild(messageDiv);

      // Scroll to bottom
      messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    toggleChat() {
      this.isOpen = !this.isOpen;
      const chatWindow = document.getElementById('llm-chat-window');
      chatWindow.style.display = this.isOpen ? 'flex' : 'none';

      if (this.isOpen) {
        document.getElementById('llm-input').focus();
      }
    }

    init() {
      this.createWidget();
      console.log('✅ LLM Chatbot initialized for:', LLM_CONFIG.customerId);
    }
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => new LLMChatbot());
  } else {
    new LLMChatbot();
  }

  // Add pulse animation
  const style = document.createElement('style');
  style.textContent = `
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.5; }
    }
  `;
  document.head.appendChild(style);
})();
```

**8. Start Everything**
```bash
# Start services
docker-compose up -d

# Check logs
docker-compose logs -f api

# Test API health
curl http://localhost:8001/api/v1/health

# Access widget at:
# http://localhost:8080/widget.js
```

**9. Integrate into Rapas Website**

Replace current chatbot code in `src/index.html`:

```html
<!-- OLD (remove handleAIResponse function) -->
<script>
  function handleAIResponse(userMessage) {
    // ... old hardcoded logic
  }
</script>

<!-- NEW (add at end of body, before </body>) -->
<script src="http://localhost:8080/widget.js" 
        data-customer-id="rapas-eng-001" 
        data-api-key="sk_live_rapas_abc123xyz"></script>
```

---

## Option 2: Managed API (Faster Setup)

### Using OpenAI GPT-4

**1. Get API Key**
- Sign up at https://platform.openai.com/
- Create API key
- Cost: ~$0.01 per message (GPT-4 Turbo)

**2. Simple Implementation**
```javascript
// No backend needed, call OpenAI directly from frontend
async function sendToGPT4(message) {
  const response = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer sk-YOUR-OPENAI-API-KEY',
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      model: 'gpt-4-turbo-preview',
      messages: [
        {
          role: 'system',
          content: 'You are a helpful marine engineering expert for Rapas Engineering with 18+ years experience. Services: Piping, Steel Works, Insulation, Engine Reconditioning, Electrical, Scaffolding. Contact: +65 6710 7052, sales@rapas.com.sg'
        },
        {
          role: 'user',
          content: message
        }
      ]
    })
  });
  
  const data = await response.json();
  return data.choices[0].message.content;
}
```

**⚠️ Warning**: Don't expose API keys in frontend! Use a proxy backend.

---

## Testing Your Chatbot

### Test Conversations

```bash
# Test 1: Service inquiry
curl -X POST http://localhost:8001/api/v1/chat/message \
  -H "Authorization: Bearer sk_live_rapas_abc123xyz" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "rapas-eng-001",
    "session_id": "test123",
    "message": "What marine engineering services do you offer?"
  }'

# Test 2: Contact information
curl -X POST http://localhost:8001/api/v1/chat/message \
  -H "Authorization: Bearer sk_live_rapas_abc123xyz" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "rapas-eng-001",
    "session_id": "test123",
    "message": "How can I contact your team?"
  }'

# Test 3: Context retention
curl -X POST http://localhost:8001/api/v1/chat/message \
  -H "Authorization: Bearer sk_live_rapas_abc123xyz" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "rapas-eng-001",
    "session_id": "test123",
    "message": "What about pricing for piping services?"
  }'
```

---

## Deployment to Production

### Option A: AWS EC2
```bash
# Launch t3.large instance (8GB RAM)
# Install Docker & Ollama
# Clone your project
# Update docker-compose.yml with production settings
# Setup domain & SSL (Let's Encrypt)
```

### Option B: DigitalOcean Droplet
```bash
# Create $24/month droplet (4GB RAM)
# One-click Docker image
# Upload project files
# Run docker-compose up -d
```

### Option C: Railway / Render
- Push to GitHub
- Connect Railway/Render
- Auto-deploy on push
- Built-in SSL + domains

---

## Next Steps (After MVP Works)

1. **Add More Knowledge**
   - Upload PDFs about your services
   - Add FAQ database
   - Scrape your website content

2. **Improve Responses**
   - Add RAG (Retrieval Augmented Generation)
   - Fine-tune model on your data
   - Add response templates

3. **Analytics**
   - Track popular questions
   - Measure satisfaction
   - Identify gaps in knowledge

4. **Multi-Customer**
   - Onboard 2-3 pilot customers
   - Test multi-tenancy
   - Refine pricing model

---

## Troubleshooting

### Ollama not responding
```bash
# Check if Ollama is running
ps aux | grep ollama

# Restart Ollama
ollama serve

# Check logs
journalctl -u ollama -f
```

### Database connection issues
```bash
# Check if PostgreSQL is running
docker-compose ps postgres

# Connect to database
docker-compose exec postgres psql -U llmuser -d llm_chatbot

# View tables
\dt

# Query customers
SELECT * FROM customers;
```

### API errors
```bash
# Check API logs
docker-compose logs -f api

# Test health endpoint
curl http://localhost:8001/api/v1/health

# Restart API
docker-compose restart api
```

---

## Cost Summary

### Self-Hosted (MVP)
- **Development**: Free (use local machine)
- **Production**: $20-50/month (VPS)
- **Scaling**: Add $50/month per 100 customers

### Managed API (MVP)
- **Development**: $0 (free tier)
- **Production**: $100-200/month
- **Scaling**: Pay per usage (~$0.01/message)

---

## Success Checklist

- [ ] Ollama installed and model pulled
- [ ] Docker Compose running all services
- [ ] API health check returns 200
- [ ] Widget loads on test page
- [ ] Can send/receive messages
- [ ] Conversations saved to database
- [ ] Response quality is good
- [ ] Mobile responsive
- [ ] Ready for Rapas website integration

---

**Ready to start? Choose your path:**

1. **Self-Hosted MVP**: Follow steps 1-9 above → 4-6 weeks
2. **Managed API MVP**: Use OpenAI + simple frontend → 1-2 weeks
3. **Hybrid**: Start with managed, migrate to self-hosted later

**Questions?** Let's implement this together! 🚀
