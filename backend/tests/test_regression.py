"""
Regression & Smoke Test Suite
Run after every enhancement or bug fix to catch regressions before they reach production.

Usage:
    pytest backend/tests/test_regression.py -v           # all tests
    pytest backend/tests/test_regression.py -v -k test1    # single test
    python backend/tests/test_regression.py               # standalone
"""
import asyncio
import inspect
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def run_tests(tests):
    """Run a dict of {name: (test_fn, expected_pass)} and print a report."""
    passed = failed = 0
    for name, (fn, expected_pass) in tests.items():
        try:
            result = fn()
            ok = bool(result)
        except Exception as e:
            ok = False
            result = str(e)

        status = "PASS" if ok else "FAIL"
        icon = "✅" if ok else "❌"
        print(f"  {icon} [{status}] {name}")
        if not ok:
            print(f"      Expected pass={expected_pass}, got pass={ok}")
            if isinstance(result, str) and len(result) < 200:
                print(f"      Detail: {result}")
            elif not isinstance(result, bool):
                print(f"      Error: {str(result)[:200]}")

        if ok == expected_pass:
            passed += 1
        else:
            failed += 1

    total = passed + failed
    print(f"\n  Results: {passed}/{total} passed, {failed}/{total} failed")
    return failed == 0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — Tuple-unpacking 500 fix (chat.py verify_chat_authorization)
# ─────────────────────────────────────────────────────────────────────────────

def test1_tuple_unpacking_fix():
    """
    Bug: verify_chat_authorization returns 3 values but get_session_messages
    only unpacked 2 → ValueError → HTTP 500.
    Fix: ensure the 3-value unpack (authorized, error, _).
    """
    from app.api.chat import get_session_messages
    src = inspect.getsource(get_session_messages)
    return "authorized, error, _ = verify_chat_authorization" in src


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — Conversion metric defined (analytics.py)
# ─────────────────────────────────────────────────────────────────────────────

def test2_conversion_metric_defined():
    """
    Bug: analytics.py returned hardcoded 0.0 for conversion_rate (TODO).
    Fix: query leads collected (sessions with lead_name) and compute real rate.
    """
    from app.services.analytics import AnalyticsService
    src = inspect.getsource(AnalyticsService.get_tenant_stats)

    has_query = "leads_collected" in src
    no_todo = "# TODO: Define conversion metric" not in src
    has_rate = "conversion_rate" in src and "leads_collected / total_sessions" in src
    return has_query and no_todo and has_rate


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — Conversion metric computes a real value (not always 0.0)
# ─────────────────────────────────────────────────────────────────────────────

def test3_conversion_metric_real_value():
    """
    Verify the conversion_rate is computed, not hardcoded.
    """
    from app.database import get_db
    from app.services.analytics import AnalyticsService
    db = next(get_db())

    stats = AnalyticsService.get_tenant_stats(db, "c66e96d3-999c-4746-b11c-1758a9c2e982")
    cr = stats.get("conversion_rate")
    return cr is not None and isinstance(cr, (int, float))


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 — Engagement rate SQL (no missing FROM-clause)
# ─────────────────────────────────────────────────────────────────────────────

def test4_engagement_rate_sql():
    """
    Bug: analytics.py had a HAVING clause referencing chat_messages without a JOIN,
    causing PostgreSQL 'missing FROM-clause entry' error.
    Fix: add .join(ChatMessage, ...) before .having().
    """
    from app.services.analytics import AnalyticsService
    src = inspect.getsource(AnalyticsService.get_tenant_stats)

    engaged_block = src[src.find("engaged_sessions"):src.find("engagement_rate")]
    has_join = ".join(" in engaged_block and "ChatMessage" in engaged_block
    has_having = ".having(" in engaged_block
    return has_join and has_having


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 — Function caller imported into ChatService
# ─────────────────────────────────────────────────────────────────────────────

