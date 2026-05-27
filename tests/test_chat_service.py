"""
Test chat service layer
"""
import pytest
from app.services.chat_service import ChatService
from app.services.self_learning import _promote_to_structured_faq
from app.services.website_crawler import WebsiteCrawlerService
from app.models import Tenant, ChatMessage


@pytest.mark.asyncio
async def test_chat_service_send_message(db):
    """Test ChatService.send_message with mock adapter"""
    # Create tenant
    tenant = Tenant(
        name="Service Test Tenant",
        slug="service-test",
        domain="service-test.com",
        model_name="test-model",
        temperature=0.7,
        max_tokens=100
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    
    # Initialize service with mock provider
    service = ChatService(db=db, llm_provider="mock")
    
    # Send message
    result = await service.send_message(
        tenant_id=tenant.id,
        content="Hello, test message",
        user_id="test-user-1"
    )
    
    assert result["role"] == "assistant"
    assert result["content"] is not None
    assert result["session_id"] is not None
    assert result["model_used"] == "test-model"
    assert "latency_ms" in result


@pytest.mark.asyncio
async def test_chat_service_with_session(db):
    """Test sending messages in the same session"""
    # Create tenant
    tenant = Tenant(
        name="Session Test Tenant",
        slug="session-test",
        domain="session-test.com"
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    
    service = ChatService(db=db, llm_provider="mock")
    
    # Send first message
    result1 = await service.send_message(
        tenant_id=tenant.id,
        content="First message"
    )
    session_id = result1["session_id"]
    
    # Send second message in same session
    result2 = await service.send_message(
        tenant_id=tenant.id,
        content="Second message",
        session_id=session_id
    )
    
    assert result2["session_id"] == session_id
    
    # Get all messages
    messages = service.get_session_messages(session_id)
    # Should have at least 4 messages (2 user + 2 assistant)
    assert len(messages) >= 4


@pytest.mark.asyncio
async def test_chat_service_invalid_tenant(db):
    """Test sending message to non-existent tenant"""
    service = ChatService(db=db, llm_provider="mock")
    
    with pytest.raises(ValueError, match="not found"):
        await service.send_message(
            tenant_id="invalid-tenant-id",
            content="Test message"
        )


@pytest.mark.asyncio
async def test_chat_service_llm_failure_returns_polite_message_and_metadata(db):
    tenant = Tenant(
        name="Nivra Studios",
        slug="nivra-studios",
        domain="nivra.example",
        model_name="test-model",
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    class AlwaysFailAdapter:
        async def generate(self, *args, **kwargs):
            return {
                "success": False,
                "error": "All providers failed. Last error: openrouter: 402 insufficient credits",
                "provider_timings": {"groq_attempt_0": 321, "gemini_attempt_0": 415, "openrouter_attempt_0": 278},
                "provider_failures": [
                    {"provider": "groq", "error_kind": "rate_limited", "status_code": 429},
                    {"provider": "gemini", "error_kind": "timeout", "status_code": 504},
                    {"provider": "openrouter", "error_kind": "insufficient_credits", "status_code": 402},
                ],
            }

    service = ChatService(db=db, llm_provider="mock")
    service.llm_adapter = AlwaysFailAdapter()

    result = await service.send_message(
        tenant_id=tenant.id,
        content="Can we continue?",
    )

    assert result["role"] == "assistant"
    content_lower = result["content"].lower()
    assert ("temporarily" in content_lower) or ("still help" in content_lower)
    assert "402" not in result["content"]
    assert "insufficient credits" not in result["content"].lower()

    assistant_msg = db.query(ChatMessage).filter(
        ChatMessage.id == result["id"],
        ChatMessage.role == "assistant",
    ).first()
    assert assistant_msg is not None
    assert assistant_msg.msg_metadata.get("llm_failure") is True
    assert isinstance(assistant_msg.msg_metadata.get("provider_failures"), list)


def test_get_session_messages_invalid(db):
    """Test getting messages from non-existent session"""
    service = ChatService(db=db, llm_provider="mock")
    
    with pytest.raises(ValueError, match="not found"):
        service.get_session_messages("invalid-session-id")


@pytest.mark.asyncio
async def test_chat_service_with_context(db):
    """Test that tenant context is used in prompts"""
    # Create tenant with custom context
    tenant = Tenant(
        name="Context Test Tenant",
        slug="context-test",
        domain="context-test.com",
        prompt_template="You are a helpful assistant.",
        knowledge_context="Important context information"
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    
    service = ChatService(db=db, llm_provider="mock")
    
    # Send message
    result = await service.send_message(
        tenant_id=tenant.id,
        content="Test with context"
    )
    
    # Should succeed and return a response
    assert result["content"] is not None
    assert result["role"] == "assistant"


@pytest.mark.asyncio
async def test_dynamic_knowledge_context_product_alias_match(db):
    """Tenant knowledge_context dict should surface relevant product by alias dynamically."""
    tenant = Tenant(
        name="Scube Tenant",
        slug="scube-test",
        domain="scubeinfotech.com.sg",
        prompt_template="You are SCUBE assistant.",
        knowledge_context={
            "company_overview": "SCUBE provides IT and business software solutions.",
            "products": [
                {
                    "name": "ChronoBill",
                    "aliases": ["chronobill", "chrono bill"],
                    "description": "Cloud billing and invoicing platform",
                    "features": ["Invoice automation", "Payment tracking", "Client portal"]
                },
                {
                    "name": "OtherSuite",
                    "aliases": ["othersuite"],
                    "description": "General ERP platform"
                }
            ]
        }
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    service = ChatService(db=db, llm_provider="mock")

    # Create a session and inject product interest in conversation history.
    first = await service.send_message(tenant_id=tenant.id, content="I need chronobill")

    system_prompt = service._build_system_prompt(tenant, first["session_id"])

    assert "ChronoBill" in system_prompt
    assert "Invoice automation" in system_prompt


@pytest.mark.asyncio
async def test_dynamic_knowledge_context_graceful_without_match(db):
    """Dynamic context should still include baseline product entries when no lexical match is found."""
    tenant = Tenant(
        name="No Match Tenant",
        slug="no-match-tenant",
        domain="nomatch.com",
        knowledge_context={
            "products": [
                {"name": "Alpha", "description": "Alpha product"},
                {"name": "Beta", "description": "Beta product"}
            ]
        }
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    service = ChatService(db=db, llm_provider="mock")
    first = await service.send_message(tenant_id=tenant.id, content="Tell me about your platform")

    system_prompt = service._build_system_prompt(tenant, first["session_id"])
    assert "Products:" in system_prompt
    assert "Alpha" in system_prompt


@pytest.mark.asyncio
async def test_short_follow_up_is_enriched_with_previous_context(db):
    """Short follow-ups like product/device names should inherit prior turn context."""
    tenant = Tenant(
        name="Follow Up Tenant",
        slug="follow-up-tenant",
        domain="followup.com",
        industry="services",
        prompt_template="You are a service advisor."
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    service = ChatService(db=db, llm_provider="mock")
    first = await service.send_message(tenant_id=tenant.id, content="I need computer")

    enriched = service._enrich_user_message_for_llm(first["session_id"], "MiniPC")

    assert "Current user follow-up: MiniPC" in enriched
    assert "Previous user request: I need computer" in enriched
    assert "Interpret the current user follow-up as a refinement" in enriched


def test_short_follow_up_detection():
    service = ChatService(db=None, llm_provider="mock")

    assert service._is_short_follow_up("MiniPC") is True
    assert service._is_short_follow_up("pricing") is True
    assert service._is_short_follow_up("Tell me more about your managed services") is False


def test_contextual_follow_up_detection_for_pricing_reference():
    service = ChatService(db=None, llm_provider="mock")

    assert service._needs_contextual_enrichment("do i need to pay for it") is True
    assert service._needs_contextual_enrichment("is it free") is True
    assert service._needs_contextual_enrichment("Tell me about your managed services in Singapore") is False


def test_business_scope_instructions_include_out_of_scope_mode():
    service = ChatService(db=None, llm_provider="mock")
    tenant = Tenant(
        name="Boundary Tenant",
        slug="boundary-tenant",
        domain="boundary.com",
        industry="services",
        out_of_scope_mode="strict_business",
        cta_goals=["lead", "support"]
    )

    instructions = service._build_business_scope_instructions(tenant)
    assert "Out-of-scope mode: strict_business" in instructions
    assert "respond politely" in instructions


def test_business_scope_instructions_assistive_general_mode():
    service = ChatService(db=None, llm_provider="mock")
    tenant = Tenant(
        name="Assistive Tenant",
        slug="assistive-tenant",
        domain="assistive.com",
        industry="services",
        out_of_scope_mode="assistive_general"
    )

    instructions = service._build_business_scope_instructions(tenant)
    assert "Out-of-scope mode: assistive_general" in instructions
    assert "one short general suggestion" in instructions


def test_infer_response_language_defaults_to_english(db):
    service = ChatService(db=db, llm_provider="mock")
    lang = service._infer_response_language(session_id=None, user_message="Can you share your pricing details?")
    assert lang == "english"


def test_infer_response_language_detects_tamil_script(db):
    service = ChatService(db=db, llm_provider="mock")
    lang = service._infer_response_language(session_id=None, user_message="வணக்கம், உங்கள் சேவை என்ன?")
    assert lang == "tamil"


def test_infer_response_language_detects_romanized_tamil(db):
    service = ChatService(db=db, llm_provider="mock")
    lang = service._infer_response_language(session_id=None, user_message="Neenga enna service kudupeenga")
    assert lang == "tamil"


def test_infer_response_language_detects_malay(db):
    service = ChatService(db=db, llm_provider="mock")
    lang = service._infer_response_language(session_id=None, user_message="Boleh saya tahu harga dan pakej anda?")
    assert lang == "malay"


def test_infer_response_language_detects_singlish(db):
    service = ChatService(db=db, llm_provider="mock")
    lang = service._infer_response_language(session_id=None, user_message="Can or not? This one good lah")
    assert lang == "singlish"


def test_infer_response_language_detects_chinese_script(db):
    service = ChatService(db=db, llm_provider="mock")
    lang = service._infer_response_language(session_id=None, user_message="你好，请介绍一下你们的服务")
    assert lang == "chinese"


def test_infer_response_language_chinese_override_phrase(db):
    service = ChatService(db=db, llm_provider="mock")
    lang = service._infer_response_language(session_id=None, user_message="in chinese please")
    assert lang == "chinese"


def test_infer_response_language_malay_override_phrase(db):
    service = ChatService(db=db, llm_provider="mock")
    lang = service._infer_response_language(session_id=None, user_message="dalam bahasa melayu")
    assert lang == "malay"


def test_infer_response_language_english_override_phrase(db):
    service = ChatService(db=db, llm_provider="mock")
    lang = service._infer_response_language(session_id=None, user_message="in english please")
    assert lang == "english"


def test_infer_response_language_does_not_flip_tamil_on_english_service_request(db):
    service = ChatService(db=db, llm_provider="mock")
    service._get_recent_user_text_for_session = lambda session_id, limit=4: "I need 10 laptop for my company and service support"
    lang = service._infer_response_language(
        session_id="dummy-session",
        user_message="I need 10 laptop for my company and service support",
    )
    assert lang == "english"


def test_system_prompt_includes_language_policy(db):
    tenant = Tenant(
        name="Language Tenant",
        slug="language-tenant",
        domain="language.com"
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    service = ChatService(db=db, llm_provider="mock")
    prompt = service._build_system_prompt(tenant, preferred_language="malay")

    assert "Language policy:" in prompt
    assert "Detected preferred language: Malay" in prompt
    assert "default to clear English" in prompt


def test_system_prompt_includes_chinese_policy(db):
    tenant = Tenant(
        name="Chinese Tenant",
        slug="chinese-tenant",
        domain="chinese.com"
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    service = ChatService(db=db, llm_provider="mock")
    prompt = service._build_system_prompt(tenant, preferred_language="chinese")

    assert "Detected preferred language: Chinese" in prompt
    assert "Simplified Chinese" in prompt


def test_system_prompt_preserves_exact_brand_name(db):
    tenant = Tenant(
        name="SCUBE Infotech",
        slug="scube-infotech",
        domain="scubeinfotech.com"
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    service = ChatService(db=db, llm_provider="mock")
    prompt = service._build_system_prompt(tenant, preferred_language="tamil")

    assert "Brand name rule:" in prompt
    assert "Never translate, transliterate" in prompt
    assert "Use this exact company name when needed: SCUBE Infotech." in prompt


def test_system_prompt_includes_greeting_safeguard(db):
    tenant = Tenant(
        name="Greeting Guard Tenant",
        slug="greeting-guard-tenant",
        domain="guard.com"
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    service = ChatService(db=db, llm_provider="mock")
    prompt = service._build_system_prompt(tenant, preferred_language="english")

    assert "greeting-only turn" in prompt
    assert "one short greeting line" in prompt


def test_postprocess_strict_business_refusal_is_polite():
    service = ChatService(db=None, llm_provider="mock")
    tenant = Tenant(
        name="Polite Boundary Tenant",
        slug="polite-boundary-tenant",
        domain="polite-boundary.com",
        industry="services",
        out_of_scope_mode="strict_business"
    )

    final_text = service._postprocess_assistant_content(
        tenant=tenant,
        user_message="i need 2 idly 1 dosa",
        assistant_content="I can't help with that request. Is there something else I can assist you with?"
    )

    assert "I may not be the right assistant" in final_text
    assert "can't help with that request" not in final_text.lower()


def test_infer_assistant_question_intent_recommendations():
    service = ChatService(db=None, llm_provider="mock")
    assistant_reply = (
        "I'm a service advisor for SCUBE. "
        "If you're looking for food recommendations, I can suggest some South Indian restaurants. "
        "Would you like some recommendations?"
    )

    intent = service._infer_assistant_question_intent(assistant_reply)
    assert intent == "recommendations"


def test_is_greeting_handles_punctuation_and_fillers():
    service = ChatService(db=None, llm_provider="mock")

    assert service._is_greeting("Hi!") is True
    assert service._is_greeting("Hello there!!!") is True
    assert service._is_greeting("hey assistant") is True


def test_is_greeting_does_not_swallow_business_query():
    service = ChatService(db=None, llm_provider="mock")

    assert service._is_greeting("Hi, what is your pricing?") is False
    assert service._is_greeting("Hello can I book a demo") is False


@pytest.mark.asyncio
async def test_affirmation_follow_up_binds_to_previous_assistant_question(db):
    tenant = Tenant(
        name="Affirmation Tenant",
        slug="affirmation-tenant",
        domain="affirmation.com",
        industry="services",
        prompt_template="You are a service advisor."
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    service = ChatService(db=db, llm_provider="mock")
    first = await service.send_message(tenant_id=tenant.id, content="i need 2 idly 1 dosa")

    # Overwrite latest assistant message to simulate an explicit recommendation question.
    assistant_msg = db.query(ChatMessage).filter(
        ChatMessage.session_id == first["session_id"],
        ChatMessage.role == "assistant"
    ).order_by(ChatMessage.created_at.desc()).first()
    assistant_msg.content = "Would you like some recommendations?"
    db.commit()

    enriched = service._enrich_user_message_for_llm(first["session_id"], "yes")
    assert "affirmative reply" in enriched
    assert "recommendations" in enriched


@pytest.mark.asyncio
async def test_pricing_follow_up_is_enriched_with_previous_topic(db):
    tenant = Tenant(
        name="Pricing Tenant",
        slug="pricing-tenant",
        domain="pricing.com",
        industry="services",
        prompt_template="You are a helpful business assistant.",
        knowledge_context={
            "products": [
                {
                    "name": "SCUBE AI Chatbot",
                    "description": "AI chatbot for websites and customer engagement",
                }
            ],
            "business_facts": [
                {
                    "topic": "pricing",
                    "statement": "SCUBE AI chatbot is free to use. No credit card and no registration are required.",
                    "source_url": "https://example.com/chatbot",
                }
            ],
        },
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    service = ChatService(db=db, llm_provider="mock")
    first = await service.send_message(tenant_id=tenant.id, content="do you have chatbot ai")

    enriched = service._enrich_user_message_for_llm(first["session_id"], "do i need to pay for it")
    retrieval_query = service._build_retrieval_query(first["session_id"], "do i need to pay for it")
    prompt_context = service._format_dict_knowledge_context(tenant.knowledge_context, {"pay", "pricing", "free"})

    assert "Previous user request: do you have chatbot ai" in enriched
    assert "do you have chatbot ai" in retrieval_query
    assert "SCUBE AI chatbot is free to use" in prompt_context


def test_website_crawler_extracts_business_facts_for_free_access_copy():
    facts = WebsiteCrawlerService._extract_business_facts(
        title="SCUBE AI Chatbot",
        description="AI chatbot for customer engagement.",
        headings=["Pricing", "Get Started"],
        content=(
            "Our chatbot is free to use for website visitors. "
            "No credit card required. No registration needed to start. "
            "Book a demo if you want enterprise features."
        ),
        url="https://example.com/chatbot",
    )

    statements = [fact["statement"] for fact in facts]
    topics = {fact["topic"] for fact in facts}

    assert any("free to use" in statement.lower() for statement in statements)
    assert any("no credit card required" in statement.lower() for statement in statements)
    assert "pricing" in topics
    assert "access" in topics


def test_promote_to_structured_faq_adds_verified_entry():
    tenant = Tenant(
        name="Learning Tenant",
        slug="learning-tenant",
        domain="learning.com",
        knowledge_context={"faqs": []},
    )

    changed = _promote_to_structured_faq(
        tenant,
        user_query="Do I need to pay for the chatbot?",
        assistant_response="No. The chatbot is free to use and does not require registration.",
        confidence=0.95,
        explicit_thumbs_up=True,
    )

    assert changed is True
    faqs = tenant.knowledge_context.get("faqs")
    assert len(faqs) == 1
    assert faqs[0]["question"] == "Do I need to pay for the chatbot?"
    assert faqs[0]["verified"] is True
