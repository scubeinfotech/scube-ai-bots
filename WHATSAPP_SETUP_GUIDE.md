# WhatsApp Integration - Complete Setup Guide

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         WhatsApp Integration Flow                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────────┐         Webhook          ┌──────────────────────┐         │
│   │  Customer    │ ───────────────────────> │   Your Server        │         │
│   │  (94561045)  │   "HI" (via MSG91)     │   (LLM Chatbot)      │         │
│   └──────────────┘                          └──────────────────────┘         │
│                                                        │                     │
│                                                        │ Process & Generate  │
│                                                        │ Response            │
│                                                        ▼                     │
│   ┌──────────────┐         API Call           ┌──────────────────────┐         │
│   │  Customer    │ <─────────────────────── │   MSG91 API          │         │
│   │  (94561045)  │   "Hello, I'm a bot..."  │   (Send Response)    │         │
│   └──────────────┘                          └──────────────────────┘         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## What Goes Where

### 1. INCOMING: Customer → Your Server

**Configure in MSG91 Dashboard (or Meta Developer Console):**

| Field | Value | Where to Put |
|-------|-------|--------------|
| **Webhook URL** | `https://chat.scubeinfotech.com.sg/api/whatsapp/webhook/fb8a4ec0-e463-4678-8178-32b8332db73a` | MSG91 Dashboard → WhatsApp → Webhook |
| **Verify Token** | `scube_wa_verify_2024` | MSG91 Dashboard → WhatsApp → Verification Token |

**Purpose:** When customer sends a message, MSG91 forwards it to your server via this webhook.

---

### 2. OUTGOING: Your Server → Customer

**Configure in Your Database (Tenant Dashboard):**

| Field | Value | Where to Put |
|-------|-------|--------------|
| **MSG91 Auth Key** | `516065A2X1NLCv6a1167dcP1` | Tenant Dashboard → WhatsApp → MSG91 Auth Key |
| **Integrated Number** | `6580786788` | Tenant Dashboard → WhatsApp → Integrated Number |
| **API Endpoint** | `https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/` | Tenant Dashboard → WhatsApp → API Endpoint |

**Purpose:** Your server uses these credentials to send responses back to customers via MSG91 API.

---

## Complete Configuration Checklist

### Step 1: Get Values FROM MSG91 → Store in YOUR Database

The tenant must provide these from their MSG91 account:

```
┌─────────────────────────────────────────────────────────┐
│              MSG91 Dashboard                            │
│  ┌──────────────────────────────────────────────────┐  │
│  │  WhatsApp → API Keys → Auth Key                 │  │
│  │  Copy: 516065A2X1NLCv6a1167dcP1                │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │  WhatsApp → Numbers → Integrated Number         │  │
│  │  Copy: 6580786788 (your business WhatsApp)      │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                              │
                              │ Copy these values
                              ▼
┌─────────────────────────────────────────────────────────┐
│         Your Tenant Dashboard                           │
│                                                         │
│  MSG91 Auth Key: [516065A2X1NLCv6a1167dcP1    ]        │
│  Integrated Number: [6580786788               ]         │
│  API Endpoint: [https://control.msg91.com... ]         │
│                                                         │
│  (These get stored in database → config_metadata)       │
└─────────────────────────────────────────────────────────┘
```

### Step 2: Give Values TO MSG91 FROM Your System

Your system provides these webhook URLs to MSG91:

```
┌─────────────────────────────────────────────────────────┐
│         Your System (Auto-Generated)                    │
│                                                         │
│  Webhook URL: https://chat.scubeinfotech.com.sg/       │
│               /api/whatsapp/webhook/                   │
│               fb8a4ec0-e463-4678-8178-32b8332db73a   │
│                                                         │
│  Verify Token: scube_wa_verify_2024                    │
│  (Stored in DB → webhook_verify_token)                 │
└─────────────────────────────────────────────────────────┘
                              │
                              │ Copy these to MSG91
                              ▼
┌─────────────────────────────────────────────────────────┐
│              MSG91 Dashboard                            │
│  ┌──────────────────────────────────────────────────┐  │
│  │  WhatsApp → Configuration → Webhook URL         │  │
│  │  Paste: https://chat.scubeinfotech.com.sg/...  │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Verify Token Field                               │  │
│  │  Paste: scube_wa_verify_2024                    │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## API Flow Explained

### Incoming Message (Customer → Bot)

```
1. Customer sends "HI" to +65 8078 6788
2. MSG91 receives message
3. MSG91 POSTs to your webhook:
   
   POST /api/whatsapp/webhook/fb8a4ec0-e463-4678-8178-32b8332db73a
   {
     "customerNumber": "6594561045",
     "integratedNumber": "6580786788",
     "text": "HI",
     ...
   }