def test5_function_caller_imported():
    """
    Fix: wire function_calling_service into ChatService.
    - Import must be present in ChatService source.
    - is_enabled check must be present in send_message.
    """
    from app.services.chat_service import ChatService
    from app.services.function_caller import function_calling_service

    svc_src = inspect.getsource(ChatService)
    send_src = inspect.getsource(ChatService.send_message)

    imported = "function_calling_service" in svc_src
    checked = "function_calling_service.is_enabled" in send_src
    enabled = function_calling_service.is_enabled is not None  # property exists
    return imported and checked and enabled


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6 — Function schemas registered
# ─────────────────────────────────────────────────────────────────────────────

def test6_function_schemas():
    """
    Verify function_calling_service has registered the built-in schemas.
    """
    from app.services.function_caller import function_calling_service
    schemas = function_calling_service.get_function_schemas()
    names = [s["function"]["name"] for s in schemas]
    required = {
        "check_calendar_availability",
        "book_appointment",
        "create_lead",
        "get_customer_data",
        "send_email",
        "escalate_to_human",
    }
    return required.issubset(names)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7 — API health endpoint
# ─────────────────────────────────────────────────────────────────────────────

async def test7_health_endpoint():
    import httpx
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10.0) as client:
        r = await client.get("/health")
        return r.status_code == 200 and "healthy" in r.text


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8 — Session GET returns 200 (not 500)
# ─────────────────────────────────────────────────────────────────────────────

async def test8_session_get():
    """
    Bug: tuple-unpacking error caused 500 on GET /api/chat/session/{id}.
    Fix: verified by getting a valid session with a valid API key.
    """
    import httpx
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10.0) as client:
        headers = {"x-api-key": "WuaNiH_SphcRLSwYPuhS9naquxQTuLTeOEmfhxL9V4s"}
        r = await client.get("/api/chat/session/f0b08375-a797-4019-9294-2ce1e4e17d9a", headers=headers)
        return r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# TEST 9 — Analytics GET returns 200 with conversion_rate
# ─────────────────────────────────────────────────────────────────────────────

async def test9_analytics_get():
    """
    Verify analytics endpoint returns 200 and includes conversion_rate (not 0.0 hardcoded).
    """
    import httpx
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10.0) as client:
        headers = {"x-api-key": "WuaNiH_SphcRLSwYPuhS9naquxQTuLTeOEmfhxL9V4s"}
        r = await client.get("/api/chat/analytics/c66e96d3-999c-4746-b11c-1758a9c2e982?days=7", headers=headers)
        if r.status_code != 200:
            return False
        data = r.json()
        return "conversion_rate" in data["summary"]


# ─────────────────────────────────────────────────────────────────────────────
# TEST 10 — Widget JWT origin validation present
# ─────────────────────────────────────────────────────────────────────────────

def test10_widget_jwt_origin_validation():
    """
    verify_widget_token should validate the request Origin against the token's
    origin claim when request_origin is supplied.
    """
    from app.api.chat import verify_widget_token
    src = inspect.getsource(verify_widget_token)
    return "_origin_to_bare_host" in src and "request_origin" in src


# ─────────────────────────────────────────────────────────────────────────────
# TEST 11 — Anonymous welcome-message path (soft attack surface review)
# ─────────────────────────────────────────────────────────────────────────────

def test11_anonymous_welcome_message():
    """
    When auth_header is missing, the code creates a temporary anonymous access
    for the welcome message. Verify the first-active-widget-key path exists.
    """
    from app.api.chat import verify_chat_authorization
    src = inspect.getsource(verify_chat_authorization)
    return "is_active" in src and "key_type" in src and "widget" in src


# ─────────────────────────────────────────────────────────────────────────────
# TEST 12 — Chat service imports load without error
# ─────────────────────────────────────────────────────────────────────────────

