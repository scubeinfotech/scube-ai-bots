"""
Chat service - business logic for chat operations
"""
import logging
import os
import random
import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import ChatMessage, ChatSession, Tenant, Document
from app.models.whatsapp import WhatsAppTentativeBooking
from app.adapters.llm import get_llm_adapter, LLMAdapter, GroqAdapter
from app.services.vector_knowledge import VectorKnowledgeService
from app.services.guardrails import GuardrailsService
from app.services.function_caller import function_calling_service
from app.config import settings
from typing import Optional, Dict, Any, List, Tuple
import time
import re

logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing chat operations"""

    SUPPORTED_RESPONSE_LANGUAGES = {"english", "singlish", "tamil", "malay", "chinese"}
    MALAY_HINTS = {
        "saya", "anda", "awak", "kami", "boleh", "tolong", "terima", "kasih",
        "selamat", "pagi", "petang", "malam", "tidak", "tak", "nak", "apa",
        "siapa", "kenapa", "mengapa", "berapa", "dengan", "untuk", "harga", "murah",
    }
    SINGLISH_HINTS = {
        "lah", "lor", "leh", "meh", "liao", "sia", "shiok", "alamak", "can", "cannot",
        "bojio", "kiasu", "sian", "steady", "chope",
    }
    SINGLISH_PHRASES = {
        "can or not", "why like that", "don't play play", "dont play play", "can meh", "cannot lah",
    }
    TAMIL_ROMANIZED_HINTS = {
        "neenga", "naan", "unga", "ungal", "enna", "epdi", "eppadi", "venum", "thevai",
        "irukku", "irukka", "inga", "anga", "sapadu", "nandri", "vanakkam", "seri", "illai",
        "aama", "ungalukku", "sevai",
    }

    SHORT_FOLLOW_UP_PATTERNS = {
        "ok", "okay", "yes", "yep", "yeah", "sure", "fine", "great", "thanks", "thank you",
        "laptop", "desktop", "computer", "server", "mini pc", "minipc", "pricing", "price",
        "support", "service", "services", "cloud", "hosting", "backup", "network", "networking",
        "demo", "quote", "trial", "billing", "invoice"
    }
    FOLLOW_UP_REFERENCE_TOKENS = {"it", "that", "this", "they", "them", "these", "those", "one", "ones"}
    # Basic profanity filter — blocks clearly offensive content without
    # being so aggressive that innocent words are caught.
    PROFANITY_WORDS = {
        "fuck", "fucking", "fucked", "shit", "shitting", "bitch", "bastard",
        "asshole", "dick", "cunt", "damn", "hell", "stupid", "idiot", "moron",
        "retard", "nigger", "chink", "paki", "fag", "faggot", "whore", "slut",
        "crap", "piss", "pissed", "kill yourself", "kys", "die", "shut up",
        "screw you", "screw off", "piss off", "wanker", "twat", "bollocks",
        "motherfucker", "dumbass", "jackass", "asshat", "dipshit",
    }

    FOLLOW_UP_INTENT_TOKENS = {
        "price", "pricing", "cost", "pay", "paid", "payment", "free", "trial", "credit",
        "card", "register", "registration", "signup", "sign", "book", "demo", "service",
        "services", "feature", "features", "plan", "plans", "package", "packages"
    }
    FOLLOW_UP_LEAD_INS = (
        "do i need", "is it", "can i", "how much", "what about", "do you charge",
        "is there any fee", "do i have to", "can we", "what is the price"
    )
    AFFIRMATION_TOKENS = {"yes", "y", "yep", "yeah", "sure", "ok", "okay", "please", "do", "go ahead"}
    NEGATION_TOKENS = {"no", "nah", "nope", "not now"}
    GREETING_PATTERNS = {
        "hi", "hello", "hey", "hi there", "hello there", "good morning", "good afternoon",
        "good evening", "good night", "howdy", "greetings", "hola", "namaste", "welcome",
    }
    GREETING_KEYWORDS = {"how are you", "how you", "whats up", "what's up", "howdy"}
    GREETING_FILLER_TOKENS = {
        "there", "team", "everyone", "guys", "folks", "sir", "madam", "bro", "sis",
        "bot", "assistant", "ai", "buddy", "mate", "friend"
    }
    NON_GREETING_INTENT_TOKENS = {
        "price", "pricing", "cost", "quote", "service", "services", "product", "products",
        "support", "issue", "problem", "error", "help", "contact", "email", "phone",
        "address", "demo", "book", "buy", "order", "refund", "policy", "hours",
        "location", "where", "what", "when", "why", "which", "who", "can", "could",
        "would", "should", "need", "want", "have", "do", "does"
    }
    GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
    GROQ_MODEL_ALIASES = {
        "llama3.1:8b": "llama-3.3-70b-versatile",
        "llama3:8b": "llama-3.3-70b-versatile",
        "llama3.1": "llama-3.3-70b-versatile",
        "llama3": "llama-3.3-70b-versatile",
        "llama-3.1-8b": "llama-3.3-70b-versatile",
        "llama-3.3-70b": "llama-3.3-70b-versatile",
    }
    
    def __init__(self, db: Session, llm_provider: str = "mock"):
        """
        Initialize chat service
        
        Args:
            db: Database session
            llm_provider: LLM provider to use ('ollama', 'mock', etc.)
        """
        self.db = db
        self.llm_adapter: LLMAdapter = get_llm_adapter(llm_provider)
        self._cached_rag_hits: List[Dict[str, Any]] = []
    
    async def send_message(
        self,
        tenant_id: str,
        content: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        extra_context: Optional[dict] = None
    ) -> Dict[str, Any]:
        """
        Send a chat message and get AI response
        
        Args:
            tenant_id: Tenant ID
            content: User message content
            session_id: Optional existing session ID
            user_id: Optional user identifier
            
        Returns:
            Dict with assistant message details
            
        Raises:
            ValueError: If tenant not found
        """
        start_time = time.time()
        timing_log = {}
        
        # Verify tenant exists
        t_tenant_start = time.time()
        tenant = self.db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")
        timing_log["tenant_lookup_ms"] = int((time.time() - t_tenant_start) * 1000)
        
        # Create or get session
        if not session_id:
            session = ChatSession(
                tenant_id=tenant_id,
                user_id=user_id,
                lead_name=None,
                lead_email=None,
                lead_phone=None,
                lead_collected_at=None,
                lead_prompt_count=0,
                session_data={"lead_collected": False, "gate_prompted": False},
            )
            self.db.add(session)
            self.db.flush()
            self.db.refresh(session)
        else:
            session = self.db.query(ChatSession).filter(
                ChatSession.id == session_id,
                ChatSession.tenant_id == tenant_id
            ).first()
            if not session:
                raise ValueError(f"Session {session_id} not found")
        
        model_name = self._resolve_model_name(tenant.model_name)

        # Store user message
        user_msg = ChatMessage(
            session_id=session.id,
            tenant_id=tenant_id,
            role="user",
            content=content,
            model_used=model_name
        )
        self.db.add(user_msg)
        self.db.commit()

        # --- EXTRACT LEAD INFO FIRST (before gate check) ---
        # This ensures that if the user types their name/email/phone, it gets
        # saved to the session BEFORE the lead gate runs, so the gate unlocks.
        self._extract_and_save_lead(session.id, content)
        self.db.refresh(session)  # reload session to pick up any newly saved lead fields

        # --- PROFANITY GATE ---
        if self._check_profanity(content):
            gate_response = (
                "We want to keep conversations respectful. "
                "Please rephrase your message without offensive language."
            )
            gate_msg = ChatMessage(
                session_id=session.id,
                tenant_id=tenant_id,
                role="assistant",
                content=gate_response,
                model_used=model_name,
                msg_metadata={"gate": "profanity", "blocked": True},
            )
            self.db.add(gate_msg)
            self.db.commit()
            self.db.refresh(gate_msg)
            return {
                "id": gate_msg.id,
                "session_id": session.id,
                "content": gate_response,
                "role": "assistant",
                "model_used": model_name,
                "latency_ms": 0,
                "tokens_used": 0,
                "retrieved_sources": [],
                "_timing_breakdown": {"total_ms": int((time.time() - start_time) * 1000)},
            }

        # --- FORCED LEAD GATE ---
        # First 5–8 messages are free (random per session); after that we ask for lead info.
        # Instead of blocking the response entirely, we answer the user's question
        # AND append a lead request. This gives value immediately while collecting contacts.
        lead_request_text = self._check_lead_gate(session, content)

        # Phase 2: Sentiment Analysis (if enabled)
        sentiment_result = None
        if tenant.enable_sentiment_analysis:
            try:
                from app.services.sentiment_analyzer import sentiment_analyzer
                sentiment_result = sentiment_analyzer.analyze(content)
                if sentiment_result.is_escalation:
                    session.session_data = session.session_data or {}
                    session.session_data["needs_escalation"] = True
                    session.session_data["escalation_reason"] = (
                        sentiment_result.keywords[0] if sentiment_result.keywords else "negative_sentiment"
                    )
                    session.session_data["last_sentiment_score"] = sentiment_result.score
                    self.db.flush()
                    logger.warning(
                        "[ChatService] Escalation flagged for session=%s reason=%s score=%.2f",
                        session.id,
                        sentiment_result.keywords,
                        sentiment_result.score,
                    )
                sentiment_analyzer.store_analysis(tenant_id, session.id, sentiment_result)
            except Exception:
                pass
        
        # Phase 2: Memory (if enabled)
        if tenant.enable_conversation_memory:
            try:
                from app.services.memory_service import memory_service
                memory_service.add_message(session.id, tenant_id, "user", content)
            except Exception:
                pass  # Don't fail chat if memory fails
        
        # Build prompt and structured chat messages for providers that support chat format.
        t_prompt_start = time.time()
        interpreted_content = self._enrich_user_message_for_llm(session.id, content)
        preferred_language = self._infer_response_language(session.id, content)
        timing_log["language_detect_ms"] = int((time.time() - t_prompt_start) * 1000)
        
        t_system_prompt = time.time()
        system_prompt = self._build_system_prompt(tenant, session.id, preferred_language, current_user_message=content, extra_context=extra_context)
        if sentiment_result and sentiment_result.is_escalation:
            system_prompt += (
                "\n\n# ESCALATION ALERT\n"
                "The user has expressed frustration or requested human assistance. "
                "Acknowledge their concern warmly and offer to connect them with the team directly. "
                "Be empathetic — do NOT deflect or give a generic 'sorry'. "
                "End with a clear next step (e.g., team will reach out within 24 hours)."
            )
        timing_log["system_prompt_ms"] = int((time.time() - t_system_prompt) * 1000)
        
        t_prompt_build = time.time()
        prompt = self._build_prompt_with_system(system_prompt, interpreted_content, session.id)
        chat_messages = self._build_chat_messages(session.id, current_user_override=interpreted_content)
        timing_log["prompt_build_ms"] = int((time.time() - t_prompt_build) * 1000)
        
        t_rag = time.time()
        retrieved_sources = self._get_retrieved_sources_preview(tenant, session.id, current_user_message=content)
        timing_log["rag_retrieve_ms"] = int((time.time() - t_rag) * 1000)
        
        # --- FUNCTION CALLING (tool execution) ---
        # Get function schemas if enabled — must happen BEFORE the LLM call so
        # tools can be passed in the request payload.
        function_tools: List[Dict[str, Any]] = []
        fc_active = (
            tenant.enable_function_calling
            and function_calling_service.is_enabled
        )
        if fc_active:
            function_tools = function_calling_service.get_function_schemas()

        # Call LLM adapter with numeric-safe config values
        t_llm = time.time()
        llm_response = await self.llm_adapter.generate(
            prompt=prompt,
            model=model_name,
            temperature=self._safe_float(tenant.temperature, 0.7),
            max_tokens=self._safe_int(tenant.max_tokens, 512),
            system_prompt=system_prompt,
            messages=chat_messages,
            tools=function_tools,
        )
        timing_log["llm_call_ms"] = int((time.time() - t_llm) * 1000)
        
        # Handle LLM error
        llm_success = llm_response.get("success", False)
        if not llm_success:
            assistant_content = self._build_service_unavailable_message(tenant, content)
            tokens_used = 0
            latency_ms = llm_response.get("router_elapsed_ms") or int((time.time() - start_time) * 1000)
        else:
            # Check if LLM returned tool_calls — execute them and continue
            tool_calls = llm_response.get("tool_calls") or []
            if fc_active and tool_calls:
                logger.info("[ChatService] LLM requested %d tool call(s)", len(tool_calls))
                tool_results, assistant_content = await self._execute_tool_calls(
                    tool_calls, session, tenant, tenant_id,
                    system_prompt, chat_messages, model_name, prompt
                )
            else:
                assistant_content = (llm_response.get("response", "") or "").strip()
                if not assistant_content:
                    assistant_content = (
                        "Could you share a bit more detail so I can help you better? "
                        "For example, tell me whether you want product features, pricing, or a demo."
                    )
            tokens_used = llm_response.get("tokens", 0)
            latency_ms = llm_response.get("latency_ms", 0)

        if llm_success:
            responding_provider = llm_response.get("provider") or os.getenv("LLM_PRIMARY", "groq")
        else:
            responding_provider = llm_response.get("provider") or "router_exhausted"

        assistant_content = self._postprocess_assistant_content(tenant, content, assistant_content, session.id)
        assistant_content = self._enforce_callback_response(tenant, content, assistant_content, session.id)
        assistant_content = self._enforce_contact_response(tenant, content, assistant_content)
        # Hallucination guards: only redact when the model output mentions
        # pricing/URLs that aren't anywhere in the grounded sources for this
        # tenant. Both helpers are conservative (no-op when the value can be
        # traced back to knowledge_context or retrieved RAG hits).
        assistant_content = self._enforce_no_invented_pricing(tenant, assistant_content, retrieved_sources)
        assistant_content = self._enforce_no_invented_urls(tenant, assistant_content, retrieved_sources)
        if llm_success:
            assistant_content = self._append_source_tags(assistant_content, retrieved_sources)

        # Append lead collection request if the gate fired this turn.
        # The user gets their answer first, then a friendly lead ask is appended.
        if lead_request_text:
            assistant_content = assistant_content.rstrip() + "\n\n" + lead_request_text

        meta: dict = {
            "provider": responding_provider,
            "llm_success": llm_success,
        }
        if llm_response.get("provider_timings"):
            meta["provider_timings"] = llm_response.get("provider_timings")
        if not llm_success:
            meta["llm_failure"] = True
            meta["llm_error_summary"] = llm_response.get("error", "All providers failed")
            provider_failures = llm_response.get("provider_failures")
            if isinstance(provider_failures, list) and provider_failures:
                meta["provider_failures"] = provider_failures
        if retrieved_sources:
            meta["retrieved_sources"] = retrieved_sources

        # Store assistant response
        assistant_msg = ChatMessage(
            session_id=session.id,
            tenant_id=tenant_id,
            role="assistant",
            content=assistant_content,
            model_used=model_name,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            msg_metadata=meta,
        )
        self.db.add(assistant_msg)
        self.db.commit()
        self.db.refresh(assistant_msg)
        
        # Phase 2: Store in memory (if enabled)
        if tenant.enable_conversation_memory:
            try:
                from app.services.memory_service import memory_service
                memory_service.add_message(session.id, tenant_id, "assistant", assistant_content)
            except Exception:
                pass

        if tenant.enable_function_calling and function_calling_service.is_enabled:
            logger.info(
                "[ChatService] Function calling is enabled for tenant=%s but tool "
                "execution is not yet wired into the LLM call path. "
                "Real tool execution will land in Phase 2.5 of the refactor plan. "
                "Set FUNCTION_CALLING_ENABLED=false in the meantime to suppress this log.",
                tenant_id
            )
        
        total_ms = int((time.time() - start_time) * 1000)
        timing_log["total_ms"] = total_ms

        # Create booking record + append ICS link if this turn confirmed a booking
        enriched = self._maybe_create_booking(session, tenant, assistant_content, content)
        if enriched != assistant_content:
            assistant_msg.content = enriched
            self.db.commit()
            assistant_content = enriched

        logger.info(f"[ChatService] Message processed: {timing_log}")
        
        result = {
            "id": assistant_msg.id,
            "session_id": assistant_msg.session_id,
            "content": assistant_msg.content,
            "role": assistant_msg.role,
            "model_used": assistant_msg.model_used,
            "latency_ms": assistant_msg.latency_ms,
            "tokens_used": assistant_msg.tokens_used,
            "retrieved_sources": retrieved_sources,
        }
        result["_timing_breakdown"] = timing_log
        return result
    
    def _build_prompt(self, tenant: Tenant, user_message: str, session_id: str) -> str:
        """Build full prompt (computes system prompt internally — used by external callers)."""
        preferred_language = self._infer_response_language(session_id, user_message)
        system_prompt = self._build_system_prompt(tenant, session_id, preferred_language, current_user_message=user_message)
        return self._build_prompt_with_system(system_prompt, user_message, session_id)

    def _is_lead_trigger_turn(self, session_id: str) -> tuple:
        """Return ``(should_prompt, missing_str)`` for the *current* turn.

        A "trigger turn" is one where the lead-collection directive was injected
        this exact turn (lead_prompt_count == 1 and user_msg_count matches the
        stored lead_ask_turn which is randomly chosen between 5–8). The
        post-processor uses this to deterministically rewrite the assistant reply
        when the model ignores the directive.

        Pure read — no side effects.
        """
        if not session_id:
            return False, ""
        session = self.db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if not session:
            return False, ""

        # Fast-path: flag set when any lead info was collected — nothing to enforce.
        session_data = session.session_data or {}
        if session_data.get("lead_collected") or (session.lead_email and session.lead_name and session.lead_phone):
            return False, ""

        # Only enforce on the exact turn the directive was injected.
        lead_prompt_count = getattr(session, "lead_prompt_count", 0) or 0
        if lead_prompt_count < 1:
            return False, ""

        user_msg_count = self.db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "user",
        ).count()

        lead_ask_turn = session_data.get("lead_ask_turn")
        if lead_ask_turn is None or user_msg_count != lead_ask_turn:
            return False, ""

        missing: List[str] = []
        if not session.lead_name:
            missing.append("name")
        if not session.lead_email:
            missing.append("email")
        if not session.lead_phone:
            missing.append("phone")
        return True, ", ".join(missing) if missing else ""

    def _enforce_lead_collection_response(
        self,
        session_id: str,
        assistant_content: str,
    ) -> str:
        """Deterministically guarantee a lead-collection ask on trigger turns.

        Llama-class models often ignore strong "STOP and ask for X" directives
        and instead emit clarifying business questions. When this happens on a
        trigger turn we rewrite the reply so the user actually sees the ask.

        Heuristic: a reply "passes" if it contains at least two of the missing
        item keywords ({name, email, phone}). Otherwise we replace the reply
        with a clean canonical ask. This is conservative — legitimate replies
        that already collect the info are left alone.
        """
        should_prompt, missing_str = self._is_lead_trigger_turn(session_id)
        if not should_prompt:
            return assistant_content

        text = (assistant_content or "").lower()
        # Count how many of the still-missing items the model actually asks
        # for. Use word-boundary checks to avoid matching e.g. "namespace".
        keywords = [w.strip() for w in missing_str.split(",") if w.strip()]
        hits = sum(1 for kw in keywords if re.search(rf"\b{re.escape(kw)}\b", text))

        # If reply already asks for at least 2 of the missing items, trust it.
        if hits >= min(2, len(keywords)):
            return assistant_content

        logger.info(
            "[Lead] post-processor rewriting reply for session=%s "
            "(model asked for %d/%d items, missing=%s)",
            session_id, hits, len(keywords), missing_str,
        )
        return (
            f"To help you better, could I please have your {missing_str}? "
            "Our team will reach out to you with personalized details."
        )

    def _build_lead_collection_directive(self, session_id: str) -> str:
        """Return a system-prompt-ready lead collection directive, or "" if
        not applicable.

        Firing rules:
        1. All 3 fields already collected → never fire.
        2. Already prompted once this session → never fire again (no spam).
        3. On the first eligible call, pick a random trigger turn between 5–8
           and store it in session_data["lead_ask_turn"]. Fire only when
           user_msg_count exactly matches that stored turn.
        4. Ask ONLY for the fields that are still missing, not all three.

        IMPORTANT: this directive is appended to the *system prompt* (not the
        text-completion ``prompt`` string) because every chat-native adapter
        (Groq / Gemini / OpenRouter / OpenAI) ignores the text prompt when a
        ``messages`` list is provided. Putting it in the system prompt is the
        only place it actually reaches the model.
        """
        session = self.db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if not session:
            return ""

        # Fast-path: flag set when any lead info was collected — skip directive.
        session_data = session.session_data or {}
        if session_data.get("lead_collected") or (session.lead_email and session.lead_name and session.lead_phone):
            return ""

        # Already prompted once this session — never nag again.
        lead_prompt_count = getattr(session, "lead_prompt_count", 0) or 0
        if lead_prompt_count >= 1:
            return ""

        user_msg_count = self.db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "user",
        ).count()

        # Resolve (or assign) the random trigger turn for this session.
        lead_ask_turn = session_data.get("lead_ask_turn")
        if lead_ask_turn is None:
            lead_ask_turn = random.randint(5, 8)
            session_data["lead_ask_turn"] = lead_ask_turn
            session.session_data = session_data
            self.db.commit()

        # Only fire on the exact trigger turn.
        if user_msg_count != lead_ask_turn:
            return ""

        # Determine which fields are still missing.
        missing: List[str] = []
        if not session.lead_name:
            missing.append("name")
        if not session.lead_email:
            missing.append("email address")
        if not session.lead_phone:
            missing.append("phone number")

        if not missing:
            return ""

        # Mark as prompted so this never fires again for this session.
        session.lead_prompt_count = 1
        session_data["gate_prompted"] = True
        session.session_data = session_data
        self.db.commit()

        missing_str = " and ".join(
            ", ".join(missing[:-1]) + ([f", and {missing[-1]}"] if len(missing) > 1 else [])
            if len(missing) > 1 else missing
        )

        return (
            f"\n\n# LEAD COLLECTION\n"
            f"The user has been chatting for a while. Naturally weave into your reply a "
            f"friendly request for their {missing_str} so our team can follow up. "
            f"Ask conversationally — not as a form. Do NOT ask for details already provided. "
            f"Do NOT make this the entire reply; answer their question first, then ask."
        )

    def _build_prompt_with_system(self, system_prompt: str, user_message: str, session_id: str) -> str:
        """Assemble full prompt from a pre-built system prompt string (avoids double RAG query)."""
        # Start with tenant's prompt template or default
        prompt_parts = []

        if system_prompt:
            prompt_parts.append(system_prompt)

        # NOTE: lead-collection directive is now applied to the system prompt
        # in send_message() (see _build_lead_collection_directive). This text
        # prompt path is only used by text-completion adapters (Ollama / mock);
        # the chat-native adapters ignore this whole string.
        
        # Add conversation history. Window size and char budget are configurable
        # via env (CHAT_HISTORY_TURNS, CHAT_HISTORY_CHAR_BUDGET). We pull up to
        # `turns` most recent messages, then drop the oldest until the total
        # size fits within the budget so we never blow the LLM token window.
        history_turns = max(1, int(getattr(settings, "chat_history_turns", 10) or 10))
        char_budget = max(500, int(getattr(settings, "chat_history_char_budget", 4000) or 4000))
        history = self.db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.created_at.desc()).limit(history_turns).all()

        if history:
            latest_user_id = next((msg.id for msg in history if msg.role == "user"), None)
            history.reverse()  # Oldest first
            # Skip the latest user message (it will be appended below as the
            # active turn) before budgeting so we don't count it twice.
            visible = [
                msg for msg in history
                if not (latest_user_id and msg.id == latest_user_id and msg.role == "user")
            ]
            # Trim from the oldest end until within char budget.
            while visible and sum(len(m.content or "") for m in visible) > char_budget:
                visible.pop(0)
            if visible:
                prompt_parts.append("\n\nConversation history:")
                for msg in visible:
                    prompt_parts.append(f"{msg.role}: {msg.content}")
        
        # Add current user message
        prompt_parts.append(f"\nuser: {user_message}")
        prompt_parts.append("\nassistant:")
        
        return "\n".join(prompt_parts)

    def _build_system_prompt(
        self,
        tenant: Tenant,
        session_id: Optional[str] = None,
        preferred_language: Optional[str] = None,
        current_user_message: str = "",
        extra_context: Optional[dict] = None,
    ) -> str:
        """Build a resilient system prompt from tenant configuration.

        The prompt is organized into six clearly labeled sections so the
        model has an easier time following role priorities and so future
        edits can be scoped without disturbing unrelated instructions:

        1. ``# IDENTITY`` — who the assistant is (tenant prompt_template).
        2. ``# SCOPE`` — business topics the assistant is allowed to cover.
        3. ``# KNOWLEDGE`` — curated knowledge_context + retrieved RAG.
        4. ``# LANGUAGE`` — response language policy.
        5. ``# BEHAVIOR`` — deterministic response rules (greetings, bullets,
           clarifying questions, callback handling, industry specifics).
        6. ``# BRAND`` — brand-name preservation.

        The wire format stays LLM-friendly (plain text, double-newline
        separators) — the section headers are comments for humans and the
        model alike.
        """
        sections: List[str] = []

        # 1) IDENTITY ----------------------------------------------------
        identity = (str(tenant.prompt_template).strip() if tenant.prompt_template else "")
        if identity:
            sections.append("# IDENTITY\n" + identity)

        # 2) SCOPE -------------------------------------------------------
        business_scope = self._build_business_scope_instructions(tenant)
        if business_scope:
            sections.append("# SCOPE\n" + business_scope)

        # 2b) USER PROFILE -----------------------------------------------
        # Inject known lead info + cross-session memory so the LLM has context.
        if session_id:
            _session = self.db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if _session:
                _name  = (_session.lead_name  or "").strip()
                _email = (_session.lead_email or "").strip()
                _phone = (_session.lead_phone or "").strip()

                profile_parts = []
                if _name:
                    profile_parts.append(f"Name: {_name}")
                if _email:
                    profile_parts.append(f"Email: {_email}")
                if _phone:
                    profile_parts.append(f"Phone: {_phone}")

                if profile_parts:
                    sections.append(
                        "# USER PROFILE\n"
                        "The user has already provided their contact details:\n"
                        + "\n".join(profile_parts) + "\n"
                        "Do NOT ask for their name, email, or phone again. "
                        "When they request a demo, callback, or quote — acknowledge by name and confirm the team will reach out."
                    )

                if tenant.enable_conversation_memory:
                    try:
                        from app.services.memory_service import memory_service
                        cross_ctx = memory_service.get_memory(tenant_id).get_cross_session_context(session_id)
                        if cross_ctx:
                            sections.append(
                                "# PRIOR CONTEXT\n"
                                "From this conversation:\n"
                                + cross_ctx
                            )
                    except Exception:
                        pass

        # 3) KNOWLEDGE ---------------------------------------------------
        # Curated knowledge_context first (tenant-authored), then retrieved
        # RAG chunks second (auto-sourced). Keeping them in one section makes
        # it easy for the model to reason about "what I know about us".
        knowledge_blocks: List[str] = []
        knowledge_context = self._build_relevant_knowledge_context(tenant, session_id)
        if knowledge_context:
            knowledge_blocks.append("## Curated knowledge\n" + knowledge_context)
        vector_context = self._build_vector_context(
            tenant, session_id, current_user_message=current_user_message
        )
        if vector_context:
            logger.debug(
                "[RAG] Injecting %d chunk(s) for tenant=%s",
                len(vector_context.splitlines()), tenant.id,
            )
            knowledge_blocks.append("## Retrieved passages\n" + vector_context)
        if knowledge_blocks:
            sections.append("# KNOWLEDGE\n" + "\n\n".join(knowledge_blocks))

        # 4) LANGUAGE ----------------------------------------------------
        resolved_language = preferred_language or self._infer_response_language(session_id)
        if resolved_language not in self.SUPPORTED_RESPONSE_LANGUAGES:
            resolved_language = "english"
        sections.append("# LANGUAGE\n" + self._build_language_policy_instructions(resolved_language))

        # 5) BEHAVIOR ----------------------------------------------------
        org_type = self._detect_organization_type(tenant)
        org_label = {
            "non-profit": "organization",
            "government": "agency",
            "default": "business",
        }.get(org_type, "business")

        behavior_rules = (
            "Behavior guidelines:\n"
            "- Keep replies concise (40-100 words) unless the user asks for detail.\n"
            "- Use bullet points for lists of services, contact info, and locations.\n"
            "- Match the user's language style naturally.\n"
            "- Never repeat the same phrase twice in one reply.\n"
            "- Treat short follow-ups ('ok', 'yes', 'tell me more') as continuations of the previous topic.\n"
            "- For greetings, reply with a short greeting plus one relevant business question.\n\n"
            "CONVERSATION:\n"
            "- Only use information from the KNOWLEDGE section above.\n"
            "- NEVER invent URLs, prices, or facts not in your knowledge.\n"
            "- If you don't know something, say so honestly and offer to connect the user with the team.\n"
            "- If the user asks for contact details, give ONLY bullet points — minimal text.\n"
            "- If the user asks for a callback ('call me back', 'call me'), ask for THEIR phone number so the team can reach them. Do NOT give the company phone number.\n"
            "- If the user asks about pricing, only give prices found in your knowledge. If unavailable, direct them to the team.\n"
            "- Do not claim an action is already done (e.g., 'I booked your demo') unless you actually performed it.\n\n"
            "LEAD COLLECTION:\n"
            "- Never ask the user for their name, email, or phone number in chat — the system handles contact collection separately.\n"
            "- When a user shows purchase intent ('I want to buy', 'interested', 'need a quote', 'arrange a demo'), acknowledge it warmly and say our team will be in touch shortly.\n\n"
            f"IDENTITY: When describing yourself, say you are a helpful assistant for this {org_label}. "
            "Never use internal terms like 'tenant' or 'system'."
        )

        sections.append("# BEHAVIOR\n" + behavior_rules)

        # 6.5) CHANNEL CONTEXT --------------------------------------------
        if extra_context:
            now = datetime.utcnow()
            day_name = now.strftime("%A")
            time_str = now.strftime("%H:%M")
            bh = (tenant.business_hours or "").strip()
            channel_ctx = (
                "# CHANNEL CONTEXT\n"
                f"Channel: {extra_context.get('channel', 'chat')}\n"
                f"Current day: {day_name}\n"
                f"Current time (UTC): {time_str}\n"
            )
            if bh:
                channel_ctx += f"Business hours: {bh}\n"
            stage = extra_context.get("conversation_stage", "")
            if stage:
                channel_ctx += f"Conversation stage: {stage}\n"
                stage_guide = {
                    "opening": "This is the first interaction. Greet warmly and ask ONE relevant question. Do NOT list all services.",
                    "info_gathering": "The customer is asking questions. Answer precisely and ask ONE follow-up. Stay on topic.",
                    "action": "The customer wants to take action (book, callback, purchase). Guide them through the next step clearly.",
                    "resolving": "The conversation is winding down. Confirm the resolution and offer a clear next step or sign-off.",
                    "closed": "The conversation is complete. End with a polite sign-off. Do NOT ask further questions.",
                }
                guide = stage_guide.get(stage, "")
                if guide:
                    channel_ctx += f"Stage guideline: {guide}\n"
            if extra_context.get("short_response_mode"):
                channel_ctx += f"Keep replies concise ({extra_context.get('target_chars', 300)} chars max).\n"
            sections.append(channel_ctx.strip())

        # 6) BRAND -------------------------------------------------------
        company_name = (tenant.name or "").strip()
        if company_name:
            sections.append(
                "# BRAND\n"
                "Always preserve official brand and product names exactly as configured. "
                "Never translate, transliterate, or phonetic-convert brand names into another script. "
                f"Use this exact company name when needed: {company_name}."
            )

        return "\n\n".join(sections).strip()

    def _build_language_policy_instructions(self, resolved_language: str) -> str:
        """Enforce supported response languages with deterministic English fallback."""
        language_label = resolved_language.capitalize()
        language_specific = {
            "singlish": (
                "For Singlish, keep it concise and natural with light colloquial tone. "
                "Avoid overusing particles like lah/lor/leh in every sentence."
            ),
            "chinese": (
                "For Chinese, use clear and natural Simplified Chinese for business communication. "
                "Keep sentences concise and avoid mixing with other languages unless user requests it."
            ),
            "tamil": (
                "For Tamil, use clear and grammatically natural Tamil. "
                "If the user types Tamil in Latin letters (romanized Tamil), avoid broken mixed forms like '-la offer pannen'. "
                "Prefer either proper Tamil script or clean English with Tamil-friendly tone."
            ),
            "malay": (
                "For Malay, use standard and polite Malay phrasing, keeping business terms clear and simple."
            ),
            "english": (
                "For English default mode, keep wording clear and concise."
            ),
        }
        return (
            "Language policy: Support these user language modes: English, Singlish, Tamil, Malay. "
            f"Detected preferred language: {language_label}. "
            "Respond in the detected language/style when clear. "
            "If detection is uncertain or mixed, default to clear English. "
            f"{language_specific.get(resolved_language, language_specific['english'])}"
        )

    def _infer_response_language(self, session_id: Optional[str], user_message: str = "") -> str:
        """
        Infer response language from recent user text.

        Priority:
        1) Tamil/Chinese script detection
        2) Explicit language request (English/Malay/Chinese)
        3) Singlish lexical/phrase hints
        4) Malay lexical hints
        5) English default fallback
        """
        text_parts = []
        user_message_clean = (user_message or "").strip()
        if user_message_clean:
            text_parts.append(user_message_clean)

        recent = (self._get_recent_user_text_for_session(session_id, limit=4) or "").strip()
        # Avoid double-counting when recent already contains the same current message.
        if recent and (not user_message_clean or user_message_clean.lower() not in recent.lower()):
            text_parts.append(recent)

        merged = " ".join(text_parts).strip()
        if not merged:
            return "english"

        # Tamil Unicode block
        if re.search(r"[\u0B80-\u0BFF]", merged):
            return "tamil"

        # Chinese CJK Unified Ideographs block
        if re.search(r"[\u4E00-\u9FFF]", merged):
            return "chinese"

        lowered = merged.lower()
        if re.search(r"\b(in english|english please|please in english|speak english|reply in english)\b", lowered):
            return "english"
        if re.search(r"\b(in malay|malay please|bahasa melayu|dalam bahasa melayu|reply in malay)\b", lowered):
            return "malay"
        if re.search(r"\b(in chinese|chinese please|mandarin please|reply in chinese|in mandarin)\b", lowered):
            return "chinese"
        if "中文" in merged or "华语" in merged or "汉语" in merged:
            return "chinese"

        alpha_tokens = re.findall(r"[a-z']+", lowered)
        # Short utterances ("ok", "hi", "thanks") used to flip us to Singlish/
        # Malay/Tamil based on a single hint token, which produced wrong-language
        # replies for plain-English users. Require at least 3 alpha tokens
        # before running the lexical scorers; otherwise default to English.
        if len(alpha_tokens) < 3:
            return "english"

        singlish_score = 0
        tamil_romanized_score = 0
        malay_score = 0

        for phrase in self.SINGLISH_PHRASES:
            if phrase in lowered:
                singlish_score += 3

        unique_tokens = set(alpha_tokens)
        for token in unique_tokens:
            if token in self.SINGLISH_HINTS:
                singlish_score += 1
            if token in self.TAMIL_ROMANIZED_HINTS:
                tamil_romanized_score += 1
            if token in self.MALAY_HINTS:
                malay_score += 1

        # Tamil-romanized: bumped from 2 to 3 unique hint tokens. Two-hint
        # detection had too many false positives on English sentences that
        # happen to contain words like "inga" / "seri" used as names/typos.
        if tamil_romanized_score >= 3 and tamil_romanized_score >= malay_score:
            return "tamil"

        if singlish_score >= max(2, malay_score + 1):
            return "singlish"
        if malay_score >= 2:
            return "malay"

        return "english"

    def _build_relevant_knowledge_context(self, tenant: Tenant, session_id: Optional[str] = None) -> str:
        """
        Build dynamic context using a generic tenant knowledge schema.

        Supports:
        - str: raw context text
        - dict: keys like company_overview/services/faqs/products
        - list: generic list of text or objects
        """
        ctx = tenant.knowledge_context
        if not ctx:
            return ""

        if isinstance(ctx, str):
            return ctx.strip()

        recent_user_text = self._get_recent_user_text_for_session(session_id)
        query_tokens = self._tokenize(recent_user_text)

        if isinstance(ctx, dict):
            return self._format_dict_knowledge_context(ctx, query_tokens)

        if isinstance(ctx, list):
            lines = [self._stringify_item(item) for item in ctx]
            return "\n".join([line for line in lines if line])

        return str(ctx)

    def _format_dict_knowledge_context(self, ctx: Dict[str, Any], query_tokens: set) -> str:
        """Format dictionary knowledge and prioritize relevant entries."""
        lines: List[str] = []

        company_overview = ctx.get("company_overview") or ctx.get("about")
        if company_overview:
            lines.append(f"Company overview: {company_overview}")

        # Include contact info from website crawl (check both keys for compatibility)
        contact_info = ctx.get("official_contact") or ctx.get("contact_info")
        if contact_info:
            if isinstance(contact_info, dict):
                # Format dict contact info nicely
                parts = []
                if contact_info.get("phone"):
                    parts.append(f"Phone: {contact_info['phone']}")
                if contact_info.get("email"):
                    email = contact_info['email']
                    parts.append(f"Email: {email} (mailto:{email})")
                if contact_info.get("whatsapp"):
                    wa = contact_info['whatsapp']
                    parts.append(f"WhatsApp: {wa}")
                if contact_info.get("address"):
                    parts.append(f"Address: {contact_info['address']}")
                lines.append("Contact information: " + ", ".join(parts))
            else:
                # Check if string contains email and format as hyperlink
                contact_str = str(contact_info)
                import re
                email_match = re.search(r'[\w.+-]+@[\w.-]+\.\w+', contact_str)
                if email_match:
                    email = email_match.group(0)
                    contact_str = contact_str.replace(email, f"{email} (mailto:{email})")
                lines.append(f"Contact information: {contact_str}")
        else:
            lines.append("Contact information: Not available - do not make up contact details")

        services = ctx.get("services")
        if isinstance(services, list) and services:
            relevant_services = self._top_relevant_items(services, query_tokens, limit=4)
            if relevant_services:
                lines.append("Services:")
                for service in relevant_services:
                    lines.append(f"- {self._stringify_item(service)}")

        products = ctx.get("products")
        if isinstance(products, list) and products:
            relevant_products = self._top_relevant_items(products, query_tokens, limit=4)
            if relevant_products:
                lines.append("Products:")
                for product in relevant_products:
                    lines.append(f"- {self._stringify_product(product)}")

        faqs = ctx.get("faqs")
        if isinstance(faqs, list) and faqs:
            relevant_faqs = self._top_relevant_items(faqs, query_tokens, limit=3)
            if relevant_faqs:
                lines.append("FAQs:")
                for faq in relevant_faqs:
                    lines.append(f"- {self._stringify_item(faq)}")

        website_pages = ctx.get("website_pages")
        if isinstance(website_pages, list) and website_pages:
            relevant_pages = self._top_relevant_items(website_pages, query_tokens, limit=3)
            if relevant_pages:
                lines.append("Website pages:")
                for page in relevant_pages:
                    lines.append(f"- {self._stringify_item(page)}")

        ctas = ctx.get("ctas") or ctx.get("next_steps")
        if isinstance(ctas, list) and ctas:
            lines.append("Preferred next actions:")
            for cta in ctas[:3]:
                lines.append(f"- {self._stringify_item(cta)}")

        business_facts = ctx.get("business_facts")
        if isinstance(business_facts, list) and business_facts:
            relevant_facts = self._top_relevant_items(business_facts, query_tokens, limit=4)
            if relevant_facts:
                lines.append("Business facts:")
                for fact in relevant_facts:
                    lines.append(f"- {self._stringify_business_fact(fact)}")

        for label, key in [
            ("Pricing", "pricing"),
            ("Pricing", "pricing_info"),
            ("Access policy", "access_policy"),
            ("Trial policy", "trial_policy"),
        ]:
            value = ctx.get(key)
            if value:
                lines.append(f"{label}: {self._stringify_item(value)}")

        # Include a compact fallback if no structured key produced lines.
        if not lines:
            lines.append(str(ctx))

        return "\n".join(lines)

    def _build_business_scope_instructions(self, tenant: Tenant) -> str:
        """Business boundary instructions that apply across industries."""
        industry = (tenant.industry or "business").strip()
        out_of_scope_mode = (tenant.out_of_scope_mode or "strict_business").strip()
        cta_goals = tenant.cta_goals if isinstance(tenant.cta_goals, list) else []
        cta_text = ", ".join([str(goal) for goal in cta_goals[:4]]) if cta_goals else "general support"

        if out_of_scope_mode == "assistive_general":
            out_of_scope_rule = (
                "For out-of-scope requests, respond politely with one short general suggestion if safe and obvious, "
                "then bridge back to relevant services with one focused follow-up question."
            )
        else:
            out_of_scope_rule = (
                "For out-of-scope requests, respond politely and transparently that this is outside the business's direct scope, "
                "then offer the nearest relevant service and one focused follow-up question. "
                "Do not recommend unrelated third-party providers in strict_business mode."
            )

        return (
            f"You represent a {industry} business. "
            f"Out-of-scope mode: {out_of_scope_mode}. "
            f"Primary outcome goals are: {cta_text}. "
            "Only claim the business provides, sells, supports, or recommends something when that is supported by business profile, website knowledge, document knowledge, or retrieved context. "
            "If a user asks for something adjacent to the business scope, do not invent unsupported offerings. "
            "Instead, explain the nearest relevant service or capability the business does provide, then ask one focused clarifying question. "
            f"{out_of_scope_rule} "
            "If the previous assistant turn offered an explicit alternative path and the user replies with yes/no, continue with that offered path rather than switching topics."
        )

    def _enrich_user_message_for_llm(self, session_id: str, user_message: str) -> str:
        """Interpret short follow-ups using recent context without changing stored user text."""
        message = (user_message or "").strip()
        if not self._needs_contextual_enrichment(message):
            return message

        recent_messages = self.db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.created_at.desc()).limit(6).all()

        if not recent_messages:
            return message

        previous_user = None
        previous_assistant = None
        skipped_current_user = False

        for msg in recent_messages:
            if msg.role == "user" and not skipped_current_user and (msg.content or "").strip() == message:
                skipped_current_user = True
                continue
            if msg.role == "assistant" and previous_assistant is None:
                previous_assistant = (msg.content or "").strip()
            elif msg.role == "user" and previous_user is None:
                previous_user = (msg.content or "").strip()

            if previous_user and previous_assistant:
                break

        if not previous_user:
            return message

        inferred_intent = self._infer_assistant_question_intent(previous_assistant)

        parts = [
            f"Current user follow-up: {message}",
            f"Previous user request: {previous_user}",
        ]
        if previous_assistant:
            parts.append(f"Previous assistant reply: {previous_assistant[:400]}")

        if self._is_affirmation(message) and inferred_intent:
            parts.append(f"Inferred user intent: affirmative reply to assistant question intent '{inferred_intent}'.")
            parts.append("Respond directly to that intent first, then provide the next best action.")
        elif self._is_negation(message) and inferred_intent:
            parts.append(f"Inferred user intent: negative reply to assistant question intent '{inferred_intent}'.")
            parts.append("Acknowledge the decline and offer one concise alternative option.")

        parts.append("Interpret the current user follow-up as a refinement or continuation of the earlier request unless the user clearly changed topics.")
        return "\n".join(parts)

    def _is_short_follow_up(self, user_message: str) -> bool:
        """Detect short continuation messages that need previous-turn context."""
        text = (user_message or "").strip().lower()
        if not text:
            return False

        tokens = re.findall(r"[a-z0-9]+", text)
        if len(tokens) <= 3 and text in self.SHORT_FOLLOW_UP_PATTERNS:
            return True
        if len(tokens) <= 2 and len(text) <= 20 and "?" not in text:
            return True
        return False

    def _needs_contextual_enrichment(self, user_message: str) -> bool:
        """Detect short or referential follow-ups that depend on previous turns."""
        if self._is_short_follow_up(user_message):
            return True

        text = (user_message or "").strip().lower()
        if not text:
            return False

        tokens = re.findall(r"[a-z0-9]+", text)
        if not tokens:
            return False

        if len(tokens) <= 12 and any(token in self.FOLLOW_UP_REFERENCE_TOKENS for token in tokens):
            return True

        if len(tokens) <= 10 and text.startswith(self.FOLLOW_UP_LEAD_INS):
            return True

        return len(tokens) <= 4 and any(token in self.FOLLOW_UP_INTENT_TOKENS for token in tokens)

    def _is_affirmation(self, user_message: str) -> bool:
        text = (user_message or "").strip().lower()
        tokens = re.findall(r"[a-z0-9]+", text)
        if not tokens:
            return False
        return " ".join(tokens) in self.AFFIRMATION_TOKENS or (len(tokens) <= 2 and any(t in self.AFFIRMATION_TOKENS for t in tokens))

    def _is_negation(self, user_message: str) -> bool:
        text = (user_message or "").strip().lower()
        tokens = re.findall(r"[a-z0-9]+", text)
        if not tokens:
            return False
        return " ".join(tokens) in self.NEGATION_TOKENS or (len(tokens) <= 2 and any(t in self.NEGATION_TOKENS for t in tokens))

    def _is_greeting(self, user_message: str) -> bool:
        """Detect simple greeting-only messages with punctuation and filler tolerance."""
        text = (user_message or "").strip().lower()
        if not text:
            return False

        normalized = re.sub(r"[^a-z0-9'\s]", " ", text)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return False

        if normalized in self.GREETING_PATTERNS:
            return True

        # Keep keyword matching strict enough to avoid classifying real business questions as greeting.
        if any(kw in normalized for kw in self.GREETING_KEYWORDS):
            return len(normalized.split()) <= 7

        tokens = re.findall(r"[a-z0-9']+", normalized)
        if not tokens:
            return False

        if len(tokens) > 7:
            return False

        compact = " ".join(tokens)
        if compact in self.GREETING_PATTERNS:
            return True

        base_greetings = {"hi", "hello", "hey", "howdy", "greetings", "hola", "namaste", "welcome"}
        first = tokens[0]
        if first in base_greetings:
            remaining = tokens[1:]
            if not remaining:
                return True

            if all(t in self.GREETING_FILLER_TOKENS for t in remaining):
                return True

            if any(t in self.NON_GREETING_INTENT_TOKENS for t in remaining):
                return False

            # Allow tiny variants like "hi all" / "hello you" without opening long-form Q&A.
            return len(tokens) <= 3

        for kw in self.GREETING_KEYWORDS:
            if kw in compact:
                return len(tokens) <= 7

        return False

    def _build_greeting_response(self, tenant: Tenant) -> str:
        """Build a quick greeting response using tenant's info."""
        name = (tenant.name or "").strip()
        welcome = (tenant.welcome_message or "").strip()
        
        if welcome:
            return welcome
        
        return f"Hello! I'm your {name} AI Assistant. How can I help you today?"

    def _infer_assistant_question_intent(self, previous_assistant: Optional[str]) -> str:
        """Infer intent from assistant's latest explicit question to bind yes/no follow-ups."""
        text = (previous_assistant or "").strip().lower()
        if not text:
            return ""

        questions = re.findall(r"([^?]+\?)", text)
        focus = questions[-1] if questions else text[-220:]

        if any(term in focus for term in ["recommend", "recommendation", "restaurant", "suggest"]):
            return "recommendations"
        if any(term in focus for term in ["service", "solution", "managed it", "support"]):
            return "service_details"
        if any(term in focus for term in ["demo", "call", "meeting", "quote", "pricing"]):
            return "next_step_cta"
        if any(term in focus for term in ["clarify", "what do you mean", "which one", "which area"]):
            return "clarification"
        return "general_follow_up"

    def _postprocess_assistant_content(self, tenant: Tenant, user_message: str, assistant_content: str, session_id: str = None) -> str:
        """Apply deterministic response quality guards independent of model behavior."""
        content = (assistant_content or "").strip()
        if not content:
            return content

        # Auto-extract lead info from user messages
        if session_id:
            self._extract_and_save_lead(session_id, user_message)

        # For explicit service-list requests, prefer deterministic catalog output
        # so configured service names are preserved exactly.
        content = self._enforce_exact_service_catalog_response(tenant, user_message, content)

        mode = (tenant.out_of_scope_mode or "strict_business").strip().lower()
        lower = content.lower()

        abrupt_refusal = any(
            marker in lower
            for marker in [
                "i can't help with that request",
                "i cannot help with that request",
                "i can't help with that",
                "i cannot help with that",
            ]
        )

        if mode == "strict_business" and abrupt_refusal:
            industry = (tenant.industry or "business").strip()
            return (
                f"I may not be the right assistant for that specific request. "
                f"I support {tenant.name} with {industry}-related services and solutions. "
                "If you share your goal, I can suggest the closest relevant option we provide."
            )

        # Apply compliance guardrails (insurance and other high-regulation industries)
        content, _ = GuardrailsService.apply(tenant, content, user_message)

        return content

    def _extract_and_save_lead(self, session_id: str, user_message: str) -> None:
        """Auto-extract contact info from user messages and save to session."""
        if not user_message:
            return
        import re
        msg = user_message.strip()
        
        # Extract email
        email_match = re.search(r'[\w.+-]+@[\w.-]+\.\w+', msg)
        email = email_match.group(0) if email_match else None
        
        # Extract phone (various formats)
        phone_patterns = [
            r'\+65\s?\d{4}\s?\d{4,5}',  # Singapore (+65 XXXX XXXX or +65 XXXXXXXXX)
            r'\+\d{1,3}\s?\d{6,12}',    # Any international format
            r'\b0[6-9]\d{9}\b',          # Indian mobile with 0
            r'\b[6-9]\d{9}\b',           # Indian without 0
            r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',  # US/Standard
            r'\b\d{8,12}\b',             # Generic 8-12 digit number (last resort)
        ]
        phone = None
        for pattern in phone_patterns:
            match = re.search(pattern, msg)
            if match:
                phone = match.group(0)
                break
        
        # Extract name ONLY if user explicitly provides it
        # Skip if message is short greeting (likely no actual name)
        msg_lower = msg.strip().lower()
        if len(msg_lower) < 25 and any(greet in msg_lower for greet in ['good morning', 'good afternoon', 'good evening', 'good night', 'hi there', 'hello there']):
            return  # Don't try to extract name from greeting
        
        name = None
        skip_words = {'hi', 'hello', 'hey', 'thanks', 'thank', 'okay', 'ok', 'yes', 'no', 'sure', 'yeah', 'yep', 'nah', 'fine', 'great', 'good', 'morning', 'evening', 'afternoon', 'how', 'what', 'can', 'may', 'please', 'would', 'you', 'we', 'they', 'our', 'my', 'is', 'the', 'a', 'an', 'back', 'soon', 'later', 'now', 'asap', 'today', 'tomorrow', 'up', 'out', 'in', 'on', 'i', 'its', 'it'}
        name_patterns = [
            r'call me (\w+)',
            r'i go by (\w+)',
            r'(?:my name is|name is|name\'s|i am|this is|its) (\w+)',
            r'(\w+) here',
            r'(\w+) speaking',
        ]
        for pattern in name_patterns:
            match = re.search(pattern, msg, re.IGNORECASE)
            if match:
                candidate = match.group(1).capitalize()
                if candidate.lower() not in skip_words and len(candidate) >= 2:
                    name = candidate
                    break

        # Fallback: if email or phone found in same message, treat first word as name.
        # Handles "sudhakar , sudhadotsudha@gmail.com, +65..." style replies.
        if not name and (email or phone):
            first_word = re.split(r'[\s,;|]+', msg.strip())[0]
            if (first_word and len(first_word) >= 2
                    and first_word.lower() not in skip_words
                    and not re.search(r'[@\d]', first_word)):
                name = first_word.capitalize()

        # Fallback: single-word reply that looks like a name (no digits, no @, 2-25 chars)
        # when the bot's last message asked for a name.
        if not name and not email and not phone:
            stripped = msg.strip()
            if (re.match(r'^[A-Za-z]{2,25}$', stripped)
                    and stripped.lower() not in skip_words):
                last_bot = self.db.query(ChatMessage).filter(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == "assistant",
                ).order_by(ChatMessage.created_at.desc()).first()
                if last_bot and re.search(r'\bname\b', (last_bot.content or ""), re.IGNORECASE):
                    name = stripped.capitalize()
        
        # Save to session if found
        if email or phone or name:
            session = self.db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if session:
                changed = False
                if name and not session.lead_name:
                    session.lead_name = name
                    changed = True
                if email and not session.lead_email:
                    session.lead_email = email
                    changed = True
                if phone and not session.lead_phone:
                    session.lead_phone = phone
                    changed = True
                if changed:
                    from datetime import datetime
                    session.lead_collected_at = datetime.now()
                    # Set flag in session_data so directive/trigger checks can short-circuit
                    # without re-querying individual fields each time.
                    sd = session.session_data or {}
                    sd["lead_collected"] = True
                    session.session_data = sd
                    self.db.flush()
                    logger.info(f"[LEAD] Saved: name={name}, email={email}, phone={phone}")

    def _enforce_exact_service_catalog_response(self, tenant: Tenant, user_message: str, assistant_content: str) -> str:
        """Return canonical tenant services for explicit service-list intents."""
        if not self._is_service_list_request(user_message):
            return assistant_content

        services = self._extract_canonical_services(tenant, limit=20)
        if not services:
            return assistant_content

        bullets = "\n".join([f"- {service}" for service in services])
        return f"Here are our services:\n{bullets}"

    def _is_service_list_request(self, user_message: str) -> bool:
        """Detect explicit requests to list services."""
        text = (user_message or "").strip().lower()
        if not text:
            return False

        patterns = [
            r"\blist\b.{0,25}\bservices?\b",
            r"\bservices?\b.{0,25}\blist\b",
            r"\bwhat\s+(are|is)\s+(your|ur|our)\s+services?\b",
            r"\bcan\s+you\s+list\s+(your|ur|our)\s+services?\b",
            r"\bshow\s+me\s+(your|ur|our)\s+services?\b",
            r"\bour\s+services\b",
        ]
        return any(re.search(pattern, text) for pattern in patterns)

    def _extract_canonical_services(self, tenant: Tenant, limit: int = 20) -> List[str]:
        """Extract canonical service names from tenant knowledge without paraphrasing."""
        knowledge = tenant.knowledge_context
        services: List[str] = []

        if isinstance(knowledge, dict):
            raw = knowledge.get("services")
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        value = (
                            str(item.get("name") or item.get("title") or item.get("service") or "").strip()
                        )
                    else:
                        value = str(item).strip()
                    if value:
                        services.append(value)
            elif isinstance(raw, str):
                for part in re.split(r"[\n•]+", raw):
                    value = part.strip(" -\t")
                    if value:
                        services.append(value)

        elif isinstance(knowledge, str):
            for line in knowledge.splitlines():
                value = line.strip().lstrip("-").strip()
                if value and len(value) <= 120:
                    services.append(value)

        deduped: List[str] = []
        seen = set()
        for service in services:
            key = service.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(service)
            if len(deduped) >= max(1, limit):
                break

        return deduped

    def _build_service_unavailable_message(self, tenant: Tenant, user_message: str = "") -> str:
        """Customer-safe degraded response when all providers fail."""
        company = (tenant.name or "our team").strip()
        message = (user_message or "").strip().lower()

        # Keep greeting turns lightweight and natural.
        if self._is_greeting(user_message):
            return self._build_greeting_response(tenant)

        service_lines = self._extract_service_highlights(tenant, limit=4)
        service_tokens = {
            "service", "services", "solution", "solutions", "support", "offer", "offering", "capabilities"
        }

        if service_lines and any(token in message for token in service_tokens):
            bullets = "\n".join([f"- {line}" for line in service_lines])
            return (
                f"Sure. Here are the key services from {company}:\n"
                f"{bullets}\n"
                "If you want, tell me your vessel or project type and I can suggest the best-fit service."
            )

        if service_lines:
            bullets = "\n".join([f"- {line}" for line in service_lines[:3]])
            return (
                f"I can still help with a quick overview for {company}:\n"
                f"{bullets}\n"
                "Share what you need and I will keep the guidance focused."
            )

        return (
            f"I can still help with {company} information. "
            "Please share whether you want services, contact details, or project support guidance."
        )

    def _extract_service_highlights(self, tenant: Tenant, limit: int = 4) -> List[str]:
        """Extract concise service lines from tenant knowledge context for degraded responses."""
        knowledge = tenant.knowledge_context
        highlights: List[str] = []

        if isinstance(knowledge, dict):
            services = knowledge.get("services")
            if isinstance(services, list):
                for item in services:
                    line = self._stringify_item(item).strip()
                    if line:
                        highlights.append(line)
            elif isinstance(services, str):
                for part in re.split(r"[\n•-]+", services):
                    line = part.strip()
                    if line:
                        highlights.append(line)

        elif isinstance(knowledge, str):
            for raw in knowledge.splitlines():
                line = raw.strip()
                if not line:
                    continue
                # Prefer bullet-like lines that look like service statements.
                if line.startswith("-"):
                    cleaned = line.lstrip("- ").strip()
                    if cleaned:
                        highlights.append(cleaned)

        deduped: List[str] = []
        seen = set()
        for line in highlights:
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(line)
            if len(deduped) >= max(1, limit):
                break

        return deduped

    def _append_source_tags(self, assistant_content: str, retrieved_sources: List[Dict[str, Any]]) -> str:
        """Sources are tracked internally but not shown to end users."""
        # Store sources in message metadata for admin review, but don't display to users
        return assistant_content

    def _check_profanity(self, text: str) -> bool:
        """Check if user message contains profanity. Returns True if offensive."""
        lowered = (text or "").lower()
        # Single-word profanity
        words = set(re.findall(r"\b\w+\b", lowered))
        if words & self.PROFANITY_WORDS:
            return True
        # Multi-word phrases that span word boundaries
        multi_word_phrases = {"kill yourself", "kys", "fuck off", "fuck you", "shut up", "piss off", "screw you"}
        for phrase in multi_word_phrases:
            if phrase in lowered:
                return True
        return False

    def _check_lead_gate(self, session: ChatSession, user_content: str = "") -> Optional[str]:
        """Return lead request text if lead collection should be appended to this turn.

        Rules:
        - First 5–8 messages are free (random per session).
        - After the free window, if lead incomplete, return a lead request to append.
        - Tracks "gate_prompted" in session_data so it never repeats.
        - If lead_collected flag is set, never ask.
        """
        # Fast-path: lead already collected via flag or all 3 fields present.
        session_data = session.session_data or {}
        if session_data.get("lead_collected") or (
            session.lead_name and session.lead_email and session.lead_phone
        ):
            return None

        user_msg_count = self.db.query(ChatMessage).filter(
            ChatMessage.session_id == session.id,
            ChatMessage.role == "user"
        ).count()

        # Resolve (or assign) the random free-message threshold for this session.
        lead_gate_threshold = session_data.get("lead_gate_threshold")
        if lead_gate_threshold is None:
            lead_gate_threshold = random.randint(5, 8)
            session_data["lead_gate_threshold"] = lead_gate_threshold
            session.session_data = session_data
            self.db.commit()

        # Messages within the free window pass through.
        if user_msg_count < lead_gate_threshold:
            return None

        # Already prompted once — allow through regardless.
        if session_data.get("gate_prompted") or (getattr(session, "lead_prompt_count", 0) or 0) >= 1:
            return None

        # Old ongoing session with many messages — never gate mid-conversation.
        if user_msg_count > 10:
            session_data["gate_prompted"] = True
            session.session_data = session_data
            self.db.commit()
            return None

        # Determine which fields are missing — ask for ONE at a time.
        has_name = bool((session.lead_name or "").strip())
        has_email = bool((session.lead_email or "").strip())
        has_phone = bool((session.lead_phone or "").strip())

        if has_name and has_email and has_phone:
            return None

        # Mark as prompted so this never fires again.
        session_data["gate_prompted"] = True
        session.session_data = session_data
        self.db.commit()

        if not has_name:
            ask = "your name"
        elif not has_email:
            ask = "your email address"
        else:
            ask = "your phone number"

        transition_phrases = {
            "your name": "Great to chat with you! To make sure our team can follow up, could you share your name?",
            "your email address": "Thanks for that! To send you the details, could I get your email address?",
            "your phone number": "Perfect! To arrange the callback, could you share your phone number?",
        }
        return transition_phrases.get(ask, f"Could you share {ask}? This helps our team follow up with you personally.")

    def _is_callback_request(self, user_message: str) -> bool:
        """Return True when the user wants the team to call THEM (not asking for company contact info)."""
        text = (user_message or "").strip().lower()
        callback_phrases = [
            "call me back", "call me please", "please call me", "call back",
            "callback", "ring me", "have someone call", "ask your team to call",
            "get someone to call", "request a call", "schedule a call", "arrange a call",
            "arrange for a call", "arrange for call", "can you arrange",
            "want a call", "need a call", "can i get a call", "can you call me",
        ]
        return any(phrase in text for phrase in callback_phrases)

    def _enforce_callback_response(self, tenant: Tenant, user_message: str, assistant_content: str, session_id: str) -> str:
        """When user asks for a callback, collect their contact details instead of giving company info."""
        if not self._is_callback_request(user_message):
            return assistant_content
        session = self.db.query(ChatSession).filter(ChatSession.id == session_id).first()

        # Check session fields AND session_data JSON fallback (widget may store lead there)
        lead_name = (session.lead_name or "").strip() if session else ""
        lead_phone = (session.lead_phone or "").strip() if session else ""
        if session and session.session_data and isinstance(session.session_data, dict):
            lead_name = lead_name or (session.session_data.get("name") or "").strip()
            lead_phone = lead_phone or (session.session_data.get("phone") or "").strip()

        if lead_name and lead_phone:
            return (
                f"Thank you, {lead_name}! Our team will call you back at {lead_phone} shortly."
            )

        # Partial info: acknowledge what we have, only ask for what's missing
        if lead_name and not lead_phone:
            return (
                f"Thank you, {lead_name}! Could I please have your phone number? "
                "Our team will reach out to arrange the callback."
            )
        if lead_phone and not lead_name:
            return (
                "I'd be happy to arrange a callback! Could I please have your name as well? "
                f"We'll call you at {lead_phone}."
            )

        return (
            "I'd be happy to arrange a callback! Could I please have your name and phone number? "
            "Our team will reach out to you shortly."
        )

    def _enforce_contact_response(self, tenant: Tenant, user_message: str, assistant_content: str) -> str:
        """Guarantee useful contact details for contact-intent queries when tenant data exists."""
        query = (user_message or "").strip().lower()
        if not query:
            return assistant_content

        if self._is_callback_request(user_message):
            return assistant_content

        contact_tokens = [
            "contact", "phone", "email", "mail", "whatsapp", "call", "address", "location", "reach"
        ]
        if not any(token in query for token in contact_tokens):
            return assistant_content

        knowledge = tenant.knowledge_context if isinstance(tenant.knowledge_context, dict) else {}
        contact_blob = ""

        official_contact = knowledge.get("official_contact")
        if isinstance(official_contact, dict):
            parts = []
            for key in ["phone", "email", "address", "whatsapp"]:
                val = str(official_contact.get(key) or "").strip()
                if val:
                    parts.append(f"{key.capitalize()}: {val}")
            contact_blob = " | ".join(parts)
        elif official_contact:
            contact_blob = str(official_contact)

        if not contact_blob:
            contact_blob = str(knowledge.get("contact_info") or "")

        # Basic extraction from combined contact text
        emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", contact_blob)
        phones = re.findall(r"(?:\+?\d[\d\-\s]{7,}\d)", contact_blob)
        whatsapp_links = re.findall(r"https?://(?:wa\.me/\d+|api\.whatsapp\.com/[^\s|]+)", contact_blob, flags=re.IGNORECASE)

        address = ""
        sg_addr_pattern = re.compile(r"(\d+[^|\n]{0,90}?Singapore\s*\d{6})", re.IGNORECASE)
        for segment in re.split(r"\|", contact_blob):
            candidate = segment.strip()
            if not candidate:
                continue
            sg_match = sg_addr_pattern.search(candidate)
            if sg_match:
                address = sg_match.group(1).strip()
                break
            if "singapore" in candidate.lower() or any(ch.isdigit() for ch in candidate) and any(k in candidate.lower() for k in ["road", "rd", "street", "st", "avenue", "ave", "drive", "dr", "lane", "way"]):
                address = candidate
                break

        # Fall back to tenant profile fields where available.
        if not emails and tenant.contact_email:
            emails = [tenant.contact_email]

        # If structured contact info is missing, mine top retrieved contact snippets.
        if not (address or phones or emails):
            try:
                hits = VectorKnowledgeService.search(
                    db=self.db,
                    tenant_id=tenant.id,
                    query="contact details phone email address",
                    top_k=5,
                )
            except Exception:
                hits = []

            snippets = []
            for hit in hits:
                blob = " ".join([
                    str(hit.get("content") or ""),
                    str(hit.get("snippet") or ""),
                ]).strip()
                if blob:
                    snippets.append(blob)
            merged = " | ".join(snippets)
            if merged:
                if not emails:
                    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", merged)
                if not phones:
                    phones = re.findall(r"(?:\+?\d[\d\-\s]{7,}\d)", merged)
                if not whatsapp_links:
                    whatsapp_links = re.findall(r"https?://(?:wa\.me/\d+|api\.whatsapp\.com/[^\s|]+)", merged, flags=re.IGNORECASE)
                if not address:
                    for segment in re.split(r"\|", merged):
                        candidate = segment.strip()
                        if not candidate:
                            continue
                        sg_match = sg_addr_pattern.search(candidate)
                        if sg_match:
                            address = sg_match.group(1).strip()
                            break
                        if "singapore" in candidate.lower() or any(ch.isdigit() for ch in candidate) and any(k in candidate.lower() for k in ["road", "rd", "street", "st", "avenue", "ave", "drive", "dr", "lane", "way"]):
                            address = candidate
                            break

        # Last deterministic fallback: parse active website docs directly.
        if not (emails and phones):
            docs = self.db.query(Document).filter(
                Document.tenant_id == tenant.id,
                Document.is_active == True,
                Document.document_type.in_(["website_page", "faq"]),
            ).order_by(Document.created_at.desc()).limit(10).all()
            merged_docs = "\n".join([(d.content or "")[:2000] for d in docs])
            if merged_docs:
                if not emails:
                    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", merged_docs)
                if not phones:
                    phones = re.findall(r"(?:\+?\d[\d\-\s]{7,}\d)", merged_docs)
                if not whatsapp_links:
                    whatsapp_links = re.findall(r"https?://(?:wa\.me/\d+|api\.whatsapp\.com/[^\s|]+)", merged_docs, flags=re.IGNORECASE)

        if emails:
            unique_emails = []
            seen = set()
            for email in emails:
                key = email.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    unique_emails.append(email.strip())

            def _email_score(addr: str) -> int:
                lower = addr.lower()
                score = 0
                if any(token in lower for token in ["sales@", "contact@", "enquiry@", "info@"]):
                    score += 3
                if any(token in lower for token in ["privacy@", "legal@", "noreply@", "no-reply@"]):
                    score -= 2
                return score

            unique_emails.sort(key=lambda e: _email_score(e), reverse=True)
            emails = unique_emails

        if address:
            address = re.sub(r"^address\s*:\s*", "", address, flags=re.IGNORECASE).strip()
            address = re.sub(r"\s+", " ", address)
            if len(address) > 120:
                address = address[:120].rstrip() + "..."

        lines = []
        if address:
            lines.append(f"- Address: {address}")
        if phones:
            lines.append(f"- Phone: {phones[0].strip()}")
        if whatsapp_links:
            wa = whatsapp_links[0].strip()
            lines.append(f"- WhatsApp: {wa}")
        if emails:
            email = emails[0].strip()
            lines.append(f"- Email: {email} (mailto:{email})")
        if tenant.website_url:
            lines.append(f"- Website: {tenant.website_url}")

        if not lines:
            return (
                "I can help you reach our team. "
                "Please share your name and preferred callback number, and we will contact you shortly."
            )

        return "Here are our contact details:\n" + "\n".join(lines)

    def _enforce_public_fact_response(self, tenant: Tenant, user_message: str, assistant_content: str) -> str:
        """Use crawled evidence for narrow public-fact questions when possible."""
        query = (user_message or "").strip().lower()
        if not query:
            return assistant_content

        leadership_terms = [
            "managing director", "ceo", "chief executive officer", "general manager", "operations director"
        ]
        if not any(term in query for term in leadership_terms):
            return assistant_content

        try:
            hits = VectorKnowledgeService.search(
                db=self.db,
                tenant_id=tenant.id,
                query=user_message,
                top_k=5,
            )
        except Exception:
            hits = []

        merged = " ".join([str(hit.get("content") or "") for hit in hits])
        if not merged:
            docs = self.db.query(Document).filter(
                Document.tenant_id == tenant.id,
                Document.is_active == True,
                Document.document_type == "website_page",
            ).order_by(Document.created_at.desc()).limit(5).all()
            merged = " ".join([(doc.content or "")[:3000] for doc in docs])
        if not merged:
            return assistant_content

        lowered = merged.lower()
        role_match = next((term for term in leadership_terms if term in lowered), None)
        if not role_match:
            return assistant_content

        # Try to extract a nearby proper name if the site publishes one.
        name_patterns = [
            rf"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,3}})\s+(?:-|,)?\s*{re.escape(role_match)}",
            rf"{re.escape(role_match)}\s+(?:-|,|:)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,3}})",
        ]
        for pattern in name_patterns:
            match = re.search(pattern, merged, flags=re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                invalid_name_tokens = {
                    "chief", "executive", "officer", "managing", "director", "general", "operations",
                    "project", "manager", "technical", "excellence", "delivery", "leading", "team",
                }
                normalized_tokens = {token.lower() for token in re.findall(r"[A-Za-z]+", name)}
                if name and len(name.split()) <= 4 and not (normalized_tokens & invalid_name_tokens):
                    return f"The {role_match} listed on the website is {name}."

        # Honest fallback when role exists but public name is not clearly published.
        if any(term in query for term in ["who", "name"]):
            return (
                f"The website mentions the role '{role_match}' in the leadership section, "
                "but the public page does not clearly publish a personal name in the crawled content."
            )

        return assistant_content

    # --- hallucination guards ----------------------------------------------
    # The two helpers below run after model output. They are deliberately
    # conservative: they only redact when the offending pricing/URL is
    # clearly absent from the tenant's grounded sources, so that legitimate
    # answers are never rewritten by accident.

    _PRICE_PATTERN = re.compile(
        r"(?:(?:USD|SGD|INR|MYR|EUR|GBP|Rs\.?|S\$|US\$)\s?|\$|₹|€|£)"
        r"\s?\d[\d,]*(?:\.\d+)?",
        flags=re.IGNORECASE,
    )

    @staticmethod
    def _numbers_in(text: str) -> set:
        """Return the set of numeric tokens (digits-only, comma-stripped) in *text*."""
        if not text:
            return set()
        return {
            n.replace(",", "")
            for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)
        }

    def _enforce_no_invented_pricing(
        self,
        tenant: Tenant,
        assistant_content: str,
        retrieved_sources: Optional[List[Dict[str, Any]]],
    ) -> str:
        """Strip currency+amount mentions whose numeric value is not present in
        any grounded source for the tenant.

        Build the allowed-numbers corpus from ``tenant.knowledge_context`` plus
        all retrieved RAG snippets. If the assistant uttered, say, ``$199`` but
        ``199`` does not appear anywhere in those grounded texts, we replace
        the offending sentence with a safe contact-us fallback rather than let
        an invented price reach the user.
        """
        if not assistant_content:
            return assistant_content
        prices = self._PRICE_PATTERN.findall(assistant_content)
        if not prices:
            return assistant_content

        corpus_parts: List[str] = []
        if tenant.knowledge_context:
            corpus_parts.append(str(tenant.knowledge_context))
        for src in retrieved_sources or []:
            corpus_parts.append(str(src.get("snippet") or ""))
            corpus_parts.append(str(src.get("content") or ""))
        corpus = "\n".join(corpus_parts)
        allowed_numbers = self._numbers_in(corpus)

        # Walk sentences, drop those whose currency-value isn't in the corpus.
        sentences = re.split(r"(?<=[.!?])\s+", assistant_content)
        kept: List[str] = []
        redacted = False
        for sentence in sentences:
            sentence_prices = self._PRICE_PATTERN.findall(sentence)
            if not sentence_prices:
                kept.append(sentence)
                continue
            sentence_numbers = self._numbers_in(sentence)
            unverified = sentence_numbers - allowed_numbers
            if unverified:
                redacted = True
                logger.info(
                    "[guard] dropping sentence with unverified pricing %s for tenant=%s",
                    sorted(unverified), tenant.id,
                )
                continue
            kept.append(sentence)

        cleaned = " ".join(s for s in kept if s).strip()
        if redacted:
            cleaned = (cleaned + " Please contact us for current pricing.").strip()
        return cleaned or assistant_content

    def _enforce_no_invented_urls(
        self,
        tenant: Tenant,
        assistant_content: str,
        retrieved_sources: Optional[List[Dict[str, Any]]],
    ) -> str:
        """Strip URLs whose hostname is not the tenant's site and isn't
        referenced in any grounded source. Conservative: when in doubt we keep
        the URL (so contact links from crawled pages survive)."""
        if not assistant_content:
            return assistant_content
        urls = re.findall(r"https?://[^\s)>\]]+", assistant_content)
        if not urls:
            return assistant_content

        def _host(u: str) -> str:
            host = re.sub(r"^https?://", "", u, flags=re.IGNORECASE).split("/", 1)[0].lower()
            host = host.split(":", 1)[0]
            return host[4:] if host.startswith("www.") else host

        allowed_hosts: set = set()
        if tenant.website_url:
            allowed_hosts.add(_host(tenant.website_url))
        if tenant.domain:
            allowed_hosts.add(_host(tenant.domain))
        # Any host appearing in knowledge_context or retrieved sources is fine.
        corpus_blob = str(tenant.knowledge_context or "")
        for src in retrieved_sources or []:
            corpus_blob += "\n" + str(src.get("snippet") or "")
            if src.get("source_url"):
                allowed_hosts.add(_host(src["source_url"]))
        for found in re.findall(r"https?://[^\s)>\]]+", corpus_blob):
            allowed_hosts.add(_host(found))
        allowed_hosts.discard("")

        result = assistant_content
        for url in urls:
            host = _host(url)
            if host and host not in allowed_hosts:
                logger.info(
                    "[guard] stripping unverified URL %s (host=%s) for tenant=%s",
                    url, host, tenant.id,
                )
                # Replace with the bare host so the user still sees *something*
                # but cannot follow an invented link.
                result = result.replace(url, f"(link omitted: {host})")
        return result

    def _resolve_model_name(self, tenant_model_name: Optional[str]) -> str:
        """Map tenant model config to provider-compatible model names with safe defaults."""
        configured = (tenant_model_name or "").strip()

        if not configured:
            return self.GROQ_DEFAULT_MODEL
        mapped = self.GROQ_MODEL_ALIASES.get(configured.lower())
        if mapped:
            return mapped
        if isinstance(self.llm_adapter, GroqAdapter):
            return configured
        return configured or self.GROQ_DEFAULT_MODEL

    def _build_vector_context(self, tenant: Tenant, session_id: Optional[str], current_user_message: str = "") -> str:
        """Retrieve top semantic chunks from tenant vector knowledge index.

        Applies three quality filters before splicing into the prompt:

        1. **Score threshold** (``RAG_MIN_SCORE``). Anything below the floor is
           dropped — these chunks are usually generic/off-topic and waste
           prompt tokens.
        2. **Dedupe vs ``knowledge_context``**. If the chunk's text is already
           substantively present in the tenant's curated knowledge_context,
           skip it — repeating the same fact twice tends to make models
           over-emphasize it and ignore other signals.
        3. **Char budget** (``RAG_CONTEXT_CHAR_BUDGET``). Stop accumulating
           once the retrieved blob hits the cap; remaining chunks are
           dropped (they were lower-scored anyway since hits come ranked).
        """
        retrieval_query = self._build_retrieval_query(session_id, current_user_message)
        if not retrieval_query:
            self._cached_rag_hits = []
            return ""

        hits = VectorKnowledgeService.search(
            db=self.db,
            tenant_id=tenant.id,
            query=retrieval_query,
            top_k=5,
        )
        # Expose raw hits so _get_retrieved_sources_preview can reuse them.
        self._cached_rag_hits = hits
        if not hits:
            return ""

        min_score = float(getattr(settings, "rag_min_score", 0.05) or 0.0)
        char_budget = int(getattr(settings, "rag_context_char_budget", 1500) or 1500)
        # ``knowledge_context`` can be a string, dict, or list depending on
        # how the tenant was onboarded (see ``_build_relevant_knowledge_context``).
        # Coerce to a single lowercase string so the dedupe substring check below
        # works regardless of shape.
        kc_blob = str(tenant.knowledge_context or "").lower()

        def _is_dup(snippet: str) -> bool:
            """Skip the chunk if a substantial slice already appears in
            knowledge_context. Cheap substring check on a normalized prefix."""
            if not snippet or not kc_blob:
                return False
            probe = snippet.lower().strip()[:120]
            return bool(probe) and probe in kc_blob

        lines: List[str] = []
        used_chars = 0
        dropped_low = dropped_dup = 0
        for hit in hits:
            score = float(hit.get("score") or 0)
            if score < min_score:
                dropped_low += 1
                continue
            snippet = (hit.get("content") or "")[:600]
            if _is_dup(snippet):
                dropped_dup += 1
                continue
            source_name = hit.get("source_name") or "Document"
            source_url = hit.get("source_url") or ""
            line = (
                f"- [{source_name}] score={score}: {snippet}"
                + (f" (source: {source_url})" if source_url else "")
            )
            # Budget check — stop before exceeding the cap.
            if used_chars + len(line) > char_budget and lines:
                break
            lines.append(line)
            used_chars += len(line)

        if dropped_low or dropped_dup:
            logger.info(
                "[RAG] tenant=%s kept=%d dropped_low=%d dropped_dup=%d budget_used=%d/%d",
                tenant.id, len(lines), dropped_low, dropped_dup, used_chars, char_budget,
            )

        return "\n".join(lines)

    def _get_retrieved_sources_preview(self, tenant: Tenant, session_id: Optional[str], current_user_message: str = "") -> List[Dict[str, Any]]:
        """Return compact retrieval evidence for debugging/observability in API responses.

        Reuses hits already fetched by ``_build_vector_context`` when available
        to avoid a redundant RAG search.
        """
        hits = getattr(self, "_cached_rag_hits", None)
        if not hits:
            retrieval_query = self._build_retrieval_query(session_id, current_user_message)
            if not retrieval_query:
                return []
            hits = VectorKnowledgeService.search(
                db=self.db,
                tenant_id=tenant.id,
                query=retrieval_query,
                top_k=5,
            )
        sources: List[Dict[str, Any]] = []
        for hit in hits:
            sources.append(
                {
                    "source_name": hit.get("source_name") or "Document",
                    "source_url": hit.get("source_url") or "",
                    "score": hit.get("score", 0),
                    "snippet": (hit.get("content") or "")[:220],
                }
            )
        return sources

    def _top_relevant_items(self, items: List[Any], query_tokens: set, limit: int = 4) -> List[Any]:
        """Score and select top relevant items without hardcoding customer-specific terms."""
        # If query asks for "all" or "list" items, return first items regardless of token match
        if query_tokens and any(t in query_tokens for t in ["all", "list", "every", "what"]):
            # For queries like "what services", "all services", return items without strict filtering
            if items:
                return items[:limit]
        
        scored = []
        for item in items:
            text_blob = self._item_text_blob(item)
            item_tokens = self._tokenize(text_blob)
            score = len(query_tokens.intersection(item_tokens)) if query_tokens else 0
            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for score, item in scored if score > 0][:limit] or items[:limit]

    def _item_text_blob(self, item: Any) -> str:
        """Build comparable text for matching relevance."""
        if isinstance(item, str):
            return item

        if isinstance(item, dict):
            parts = []
            for key in ["name", "title", "aliases", "summary", "description", "features", "benefits", "question", "answer", "headings", "url", "topic", "statement"]:
                value = item.get(key)
                if isinstance(value, list):
                    parts.extend([str(v) for v in value])
                elif value:
                    parts.append(str(value))
            return " ".join(parts)

        return str(item)

    def _stringify_product(self, item: Any) -> str:
        """Format product objects into concise context lines."""
        if not isinstance(item, dict):
            return self._stringify_item(item)

        name = item.get("name") or item.get("title") or "Product"
        description = item.get("description") or item.get("summary")
        aliases = item.get("aliases")
        features = item.get("features")

        parts = [str(name)]
        if aliases and isinstance(aliases, list):
            parts.append(f"aliases: {', '.join([str(a) for a in aliases[:4]])}")
        if description:
            parts.append(f"desc: {description}")
        if features and isinstance(features, list):
            parts.append(f"features: {', '.join([str(f) for f in features[:5]])}")

        return " | ".join(parts)

    def _stringify_item(self, item: Any) -> str:
        """Serialize a context item for prompt use."""
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            if "topic" in item and "statement" in item:
                return self._stringify_business_fact(item)
            if "question" in item and "answer" in item:
                return f"Q: {item['question']} A: {item['answer']}"
            name = item.get("name") or item.get("title")
            description = item.get("description") or item.get("summary")
            url = item.get("url")
            if name and description:
                return f"{name}: {description}" + (f" (source: {url})" if url else "")
            return str(item)
        return str(item)

    def _stringify_business_fact(self, item: Any) -> str:
        if not isinstance(item, dict):
            return str(item)
        topic = str(item.get("topic") or "fact").strip().replace("_", " ")
        statement = str(item.get("statement") or "").strip()
        source_url = str(item.get("source_url") or item.get("url") or "").strip()
        prefix = f"{topic.capitalize()}: " if topic and topic != "fact" else ""
        return prefix + statement + (f" (source: {source_url})" if source_url else "")

    def _build_retrieval_query(self, session_id: Optional[str], current_user_message: str = "") -> str:
        """Compose a retrieval query that carries forward the active topic for follow-ups."""
        current = (current_user_message or "").strip()
        recent_text = self._get_recent_user_text_for_session(session_id, limit=4)
        if not current:
            return recent_text

        if not self._needs_contextual_enrichment(current):
            return current

        recent_messages = self.db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.created_at.desc()).limit(6).all() if session_id else []

        previous_user = ""
        previous_assistant = ""
        skipped_current_user = False
        for msg in recent_messages:
            msg_content = (msg.content or "").strip()
            if msg.role == "user" and not skipped_current_user and msg_content == current:
                skipped_current_user = True
                continue
            if msg.role == "user" and not previous_user:
                previous_user = msg_content
            elif msg.role == "assistant" and not previous_assistant:
                # Keep more of the previous assistant reply (was 220). Short
                # follow-ups like picking an item from a bulleted list of 6-10
                # services need the whole list to be present in the retrieval
                # query so the selected item's name reaches the vector search.
                previous_assistant = msg_content[:500]
            if previous_user and previous_assistant:
                break

        query_parts = [current]
        if previous_user:
            query_parts.append(previous_user)
        if previous_assistant:
            query_parts.append(previous_assistant)
        elif recent_text and recent_text != current:
            query_parts.append(recent_text)
        return "\n".join([part for part in query_parts if part]).strip()

    def _detect_organization_type(self, tenant: Tenant) -> str:
        """
        Auto-detect organization type from website content and crawled data.
        Looks for keywords to determine if it's non-profit, government, etc.
        """
        # Check tenant website URL and name for indicators
        check_text = " "
        if tenant.website_url:
            check_text += tenant.website_url.lower() + " "
        if tenant.name:
            check_text += tenant.name.lower() + " "
        if tenant.prompt_template:
            check_text += str(tenant.prompt_template).lower() + " "
        
        # Check knowledge context for indicators
        if tenant.knowledge_context:
            if isinstance(tenant.knowledge_context, dict):
                for key, value in tenant.knowledge_context.items():
                    check_text += str(value).lower() + " "
            else:
                check_text += str(tenant.knowledge_context).lower() + " "
        
        # Check documents for keywords
        from app.models import Document
        docs = self.db.query(Document).filter(
            Document.tenant_id == tenant.id,
            Document.is_active == True
        ).limit(10).all()
        for doc in docs:
            check_text += (doc.name or "").lower() + " "
            check_text += (doc.content[:1000] if doc.content else "").lower() + " "
        
        # Non-profit indicators
        non_profit_keywords = ["donate", "donation", "volunteer", "charity", "non-profit", 
                        "foundation", "welfare", "IPC", "community service", 
                        "social service", "merdeka grant"]
        for kw in non_profit_keywords:
            if kw in check_text:
                return "non-profit"
        
        # Government indicators
        government_keywords = ["gov.sg", "government", "ministry", "public sector", 
                       "national", "Civic", "community centre"]
        for kw in government_keywords:
            if kw in check_text:
                return "government"
        
        return "default"

    def _tokenize(self, text: str) -> set:
        """Tokenize text into lowercase alphanumeric words."""
        if not text:
            return set()
        return set(re.findall(r"[a-z0-9]+", text.lower()))

    def _get_recent_user_text_for_session(self, session_id: Optional[str], limit: int = 6) -> str:
        """Collect recent user messages for the current session to guide relevance."""
        if not session_id:
            return ""

        rows = self.db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "user"
        ).order_by(ChatMessage.created_at.desc()).limit(limit).all()

        if not rows:
            return ""

        rows.reverse()
        return " ".join([row.content for row in rows if row.content])

    def _build_chat_messages(self, session_id: str, limit: int = 12, current_user_override: Optional[str] = None):
        """Build structured chat messages for chat-native providers."""
        history = self.db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.created_at.desc()).limit(limit).all()

        if not history:
            return []

        latest_user_id = next((msg.id for msg in history if msg.role == "user"), None)
        history.reverse()
        messages = []
        for msg in history:
            role = "assistant" if msg.role == "assistant" else "user"
            content = msg.content
            if current_user_override and latest_user_id and msg.id == latest_user_id and role == "user":
                content = current_user_override
            messages.append({"role": role, "content": content})

        return messages
    
    def get_session_messages(self, session_id: str):
        """
        Get all messages in a session
        
        Args:
            session_id: Session ID
            
        Returns:
            List of serializable message dicts
            
        Raises:
            ValueError: If session not found
        """
        messages = self.db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.created_at).all()
        
        if not messages:
            raise ValueError(f"Session {session_id} not found")
        
        result = []
        for msg in messages:
            metadata = msg.msg_metadata if isinstance(msg.msg_metadata, dict) else {}
            result.append(
                {
                    "id": msg.id,
                    "session_id": msg.session_id,
                    "content": msg.content,
                    "role": msg.role,
                    "model_used": msg.model_used,
                    "latency_ms": msg.latency_ms,
                    "tokens_used": msg.tokens_used,
                    "feedback_score": msg.feedback_score,
                    "feedback_comment": msg.feedback_comment,
                    "retrieved_sources": metadata.get("retrieved_sources") if msg.role == "assistant" else None,
                }
            )

        return result

    @staticmethod
    def _safe_int(value, default: int) -> int:
        """Convert DB-stored numeric values to int safely."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value, default: float) -> float:
        """Convert DB-stored numeric values to float safely."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    async def _execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        session: ChatSession,
        tenant: Tenant,
        tenant_id: str,
        system_prompt: str,
        chat_messages: List[Dict[str, str]],
        model_name: str,
        prompt: str,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Execute tool calls from the LLM and generate a follow-up response.

        Flow:
        1. Execute each tool via function_calling_service.
        2. Accumulate tool results as [TOOL_RESULT] messages in chat_messages.
        3. Re-call the LLM with the updated context for a final response.
        """
        tool_results: List[Dict[str, Any]] = []
        context = {
            "tenant_id": tenant_id,
            "session_id": session.id,
            "user_id": session.user_id,
        }

        for tc in tool_calls:
            func_name = tc.get("function", {}).get("name", "")
            raw_args = tc.get("function", {}).get("arguments", "{}")
            if isinstance(raw_args, str):
                import json
                try:
                    raw_args = json.loads(raw_args)
                except Exception:
                    raw_args = {}
            args = {k: v for k, v in raw_args.items() if k not in ("_context", "_tenant_id")}

            logger.info("[ChatService] Executing tool=%s args=%s", func_name, args)
            result = await function_calling_service.execute_function(func_name, args, context)
            tool_results.append(result.to_dict())

            chat_messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": json.dumps(result.to_dict()),
            })

        if not tool_results:
            return [], "I wasn't able to complete that request. Please try again."

        # Re-call LLM with tool results prepended as a system note
        result_summary = "\n".join([
            f"[TOOL RESULT: {r['success']} — {r.get('result', r.get('error', ''))}]"
            for r in tool_results
        ])
        follow_up_system = (
            system_prompt
            + f"\n\n# TOOL RESULTS\n"
            + result_summary
            + "\nUse the tool results above to provide a clear, concise response to the user."
        )

        follow_up_messages = list(chat_messages)
        follow_up_response = await self.llm_adapter.generate(
            prompt=prompt,
            model=model_name,
            temperature=self._safe_float(tenant.temperature, 0.7),
            max_tokens=self._safe_int(tenant.max_tokens, 512),
            system_prompt=follow_up_system,
            messages=follow_up_messages,
        )

        if follow_up_response.get("success"):
            final_content = (follow_up_response.get("response", "") or "").strip()
        else:
            final_content = (
                "I've processed your request but encountered an issue. "
                "Please contact our team for further assistance."
            )

        return tool_results, final_content

    def _maybe_create_booking(
        self,
        session: ChatSession,
        tenant: Tenant,
        assistant_content: str,
        user_message: str,
    ) -> str:
        """If this turn confirmed a booking and lead data is complete, create a
        WhatsAppTentativeBooking record and append an ICS download link.

        Returns the (possibly modified) assistant_content.
        """
        if session.booking_id:
            return assistant_content
        lead_name = (session.lead_name or "").strip()
        lead_phone = (session.lead_phone or "").strip()
        if not lead_name or not lead_phone:
            return assistant_content

        # Check for booking confirmation keywords in the assistant reply
        reply_lower = (assistant_content or "").lower()
        if not any(w in reply_lower for w in (
            "booking confirmed", "confirmed! \U0001f4c5", "\u2705 booking",
        )):
            return assistant_content

        date = self._extract_date_from_text(user_message) or self._extract_date_from_text(assistant_content)
        time = self._extract_time_from_text(user_message) or self._extract_time_from_text(assistant_content)
        if not date or not time:
            return assistant_content

        service_type = "booking"
        combined = (user_message + " " + assistant_content).lower()
        for kw, t in [("appointment","appointment"),("meeting","meeting"),("demo","demo"),("service","service")]:
            if kw in combined:
                service_type = t
                break

        persons = 1
        m = re.search(r"(\d+)\s*(?:people|persons?|guests?|pax)", combined)
        if m:
            persons = int(m.group(1))

        import uuid
        booking = WhatsAppTentativeBooking(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            contact_id=None,
            intent_type="booking",
            status="confirmed",
            requested_date=date,
            requested_time=time,
            requested_type=service_type,
            requested_persons=persons,
            raw_text=f"Chatbot booking: {lead_name} - {date} {time}",
            extracted_fields={"date": date, "time": time, "type": service_type, "persons": persons},
            source="chatbot",
        )
        self.db.add(booking)
        session.booking_id = booking.id
        self.db.commit()

        api_base = (os.getenv("API_BASE_URL") or "").strip().rstrip("/") or "http://localhost:8001"
        ics_url = f"{api_base}/api/ics/{booking.id}.ics"
        logger.info("[ChatService] Created booking %s for %s (%s)", booking.id[:8], lead_name, lead_phone)
        return assistant_content + f"\n\n\uD83D\uDCC5 Add to calendar: {ics_url}"

    @staticmethod
    def _extract_date_from_text(text: str) -> Optional[str]:
        from datetime import timedelta
        t = (text or "").lower()
        # relative
        if "tomorrow" in t:
            return (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
        if "today" in t or "tonight" in t:
            return datetime.utcnow().strftime("%Y-%m-%d")
        next_map = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}
        m = re.search(r"next\s+(mon|tue|wed|thu|fri|sat|sun)", t)
        if m:
            day_map = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}
            target = day_map.get(m.group(1), 0)
            today = datetime.utcnow().weekday()
            days_ahead = (target - today + 7) % 7 or 7
            return (datetime.utcnow() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return None

    @staticmethod
    def _extract_time_from_text(text: str) -> Optional[str]:
        t = (text or "").strip().lower()
        m = re.search(r"(\d{1,2}):?(\d{2})?\s*(am|pm)", t)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
            if hour > 12 or minute >= 60:
                return None
            if m.group(3) == "pm" and hour != 12:
                hour += 12
            elif m.group(3) == "am" and hour == 12:
                hour = 0
            return f"{hour:02d}:{minute:02d}"
        m = re.search(r"(\d{1,2}):(\d{2})", t)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))
            if hour >= 24 or minute >= 60:
                return None
            return f"{hour:02d}:{minute:02d}"
        if "noon" in t or "midday" in t:
            return "12:00"
        if "midnight" in t:
            return "00:00"
        return None
