"""
Unit tests for ChatService._infer_response_language.

These exercise the lexical detector across the five supported languages and
specifically pin the regressions fixed in Phase 2.3 of EVENING_FIX_PLAN.md:

* short utterances (< 3 alpha tokens) must default to English; a single
  Singlish/Malay hint word is no longer enough to flip language.
* Tamil-romanized detection now requires 3 distinct hint tokens (was 2),
  cutting false positives on plain English with one or two ambiguous words.
"""
import pytest

from app.services.chat_service import ChatService


@pytest.fixture
def svc(db):
    """ChatService bound to the in-memory test DB; uses the mock adapter."""
    return ChatService(db=db, llm_provider="mock")


def detect(svc: ChatService, text: str) -> str:
    """Helper: detect language for a one-shot user message (no session history)."""
    return svc._infer_response_language(session_id=None, user_message=text)


# ----------------------------- script-based -----------------------------

def test_tamil_script_detected(svc):
    assert detect(svc, "வணக்கம், எப்படி இருக்கீங்க?") == "tamil"


def test_chinese_script_detected(svc):
    assert detect(svc, "你好，请问有什么可以帮助您的？") == "chinese"


# ------------------------- explicit language requests -------------------

def test_explicit_english_request(svc):
    assert detect(svc, "please reply in english from now on") == "english"


def test_explicit_malay_request(svc):
    assert detect(svc, "please reply in malay") == "malay"


def test_explicit_chinese_request(svc):
    assert detect(svc, "in chinese please") == "chinese"


# ----------------------------- Singlish ---------------------------------

def test_singlish_phrase_detected(svc):
    # Multi-word phrase is weighted 3 → enough on its own.
    assert detect(svc, "can or not? i need this lah") == "singlish"


def test_singlish_multiple_hints(svc):
    assert detect(svc, "the food shiok lah, can chope a table?") == "singlish"


# ------------------------------ Malay -----------------------------------

def test_malay_two_hint_tokens(svc):
    # Two distinct Malay hints + length >= 3 alpha tokens → malay.
    assert detect(svc, "saya nak tolong dengan tempahan") == "malay"


# ------------------------- Tamil-romanized ------------------------------

def test_tamil_romanized_three_hints(svc):
    # Three distinct hints → must classify as tamil.
    assert detect(svc, "naan inga irukku, enna sapadu venum?") == "tamil"


def test_tamil_romanized_two_hints_no_longer_enough(svc):
    # Two-hint case: post Phase 2.3 we expect English, not Tamil. This is the
    # regression guard for the threshold bump from 2 -> 3.
    assert detect(svc, "naan inga only") == "english"


# ----------------- short-utterance default-to-english -------------------

@pytest.mark.parametrize(
    "msg",
    [
        "ok",
        "hi",
        "thanks",
        "lah",          # single Singlish hint, but only 1 token → english
        "saya",         # single Malay hint, 1 token → english
        "naan inga",    # 2 Tamil hints but only 2 alpha tokens → english
    ],
)
def test_short_utterance_defaults_to_english(svc, msg):
    assert detect(svc, msg) == "english"


# ----------------- empty / non-textual inputs ---------------------------

def test_empty_message_defaults_to_english(svc):
    assert detect(svc, "") == "english"


def test_only_punctuation_defaults_to_english(svc):
    assert detect(svc, "!!! ??? ...") == "english"


# ----------------- plain English doesn't get reclassified ---------------

@pytest.mark.parametrize(
    "msg",
    [
        "hello, what services do you offer?",
        "I would like to know your pricing for catering",
        "Can you tell me about delivery options please",
        "What time do you open on Sunday morning",
        "Do you have vegetarian items on the menu",
    ],
)
def test_english_business_queries_stay_english(svc, msg):
    assert detect(svc, msg) == "english"