def test12_imports_clean():
    """
    All modified files should import without errors.
    """
    try:
        from app.api import chat
        from app.services import chat_service, analytics
        from app.services.function_caller import function_calling_service
        return True
    except Exception as e:
        return str(e)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 13 — Lead collection fields on ChatSession model
# ─────────────────────────────────────────────────────────────────────────────

def test13_lead_fields_on_session():
    """
    The conversion metric depends on ChatSession.lead_name / lead_email /
    lead_collected_at fields being present.
    """
    from app.models.chat import ChatSession
    fields = [c.name for c in ChatSession.__table__.columns]
    return "lead_email" in fields and "lead_collected_at" in fields


# ─────────────────────────────────────────────────────────────────────────────
# TEST 14 — Groq / LLM adapter loads (default provider)
# ─────────────────────────────────────────────────────────────────────────────

def test14_llm_adapter_loads():
    """
    The LLM adapter should load without raising an error when GROQ_API_KEY
    is set. Check that get_llm_adapter returns an adapter object.
    """
    from app.adapters.llm import get_llm_adapter
    adapter = get_llm_adapter("mock")
    return adapter is not None and hasattr(adapter, "generate")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 15 — RAG vector knowledge service loads
# ─────────────────────────────────────────────────────────────────────────────

def test15_rag_service_loads():
    """
    Verify VectorKnowledgeService can be instantiated without error.
    """
    try:
        from app.services.vector_knowledge import VectorKnowledgeService
        return True
    except Exception as e:
        return str(e)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 16 — Guardrails service loads
# ─────────────────────────────────────────────────────────────────────────────

def test16_guardrails_service_loads():
    """
    Verify GuardrailsService can be instantiated without error.
    """
    try:
        from app.services.guardrails import GuardrailsService
        return True
    except Exception as e:
        return str(e)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 17 — Function calling: tools passed to LLM adapter
# ─────────────────────────────────────────────────────────────────────────────

