"""
LLM Adapter abstraction layer - switch between providers
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import aiohttp
import time
import os
import logging
import asyncio
import re
import threading


logger = logging.getLogger(__name__)


class LLMProviderStats:
    """Track LLM provider usage stats - today and overall"""
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._stats = {
            "groq": {"today": 0, "total": 0, "failures": 0},
            "gemini": {"today": 0, "total": 0, "failures": 0},
            "openrouter": {"today": 0, "total": 0, "failures": 0},
            "mock": {"today": 0, "total": 0, "failures": 0},
        }
        self._last_reset = None
        self._load_stats()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load_stats(self):
        """Load stats from file if exists"""
        import json
        from datetime import datetime, date
        try:
            stats_file = os.path.join(os.path.dirname(__file__), "llm_stats.json")
            if os.path.exists(stats_file):
                with open(stats_file, "r") as f:
                    data = json.load(f)
                    saved_date = data.get("last_date", "")
                    today_str = date.today().isoformat()

                    if saved_date == today_str:
                        self._stats = data.get("stats", self._stats)
                    else:
                        for provider in self._stats:
                            self._stats[provider]["today"] = 0

                    self._last_reset = data.get("last_date", "")
        except Exception as e:
            logger.warning(f"Could not load LLM stats: {e}")

    def _save_stats(self):
        """Save stats to file"""
        import json
        from datetime import date
        try:
            stats_file = os.path.join(os.path.dirname(__file__), "llm_stats.json")
            data = {
                "stats": self._stats,
                "last_date": date.today().isoformat()
            }
            with open(stats_file, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Could not save LLM stats: {e}")

    def record_success(self, provider: str):
        """Record successful response from provider"""
        provider = provider.lower()
        if provider in self._stats:
            with self._lock:
                self._stats[provider]["today"] += 1
                self._stats[provider]["total"] += 1
            self._save_stats()

    def record_failure(self, provider: str):
        """Record failed response from provider"""
        provider = provider.lower()
        if provider in self._stats:
            with self._lock:
                self._stats[provider]["failures"] += 1
            self._save_stats()

    def get_stats(self) -> dict:
        """Get current stats"""
        return {
            "today": {k: v["today"] for k, v in self._stats.items()},
            "total": {k: v["total"] for k, v in self._stats.items()},
            "failures": {k: v["failures"] for k, v in self._stats.items()},
        }

    def get_summary(self) -> dict:
        """Get formatted summary"""
        today_total = sum(v["today"] for v in self._stats.values())
        total_total = sum(v["total"] for v in self._stats.values())
        total_failures = sum(v["failures"] for v in self._stats.values())

        return {
            "providers": {
                "groq": {"today": self._stats["groq"]["today"], "total": self._stats["groq"]["total"]},
                "gemini": {"today": self._stats["gemini"]["today"], "total": self._stats["gemini"]["total"]},
                "openrouter": {"today": self._stats["openrouter"]["today"], "total": self._stats["openrouter"]["total"]},
                "mock": {"today": self._stats["mock"]["today"], "total": self._stats["mock"]["total"]},
            },
            "summary": {
                "today_total": today_total,
                "overall_total": total_total,
                "total_failures": total_failures,
            }
        }


_llm_stats = LLMProviderStats.get_instance()


def get_llm_stats():
    return _llm_stats.get_summary()


def _get_provider_health_tracker():
    """Lazy import to avoid circular dependency"""
    try:
        from app.api.health import get_provider_health_tracker
        return get_provider_health_tracker()
    except Exception:
        return None


class LLMAdapter(ABC):
    """Base class for LLM adapters"""
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        model: str = "llama3.1:8b",
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate response from LLM"""
        pass


