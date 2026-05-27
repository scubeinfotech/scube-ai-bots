# WhatsApp Connector Implementation - Step 1

## Overview

This document describes the WhatsApp Connector implementation for the centralized LLM platform. It extends the existing chatbot to support WhatsApp Business API while reusing the current RAG/vector/LLM stack without any modifications to existing logic or data storage.

## Architecture

```
WhatsApp Business API
    ↓ (Webhook)
WhatsApp Connector
    ├─ Webhook Handler (verify & receive messages)
    ├─ Message Broker (RabbitMQ/Kafka/In-Memory)
    ├─ WhatsApp Service (business logic)
    ├─ Chat Service Adapter (reuse existing LLM)
    ├─ Response Formatter (short-form replies)
    └─ WhatsApp API Client (send responses)
```

## Components

### 1. WhatsApp Adapter (`app/adapters/whatsapp.py`)

**Purpose**: Handles all communication with WhatsApp Business API

**Key Classes**:
- `WhatsAppProvider` (abstract base)
- `CloudAPIWhatsAppProvider` - Meta's official Cloud API implementation

**Features**:
- Send text messages
- Send interactive messages (buttons, lists)
- Template support
- Async/await compatible
- Error handling and retry logic
- Latency tracking

**Usage**:
```python
from app.adapters.whatsapp import get_whatsapp_provider

provider = get_whatsapp_provider(
    provider_type="cloud_api",
    phone_number_id="1234567890",
    business_account_id="abcdef",
    access_token="your_token",
    api_version="v18.0"
)

result = await provider.send_message(
    recipient_phone="+1234567890",
    message_text="Hello! How can I help you?"
)
```

### 2. Message Broker (`app/adapters/message_broker.py`)

**Purpose**: Queue and process WhatsApp messages asynchronously

**Supported Brokers**:
- **RabbitMQ**: `RabbitMQBroker` (requires `aio_pika`)
- **Kafka**: `KafkaBroker` (requires `aiokafka`)
- **In-Memory**: `InMemoryBroker` (default, no dependencies)

**Features**:
- Async publish/subscribe
- Topic-based routing
- Priority levels (low, normal, high)
- Graceful degradation (sync fallback if broker unavailable)

**Usage**:
```python
from app.adapters.message_broker import get_message_broker

# Development/testing (no external deps)
broker = get_message_broker("in_memory")

# Or with RabbitMQ
broker = get_message_broker(
    broker_type="rabbitmq",
    host="localhost",
    port=5672,
    username="guest",
    password="guest"
)

# Or with Kafka
broker = get_message_broker(
    broker_type="kafka",
    bootstrap_servers="localhost:9092"
)

await broker.connect()
await broker.publish("whatsapp_messages", {"content": "..."}, priority="high")
await broker.disconnect()
```

### 3. Response Formatter (`app/services/response_formatter.py`)

**Purpose**: Formats long-form LLM responses for WhatsApp constraints

**Key Limits**:
- Max message length: 4,096 characters (WhatsApp technical limit)
- Short-form target: 300 characters
- Medium-form target: 800 characters

**Features**:
- Intelligent truncation (respects sentence boundaries)
- HTML/markdown cleaning
- Transaction response templates
- Interactive message creation (buttons, lists)

**Usage**:
```python
from app.services.response_formatter import ResponseFormatter

formatter = ResponseFormatter(target_length=300)

# Format regular response
result = formatter.format_for_whatsapp(
    response="Your long LLM response here...",
    include_metadata=True
)
formatted_text = result["formatted_text"]

# Format transaction response
booking_response = formatter.format_transaction_response(
    action="booking_confirmation",
    status="success",
    details={"date": "2026-04-20", "time": "2PM"}
)

# Create interactive buttons
button_payload = formatter.create_interactive_buttons(
    title="What would you like to do?",
    buttons=[
        {"text": "Book a Demo", "id": "book_demo"},
        {"text": "Get Pricing", "id": "get_pricing"},
        {"text": "Contact Us", "id": "contact"}
    ]
)
```

### 4. WhatsApp Models (`app/models/whatsapp.py`)

**Database Tables**:

1. **whatsapp_contacts**: Represents users on WhatsApp
   - phone_number (E.164 format)
   - contact_name, profile_picture_url
   - first_message_at, last_message_at
   - total_messages count
   - opted_out (GDPR compliance)