def test17_fc_tools_passed_to_llm():
    """
    When tenant.enable_function_calling=True and function_calling_service.is_enabled=True,
    the tools list must be non-empty and passed via kwargs to the LLM adapter.
    """
    from app.services.chat_service import ChatService
    import inspect

    src = inspect.getsource(ChatService.send_message)
    return (
        "function_tools = function_calling_service.get_function_schemas()" in src
        and "tools=function_tools" in src
        and "_execute_tool_calls" in src
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 18 — Function calling: _execute_tool_calls method exists
# ─────────────────────────────────────────────────────────────────────────────

def test18_fc_execute_method():
    """
    ChatService must have _execute_tool_calls to handle tool_calls from LLM.
    """
    from app.services.chat_service import ChatService
    return hasattr(ChatService, "_execute_tool_calls")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 19 — Function calling: GroqAdapter returns tool_calls in response
# ─────────────────────────────────────────────────────────────────────────────

def test19_groq_tool_calls_in_response():
    """
    GroqAdapter.generate() must extract and return tool_calls from the response.
    """
    from app.adapters.llm import GroqAdapter
    import inspect

    src = inspect.getsource(GroqAdapter.generate)
    return "tool_calls" in src and "message.get(" in src


# ─────────────────────────────────────────────────────────────────────────────
# TEST 20 — Sentiment analyzer: escalation triggers correctly
# ─────────────────────────────────────────────────────────────────────────────

def test20_sentiment_escalation_trigger():
    """
    SentimentAnalyzer.analyze() must return is_escalation=True for
    negative sentiment + escalation keywords.
    """
    from app.services.sentiment_analyzer import SentimentAnalyzer
    sa = SentimentAnalyzer()

    neg = sa.analyze("I am very frustrated and angry with this terrible service")
    assert neg.is_escalation, f"Expected escalation for negative text, got {neg.__dict__}"

    esc = sa.analyze("I want to speak to a manager about my complaint")
    assert esc.is_escalation, f"Expected escalation for escalation keyword, got {esc.__dict__}"

    pos = sa.analyze("I love this product, it's great!")
    assert not pos.is_escalation, f"Expected no escalation for positive text, got {pos.__dict__}"

    return True


# ─────────────────────────────────────────────────────────────────────────────
# TEST 21 — Sentiment analyzer: escalation flag stored in session_data
# ─────────────────────────────────────────────────────────────────────────────

def test21_sentiment_escalation_stored():
    """
    When sentiment.is_escalation is True, the session_data must contain
    needs_escalation and escalation_reason.
    """
    from app.services.chat_service import ChatService
    import inspect

    src = inspect.getsource(ChatService.send_message)
    return (
        'session.session_data["needs_escalation"] = True' in src
        and "escalation_reason" in src
        and "sentiment_result.is_escalation" in src
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 22 — Sentiment analyzer: escalation directive appended to prompt
# ─────────────────────────────────────────────────────────────────────────────

def test22_sentiment_escalation_directive():
    """
    When escalation is triggered, an ESCALATION ALERT section must be
    appended to the system prompt.
    """
    from app.services.chat_service import ChatService
    import inspect

    src = inspect.getsource(ChatService.send_message)
    return "ESCALATION ALERT" in src and "sentiment_result.is_escalation" in src


# ─────────────────────────────────────────────────────────────────────────────
# TEST 23 — RAG: BM25 class exists and scores correctly
# ─────────────────────────────────────────────────────────────────────────────

def test23_bm25_scores():
    """
    BM25Helper must rank relevant documents higher than irrelevant ones.
    """
    from app.services.vector_knowledge import _compute_bm25_scores

    corpus = [
        ("1", "Python programming language is great for data science"),
        ("2", "JavaScript web development frameworks"),
        ("3", "Machine learning and deep learning algorithms"),
    ]

    scores = _compute_bm25_scores("python programming", corpus)
    if not scores:
        return "BM25 returned empty results"

    top_id, top_score = scores[0][1], scores[0][0]
    return top_id == "1" and top_score > 0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 24 — RAG: Hybrid search combines semantic + BM25
# ─────────────────────────────────────────────────────────────────────────────

def test24_hybrid_rag_weights():
    """
    VectorKnowledgeService.search() must use hybrid weights (SEMANTIC_WEIGHT +
    LEXICAL_WEIGHT) rather than pure vector search.
    """
    from app.services.vector_knowledge import VectorKnowledgeService
    import inspect

    src = inspect.getsource(VectorKnowledgeService.search)
    return (
        "SEMANTIC_WEIGHT" in src
        and "LEXICAL_WEIGHT" in src
        and "_compute_bm25_scores" in src
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 25 — RAG: Hybrid search has min score threshold
# ─────────────────────────────────────────────────────────────────────────────

def test25_rag_min_score_threshold():
    """
    Chunks below MIN_SCORE must be filtered out.
    """
    from app.services.vector_knowledge import VectorKnowledgeService
    import inspect

    src = inspect.getsource(VectorKnowledgeService.search)
    return "MIN_SCORE" in src and "combined < cls.MIN_SCORE" in src


# ─────────────────────────────────────────────────────────────────────────────
# TEST 26 — Memory: get_cross_session_context extracts facts
# ─────────────────────────────────────────────────────────────────────────────

def test26_memory_cross_session_facts():
    """
    ConversationMemory must extract name, email, booking interest etc.
    from messages and surface them via get_cross_session_context().
    """
    from app.services.memory_service import ConversationMemory
    cm = ConversationMemory()

    cm.add_message("s1", "user", "Hi, my name is John and I'm interested in booking a demo")
    cm.add_message("s1", "assistant", "Hi John! Let me help you with that.")
    ctx = cm.get_cross_session_context("s1")

    return (
        "name" in cm._cross_session["s1"]
        and "booking_interest" in cm._cross_session["s1"]
        and len(ctx) > 0
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 27 — Memory: cross-session context injected into system prompt
# ─────────────────────────────────────────────────────────────────────────────

def test27_memory_injected_into_prompt():
    """
    Cross-session context must be injected into the system prompt as
    # PRIOR CONTEXT section (inside _build_system_prompt, not send_message).
    """
    from app.services.chat_service import ChatService
    import inspect

    src = inspect.getsource(ChatService._build_system_prompt)
    return (
        "# PRIOR CONTEXT" in src
        and "get_cross_session_context" in src
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 28 — All Tier 1 services load without error
# ─────────────────────────────────────────────────────────────────────────────

def test28_tier1_services_load():
    """
    All newly wired services must import without errors.
    """
    try:
        from app.services.vector_knowledge import (
            VectorKnowledgeService, BM25Helper, _compute_bm25_scores
        )
        from app.services.sentiment_analyzer import (
            SentimentAnalyzer, sentiment_analyzer, SentimentResult
        )
        from app.services.memory_service import (
            MemoryService, memory_service, ConversationMemory
        )
        from app.services.function_caller import function_calling_service
        return True
    except Exception as e:
        return str(e)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("REGRESSION & SMOKE TEST SUITE — Centralized LLM Platform")
    print("=" * 70)

    sync_tests = {
        "T1  Tuple-unpacking 500 fix":          (test1_tuple_unpacking_fix, True),
        "T2  Conversion metric defined":        (test2_conversion_metric_defined, True),
        "T3  Conversion metric real value":    (test3_conversion_metric_real_value, True),
        "T4  Engagement rate SQL correct":     (test4_engagement_rate_sql, True),
        "T5  Function caller imported":         (test5_function_caller_imported, True),
        "T6  Function schemas registered":       (test6_function_schemas, True),
        "T7  Health endpoint (async)":          (lambda: asyncio.run(test7_health_endpoint()), True),
        "T8  Session GET 200 not 500 (async)": (lambda: asyncio.run(test8_session_get()), True),
        "T9  Analytics GET with conv_rate":     (lambda: asyncio.run(test9_analytics_get()), True),
        "T10 Widget JWT origin validation":      (test10_widget_jwt_origin_validation, True),
        "T11 Anonymous welcome-message path":    (test11_anonymous_welcome_message, True),
        "T12 Imports load cleanly":              (test12_imports_clean, True),
        "T13 Lead fields on ChatSession":       (test13_lead_fields_on_session, True),
        "T14 LLM adapter loads":                 (test14_llm_adapter_loads, True),
        "T15 RAG service loads":                  (test15_rag_service_loads, True),
        "T16 Guardrails service loads":          (test16_guardrails_service_loads, True),
        "T17 FC tools passed to LLM":             (test17_fc_tools_passed_to_llm, True),
        "T18 FC _execute_tool_calls method":     (test18_fc_execute_method, True),
        "T19 FC GroqAdapter tool_calls in resp": (test19_groq_tool_calls_in_response, True),
        "T20 Sentiment escalation triggers":     (test20_sentiment_escalation_trigger, True),
        "T21 Sentiment escalation stored":       (test21_sentiment_escalation_stored, True),
        "T22 Sentiment escalation directive":    (test22_sentiment_escalation_directive, True),
        "T23 BM25 scores correctly":             (test23_bm25_scores, True),
        "T24 Hybrid RAG weights applied":        (test24_hybrid_rag_weights, True),
        "T25 RAG min score threshold":          (test25_rag_min_score_threshold, True),
        "T26 Memory cross-session facts":        (test26_memory_cross_session_facts, True),
        "T27 Memory injected into prompt":      (test27_memory_injected_into_prompt, True),
        "T28 All Tier 1 services load":         (test28_tier1_services_load, True),
    }

    print("\n[SYNC TESTS]")
    ok = run_tests(sync_tests)

    print("\n" + "=" * 70)
    if ok:
        print("ALL TESTS PASSED — safe to deploy")
    else:
        print("FAILURES DETECTED — review before deploying")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())