class OllamaAdapter(LLMAdapter):
    """Ollama local LLM adapter"""
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
    
    async def generate(
        self,
        prompt: str,
        model: str = "llama3.1:8b",
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate response using Ollama"""
        async with aiohttp.ClientSession() as session:
            start_time = time.time()

            system_prompt = kwargs.get("system_prompt", "")
            messages = kwargs.get("messages") or []
            effective_prompt = prompt

            if messages:
                transcript = []
                if system_prompt:
                    transcript.append(f"system: {system_prompt}")
                for msg in messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    transcript.append(f"{role}: {content}")
                transcript.append("assistant:")
                effective_prompt = "\n".join(transcript)
            
            payload = {
                "model": model,
                "prompt": effective_prompt,
                "temperature": temperature,
                "num_predict": max_tokens,
                "stream": False
            }
            
            try:
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=300)
                ) as resp:
                    if resp.status != 200:
                        return {
                            "success": False,
                            "error": f"Ollama returned {resp.status}",
                            "response": ""
                        }
                    
                    data = await resp.json()
                    latency_ms = int((time.time() - start_time) * 1000)
                    
                    return {
                        "success": True,
                        "response": data.get("response", ""),
                        "model": model,
                        "tokens": data.get("eval_count", 0),
                        "latency_ms": latency_ms
                    }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "response": ""
                }


class GroqAdapter(LLMAdapter):
    """
    Groq Cloud API adapter - FREE tier available!
    
    Features:
    - Very fast inference (fastest in the market)
    - Generous free tier: 14,400 requests/day
    - OpenAI-compatible API
    - No credit card required for free tier
    
    Setup:
    1. Get free API key from https://console.groq.com
    2. Set environment variable: GROQ_API_KEY=your_key_here
    """
    
    _shared_session: Optional[aiohttp.ClientSession] = None
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        
        if not self.api_key:
            raise ValueError(
                "Groq API key required. Set GROQ_API_KEY environment variable or pass api_key parameter. "
                "Get free key at: https://console.groq.com"
            )
    
    @classmethod
    async def _get_session(cls) -> aiohttp.ClientSession:
        """Reuse a single aiohttp session with connection pooling for fast first requests."""
        if cls._shared_session is None or cls._shared_session.closed:
            connector = aiohttp.TCPConnector(
                limit=20,
                limit_per_host=10,
                ttl_dns_cache=300,
                keepalive_timeout=60,
            )
            cls._shared_session = aiohttp.ClientSession(connector=connector)
        return cls._shared_session
    
    async def generate(
        self,
        prompt: str,
        model: str = "llama-3.3-70b-versatile",
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate response using Groq API

        Available free models:
        - llama-3.3-70b-versatile (recommended, best instruction following)
        - llama-3.1-8b-instant (fastest, lower quality)
        - mixtral-8x7b-32768 (large context)
        """
        session = await self._get_session()
        start_time = time.time()
        timeout_ms = int(kwargs.get("timeout_ms", os.getenv("LLM_PROVIDER_TIMEOUT_MS", "3000")))

        system_prompt = kwargs.get("system_prompt", "")
        messages = kwargs.get("messages") or []
        tools = kwargs.get("tools") or []

        if messages:
            payload_messages = []
            if system_prompt:
                payload_messages.append({"role": "system", "content": system_prompt})
            payload_messages.extend(messages)
        else:
            if system_prompt:
                payload_messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]
            else:
                payload_messages = [
                    {"role": "user", "content": prompt}
                ]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload: Dict[str, Any] = {
            "model": model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }

        if tools:
            payload["tools"] = tools

        try:
            async with session.post(
                self.base_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=max(timeout_ms / 1000.0, 1.0))
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    return {
                        "success": False,
                        "error": f"Groq API returned {resp.status}: {error_text}",
                        "response": ""
                    }
                
                data = await resp.json()
                latency_ms = int((time.time() - start_time) * 1000)

                # Extract response — handle tool_calls (function calling)
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                response_text = message.get("content") or ""
                tool_calls = message.get("tool_calls") or []

                tokens_used = data.get("usage", {}).get("completion_tokens", 0)

                return {
                    "success": True,
                    "response": response_text,
                    "model": model,
                    "tokens": tokens_used,
                    "latency_ms": latency_ms,
                    "tool_calls": tool_calls,
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Groq API error: {str(e)}",
                "response": ""
            }


