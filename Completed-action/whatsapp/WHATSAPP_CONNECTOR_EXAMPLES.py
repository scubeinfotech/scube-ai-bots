"""
WhatsApp Connector - Testing and Examples
Demonstrates how to test WhatsApp integration
"""
import asyncio
import json
from typing import Dict, Any

# Example WhatsApp webhook payloads

def get_text_message_payload(
    from_phone: str = "+1234567890",
    message_text: str = "Hello, I need help with your services",
    message_id: str = "msg_123"
) -> Dict[str, Any]:
    """
    Create example text message webhook payload
    
    This is what WhatsApp sends to your webhook when a customer messages
    """
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": from_phone,
                        "id": message_id,
                        "timestamp": "1713182400",
                        "type": "text",
                        "text": {
                            "body": message_text
                        }
                    }],
                    "metadata": {
                        "display_phone_number": "1234567890",
                        "phone_number_id": "1234567890"
                    }
                }
            }]
        }]
    }


def get_button_reply_payload(
    from_phone: str = "+1234567890",
    button_text: str = "Book a Demo"
) -> Dict[str, Any]:
    """
    Create example button reply webhook payload
    
    When customer clicks a button, WhatsApp sends this
    """
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": from_phone,
                        "id": "msg_456",
                        "timestamp": "1713182401",
                        "type": "button",
                        "button": {
                            "text": button_text
                        }
                    }]
                }
            }]
        }]
    }


def get_list_reply_payload(
    from_phone: str = "+1234567890",
    selected_title: str = "Premium Plan - $99/month"
) -> Dict[str, Any]:
    """
    Create example list reply webhook payload
    
    When customer selects from a list, WhatsApp sends this
    """
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": from_phone,
                        "id": "msg_789",
                        "timestamp": "1713182402",
                        "type": "interactive",
                        "interactive": {
                            "type": "list_reply",
                            "list_reply": {
                                "id": "pricing_selection",
                                "title": selected_title
                            }
                        }
                    }]
                }
            }]
        }]
    }


# Example test cases

async def test_text_message():
    """Test receiving and processing a text message"""
    print("\n" + "="*60)
    print("TEST 1: Text Message")
    print("="*60)
    
    tenant_id = "test-tenant"
    payload = get_text_message_payload(
        from_phone="+1234567890",
        message_text="What's your pricing?"
    )
    
    print("\nPayload:")
    print(json.dumps(payload, indent=2))
    
    print("\nExpected Flow:")
    print("1. WhatsApp webhook handler receives POST request")
    print("2. Extracts phone number: +1234567890")
    print("3. Creates WhatsAppContact (if new)")
    print("4. Stores WhatsAppMessage (inbound)")
    print("5. Publishes to message broker with priority='high'")
    print("6. WhatsAppService processes message:")
    print("   - Creates WhatsAppSession")
    print("   - Creates ChatSession (links to LLM)")
    print("   - Calls ChatService.send_message() with LLM provider")
    print("   - LLM retrieves context from vector DB (RAG)")
    print("   - Formats response via ResponseFormatter")
    print("   - Sends reply via WhatsApp API")
    print("7. Stores WhatsAppMessage (outbound)")
    print("\nExpected Response to Customer:")
    print("'Our pricing starts at $99/month for basic plan. Premium at $299/month.'")