2. **whatsapp_messages**: Incoming and outgoing messages
   - direction (inbound/outbound)
   - message_type (text, image, video, document, interactive)
   - delivery_status (pending, sent, delivered, read, failed)
   - Reference to chat_session_id (links to LLM chat)
   - processed flag

3. **whatsapp_sessions**: Conversation context
   - tenant_id, contact_id
   - llm_session_id (links to existing chat sessions)
   - status (active, paused, closed)
   - current_intent (booking, support, etc)
   - booking_flow_state and booking_data (for multi-step flows)

4. **whatsapp_configurations**: Per-tenant WhatsApp settings
   - API credentials (phone_number_id, business_account_id, access_token)
   - webhook_url, webhook_verify_token
   - Feature flags (booking_flow, interactive_responses, auto_response)
   - response_timeout_seconds
   - short_response_mode

5. **whatsapp_metrics**: Usage and performance metrics
   - messages_received, messages_sent, messages_failed
   - avg_response_time_ms, avg_llm_latency_ms
   - unique_contacts, conversations_started/completed
   - booking_attempts, booking_completions

### 5. WhatsApp Service (`app/services/whatsapp_service.py`)

**Purpose**: Core business logic orchestrating all components

**Key Methods**:

- `process_incoming_webhook(tenant_id, webhook_payload)` - Entry point for webhook messages
- `_process_single_message(tenant_id, message_payload)` - Process individual message
- `_process_message_to_llm(...)` - Forward to LLM, format response, send back
- `_send_whatsapp_message(...)` - Send via WhatsApp API
- `_get_or_create_contact(...)` - Contact management
- `_get_or_create_whatsapp_session(...)` - Session management
- `verify_webhook(challenge, verify_token, tenant_id)` - Webhook verification

**Flow**:
```
Incoming Webhook
    ↓
Extract message from WhatsApp payload
    ↓
Create/update WhatsAppContact
    ↓
Store WhatsAppMessage (inbound)
    ↓
Publish to message broker (async)
    ↓
Process through LLM (via ChatService - REUSES EXISTING RAG/VECTOR STACK)
    ↓
Format response (ResponseFormatter)
    ↓
Send via WhatsApp API
    ↓
Store WhatsAppMessage (outbound)
    ↓
Update WhatsAppSession
```

### 6. WhatsApp API Endpoints (`app/api/whatsapp.py`)

**Endpoints**:

1. **POST `/api/whatsapp/configure/{tenant_id}`** - Configure WhatsApp
   ```json
   {
     "phone_number_id": "1234567890",
     "business_account_id": "abcdef",
     "access_token": "your_token",
     "webhook_url": "https://yourdomain.com/api/whatsapp/webhook/tenant_id",
     "webhook_verify_token": "random_token",
     "enable_booking_flow": false,
     "enable_interactive_responses": true
   }
   ```

2. **GET `/api/whatsapp/configure/{tenant_id}`** - Get configuration

3. **DELETE `/api/whatsapp/configure/{tenant_id}`** - Disable WhatsApp

4. **GET `/api/whatsapp/webhook/{tenant_id}`** - Webhook verification
   - WhatsApp calls this with hub_mode, hub_challenge, hub_verify_token
   - Returns challenge if valid

5. **POST `/api/whatsapp/webhook/{tenant_id}`** - Receive messages
   - Called by WhatsApp with message webhooks
   - Processes and forwards to LLM

6. **GET `/api/whatsapp/health/{tenant_id}`** - Health check
   - Returns configuration status and features

## Setup & Configuration

### Prerequisites

