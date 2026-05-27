# Tenant WhatsApp Setup - Cheat Sheet

## Quick Answer: What Goes Where

### 🔴 GIVE TO MSG91 (From Your System → MSG91 Dashboard)

| Setting | Value for scubeinfotech |
|---------|------------------------|
| **Webhook URL** | `https://chat.scubeinfotech.com.sg/api/whatsapp/webhook/fb8a4ec0-e463-4678-8178-32b8332db73a` |
| **Verify Token** | `scube_wa_verify_2024` |

**Where in MSG91:** Dashboard → WhatsApp → Configuration → Webhook Settings

---

### 🟢 GET FROM MSG91 (MSG91 Dashboard → Your System)

| Setting | Value for scubeinfotech | Where to Store |
|---------|------------------------|----------------|
| **Auth Key** | `516065A2X1NLCv6a1167dcP1` | Tenant Dashboard → MSG91 Auth Key |
| **Integrated Number** | `6580786788` | Tenant Dashboard → Integrated Number |
| **API Endpoint** | `https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/` | Tenant Dashboard → API Endpoint |

**Where in MSG91:** 
- Auth Key: Dashboard → API Keys → WhatsApp
- Integrated Number: Dashboard → WhatsApp → Numbers

---

## Visual Flow

```
CUSTOMER
    │ sends "HI" to +65 8078 6788
    ▼
MSG91 receives message
    │ forwards via webhook
    ▼
YOUR SERVER (LLM Bot)
    │ processes with AI
    │ generates response
    │ calls MSG91 API
    ▼
MSG91 sends message
    ▼
CUSTOMER receives reply
```

---

## API Credentials Needed

### For INCOMING (Customer → Bot)
```
Webhook URL:    /api/whatsapp/webhook/{tenant_id}
Verify Token:   Stored in DB (webhook_verify_token)
                ↓
                Give this to MSG91
```

### For OUTGOING (Bot → Customer)
```
Auth Key:       From MSG91 → Store in DB (config_metadata.msg91_auth_key)
Integrated #:   From MSG91 → Store in DB (config_metadata.msg91_integrated_number)
API Endpoint:   From MSG91 → Store in DB (config_metadata.msg91_api_endpoint)
                ↓
                Use these to call MSG91 API
```

---

## Current scubeinfotech Values (Confirmed Working)

| Direction | Credential | Value | Location |
|-----------|------------|-------|----------|
| → MSG91 | Webhook URL | `https://chat.scubeinfotech.com.sg/api/whatsapp/webhook/fb8a4ec0-e463-4678-8178-32b8332db73a` | DB + Give to MSG91 |
| → MSG91 | Verify Token | `scube_wa_verify_2024` | DB + Give to MSG91 |
| ← MSG91 | Auth Key | `516065A2X1NLCv6a1167dcP1` | DB (from MSG91) |
| ← MSG91 | Integrated # | `6580786788` | DB (from MSG91) |

---

## For Each New Tenant

### Step 1: Tenant gets from MSG91
1. Log into MSG91 Dashboard
2. Copy Auth Key
3. Copy Integrated Number
4. Paste into YOUR Tenant Dashboard

### Step 2: Your system gives to MSG91
1. Generate Webhook URL: `https://your-domain/api/whatsapp/webhook/{tenant_id}`
2. Generate Verify Token (random string)
3. Store both in database
4. Show tenant these values to paste in MSG91

### Step 3: Verify
1. Tenant pastes webhook URL in MSG91
2. Tenant pastes verify token in MSG91
3. Click "Verify" in MSG91
4. Send test message

---

## Common Mistakes

❌ **Wrong:** Putting tenant WhatsApp credentials in `.env`  
✅ **Right:** Store per-tenant in database

❌ **Wrong:** Using `phone_number_id` for MSG91 integrated number  
✅ **Right:** Use `config_metadata.msg91_integrated_number`

❌ **Wrong:** Webhook URL without tenant ID  
✅ **Right:** Must include `/webhook/{tenant_id}`

---

## Database Query for Verification

```sql
-- Check scubeinfotech config
SELECT 
  tenant_id,
  webhook_url,              -- What we give to MSG91
  webhook_verify_token,     -- What we give to MSG91
  config_metadata->>'msg91_auth_key' as auth_key,              -- What we get from MSG91
  config_metadata->>'msg91_integrated_number' as integrated  -- What we get from MSG91
FROM whatsapp_configurations 
WHERE tenant_id = 'fb8a4ec0-e463-4678-8178-32b8332db73a';
```

---

## Is This Clear?

**Key Points:**
1. Webhook URL goes TO MSG91 (for incoming messages)
2. Auth Key comes FROM MSG91 (for outgoing replies)
3. Both directions use the same integrated number
4. All per-tenant config lives in database, not `.env`
