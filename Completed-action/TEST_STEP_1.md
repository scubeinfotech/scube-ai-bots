# Step 1: WhatsApp Integration Testing Guide

## Prerequisites
- Backend running: `uvicorn app.main:app --reload` (or via docker-compose)
- Tenant seeded: `python backend/seed_rapas_tenant.py`
- Service control script ready: `./service-control.sh`

## Test Tenant ID
```
c66e96d3-999c-4746-b11c-1758a9c2e982
```

---

## Test Suite 1: Service Health & Status

### 1.1 Check Core Services
```bash
./service-control.sh status
```
Expected: Shows API and Database both healthy ✅

### 1.2 Check WhatsApp Integration Status
```bash
./service-control.sh whatsapp
```
Expected Output:
```
✅ WhatsApp API is available
WhatsApp Database Tables:
- whatsapp_configurations (48 kB)
- whatsapp_contacts (32 kB)
- whatsapp_messages (32 kB)
- whatsapp_sessions (32 kB)
- whatsapp_metrics (8 kB)
```

### 1.3 View WhatsApp Metrics
```bash
./service-control.sh whatsapp-metrics
```
Expected: Shows message statistics (initially empty for new setup)

---

## Test Suite 2: API Endpoints

### 2.1 Health Check
```bash
TENANT_ID="c66e96d3-999c-4746-b11c-1758a9c2e982"

curl -s http://localhost:8000/api/whatsapp/health/$TENANT_ID | jq .
```

Expected Response:
```json
{
  "status": "healthy",
  "configured": true,
  "active": true,
  "phone_number_id": "1234567890",
  "features": {
    "booking_flow": false,
    "interactive_responses": true,
    "auto_response": true,
    "short_response_mode": true
  }
}
```

### 2.2 Configure WhatsApp
```bash
TENANT_ID="c66e96d3-999c-4746-b11c-1758a9c2e982"

curl -X POST http://localhost:8000/api/whatsapp/configure/$TENANT_ID \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number_id": "1234567890",
    "business_account_id": "abcdef123",
    "access_token": "EAABSZ_test_token",
    "webhook_url": "https://yourdomain.com/api/whatsapp/webhook/'$TENANT_ID'",
    "webhook_verify_token": "test_verify_token_12345",
    "enable_interactive_responses": true,
    "short_response_mode": true,
    "auto_response_enabled": true
  }' | jq .
```

Expected Response:
```json
{
  "id": "config-uuid",
  "tenant_id": "c66e96d3-999c-4746-b11c-1758a9c2e982",
  "phone_number_id": "1234567890",
  "is_active": true,
  "enable_booking_flow": false,
  "enable_interactive_responses": true
}
```

### 2.3 Webhook Verification (GET)
```bash
TENANT_ID="c66e96d3-999c-4746-b11c-1758a9c2e982"

curl -X GET "http://localhost:8000/api/whatsapp/webhook/$TENANT_ID?hub.mode=subscribe&hub.challenge=test_challenge&hub.verify_token=test_verify_token_12345" | jq .
```

Expected Response:
```
test_challenge
```

### 2.4 Webhook Message Processing (POST)
```bash
TENANT_ID="c66e96d3-999c-4746-b11c-1758a9c2e982"

curl -X POST http://localhost:8000/api/whatsapp/webhook/$TENANT_ID \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{
      "changes": [{
        "value": {
          "messages": [{
            "from": "+1234567890",
            "id": "msg_test_001",
            "timestamp": "1713182400",
            "type": "text",
            "text": {"body": "What are your marine engineering services?"}
          }]
        }
      }]
    }]
  }' | jq .
```

Expected Response:
```json
{
  "success": true,
  "messages_processed": 1,
  "results": [
    {
      "success": true,
      "message_id": "uuid",
      "whatsapp_message_id": "msg_test_001",
      "queued": true
    }
  ]
}
```

---

## Test Suite 3: Message Broker Pipeline

### 3.1 View WhatsApp Logs
```bash
./service-control.sh whatsapp-logs
```

Expected logs:
```
INFO:app.adapters.message_broker:[InMemory] Broker ready
INFO:app.adapters.message_broker:[InMemory] Published to whatsapp_messages_c66e96d3-...
INFO:     127.0.0.1:xxxxx - "POST /api/whatsapp/webhook/c66e96d3-... HTTP/1.1" 200 OK
```

### 3.2 Check Database Records
```bash
# Check WhatsApp messages
docker exec llm-postgres psql -U llmuser -d llm_chatbot -c "
  SELECT id, whatsapp_message_id, sender, message_text, status, created_at 
  FROM whatsapp_messages 
  ORDER BY created_at DESC 
  LIMIT 5;
"

# Check WhatsApp contacts
docker exec llm-postgres psql -U llmuser -d llm_chatbot -c "
  SELECT id, phone_number, first_message_at, last_message_at 
  FROM whatsapp_contacts 
  ORDER BY last_message_at DESC 
  LIMIT 5;
"

# Check WhatsApp sessions
docker exec llm-postgres psql -U llmuser -d llm_chatbot -c "
  SELECT id, tenant_id, contact_id, started_at, ended_at, message_count 
  FROM whatsapp_sessions 
  ORDER BY started_at DESC 
  LIMIT 5;
"
```

