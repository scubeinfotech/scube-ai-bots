"""
LLM Adapter tests
"""
import pytest
from app.adapters import get_llm_adapter, MockAdapter, GroqAdapter, RouterAdapter
import os


@pytest.mark.asyncio
async def test_mock_adapter():
    """Test mock LLM adapter"""
    adapter = MockAdapter()
    
    result = await adapter.generate(
        prompt="What is 2+2?",
        model="mock-model"
    )
    
    assert result["success"] is True
    assert "response" in result
    assert result["model"] == "mock-model"
    assert result["latency_ms"] > 0


def test_get_adapter_mock():
    """Test getting mock adapter"""
    adapter = get_llm_adapter("mock")
    assert isinstance(adapter, MockAdapter)


@pytest.mark.asyncio
async def test_ollama_adapter_unavailable():
    """Test Ollama adapter when service unavailable"""
    adapter = get_llm_adapter("ollama", "http://localhost:99999")
    
    result = await adapter.generate(
        prompt="Test",
        model="llama3.1:8b"
    )
    
    # Should return error response
    assert result["success"] is False
    assert "error" in result


def test_get_adapter_groq():
    """Test getting Groq adapter"""
    # Test with explicit API key
    try:
        adapter = get_llm_adapter("groq", api_key="test_key_12345")
        assert isinstance(adapter, GroqAdapter)
    except ValueError as e:
        # Expected if no API key provided
        assert "API key" in str(e)


@pytest.mark.asyncio
async def test_groq_adapter_without_key():
    """Test Groq adapter fails gracefully without API key"""
    # Clear env variable if set
    old_key = os.environ.get("GROQ_API_KEY")
    if "GROQ_API_KEY" in os.environ:
        del os.environ["GROQ_API_KEY"]
    
    try:
        # Should raise error without API key
        with pytest.raises(ValueError, match="API key"):
            adapter = get_llm_adapter("groq")
    finally:
        # Restore old key if it existed
        if old_key:
            os.environ["GROQ_API_KEY"] = old_key


@pytest.mark.asyncio
async def test_groq_adapter_with_invalid_key():
    """Test Groq adapter with invalid API key"""
    adapter = GroqAdapter(api_key="invalid_test_key_12345")
    
    result = await adapter.generate(
        prompt="Test prompt",
        model="llama-3.1-8b-instant"
    )
    
    # Should return error response with invalid key
    assert result["success"] is False
    assert "error" in result


def test_unknown_provider():
    """Test getting unknown provider raises error"""
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_llm_adapter("nonexistent-provider")


@pytest.mark.asyncio
async def test_router_primary_success(monkeypatch):
    """Router should return primary response when first provider succeeds."""
    router = RouterAdapter(provider_chain=["groq", "gemini"], max_retries=0, provider_timeout_ms=1000)

    class _FakeSuccessAdapter:
        def __init__(self):
            self.calls = 0

        async def generate(self, *args, **kwargs):
            self.calls += 1
            return {
                "success": True,
                "response": "primary ok",
                "model": "fake-primary",
                "tokens": 5,
                "latency_ms": 10,
            }

    class _FakeSecondaryAdapter:
        def __init__(self):
            self.calls = 0

        async def generate(self, *args, **kwargs):
            self.calls += 1
            return {
                "success": True,
                "response": "secondary ok",
                "model": "fake-secondary",
                "tokens": 5,
                "latency_ms": 10,
            }

    primary = _FakeSuccessAdapter()
    secondary = _FakeSecondaryAdapter()

    def _fake_get_or_create(provider):
        return primary if provider == "groq" else secondary

    monkeypatch.setattr(router, "_get_or_create_adapter", _fake_get_or_create)

    result = await router.generate("hello")

    assert result["success"] is True
    assert result["provider"] == "groq"
    assert primary.calls == 1
    assert secondary.calls == 0


@pytest.mark.asyncio
async def test_router_fallback_to_secondary(monkeypatch):
    """Router should fallback when primary fails with transient error."""
    router = RouterAdapter(provider_chain=["groq", "gemini"], max_retries=0, provider_timeout_ms=1000)

    class _FakePrimaryFailAdapter:
        async def generate(self, *args, **kwargs):
            return {
                "success": False,
                "error": "429 rate limit",
                "response": "",
                "status_code": 429,
            }

    class _FakeSecondaryAdapter:
        async def generate(self, *args, **kwargs):
            return {
                "success": True,
                "response": "secondary ok",
                "model": "fake-secondary",
                "tokens": 7,
                "latency_ms": 12,
            }

    def _fake_get_or_create(provider):
        return _FakePrimaryFailAdapter() if provider == "groq" else _FakeSecondaryAdapter()

    monkeypatch.setattr(router, "_get_or_create_adapter", _fake_get_or_create)

    result = await router.generate("hello")

    assert result["success"] is True
    assert result["provider"] == "gemini"