async def test_multi_turn_conversation():
    """Test multi-turn conversation with context"""
    print("\n" + "="*60)
    print("TEST 2: Multi-Turn Conversation")
    print("="*60)
    
    tenant_id = "test-tenant"
    phone = "+1234567890"
    
    # Turn 1: Initial question
    print("\nTurn 1: Customer Question")
    msg1 = get_text_message_payload(
        from_phone=phone,
        message_text="Do you offer discounts for annual billing?"
    )
    print(f"Customer: {msg1['entry'][0]['changes'][0]['value']['messages'][0]['text']['body']}")
    print("Bot Response: Yes, we offer 20% discount for annual contracts. Would you like to book a call?")
    
    # Turn 2: Follow-up (LLM has context from Turn 1)
    print("\nTurn 2: Follow-up Question")
    msg2 = get_text_message_payload(
        from_phone=phone,
        message_text="Great! Can I schedule for next Monday?"
    )
    print(f"Customer: {msg2['entry'][0]['changes'][0]['value']['messages'][0]['text']['body']}")
    print("Bot Response: Sure! What time works best for you? (9AM - 5PM)")
    
    print("\nContext Flow:")
    print("- Same WhatsAppSession used for both messages")
    print("- Same ChatSession linked to WhatsApp session")
    print("- LLM has access to conversation history")
    print("- Database tables populated:")
    print("  • whatsapp_messages: 4 rows (2 inbound, 2 outbound)")
    print("  • chat_messages: 4 rows (same content, tagged with LLM provider)")
    print("  • whatsapp_sessions: 1 row (updated with timestamps)")


async def test_short_response_formatting():
    """Test response formatting for WhatsApp"""
    print("\n" + "="*60)
    print("TEST 3: Short Response Formatting")
    print("="*60)
    
    print("\nOriginal LLM Response (Long):")
    long_response = """
    Our company provides comprehensive enterprise software solutions including 
    cloud infrastructure, managed services, and dedicated support. We have been 
    serving Fortune 500 companies for over 15 years. Our pricing is tiered based 
    on deployment size and feature set. The basic tier starts at $99 per month and 
    includes essential features. Our premium tier at $299 per month includes advanced 
    analytics and priority support. We also offer custom enterprise agreements. 
    For more information, please visit our website or contact our sales team.
    """
    print(f"Length: {len(long_response)} characters")
    print(f"Text: {long_response[:150]}...")
    
    print("\nFormatted for WhatsApp (Short):")
    short_response = """
    Our pricing: Basic $99/mo, Premium $299/mo. Fortune 500 trusted provider. 
    Visit our website or contact sales for custom enterprise plans.
    """
    print(f"Length: {len(short_response)} characters")
    print(f"Text: {short_response}")
    
    print("\nFormatting Applied:")
    print(f"- Removed markdown/HTML")
    print(f"- Truncated intelligently (sentence boundary)")
    print(f"- Added ellipsis indicator")
    print(f"- Preserved key information")
    print(f"- Result: {len(long_response) - len(short_response)} chars reduction")


async def test_interactive_response():
    """Test interactive buttons/list response"""
    print("\n" + "="*60)
    print("TEST 4: Interactive Response (Buttons)")
    print("="*60)
    
    print("\nCustomer Question:")
    print("'What are your service plans?'")
    
    print("\nBot Response with Interactive Buttons:")
    print("┌─ What would you like to know? ─┐")
    print("│ 1. View Pricing                  │")
    print("│ 2. Book a Demo                   │")
    print("│ 3. Contact Sales                 │")
    print("└──────────────────────────────────┘")
    print("\nFooter: We'll help you find the right plan")
    
    print("\nPayload Structure:")
    interactive_payload = {
        "type": "button",
        "body": {
            "text": "What would you like to know?"
        },
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": "btn_pricing", "title": "View Pricing"}},
                {"type": "reply", "reply": {"id": "btn_demo", "title": "Book a Demo"}},
                {"type": "reply", "reply": {"id": "btn_sales", "title": "Contact Sales"}}
            ]
        },
        "footer": {
            "text": "We'll help you find the right plan"
        }
    }
    print(json.dumps(interactive_payload, indent=2))


