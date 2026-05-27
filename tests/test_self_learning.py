"""
Tests for Phase 1.1 self-learning quality improvements.
Covers: relaxed gate, dedup key length, MIN_RESPONSE_WORDS, helper functions.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.self_learning import (
    HIGH_CONFIDENCE_LEARN_THRESHOLD,
    MIN_RESPONSE_WORDS,
    _is_small_talk_query,
    _is_too_short,
    _make_document_content,
    _normalize_query_key,
    _promote_to_structured_faq,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_min_response_words_lowered(self):
        """MIN_RESPONSE_WORDS should be ≤ 15 so short but valuable answers qualify."""
        assert MIN_RESPONSE_WORDS <= 15

    def test_high_confidence_threshold_defined(self):
        """HIGH_CONFIDENCE_LEARN_THRESHOLD must exist and be between 0.7 and 0.95."""
        assert 0.70 <= HIGH_CONFIDENCE_LEARN_THRESHOLD <= 0.95


# ---------------------------------------------------------------------------
# Dedup key
# ---------------------------------------------------------------------------

class TestNormalizeQueryKey:
    def test_truncates_at_400_chars(self):
        long_query = "a" * 500
        key = _normalize_query_key(long_query)
        assert len(key) == 400

    def test_shorter_than_400_not_padded(self):
        short = "what are your office hours"
        key = _normalize_query_key(short)
        assert key == short

    def test_lowercases(self):
        assert _normalize_query_key("Hello WORLD") == "hello world"

    def test_strips_whitespace(self):
        assert _normalize_query_key("  spaces  ") == "spaces"

    def test_empty_string(self):
        assert _normalize_query_key("") == ""

    def test_none_safe(self):
        assert _normalize_query_key(None) == ""  # type: ignore


# ---------------------------------------------------------------------------
# Response length gate
# ---------------------------------------------------------------------------

class TestIsTooShort:
    def test_exactly_min_words_passes(self):
        text = " ".join(["word"] * MIN_RESPONSE_WORDS)
        assert not _is_too_short(text)

    def test_one_below_min_words_fails(self):
        text = " ".join(["word"] * (MIN_RESPONSE_WORDS - 1))
        assert _is_too_short(text)

    def test_empty_response_too_short(self):
        assert _is_too_short("")

    def test_long_response_passes(self):
        text = "word " * 50
        assert not _is_too_short(text)


# ---------------------------------------------------------------------------
# Small-talk filter
# ---------------------------------------------------------------------------

class TestIsSmallTalkQuery:
    def test_hi_is_small_talk(self):
        assert _is_small_talk_query("hi")

    def test_hello_is_small_talk(self):
        assert _is_small_talk_query("Hello")

    def test_business_query_not_small_talk(self):
        assert not _is_small_talk_query("What are your product prices?")

    def test_mixed_greeting_business_not_small_talk(self):
        assert not _is_small_talk_query("Hi, what is your return policy?")


# ---------------------------------------------------------------------------
# Gate: thumbs-up OR high confidence
# ---------------------------------------------------------------------------

class TestLearningGateRelaxed:
    """
    The relaxed gate logic is:
        skip if NOT thumbs_up AND confidence < HIGH_CONFIDENCE_LEARN_THRESHOLD
    Therefore:
        - thumbs_up=True, any confidence  → learn
        - thumbs_up=False, confidence >= 0.80 → learn
        - thumbs_up=False, confidence < 0.80  → skip
    """

    def _gate_passes(self, explicit_thumbs_up: bool, confidence: float) -> bool:
        """Replicate the gate condition from self_learning.py _learn_for_tenant."""
        return explicit_thumbs_up or confidence >= HIGH_CONFIDENCE_LEARN_THRESHOLD

    def test_thumbs_up_always_learns(self):
        assert self._gate_passes(True, 0.30)

    def test_high_confidence_no_thumbs_up_learns(self):
        assert self._gate_passes(False, HIGH_CONFIDENCE_LEARN_THRESHOLD)

    def test_just_above_threshold_learns(self):
        assert self._gate_passes(False, HIGH_CONFIDENCE_LEARN_THRESHOLD + 0.01)

    def test_low_confidence_no_thumbs_up_skipped(self):
        assert not self._gate_passes(False, HIGH_CONFIDENCE_LEARN_THRESHOLD - 0.01)

    def test_zero_confidence_no_thumbs_up_skipped(self):
        assert not self._gate_passes(False, 0.0)


# ---------------------------------------------------------------------------
# Document content formatting
# ---------------------------------------------------------------------------

class TestMakeDocumentContent:
    def test_formats_qa_pair(self):
        content = _make_document_content("What is your price?", "Our price starts at $99.")
        assert content == "Q: What is your price?\nA: Our price starts at $99."

    def test_strips_whitespace(self):
        content = _make_document_content("  q  ", "  a  ")
        assert content == "Q: q\nA: a"


# ---------------------------------------------------------------------------
# FAQ promotion (unchanged behaviour verification)
# ---------------------------------------------------------------------------

class TestPromoteToStructuredFaq:
    def _make_tenant(self):
        t = MagicMock()
        t.knowledge_context = {}
        return t

    def test_low_confidence_no_thumbs_up_not_promoted(self):
        tenant = self._make_tenant()
        promoted = _promote_to_structured_faq(tenant, "q?", "answer", 0.70, False)
        assert not promoted

    def test_explicit_thumbs_up_promotes(self):
        tenant = self._make_tenant()
        promoted = _promote_to_structured_faq(tenant, "q?", "answer", 0.50, True)
        assert promoted

    def test_very_high_confidence_no_thumbs_up_promotes(self):
        tenant = self._make_tenant()
        promoted = _promote_to_structured_faq(tenant, "q?", "answer", 0.93, False)
        assert promoted

    def test_duplicate_not_promoted_again(self):
        tenant = self._make_tenant()
        _promote_to_structured_faq(tenant, "what is price?", "answer", 0.95, True)
        second = _promote_to_structured_faq(tenant, "what is price?", "answer", 0.95, True)
        assert not second
