"""
Memory Service - Conversation memory across sessions with cross-session context.
"""
import logging
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import re

logger = logging.getLogger(__name__)


class ConversationMemory:
    """In-memory conversation storage per session, with cross-session summary support."""

    KNOWN_FACTS_KEY = "known_facts"

    def __init__(self, max_messages: int = 20, max_tokens: int = 4000):
        self.max_messages = max_messages
        self.max_tokens = max_tokens
        self._sessions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._last_summary: Dict[str, str] = {}
        self._cross_session: Dict[str, Dict[str, Any]] = defaultdict(dict)

    def add_message(self, session_id: str, role: str, content: str, metadata: Dict = None):
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        }
        self._sessions[session_id].append(msg)
        if len(self._sessions[session_id]) > self.max_messages:
            self._sessions[session_id] = self._sessions[session_id][-self.max_messages :]

        self._update_cross_session(session_id, role, content)

    def _update_cross_session(self, session_id: str, role: str, content: str):
        """Extract and store key facts across sessions for a user."""
        if role != "user":
            return
        facts = self._cross_session[session_id]
        lowered = (content or "").lower()
        if "@" in content:
            email_match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", content)
            if email_match and "email" not in facts:
                facts["email"] = email_match.group(0)
        name_patterns = [
            r"\b(?:my name is|i'm|i am|call me|name:?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"
        ]
        for pat in name_patterns:
            m = re.search(pat, content, re.IGNORECASE)
            if m and "name" not in facts:
                facts["name"] = m.group(1).strip()
        for kw, key in [
            (["book", "demo", "meeting", "appointment"], "booking_interest"),
            (["price", "cost", "pricing", "quote"], "pricing_interest"),
            (["support", "help", "issue", "problem"], "support_interest"),
        ]:
            if any(k in lowered for k in kw) and key not in facts:
                facts[key] = True

    def get_cross_session_context(self, session_id: str) -> str:
        """Return a brief summary of known facts across sessions."""
        facts = self._cross_session.get(session_id, {})
        if not facts:
            return ""
        lines = []
        if "name" in facts:
            lines.append(f"User name: {facts['name']}")
        if "email" in facts:
            lines.append(f"User email: {facts['email']}")
        if "booking_interest" in facts:
            lines.append("User interest: booking/demo inquiry")
        if "pricing_interest" in facts:
            lines.append("User interest: pricing inquiry")
        if "support_interest" in facts:
            lines.append("User interest: support request")
        return "; ".join(lines) if lines else ""

    def get_recent(self, session_id: str, count: int = 10) -> List[Dict[str, Any]]:
        return self._sessions[session_id][-count:]

    def get_messages_for_prompt(self, session_id: str) -> str:
        messages = self.get_recent(session_id, count=self.max_messages)
        if not messages:
            return ""
        formatted = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                formatted.append(f"User: {content}")
            elif role == "assistant":
                formatted.append(f"Assistant: {content}")
            elif role == "system":
                formatted.append(f"System: {content}")
        return "\n".join(formatted)

    def clear(self, session_id: str):
        if session_id in self._sessions:
            del self._sessions[session_id]
        if session_id in self._last_summary:
            del self._last_summary[session_id]
        if session_id in self._cross_session:
            del self._cross_session[session_id]

    def get_context_summary(self, session_id: str) -> Optional[str]:
        if session_id in self._last_summary:
            return self._last_summary[session_id]
        messages = self._sessions.get(session_id, [])
        if not messages:
            return None
        recent = messages[-5:]
        topics = []
        for msg in recent:
            content = msg.get("content", "")
            if "@" in content:
                topics.append("email contact")
            if any(w in content.lower() for w in ["book", "demo", "meeting", "appointment"]):
                topics.append("booking inquiry")
            if any(w in content.lower() for w in ["price", "cost", "pricing"]):
                topics.append("pricing discussion")
        if topics:
            self._last_summary[session_id] = f"Context: {'; '.join(set(topics))}"
            return self._last_summary[session_id]
        return None


class MemoryService:
    """
    Service for managing conversation memory across sessions.
    
    Usage (in chat_service.py):
        from app.services.memory_service import memory_service
        
        # Add user message
        memory_service.add_message(session_id, "user", "I'm interested in booking a demo")
        
        # Get context for prompt
        context = memory_service.get_memory_context(session_id)
    """
    
    def __init__(self, enabled: Optional[bool] = None, max_messages: int = 20):
        if enabled is None:
            enabled = os.getenv("CONVERSATION_MEMORY_ENABLED", "false").lower() in ("1", "true", "yes")
        self.enabled = enabled
        self.max_messages = max_messages
        self._tenant_sessions: Dict[str, ConversationMemory] = {}
        logger.info(f"MemoryService initialized (enabled={enabled})")
    
    def enable(self):
        """Enable memory service"""
        self.enabled = True
        logger.info("Memory service enabled")
    
    def disable(self):
        """Disable memory service"""
        self.enabled = False
        logger.info("Memory service disabled")
    
    def get_memory(self, tenant_id: str) -> ConversationMemory:
        """Get or create memory for tenant"""
        if tenant_id not in self._tenant_sessions:
            self._tenant_sessions[tenant_id] = ConversationMemory(
                max_messages=self.max_messages
            )
        return self._tenant_sessions[tenant_id]
    
    def add_message(self, session_id: str, tenant_id: str, role: str, content: str, metadata: Dict = None):
        """Add message to session memory"""
        if not self.enabled:
            return
        
        memory = self.get_memory(tenant_id)
        memory.add_message(session_id, role, content, metadata)
    
    def get_recent(self, session_id: str, tenant_id: str, count: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages"""
        if not self.enabled:
            return []
        return self.get_memory(tenant_id).get_recent(session_id, count)
    
    def get_memory_context(self, session_id: str, tenant_id: str) -> str:
        """Get formatted memory context for LLM"""
        if not self.enabled:
            return ""
        return self.get_memory(tenant_id).get_messages_for_prompt(session_id)
    
    def get_summary(self, session_id: str, tenant_id: str) -> Optional[str]:
        """Get context summary"""
        if not self.enabled:
            return None
        return self.get_memory(tenant_id).get_context_summary(session_id)
    
    def clear_session(self, session_id: str, tenant_id: str):
        """Clear session memory"""
        if tenant_id in self._tenant_sessions:
            self._tenant_sessions[tenant_id].clear(session_id)


# Singleton instance
memory_service = MemoryService(enabled=False)