class OpenAIAdapter(LLMAdapter):
    """OpenAI Chat Completions adapter."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = "https://api.openai.com/v1/chat/completions"
        if not self.api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY.")

    async def generate(
        self,
        prompt: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            start_time = time.time()

            system_prompt = kwargs.get("system_prompt", "")
            messages = kwargs.get("messages") or []
            timeout_ms = int(kwargs.get("timeout_ms", os.getenv("LLM_PROVIDER_TIMEOUT_MS", "3000")))

            if messages:
                payload_messages = []
                if system_prompt:
                    payload_messages.append({"role": "system", "content": system_prompt})
                payload_messages.extend(messages)
            else:
                payload_messages = [{"role": "user", "content": prompt}]
                if system_prompt:
                    payload_messages.insert(0, {"role": "system", "content": system_prompt})

            payload: Dict[str, Any] = {
                "model": model,
                "messages": payload_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            tools = kwargs.get("tools") or []
            if tools:
                payload["tools"] = tools
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            try:
                async with session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=max(timeout_ms / 1000.0, 1.0)),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return {
                            "success": False,
                            "error": f"OpenAI API returned {resp.status}: {error_text}",
                            "response": "",
                            "status_code": resp.status,
                        }

                    data = await resp.json()
                    latency_ms = int((time.time() - start_time) * 1000)
                    choice = data.get("choices", [{}])[0]
                    message = choice.get("message", {})
                    response_text = message.get("content") or ""
                    tool_calls = message.get("tool_calls") or []
                    tokens_used = data.get("usage", {}).get("completion_tokens", 0)

                    return {
                        "success": True,
                        "response": response_text,
                        "model": model,
                        "tokens": tokens_used,
                        "latency_ms": latency_ms,
                        "tool_calls": tool_calls,
                    }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"OpenAI API error: {str(e)}",
                    "response": "",
                }


class OpenRouterAdapter(LLMAdapter):
    """OpenRouter Chat Completions adapter."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        if not self.api_key:
            raise ValueError("OpenRouter API key required. Set OPENROUTER_API_KEY.")

    async def generate(
        self,
        prompt: str,
        model: str = "openai/gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            start_time = time.time()

            system_prompt = kwargs.get("system_prompt", "")
            messages = kwargs.get("messages") or []
            timeout_ms = int(kwargs.get("timeout_ms", os.getenv("LLM_PROVIDER_TIMEOUT_MS", "3000")))

            if messages:
                payload_messages = []
                if system_prompt:
                    payload_messages.append({"role": "system", "content": system_prompt})
                payload_messages.extend(messages)
            else:
                payload_messages = [{"role": "user", "content": prompt}]
                if system_prompt:
                    payload_messages.insert(0, {"role": "system", "content": system_prompt})

            payload: Dict[str, Any] = {
                "model": model,
                "messages": payload_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            tools = kwargs.get("tools") or []
            if tools:
                payload["tools"] = tools
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            try:
                async with session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=max(timeout_ms / 1000.0, 1.0)),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return {
                            "success": False,
                            "error": f"OpenRouter API returned {resp.status}: {error_text}",
                            "response": "",
                            "status_code": resp.status,
                        }

                    data = await resp.json()
                    latency_ms = int((time.time() - start_time) * 1000)
                    choice = data.get("choices", [{}])[0]
                    message = choice.get("message", {})
                    response_text = message.get("content") or ""
                    tool_calls = message.get("tool_calls") or []
                    tokens_used = data.get("usage", {}).get("completion_tokens", 0)

                    return {
                        "success": True,
                        "response": response_text,
                        "model": model,
                        "tokens": tokens_used,
                        "latency_ms": latency_ms,
                        "tool_calls": tool_calls,
                    }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"OpenRouter API error: {str(e)}",
                    "response": "",
                }


