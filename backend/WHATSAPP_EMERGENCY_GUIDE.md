# WhatsApp Emergency Response Guide

## Critical Issue: Bot Stops Responding

### Symptoms
- Users send messages but receive no replies
- Inbound messages are stored in database
- Outbound messages are not created/sent
- Response rate drops to 0%

### Root Causes (from investigation)
1. **MSG91 configuration removed** - Most common cause
2. **Configuration updated** - Someone modified WhatsApp settings
3. **Meta API restrictions** - Recipient not in allowed list
4. **Access token expired** - Authentication failure

### Immediate Actions

#### 1. Check Health Status
```bash
curl "http://localhost:8000/api/whatsapp/health/fb8a4ec0-e463-4678-8178-32b8332db73a"
```

#### 2. Restore Working Configuration (Emergency)
```bash
curl -X POST "http://localhost:8000/api/whatsapp/restore/fb8a4ec0-e463-4678-8178-32b8332db73a" \
  -H "Content-Type: application/json" \
  -d '{
    "confirm": true,
    "reason": "Bot not responding - emergency restore"
  }'
```

#### 3. Verify Restoration
```bash
# Check if bot responds to test message
python3 -c "
from app.database import get_db
from app.services.whatsapp_service import WhatsAppService
import asyncio

async def test():
    db = next(get_db())
    service = WhatsAppService(db)
    result = await service._send_whatsapp_message(
        wa_config=service.db.query(WhatsAppConfiguration).filter(
            WhatsAppConfiguration.tenant_id == 'fb8a4ec0-e463-4678-8178-32b8332db73a'
        ).first(),
        recipient_phone='6594561045',
        message_text='Bot restored - testing'
    )
    print(f'Test result: {result}')

asyncio.run(test())
"
```

### Working Configuration Backup

#### MSG91 Configuration (REQUIRED)
```json
{
  "phone_number_id": "1069501506253151",
  "business_account_id": "2025919281614311",
  "access_token": "EAAdPhtILTHEBRv8SZBr0FEmFsTlCo...",
  "webhook_url": "https://chat.scubeinfotech.com.sg/api/whatsapp/webhook/fb8a4ec0-e463-4678-8178-32b8332db73a",
  "webhook_verify_token": "scube_wa_verify_2024",
  "is_active": true,
  "auto_response_enabled": true,
  "config_metadata": {
    "msg91_auth_key": "516065A2X1NLCv6a1167dcP1",
    "msg91_integrated_number": "6580786788",
    "msg91_api_endpoint": "https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/"
  }
}
```

### Prevention Measures

#### 1. Configuration Validation
- System now validates changes before saving
- Removing MSG91 config is BLOCKED
- Critical warnings for dangerous changes

#### 2. Health Monitoring
- Response rate monitored every hour
- Automatic alerts when response rate < 50%
- Configuration change logging

#### 3. Access Control
- Limit who can modify WhatsApp settings
- Require confirmation for critical changes
- Audit trail of all modifications

### What NOT To Do

❌ **NEVER remove `config_metadata`** - Contains MSG91 settings
❌ **NEVER switch to Meta API only** - Has recipient restrictions  
❌ **NEVER disable auto_response** - Bot won't reply
❌ **NEVER change access token without testing**

### Contact Information

If issue persists after restore:
1. Check MSG91 API status
2. Verify webhook is receiving messages
3. Check database for error logs
4. Contact MSG91 support if needed

### Recovery Checklist

- [ ] Restore configuration using API
- [ ] Test message sending
- [ ] Verify response rate > 80%
- [ ] Monitor for 1 hour
- [ ] Notify affected users if needed

### Last Resort

If all else fails:
1. Check backup file: `whatsapp_config_backup.json`
2. Manually update database with working config
3. Restart server
4. Test with known working number

---

**CRITICAL**: Never modify WhatsApp configuration without understanding the impact. MSG91 allows sending to any user, Meta API has restrictions that will break the bot.
