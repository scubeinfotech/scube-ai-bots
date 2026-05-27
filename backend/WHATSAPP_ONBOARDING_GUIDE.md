# WhatsApp Onboarding Process - Streamlined

## Current Problem
WhatsApp configuration is scattered across 4 places:
1. **Database** - Primary configuration
2. **.env file** - MSG91 and access tokens
3. **Settings Tab** - External API settings
4. **Channel Tab** - WhatsApp configuration UI

## Single Source of Truth

### DATABASE is the ONLY source of truth
All WhatsApp configuration should be stored in the `WhatsAppConfiguration` table.

### What to remove from .env:
- `MSG91_AUTH_KEY` - Move to database config_metadata
- `WHATSAPP_ACCESS_TOKEN` - Move to database

### What to keep in .env:
- System-wide settings only
- No tenant-specific credentials

## New Tenant Onboarding Process

### Step 1: Create Tenant (Admin Panel)
1. Go to Admin Panel
2. Create new tenant
3. Note the tenant ID

### Step 2: Configure WhatsApp (Channel Tab)
1. Login to tenant dashboard
2. Go to "Channels" tab
3. Select "WhatsApp"
4. Fill in the following:

#### MSG91 Configuration (Recommended):
```
Provider: MSG91
MSG91 Auth Key: [Get from MSG91 dashboard]
MSG91 Integrated Number: [Your WhatsApp number]
Phone Number ID: [Can be empty for MSG91]
Business Account ID: [Can be empty for MSG91]
Access Token: [MSG91 auth key again]
```

#### Meta API Configuration (Advanced):
```
Provider: Meta
Phone Number ID: [From Meta Developer Console]
Business Account ID: [From Meta Developer Console]
Access Token: [From Meta Developer Console]
```

### Step 3: Configure Webhook (Meta Developer Console)
If using Meta API:
1. Go to Meta Developer Console
2. Webhook URL: `https://yourdomain.com/api/whatsapp/webhook/{tenant_id}`
3. Verify Token: `scube_wa_verify_2024`
4. Subscribe to `messages` event

### Step 4: Test Configuration
1. Send test message to WhatsApp number
2. Check if bot responds
3. Use health check: `/api/whatsapp/health/{tenant_id}`

## Configuration Fields Explained

### Required Fields:
- `tenant_id` - Auto-generated
- `phone_number_id` - Meta Phone ID or MSG91 number
- `business_account_id` - Meta Business ID
- `access_token` - Meta or MSG91 token
- `webhook_url` - Auto-generated
- `webhook_verify_token` - Auto-generated

### Optional Fields:
- `auto_response_enabled` - Enable bot replies (default: true)
- `rate_limit_max_per_minute` - Rate limiting (default: 5)
- `cooldown_seconds` - Cooldown between messages (default: 2)
- `response_target_chars` - Target response length (default: 300)

### MSG91 Specific (in config_metadata):
```json
{
  "msg91_auth_key": "your_msg91_key",
  "msg91_integrated_number": "6580786788",
  "msg91_api_endpoint": "https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/"
}
```

## API Endpoints for Onboarding

### Create/Update Configuration:
```bash
POST /api/whatsapp/configure/{tenant_id}
{
  "phone_number_id": "1069501506253151",
  "business_account_id": "2025919281614311",
  "access_token": "EAAdPht...",
  "auto_response_enabled": true,
  "config_metadata": {
    "msg91_auth_key": "516065A2X1NLCv6a1167dcP1",
    "msg91_integrated_number": "6580786788"
  }
}
```

### Check Health:
```bash
GET /api/whatsapp/health/{tenant_id}
```

### Emergency Restore:
```bash
POST /api/whatsapp/restore/{tenant_id}
{
  "confirm": true,
  "reason": "Onboarding test"
}
```

## Migration Plan

### Phase 1: Document Current State
- ✅ Document all configuration locations
- ✅ Identify redundant settings

### Phase 2: Update Code
- Remove MSG91_AUTH_KEY from .env checks
- Use database as single source
- Update validation logic

### Phase 3: Update Frontend
- Simplify Channel tab UI
- Add clear instructions
- Show configuration status

### Phase 4: Testing
- Test new tenant onboarding
- Verify all configurations work
- Update documentation

## Common Issues & Solutions

### Issue: Bot not responding
**Solution**: Check if MSG91 is configured in config_metadata

### Issue: "Recipient not in allowed list"
**Solution**: Use MSG91 or add numbers to Meta allowed list

### Issue: Webhook not working
**Solution**: Verify webhook URL and token in Meta Console

## Best Practices

1. **Always use MSG91** for new tenants (easier setup)
2. **Never store credentials in .env** for tenant-specific data
3. **Test with real messages** after configuration
4. **Monitor health** regularly
5. **Keep backup** of working configurations

## Support Contact

For onboarding issues:
1. Check health endpoint
2. Review configuration in database
3. Use emergency restore if needed
4. Check WHATSAPP_EMERGENCY_GUIDE.md