4. Your server receives, processes with LLM
5. Your server generates response: "Hello, I'm a bot..."
```

### Outgoing Message (Bot → Customer)

```
1. Your server prepares response
2. Your server calls MSG91 API:
   
   POST https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/
   Headers:
     authkey: 516065A2X1NLCv6a1167dcP1
   Body:
   {
     "integrated_number": "6580786788",
     "recipient_number": "+6594561045",
     "content_type": "text",
     "text": "Hello, I'm a bot..."
   }

3. MSG91 forwards to customer's WhatsApp
4. Customer receives message
```

---

## Required Credentials Summary

### What Tenant Needs FROM MSG91:

| Credential | Where in MSG91 | Where to Store in Your System |
|------------|----------------|--------------------------------|
| **Auth Key** | Dashboard → API Keys → WhatsApp Auth Key | `config_metadata.msg91_auth_key` |
| **Integrated Number** | Dashboard → WhatsApp → Numbers | `config_metadata.msg91_integrated_number` |
| **API Endpoint** | Usually fixed, but configurable | `config_metadata.msg91_api_endpoint` |

### What Tenant Needs TO GIVE TO MSG91:

| Credential | Where in Your System | Where to Put in MSG91 |
|------------|----------------------|----------------------|
| **Webhook URL** | `/api/whatsapp/webhook/{tenant_id}` | Dashboard → WhatsApp → Webhook URL |
| **Verify Token** | `webhook_verify_token` field | Dashboard → WhatsApp → Verify Token |

---

## Database Storage

```sql
-- For scubeinfotech tenant
SELECT 
  tenant_id,
  webhook_verify_token,  -- 'scube_wa_verify_2024' (give to MSG91)
  config_metadata->>'msg91_auth_key' as auth_key,           -- (get from MSG91)
  config_metadata->>'msg91_integrated_number' as integrated_number  -- (get from MSG91)
FROM whatsapp_configurations 
WHERE tenant_id = 'fb8a4ec0-e463-4678-8178-32b8332db73a';
```

---

## Meta (Direct API) Alternative

If using **Meta directly** instead of MSG91:

### What Tenant Needs FROM Meta:

| Credential | Where in Meta | Where to Store |
|------------|---------------|----------------|
| **Phone Number ID** | Developer Console → WhatsApp → Phone Numbers | `phone_number_id` |
| **Business Account ID** | Business Manager → WhatsApp Accounts | `business_account_id` |
| **Access Token** | Developer Console → Tokens | `access_token` |

### What Tenant Needs TO GIVE TO Meta:

| Credential | Value | Where in Meta |
|------------|-------|---------------|
| **Callback URL** | `https://chat.scubeinfotech.com.sg/api/whatsapp/webhook/{tenant_id}` | Configuration → Webhook |
| **Verify Token** | `scube_wa_verify_2024` | Configuration → Verify Token |

---

## Quick Reference: scubeinfotech

| Direction | What | Value |
|-----------|------|-------|
| **→ MSG91** (Give) | Webhook URL | `https://chat.scubeinfotech.com.sg/api/whatsapp/webhook/fb8a4ec0-e463-4678-8178-32b8332db73a` |
| **→ MSG91** (Give) | Verify Token | `scube_wa_verify_2024` |
| **← MSG91** (Get) | Auth Key | `516065A2X1NLCv6a1167dcP1` |
| **← MSG91** (Get) | Integrated Number | `6580786788` |
| **← MSG91** (Get) | API Endpoint | `https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/` |

---

## Troubleshooting

### Messages Not Received by Customer

1. Check `config_metadata` has correct `msg91_auth_key`
2. Check `config_metadata` has correct `msg91_integrated_number`
3. Verify integrated number is active in MSG91
4. Check MSG91 logs for delivery failures

### Webhook Not Working

1. Verify webhook URL is correct in MSG91
2. Verify verify token matches `webhook_verify_token` in DB
3. Test: `curl "https://your-domain/api/whatsapp/webhook/{tenant_id}?challenge=test&verify_token=scube_wa_verify_2024"`

---

## Does This Answer Your Question?

This guide shows:
- ✅ What callback URL to put in MSG91 (webhook URL)
- ✅ What API key is needed for replies (auth key)
- ✅ What values tenant gets from MSG91
- ✅ What values tenant gives to MSG91
- ✅ How the two-way flow works