async def test_message_broker():
    """Test message broker publish/subscribe"""
    print("\n" + "="*60)
    print("TEST 5: Message Broker")
    print("="*60)
    
    print("\nMessage Broker Options:")
    print("1. In-Memory (default, no dependencies)")
    print("   - Good for: Development, testing")
    print("   - Limitation: Not persistent, lost on app restart")
    
    print("\n2. RabbitMQ (production)")
    print("   - Good for: High volume, persistent queue")
    print("   - Setup: pip install aio-pika")
    
    print("\n3. Kafka (production)")
    print("   - Good for: High volume, distributed")
    print("   - Setup: pip install aiokafka")
    
    print("\nMessage Flow:")
    print("1. Webhook receives message")
    print("2. Publish to: 'whatsapp_messages_<tenant_id>' topic")
    print("3. Message: {'wa_message_id': '...', 'tenant_id': '...', 'content': '...'}")
    print("4. Priority: 'high' (processed immediately)")
    print("5. Async subscriber processes and sends response")
    print("6. If broker unavailable, falls back to sync processing")


async def test_webhook_verification():
    """Test WhatsApp webhook verification"""
    print("\n" + "="*60)
    print("TEST 6: Webhook Verification")
    print("="*60)
    
    print("\nStep 1: WhatsApp sends GET request")
    print("GET /api/whatsapp/webhook/{tenant_id}")
    print("  ?hub_mode=subscribe")
    print("  &hub_challenge=abc123xyz")
    print("  &hub_verify_token=my_verify_token")
    
    print("\nStep 2: Server verifies token")
    print("- Query WhatsAppConfiguration for tenant_id")
    print("- Compare hub_verify_token with stored webhook_verify_token")
    print("- If match: return hub_challenge")
    print("- If no match: return 403 Forbidden")
    
    print("\nStep 3: WhatsApp validates response")
    print("- If challenge returned: webhook verified ✓")
    print("- If 403 returned: webhook verification failed ✗")


# Example usage with actual API

def example_curl_commands():
    """Show example curl commands"""
    print("\n" + "="*60)
    print("CURL Commands for Testing")
    print("="*60)
    
    print("\n1. Configure WhatsApp:")
    print("""
    curl -X POST http://localhost:8000/api/whatsapp/configure/test-tenant \\
      -H "Content-Type: application/json" \\
      -d '{
        "phone_number_id": "1234567890",
        "business_account_id": "abcdef",
        "access_token": "EAABSZ...",
        "webhook_url": "https://yourdomain.com/api/whatsapp/webhook/test-tenant",
        "webhook_verify_token": "my_token"
      }'
    """)
    
    print("\n2. Verify Webhook:")
    print("""
    curl -X GET "http://localhost:8000/api/whatsapp/webhook/test-tenant" \\
      -G \\
      -d "hub_mode=subscribe" \\
      -d "hub_challenge=abc123" \\
      -d "hub_verify_token=my_token"
    """)
    
    print("\n3. Send Test Message:")
    print("""
    curl -X POST http://localhost:8000/api/whatsapp/webhook/test-tenant \\
      -H "Content-Type: application/json" \\
      -d '{
        "entry": [{
          "changes": [{
            "value": {
              "messages": [{
                "from": "+1234567890",
                "id": "msg_123",
                "timestamp": "1713182400",
                "type": "text",
                "text": {"body": "Hello!"}
              }]
            }
          }]
        }]
      }'
    """)
    
    print("\n4. Get Configuration:")
    print("""
    curl -X GET http://localhost:8000/api/whatsapp/configure/test-tenant
    """)
    
    print("\n5. Health Check:")
    print("""
    curl -X GET http://localhost:8000/api/whatsapp/health/test-tenant
    """)


async def main():
    """Run all tests"""
    print("\n")
    print("#" * 60)
    print("# WhatsApp Connector - Testing and Examples")
    print("#" * 60)
    
    await test_text_message()
    await test_multi_turn_conversation()
    await test_short_response_formatting()
    await test_interactive_response()
    await test_message_broker()
    await test_webhook_verification()
    
    example_curl_commands()
    
    print("\n" + "#" * 60)
    print("# End of Examples")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