---

## Test Suite 4: Integration with Existing Systems

### 4.1 Verify No Data Loss
```bash
# Check existing chat tables are untouched
docker exec llm-postgres psql -U llmuser -d llm_chatbot -c "
  SELECT COUNT(*) as total_chats FROM chat_messages;
"

# Check existing chat sessions
docker exec llm-postgres psql -U llmuser -d llm_chatbot -c "
  SELECT COUNT(*) as total_sessions FROM chat_sessions;
"
```

Expected: Original data counts should be unchanged ✅

### 4.2 Verify Tenant Relationship
```bash
# Check rapas tenant
docker exec llm-postgres psql -U llmuser -d llm_chatbot -c "
  SELECT id, name, slug, created_at FROM tenants WHERE slug = 'rapas';
"

# Check WhatsApp config is linked to tenant
docker exec llm-postgres psql -U llmuser -d llm_chatbot -c "
  SELECT wc.id, wc.tenant_id, t.name, wc.phone_number_id, wc.is_active
  FROM whatsapp_configurations wc
  JOIN tenants t ON wc.tenant_id = t.id;
"
```

---

## Test Suite 5: Performance & Edge Cases

### 5.1 Multiple Messages in Sequence
```bash
TENANT_ID="c66e96d3-999c-4746-b11c-1758a9c2e982"

# Send 5 messages rapidly
for i in {1..5}; do
  curl -s -X POST http://localhost:8000/api/whatsapp/webhook/$TENANT_ID \
    -H "Content-Type: application/json" \
    -d "{
      \"entry\": [{
        \"changes\": [{
          \"value\": {
            \"messages\": [{
              \"from\": \"+1234567890\",
              \"id\": \"msg_test_00$i\",
              \"timestamp\": \"1713182400\",
              \"type\": \"text\",
              \"text\": {\"body\": \"Test message $i\"}
            }]
          }
        }]
      }]
    }" | jq .success
done
```

Expected: All return `true` ✅

### 5.2 Invalid Tenant ID
```bash
curl -X GET http://localhost:8000/api/whatsapp/health/invalid-uuid | jq .
```

Expected: Returns 404 with appropriate error ✅

### 5.3 Missing Required Fields
```bash
TENANT_ID="c66e96d3-999c-4746-b11c-1758a9c2e982"

curl -X POST http://localhost:8000/api/whatsapp/webhook/$TENANT_ID \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{
      "changes": [{
        "value": {}
      }]
    }]
  }' | jq .
```

Expected: Handles gracefully (no error crash) ✅

---

## Test Suite 6: Database Integrity

### 6.1 Table Sizes
```bash
./service-control.sh whatsapp
```

### 6.2 Data Relationships
```bash
# Verify foreign key relationships
docker exec llm-postgres psql -U llmuser -d llm_chatbot -c "
  SELECT constraint_name, table_name, column_name
  FROM information_schema.key_column_usage
  WHERE table_name LIKE 'whatsapp%'
  ORDER BY table_name;
"
```

Expected: All relationships intact ✅

### 6.3 Schema Validation
```bash
# List all WhatsApp tables and columns
docker exec llm-postgres psql -U llmuser -d llm_chatbot -c "
  SELECT tablename FROM pg_tables 
  WHERE schemaname = 'public' AND tablename LIKE 'whatsapp%'
  ORDER BY tablename;
"
```

Expected Output:
```
whatsapp_configurations
whatsapp_contacts
whatsapp_messages
whatsapp_metrics
whatsapp_sessions
```

---

## Passing Criteria for Step 1 ✅

- [ ] All 6 endpoints respond with correct status codes
- [ ] Health check shows all features enabled
- [ ] Messages are queued successfully
- [ ] Message broker logs show proper initialization
- [ ] Database tables created with correct schema
- [ ] No modifications to existing chat tables
- [ ] Webhook verification token works
- [ ] Multiple messages handled correctly
- [ ] Invalid tenant IDs return 404
- [ ] Foreign key relationships intact

---

## Troubleshooting

### Issue: "Tenant not found" on configure
**Solution**: Re-seed tenant: `python backend/seed_rapas_tenant.py`

### Issue: Message broker not initializing
**Solution**: Check logs: `./service-control.sh whatsapp-logs`

### Issue: Database errors
**Solution**: Verify PostgreSQL is running: `./service-control.sh status`

### Issue: Webhook returns 404
**Solution**: Use correct tenant UUID, not slug

---

## Next Steps (Step 2)

Once all tests pass, Step 2 will include:
- Human-in-the-loop dashboard for admin takeover
- Booking flow support (multi-step form collection)
- Conversation management UI
- Admin routing and priority handling