1. WhatsApp Business Account (https://developers.facebook.com)
2. Verified Phone Number on WhatsApp Business Platform
3. API Access Token
4. Webhook URL (public HTTPS endpoint)

### Installation

1. **Install Dependencies** (optional message brokers):
   ```bash
   # For RabbitMQ support
   pip install aio-pika==9.0.5

   # For Kafka support
   pip install aiokafka==0.8.1
   ```

2. **Create Database Tables**:
   - WhatsApp models are automatically created when app starts
   - SQLAlchemy will create tables via `Base.metadata.create_all()`

### Configuration

1. **Configure WhatsApp for Tenant**:
   ```bash
   curl -X POST http://localhost:8000/api/whatsapp/configure/tenant_id \
     -H "Content-Type: application/json" \
     -d '{
       "phone_number_id": "1234567890",
       "business_account_id": "abcdef",
       "access_token": "EAABSZ...",
       "webhook_url": "https://yourdomain.com/api/whatsapp/webhook/tenant_id",
       "webhook_verify_token": "my_verify_token_12345",
       "enable_interactive_responses": true
     }'
   ```

2. **Set Webhook in WhatsApp Business Platform**:
   - Go to App Dashboard → WhatsApp → Configuration
   - Set Webhook URL: `https://yourdomain.com/api/whatsapp/webhook/{tenant_id}`
   - Set Verify Token: same as configured above
   - Subscribe to: `messages`, `message_status`

3. **Verify Webhook**:
   - WhatsApp will automatically verify by calling webhook with GET
   - Our endpoint returns the challenge if token matches

## Data Storage & RAG Integration

**IMPORTANT**: The WhatsApp connector reuses existing LLM and vector pipeline:

1. **Chat Service**: `WhatsAppService._process_message_to_llm()` calls `ChatService.send_message()`
   - Same LLM providers (Ollama, Groq, etc.)
   - Same RAG via `VectorKnowledgeService`
   - Same guardrails and formatting

2. **Vector Database**: No changes to knowledge base retrieval
   - `WhatsAppMessage` stores reference to `ChatSession`
   - Both inbound and outbound messages link to same session
   - LLM can access conversation history

3. **Data Tables**: 
   - `chat_messages` - All messages (web widget + WhatsApp)
   - `chat_sessions` - Conversation context (web widget + WhatsApp)
   - `whatsapp_messages` - WhatsApp-specific metadata & delivery tracking

## Message Flow Examples

### Example 1: Simple Q&A

```
Customer:  "What's your pricing?"
          ↓ (via WhatsApp webhook)
Backend:  Store in whatsapp_messages (inbound)
          ↓
          Forward to ChatService with chat_session_id
          ↓
          LLM retrieves pricing from vector DB using RAG
          ↓
          Returns: "Our basic plan is $99/month with..."
          ↓
          ResponseFormatter truncates to 300 chars:
          "Our basic plan is $99/month. Advanced features available at higher tiers. Contact us for custom pricing."
          ↓
          Send via WhatsApp API
          ↓
          Store in whatsapp_messages (outbound)

Result:  Customer receives concise, WhatsApp-optimized response
```

### Example 2: Conversation Context

```
Session Start:
- WhatsAppContact created for +1234567890
- WhatsAppSession created
- New ChatSession created and linked

Message 1: "Tell me about your services"
- Both stored in chat_messages and whatsapp_messages
- LLM generates response with RAG context

Message 2: "Can I book a demo?"
- ChatService has access to previous message in same session
- Can reference prior context when generating response

Result: Multi-turn conversation with full context
```

## Testing

### 1. Unit Tests

```python
# Test response formatter
def test_truncate_response():
    formatter = ResponseFormatter(target_length=300)
    long_response = "A" * 500
    result = formatter.format_for_whatsapp(long_response)
    assert len(result["formatted_text"]) <= 300
    assert result["truncated"] == True

# Test message broker
@pytest.mark.asyncio
async def test_message_broker():
    broker = get_message_broker("in_memory")
    await broker.connect()
    result = await broker.publish("test_topic", {"msg": "test"})
    assert result["success"] == True
```

### 2. Integration Test

```bash
# 1. Configure WhatsApp
curl -X POST http://localhost:8000/api/whatsapp/configure/test-tenant \
  -H "Content-Type: application/json" \
  -d '{"phone_number_id":"1234","business_account_id":"abc","access_token":"token",...}'

# 2. Verify webhook
curl "http://localhost:8000/api/whatsapp/webhook/test-tenant?hub_mode=subscribe&hub_challenge=abc123&hub_verify_token=token"

# 3. Send test message
curl -X POST http://localhost:8000/api/whatsapp/webhook/test-tenant \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{
      "changes": [{
        "value": {
          "messages": [{
            "from": "+1234567890",
            "id": "msg123",
            "timestamp": "1234567890",
            "type": "text",
            "text": {"body": "Hello"}
          }]
        }
      }]
    }]
  }'
```

### 3. Manual Testing with WhatsApp

1. Send a message from any WhatsApp account to your business number
2. Check application logs for processing
3. Verify response arrives in WhatsApp
4. Check database for stored messages in `whatsapp_messages` table
5. Verify LLM response stored in `chat_messages` table

## Production Deployment Considerations

### Security

1. **Encrypt Access Token**:
   - Store `access_token` encrypted in database (not plain text as shown)
   - Use environment variables or secrets manager

2. **Webhook Verification**:
   - Always verify webhook_verify_token
   - Validate HTTPS certificates
   - Implement rate limiting

3. **API Keys**:
   - Rotate WhatsApp API tokens regularly
   - Use IP whitelisting if possible

### Performance

1. **Message Broker**:
   - Use RabbitMQ/Kafka in production (not in-memory)
   - Configure appropriate queue depth
   - Monitor broker health

2. **Async Processing**:
   - Process messages async via broker
   - Prevents webhook timeout (WhatsApp expects response in 30s)
   - Queue messages for batch processing if needed

3. **Caching**:
   - Cache tenant configurations
   - Cache LLM responses for common queries
   - Monitor vector DB lookup performance

### Monitoring

1. **Metrics to Track**:
   - Messages received/sent/failed per tenant
   - Response latency (LLM + WhatsApp)
   - Webhook success rate
   - Vector DB query latency

2. **Alerting**:
   - Alert on webhook failures
   - Alert on LLM provider failures
   - Alert on message delivery failures
   - Alert on high response latency

3. **Logging**:
   - Log all webhook events
   - Log LLM responses and formatting
   - Log WhatsApp API calls
   - Log broker publish/subscribe events

## Future Enhancements (Phase 2)

1. **Human-in-the-Loop Dashboard**:
   - Admin dashboard to view conversations
   - Ability to take over conversations
   - Feedback loops to improve LLM responses

2. **Booking Flows**:
   - Multi-step booking via WhatsApp
   - Calendar integration
   - Confirmation emails/SMS

3. **Advanced Interactions**:
   - Media handling (images, documents)
   - Catalog integration
   - Transactional messages

4. **Analytics**:
   - Conversation analytics dashboard
   - Intent detection and tracking
   - Conversion funnel tracking

5. **Multi-Channel**:
   - SMS integration
   - Telegram integration
   - Other messaging platforms

## Troubleshooting

### Webhook not receiving messages

1. Verify webhook URL is publicly accessible
2. Check webhook verify token matches configuration
3. Verify phone number is properly linked
4. Check WhatsApp configuration in Business Platform

### Messages not being sent

1. Check WhatsApp API credentials
2. Verify phone number format (E.164: +country_code...)
3. Check access token hasn't expired
4. Review error messages in application logs

### Slow response times

1. Check LLM provider is responding quickly
2. Monitor vector database queries
3. Check message broker isn't bottlenecked
4. Consider enabling short_response_mode

### Message broker not working

1. If using RabbitMQ, ensure it's running and accessible
2. Check credentials and connection string
3. Review broker logs for errors
4. Fall back to in-memory broker for testing

## Architecture Decisions

1. **In-Memory Broker as Default**:
   - No external dependencies required
   - Easy for development/testing
   - Synchronous fallback for reliability

2. **Separate WhatsApp Tables**:
   - Maintains audit trail of WhatsApp-specific data
   - Enables WhatsApp-specific features (delivery tracking)
   - Doesn't modify existing chat infrastructure

3. **Response Formatting at Service Layer**:
   - Centralized formatting logic
   - Reusable across different output channels
   - Easy to customize per tenant

4. **Link to Existing Chat Sessions**:
   - Reuses all RAG/vector/LLM logic
   - No duplication of chat infrastructure
   - Unified conversation history

## Files Created/Modified

### New Files
- `backend/app/adapters/whatsapp.py` - WhatsApp provider
- `backend/app/adapters/message_broker.py` - Message broker abstraction
- `backend/app/services/whatsapp_service.py` - WhatsApp business logic
- `backend/app/services/response_formatter.py` - Response formatting
- `backend/app/models/whatsapp.py` - Database models
- `backend/app/api/whatsapp.py` - API endpoints

### Modified Files
- `backend/app/main.py` - Added WhatsApp router
- `backend/app/models/__init__.py` - Exported WhatsApp models
- `backend/app/api/__init__.py` - Exported WhatsApp router
- `backend/requirements.txt` - Added optional dependencies

## References

- WhatsApp Cloud API: https://developers.facebook.com/docs/whatsapp/cloud-api
- RabbitMQ Python: https://aio-pika.readthedocs.io/
- Kafka Python: https://aiokafka.readthedocs.io/
- FastAPI: https://fastapi.tiangolo.com/