class GeminiAdapter(LLMAdapter):
    """Gemini REST adapter."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("Gemini API key required. Set GEMINI_API_KEY.")

    async def generate(
        self,
        prompt: str,
        model: str = "gemini-1.5-flash",
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            start_time = time.time()

            system_prompt = kwargs.get("system_prompt", "")
            messages = kwargs.get("messages") or []
            timeout_ms = int(kwargs.get("timeout_ms", os.getenv("LLM_PROVIDER_TIMEOUT_MS", "3000")))

            if messages:
                lines = []
                if system_prompt:
                    lines.append(f"System: {system_prompt}")
                for msg in messages:
                    role = msg.get("role", "user")
                    lines.append(f"{role.capitalize()}: {msg.get('content', '')}")
                merged_prompt = "\n".join(lines)
            else:
                merged_prompt = prompt
                if system_prompt:
                    merged_prompt = f"System: {system_prompt}\n\nUser: {prompt}"

            url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={self.api_key}"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": merged_prompt}
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            }

            try:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=max(timeout_ms / 1000.0, 1.0)),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return {
                            "success": False,
                            "error": f"Gemini API returned {resp.status}: {error_text}",
                            "response": "",
                            "status_code": resp.status,
                        }

                    data = await resp.json()
                    latency_ms = int((time.time() - start_time) * 1000)
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    response_text = "".join([p.get("text", "") for p in parts])

                    return {
                        "success": True,
                        "response": response_text,
                        "model": model,
                        "tokens": 0,
                        "latency_ms": latency_ms,
                    }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Gemini API error: {str(e)}",
                    "response": "",
                }


class RouterAdapter(LLMAdapter):
    """Thin fallback router across multiple providers (minimal, env-driven, replaceable)."""

    GROQ_MODEL_ALIASES = {
        "llama3.1:8b": "llama-3.3-70b-versatile",
        "llama3:8b": "llama-3.3-70b-versatile",
        "llama3.1": "llama-3.3-70b-versatile",
        "llama3": "llama-3.3-70b-versatile",
        "llama-3.1-8b": "llama-3.3-70b-versatile",
        "llama-3.3-70b": "llama-3.3-70b-versatile",
    }

    DEFAULT_PROVIDER_MODELS = {
        "groq": os.getenv("LLM_GROQ_MODEL", "llama-3.3-70b-versatile"),
        "gemini": os.getenv("LLM_GEMINI_MODEL", "gemini-1.5-flash"),
        "openai": os.getenv("LLM_OPENAI_MODEL", "gpt-4o-mini"),
        "openrouter": os.getenv("LLM_OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        "ollama": os.getenv("LLM_OLLAMA_MODEL", "llama3.1:8b"),
        "mock": "mock-model",
    }

    def __init__(
        self,
        provider_chain: Optional[list] = None,
        max_retries: Optional[int] = None,
        provider_timeout_ms: Optional[int] = None,
    ):
        if provider_chain is None:
            provider_chain = [
                os.getenv("LLM_PRIMARY", "groq"),
                os.getenv("LLM_SECONDARY", "gemini"),
                os.getenv("LLM_TERTIARY", "openrouter"),
            ]

        self.provider_chain = [p.strip().lower() for p in provider_chain if p and p.strip()]
        self.max_retries = int(max_retries if max_retries is not None else os.getenv("LLM_MAX_RETRIES", "1"))
        self.provider_timeout_ms = int(
            provider_timeout_ms if provider_timeout_ms is not None else os.getenv("LLM_PROVIDER_TIMEOUT_MS", "3000")
        )
        self._adapters: Dict[str, LLMAdapter] = {}

        routing_mode = os.getenv("LLM_ROUTING_MODE", "fallback").strip().lower()
        self.routing_mode = routing_mode if routing_mode in ["fallback", "round_robin", "load_balance", "smart"] else "fallback"

        load_balance_pct = int(os.getenv("LLM_GEMINI_PERCENT", "30"))
        self.gemini_percent = max(0, min(100, load_balance_pct))
        self._round_robin_index = 0
        self._round_robin_lock = threading.Lock()

        self._gemini_daily_count = 0
        self._gemini_daily_reset = None

    def _analyze_question_complexity(self, prompt: str) -> dict:
        """Analyze if a question is complex enough to need Gemini."""
        if not prompt:
            return {"is_complex": False, "reason": "empty"}

        prompt_lower = prompt.lower()
        word_count = len(prompt.split())
        sentence_count = prompt.count('.') + prompt.count('?') + 1

        complexity_score = 0
        reasons = []

        if word_count > 50:
            complexity_score += 2
            reasons.append(f"long ({word_count} words)")
        elif word_count > 25:
            complexity_score += 1
            reasons.append(f"medium ({word_count} words)")

        if sentence_count > 2:
            complexity_score += 1
            reasons.append(f"multi-sentence ({sentence_count})")

        technical_keywords = [
            'explain', 'compare', 'difference', 'analyze', 'why', 'how',
            'implement', 'debug', 'code', 'function', 'algorithm',
            'technical', 'architecture', 'system', 'database', 'api',
            'integrate', 'optimize', 'performance', 'security',
            'research', 'summary', 'detailed', 'comprehensive'
        ]
        keyword_matches = sum(1 for kw in technical_keywords if kw in prompt_lower)
        if keyword_matches >= 2:
            complexity_score += 2
            reasons.append(f"technical ({keyword_matches} keywords)")
        elif keyword_matches == 1:
            complexity_score += 1
            reasons.append(f"some technical terms")

        math_symbols = ['+', '-', '*', '/', '=', '公式', 'equation', 'calculate']
        if any(s in prompt for s in math_symbols):
            complexity_score += 1
            reasons.append("contains math/symbols")

        is_complex = complexity_score >= 2

        return {
            "is_complex": is_complex,
            "score": complexity_score,
            "word_count": word_count,
            "reasons": reasons
        }

    def _should_use_gemini(self, prompt: str) -> bool:
        """Smart routing: use Gemini for complex questions if quota available."""
        if self.routing_mode != "smart":
            return False

        if not self._check_gemini_quota():
            logger.info("[LLM Router] Smart mode: Gemini quota exhausted, using Groq")
            return False

        analysis = self._analyze_question_complexity(prompt)
        logger.info(f"[LLM Router] Smart mode: complexity score={analysis['score']}, reasons={analysis['reasons']}")

        return analysis["is_complex"]

    def _check_gemini_quota(self) -> bool:
        """Check if Gemini daily limit (1000) reached. Returns True if OK to use."""
        from datetime import datetime, timedelta
        now = datetime.now()

        if self._gemini_daily_reset is None:
            self._gemini_daily_reset = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

        if now >= self._gemini_daily_reset:
            self._gemini_daily_count = 0
            self._gemini_daily_reset = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            logger.info("[LLM Router] Gemini daily counter reset (limit: 1000/day)")

        if self._gemini_daily_count >= 1000:
            logger.warning("[LLM Router] Gemini daily limit (1000) reached, skipping Gemini")
            return False
        return True

    def _record_gemini_call(self):
        """Record successful Gemini call for daily tracking."""
        self._gemini_daily_count += 1
        logger.info(f"[LLM Router] Gemini call recorded: {self._gemini_daily_count}/1000 today")

    def _get_or_create_adapter(self, provider: str) -> LLMAdapter:
        if provider in self._adapters:
            return self._adapters[provider]

        if provider == "groq":
            adapter = GroqAdapter()
        elif provider == "gemini":
            adapter = GeminiAdapter()
        elif provider == "openai":
            adapter = OpenAIAdapter()
        elif provider == "openrouter":
            adapter = OpenRouterAdapter()
        elif provider == "ollama":
            adapter = OllamaAdapter(os.getenv("OLLAMA_URL", "http://localhost:11434"))
        elif provider == "mock":
            adapter = MockAdapter()
        else:
            raise ValueError(f"Unsupported router provider: {provider}")

        self._adapters[provider] = adapter
        return adapter

    def _is_transient_error(self, error_text: str, status_code: Optional[int] = None) -> bool:
        text = (error_text or "").lower()

        # Billing/quota exhaustion should not be retried as transient failures.
        quota_tokens = [
            "insufficient_quota",
            "insufficient credits",
            "never purchased credits",
            "billing details",
            "exceeded your current quota",
        ]
        if any(token in text for token in quota_tokens):
            return False

        if status_code in {408, 429, 500, 502, 503, 504}:
            return True
        transient_tokens = ["timeout", "timed out", "rate limit", "429", "connection reset", "temporar"]
        return any(token in text for token in transient_tokens)

    def _classify_error_kind(self, error_text: str, status_code: Optional[int] = None) -> str:
        text = (error_text or "").lower()
        if (
            status_code == 402
            or "insufficient credits" in text
            or "insufficient_quota" in text
            or "never purchased credits" in text
            or "billing details" in text
            or "exceeded your current quota" in text
        ):
            return "insufficient_credits"
        if status_code == 401 or "unauthorized" in text or "invalid api key" in text:
            return "auth_error"
        if status_code == 429 or "rate limit" in text:
            return "rate_limited"
        if status_code in {408, 504} or "timeout" in text or "timed out" in text:
            return "timeout"
        if status_code in {500, 502, 503}:
            return "provider_unavailable"
        if "connection" in text or "network" in text:
            return "network_error"
        return "unknown"

    def _error_excerpt(self, error_text: str, max_len: int = 280) -> str:
        text = (error_text or "").strip()
        if len(text) <= max_len:
            return text
        return f"{text[:max_len]}..."

    def _extract_retry_delay_seconds(self, error_text: str, status_code: Optional[int] = None, attempt: int = 0) -> float:
        """Parse provider hints like 'try again in 8.65s' and apply bounded backoff."""
        text = (error_text or "").lower()
        match = re.search(r"try again in\s*([0-9]+(?:\.[0-9]+)?)s", text)
        if match:
            try:
                hinted = float(match.group(1))
                return max(0.5, min(hinted, 20.0))
            except ValueError:
                pass

        if status_code == 429 or "rate limit" in text:
            # Bounded exponential backoff when provider doesn't return explicit wait time.
            return float(min(10, 2 ** (attempt + 1)))

        return 0.0

    # Groq-specific model names that must not be forwarded to other providers.
    GROQ_SPECIFIC_MODELS = {
        "llama-3.1-8b-instant",
        "llama-3.1-70b-versatile",
        "llama-3.3-70b-versatile",
        "llama-3.2-90b-vision-preview",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
        "whisper-large-v3",
    }

    def _resolve_model_for_provider(self, provider: str, incoming_model: str) -> str:
        normalized = (incoming_model or "").strip().lower()
        provider = (provider or "").strip().lower()

        if provider == "groq":
            if normalized in self.GROQ_MODEL_ALIASES:
                return self.GROQ_MODEL_ALIASES[normalized]
            # Avoid passing local ollama-style model names to Groq.
            if ":" in normalized and "llama" in normalized:
                return self.DEFAULT_PROVIDER_MODELS["groq"]
            if incoming_model:
                return incoming_model
            return self.DEFAULT_PROVIDER_MODELS["groq"]

        # For all other cloud providers: never pass Groq-specific or Ollama-style model names.
        if provider in {"gemini", "openai", "openrouter"}:
            if ":" in normalized or normalized in self.GROQ_SPECIFIC_MODELS:
                return self.DEFAULT_PROVIDER_MODELS[provider]

        if incoming_model:
            return incoming_model
        return self.DEFAULT_PROVIDER_MODELS.get(provider, "mock-model")

    async def generate(
        self,
        prompt: str,
        model: str = "llama3.1:8b",
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> Dict[str, Any]:
        last_error = "No provider available"
        router_start = time.time()
        provider_timings: Dict[str, int] = {}
        provider_failures = []

        force_fallback = os.getenv("LLM_FORCE_FALLBACK", "false").lower() == "true"
        if force_fallback:
            logger.warning("[LLM Router] ⚠️ TEST MODE: Groq bypassed — using Gemini")
            if len(self.provider_chain) > 1:
                self.provider_chain = self.provider_chain[1:]
                logger.info("[LLM Router] Fallback provider chain: %s", self.provider_chain)

        health_tracker = _get_provider_health_tracker()

        if self.routing_mode == "round_robin":
            with self._round_robin_lock:
                provider = self.provider_chain[self._round_robin_index % len(self.provider_chain)]
                self._round_robin_index += 1
            logger.info("[LLM Router] Round-robin selected provider: %s", provider)

            try:
                adapter = self._get_or_create_adapter(provider)
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Provider {provider} setup failed: {str(e)}",
                    "response": "",
                }

            provider_model = self._resolve_model_for_provider(provider, model)
            result = await adapter.generate(
                prompt=prompt,
                model=provider_model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_ms=self.provider_timeout_ms,
                **kwargs,
            )

            if result.get("success"):
                result["provider"] = provider
                result["routing_mode"] = "round_robin"
                if health_tracker:
                    health_tracker.record_call(provider, True, result.get("latency_ms", 0))
                _llm_stats.record_success(provider)
                return result
            else:
                logger.warning("[LLM Router] Round-robin provider %s failed, trying next...", provider)
                fallback_providers = [p for p in self.provider_chain if p != provider]
                for fb_provider in fallback_providers:
                    try:
                        fb_adapter = self._get_or_create_adapter(fb_provider)
                        fb_model = self._resolve_model_for_provider(fb_provider, model)
                        fb_result = await fb_adapter.generate(
                            prompt=prompt,
                            model=fb_model,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            timeout_ms=self.provider_timeout_ms,
                            **kwargs,
                        )
                        if fb_result.get("success"):
                            fb_result["provider"] = fb_provider
                            fb_result["routing_mode"] = "round_robin_with_fallback"
                            if health_tracker:
                                health_tracker.record_call(fb_provider, True, fb_result.get("latency_ms", 0))
                            return fb_result
                    except Exception as fb_e:
                        logger.warning("[LLM Router] Fallback %s failed: %s", fb_provider, fb_e)
                        continue

                return {
                    "success": False,
                    "error": "All round-robin providers failed",
                    "response": "",
                }

        if self.routing_mode == "load_balance":
            import random
            gemini_pct = self.gemini_percent
            providers_to_try = []

            if gemini_pct >= 100:
                providers_to_try = ["gemini"]
            elif gemini_pct <= 0:
                providers_to_try = ["groq"]
            else:
                if random.randint(1, 100) <= gemini_pct:
                    providers_to_try = ["gemini", "groq"]
                else:
                    providers_to_try = ["groq", "gemini"]

            if not self._check_gemini_quota():
                providers_to_try = ["groq"]
                logger.info("[LLM Router] Gemini quota exhausted, using Groq only")

            logger.info(f"[LLM Router] Load-balance ({gemini_pct}% gemini): trying {providers_to_try[0]}")

            for provider in providers_to_try:
                try:
                    adapter = self._get_or_create_adapter(provider)
                    provider_model = self._resolve_model_for_provider(provider, model)
                    result = await adapter.generate(
                        prompt=prompt,
                        model=provider_model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout_ms=self.provider_timeout_ms,
                        **kwargs,
                    )
                    if result.get("success"):
                        result["provider"] = provider
                        result["routing_mode"] = "load_balance"
                        if provider == "gemini":
                            self._record_gemini_call()
                        if health_tracker:
                            health_tracker.record_call(provider, True, result.get("latency_ms", 0))
                        _llm_stats.record_success(provider)
                        return result

                    error_text = result.get("error", "")
                    if "429" in error_text or "quota" in error_text.lower() or "RESOURCE_EXHAUSTED" in error_text:
                        logger.warning(f"[LLM Router] {provider} quota exhausted (429), trying next provider")
                        if provider == "gemini":
                            self._gemini_daily_count = 999
                        continue

                    logger.warning(f"[LLM Router] Load-balance primary {provider} failed: {error_text[:50]}")
                except Exception as e:
                    logger.warning(f"[LLM Router] Load-balance {provider} error: {e}")
                    continue

            return {
                "success": False,
                "error": "All load-balance providers failed",
                "response": "",
            }

        if self.routing_mode == "smart":
            analysis = self._analyze_question_complexity(prompt)
            use_gemini = self._should_use_gemini(prompt)

            if use_gemini:
                logger.info(f"[LLM Router] Smart mode: Complex question → using Gemini (score={analysis['score']})")
                providers_to_try = ["gemini", "groq"]
            else:
                logger.info(f"[LLM Router] Smart mode: Simple question → using Groq (score={analysis['score']})")
                providers_to_try = ["groq", "gemini"]

            for provider in providers_to_try:
                try:
                    adapter = self._get_or_create_adapter(provider)
                    provider_model = self._resolve_model_for_provider(provider, model)
                    result = await adapter.generate(
                        prompt=prompt,
                        model=provider_model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout_ms=self.provider_timeout_ms,
                        **kwargs,
                    )
                    if result.get("success"):
                        result["provider"] = provider
                        result["routing_mode"] = "smart"
                        result["complexity"] = analysis
                        if provider == "gemini":
                            self._record_gemini_call()
                        if health_tracker:
                            health_tracker.record_call(provider, True, result.get("latency_ms", 0))
                        _llm_stats.record_success(provider)
                        return result

                    error_text = result.get("error", "")
                    if "429" in error_text or "quota" in error_text.lower():
                        if provider == "gemini":
                            self._gemini_daily_count = 999
                            logger.warning("[LLM Router] Smart mode: Gemini quota hit, trying Groq")
                        continue
                except Exception as e:
                    logger.warning(f"[LLM Router] Smart mode {provider} error: {e}")
                    continue

            return {
                "success": False,
                "error": "All smart routing providers failed",
                "response": "",
            }

        for provider in self.provider_chain:
            if health_tracker:
                health = health_tracker.get_health(provider)
                if health.get("status") == "circuit_open":
                    logger.warning(
                        "[LLM Router] Circuit breaker OPEN for %s, skipping",
                        provider
                    )
                    continue

            try:
                adapter = self._get_or_create_adapter(provider)
            except Exception as e:
                last_error = str(e)
                logger.warning("[LLM Router] Skipping provider=%s due to setup error: %s", provider, e)
                provider_failures.append(
                    {
                        "provider": provider,
                        "attempt": 0,
                        "status_code": None,
                        "error_kind": "setup_error",
                        "retryable": False,
                        "error": self._error_excerpt(str(e)),
                    }
                )
                continue

            provider_model = self._resolve_model_for_provider(provider, model)

            for attempt in range(self.max_retries + 1):
                provider_call_start = time.time()
                result = await adapter.generate(
                    prompt=prompt,
                    model=provider_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_ms=self.provider_timeout_ms,
                    **kwargs,
                )
                provider_call_ms = int((time.time() - provider_call_start) * 1000)
                provider_timings[f"{provider}_attempt_{attempt}"] = provider_call_ms

                if result.get("success"):
                    router_elapsed_ms = int((time.time() - router_start) * 1000)
                    result["provider"] = provider
                    result["provider_attempt"] = attempt
                    result["router_elapsed_ms"] = router_elapsed_ms
                    result["provider_timings"] = provider_timings
                    if provider_failures:
                        result["provider_failures"] = provider_failures
                    logger.info(
                        "[LLM Router] SUCCESS provider=%s model=%s attempt=%d latency_ms=%d router_total_ms=%d",
                        provider,
                        provider_model,
                        attempt,
                        provider_call_ms,
                        router_elapsed_ms,
                    )
                    if health_tracker:
                        health_tracker.record_call(provider, True, provider_call_ms)

                    _llm_stats.record_success(provider)
                    return result

                error_text = result.get("error", "unknown error")
                status_code = result.get("status_code")
                last_error = f"{provider}: {error_text}"

                if attempt < self.max_retries and self._is_transient_error(error_text, status_code):
                    retry_after_s = self._extract_retry_delay_seconds(error_text, status_code, attempt)
                    logger.warning(
                        "[LLM Router] retrying provider=%s attempt=%s latency_ms=%d retry_after_s=%.2f transient_error=%s",
                        provider,
                        attempt + 1,
                        provider_call_ms,
                        retry_after_s,
                        error_text,
                    )
                    if retry_after_s > 0:
                        await asyncio.sleep(retry_after_s)
                    continue

                logger.warning(
                    "[LLM Router] fallback provider=%s latency_ms=%d reason=%s",
                    provider,
                    provider_call_ms,
                    error_text,
                )
                provider_failures.append(
                    {
                        "provider": provider,
                        "attempt": attempt,
                        "status_code": status_code,
                        "error_kind": self._classify_error_kind(error_text, status_code),
                        "retryable": self._is_transient_error(error_text, status_code),
                        "error": self._error_excerpt(error_text),
                    }
                )
                if health_tracker:
                    health_tracker.record_call(provider, False, provider_call_ms)
                break

        router_total_ms = int((time.time() - router_start) * 1000)
        logger.error(
            "[LLM Router] ALL PROVIDERS FAILED after %dms. Provider timings: %s. Last error: %s",
            router_total_ms,
            provider_timings,
            last_error,
        )

        for pf in provider_failures:
            _llm_stats.record_failure(pf.get("provider", "unknown"))

        try:
            mock = MockAdapter()
            mock_result = await mock.generate(prompt=prompt, model="mock", temperature=temperature, max_tokens=max_tokens, **kwargs)
            mock_result["provider"] = "mock"
            mock_result["provider_failures"] = provider_failures
            mock_result["fallback_used"] = True
            logger.warning("[LLM Router] Using MOCK as final fallback to prevent failure")
            return mock_result
        except Exception as e:
            logger.error("[LLM Router] Even MOCK fallback failed: %s", e)
            return {
                "success": False,
                "error": f"All providers failed. Last error: {last_error}",
                "response": "",
                "router_elapsed_ms": router_total_ms,
                "provider_timings": provider_timings,
                "provider_failures": provider_failures,
            }


class MockAdapter(LLMAdapter):
    """Mock LLM adapter for testing"""
    
    async def generate(
        self,
        prompt: str,
        model: str = "mock-model",
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> Dict[str, Any]:
        """Return mock response"""
        messages = kwargs.get("messages") or []
        if messages:
            # Keep mock deterministic while reflecting chat-style input.
            last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
            summary = (last_user or {}).get("content", prompt)[:50]
        else:
            summary = prompt[:50]

        return {
            "success": True,
            "response": f"Mock response to: {summary}...",
            "model": model,
            "tokens": 10,
            "latency_ms": 50,
            "tool_calls": [],
        }


def get_llm_adapter(provider: str = "ollama", base_url: str = "", api_key: str = None) -> LLMAdapter:
    """
    Factory function to get LLM adapter
    
    Supported providers:
    - 'router': Thin fallback router (recommended for production safety)
    - 'groq': Free tier cloud API (recommended for starting)
    - 'gemini': Gemini REST API
    - 'openai': OpenAI API
    - 'openrouter': OpenRouter API
    - 'mock': Testing/development
    - 'ollama': Self-hosted (requires local setup)
    
    Args:
        provider: LLM provider name
        base_url: Base URL for API (ollama only)
        api_key: API key (groq only)
    """
    if provider == "router":
        return RouterAdapter()
    elif provider == "groq":
        return GroqAdapter(api_key=api_key)
    elif provider == "gemini":
        return GeminiAdapter(api_key=api_key)
    elif provider == "openai":
        return OpenAIAdapter(api_key=api_key)
    elif provider == "openrouter":
        return OpenRouterAdapter(api_key=api_key)
    elif provider == "ollama":
        return OllamaAdapter(base_url or "http://localhost:11434")
    elif provider == "mock":
        return MockAdapter()
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Supported: 'router', 'groq', 'gemini', 'openai', 'openrouter', 'mock', 'ollama'"
        )
