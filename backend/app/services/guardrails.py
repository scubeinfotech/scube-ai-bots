"""
Insurance Guardrails Service - domain-specific response compliance for regulated industries.

Applies to tenants where industry='insurance' or compliance_mode='high-regulation'.
Config can be overridden per-tenant via the tenant.guardrails JSON column.
"""
import re
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.models import Tenant

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in defaults for insurance tenants
# ---------------------------------------------------------------------------
_DEFAULT_INSURANCE_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "require_disclaimer": True,
    "disclaimer_text": (
        "This is general information only, not official insurance advice. "
        "Please consult your licensed agent for your specific policy details."
    ),
    "disclaimer_trigger_keywords": [
        "cover", "coverage", "covers", "covered", "covering",
        "policy", "policies", "claim", "claims",
        "premium", "deductible", "exclusion", "pre-existing",
        "benefit", "benefits", "reimbursement", "payout",
    ],
    "prohibited_phrase_patterns": [
        {
            # "Yes, your policy covers diabetes" → softened
            "pattern": (
                r"\byes\b.{0,60}"
                r"(policy|plan|coverage|insurance).{0,60}"
                r"\b(covers?|includes?|provides?|pays?)\b"
            ),
            "replacement": (
                "Coverage for that depends on your specific policy terms and conditions"
            ),
            "reason": "direct_coverage_assertion",
        },
        {
            # "We guarantee coverage / guaranteed payout"
            "pattern": r"\bguarantee[sd]?\b.{0,80}\b(coverage|covered|pay|payout|claim|benefit)\b",
            "replacement": "specific coverage is subject to your policy terms and conditions",
            "reason": "guarantee_language",
        },
        {
            # "You should buy / I recommend you invest in insurance"
            "pattern": (
                r"\b(you should|we recommend|i recommend|i suggest)\b"
                r".{0,100}"
                r"\b(invest|buy|purchase|switch|upgrade)\b"
                r".{0,60}"
                r"\b(insurance|policy|plan|coverage)\b"
            ),
            "replacement": (
                "it would be best to speak with a licensed agent to evaluate your options"
            ),
            "reason": "financial_advice",
        },
        {
            # "Your claim will be approved / claims are paid"
            "pattern": (
                r"\b(your )?(claim|claims)\b.{0,60}"
                r"\b(will be|shall be|is|are)\b.{0,30}"
                r"\b(approved|paid|settled|accepted|processed)\b"
            ),
            "replacement": (
                "claim eligibility and outcomes depend on your policy terms "
                "and the specific circumstances"
            ),
            "reason": "claim_outcome_assertion",
        },
    ],
}

_INSURANCE_INDUSTRIES = {"insurance"}

# Phrases that signal a disclaimer is already present — avoid double-appending
_DISCLAIMER_ALREADY_PRESENT_PHRASES = [
    "general information only",
    "consult your agent",
    "consult a licensed",
    "contact your agent",
    "not official insurance",
    "not financial advice",
    "licensed agent",
    "speak with your agent",
    "speak to your agent",
]


class GuardrailsService:
    """
    Apply compliance guardrails to LLM responses for regulated industry tenants.

    Usage::

        modified, audit = GuardrailsService.apply(tenant, response, user_message)
    """

    @classmethod
    def apply(
        cls,
        tenant: Tenant,
        response: str,
        user_message: str = "",
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Apply guardrails to a single LLM response.

        Returns:
            Tuple of (modified_response, audit_metadata).
            audit_metadata contains 'applied' boolean and 'actions' list.
        """
        config = cls._resolve_config(tenant)
        if not config.get("enabled"):
            return response, {"applied": False}

        modified = response
        audit: Dict[str, Any] = {"applied": True, "tenant_id": tenant.id, "actions": []}

        # Step 1: Replace prohibited response patterns
        modified, pattern_actions = cls._apply_pattern_replacements(modified, config)
        audit["actions"].extend(pattern_actions)

        # Step 2: Inject required disclaimer when trigger keywords are present
        modified, disclaimer_action = cls._apply_disclaimer(modified, user_message, config)
        if disclaimer_action:
            audit["actions"].append(disclaimer_action)

        if audit["actions"]:
            logger.info(
                "[Guardrails] tenant=%s applied %d guardrail action(s): %s",
                tenant.id,
                len(audit["actions"]),
                [a.get("action") or a.get("reason") for a in audit["actions"]],
            )

        return modified, audit

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _resolve_config(cls, tenant: Tenant) -> Dict[str, Any]:
        """
        Resolve the effective guardrail configuration for a tenant.

        Priority:
        1. If stored guardrails JSON has an explicit ``enabled`` key → use it
           (merged on top of defaults so per-tenant overrides still work).
        2. If tenant.industry is 'insurance' or compliance_mode is 'high-regulation'
           → auto-enable with full default config, overriding with any stored values.
        3. Otherwise → disabled.
        """
        stored: Dict[str, Any] = (
            tenant.guardrails if isinstance(tenant.guardrails, dict) else {}
        )

        if "enabled" in stored:
            # Merge: defaults first, stored overrides on top
            config = dict(_DEFAULT_INSURANCE_CONFIG)
            config.update(stored)
            return config

        industry = (tenant.industry or "").lower().strip()
        compliance_mode = (tenant.compliance_mode or "normal").lower().strip()

        if industry in _INSURANCE_INDUSTRIES or compliance_mode == "high-regulation":
            config = dict(_DEFAULT_INSURANCE_CONFIG)
            # Allow partial overrides (e.g. custom disclaimer_text) from stored config
            config.update({k: v for k, v in stored.items() if v is not None})
            return config

        return {"enabled": False}

    @classmethod
    def _apply_pattern_replacements(
        cls, response: str, config: Dict[str, Any]
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Apply each prohibited-phrase regex rule to the response text."""
        modified = response
        actions: List[Dict[str, Any]] = []

        for rule in config.get("prohibited_phrase_patterns", []):
            pattern: str = rule.get("pattern", "")
            replacement: str = rule.get("replacement", "")
            reason: str = rule.get("reason", "pattern_match")
            if not pattern:
                continue

            new_text, count = re.subn(pattern, replacement, modified, flags=re.IGNORECASE)
            if count > 0:
                modified = new_text
                actions.append({"action": "pattern_replaced", "reason": reason, "count": count})

        return modified, actions

    @classmethod
    def _apply_disclaimer(
        cls, response: str, user_message: str, config: Dict[str, Any]
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Append the required disclaimer to the response when:
        - require_disclaimer is enabled AND
        - a trigger keyword appears in user message or LLM response AND
        - the response does not already contain a disclaimer-like phrase.
        """
        if not config.get("require_disclaimer"):
            return response, None

        disclaimer_text: str = config.get("disclaimer_text") or (
            "This is general information only. "
            "Please consult your licensed agent for accurate policy details."
        )

        trigger_keywords: List[str] = config.get("disclaimer_trigger_keywords", [])

        # Check if response already contains a disclaimer phrase
        lower_response = response.lower()
        if any(phrase in lower_response for phrase in _DISCLAIMER_ALREADY_PRESENT_PHRASES):
            return response, None

        # Check for trigger keyword presence
        combined = (response + " " + user_message).lower()
        triggered = any(kw.lower() in combined for kw in trigger_keywords)
        if not triggered:
            return response, None

        modified = response.rstrip() + "\n\n*" + disclaimer_text + "*"
        return modified, {"action": "disclaimer_appended", "trigger": "keyword_match"}
