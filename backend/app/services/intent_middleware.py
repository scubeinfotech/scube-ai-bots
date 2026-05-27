"""
Intent detection middleware for WhatsApp inbound messages.

Provides lightweight intent classification and structured field extraction
for booking-oriented workflows.
"""
import re
from typing import Any, Dict, Optional


BOOKING_INTENT = "booking"
BOOKING_LOOKUP_INTENT = "booking_lookup"
CALLBACK_INTENT = "callback"
DEMO_SCHEDULING_INTENT = "demo_scheduling"
FAQ_INTENT = "faq"
UNKNOWN_INTENT = "unknown"


class IntentDetectionMiddleware:
    """Classify inbound message intent and extract structured booking fields."""

    _BOOKING_LOOKUP_KEYWORDS = (
        "my booking", "my bookings", "my reservation", "my reservations",
        "existing booking", "existing bookings",
        "share the booking", "share the bookings",
        "list booking", "list bookings",
        "what booking", "what bookings",
        "show booking", "show bookings",
        "upcoming booking", "upcoming bookings",
        "check booking", "check bookings",
        "do i have a booking", "do i have any booking",
        "view booking", "view bookings",
        "can you share",
    )
    _BOOKING_KEYWORDS = (
        "book", "booking", "reserve", "reservation", "appointment", "schedule",
        "meeting", "meet", "discuss", "discussion", "talk", "session", "consultation",
        "visit", "come in", "stop by", "see you", "catch up"
    )
    _CALLBACK_KEYWORDS = (
        "callback", "call back", "call me", "ring me", "phone me", "contact me"
    )
    _DEMO_KEYWORDS = (
        "demo", "demonstration", "walkthrough", "show me", "product demo"
    )
    _FAQ_HINTS = (
        "what", "how", "when", "where", "which", "why", "can", "do", "does"
    )

    _DATE_PATTERNS = (
        re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", re.IGNORECASE),
        re.compile(
            r"\b(?:today|tomorrow|day after tomorrow|"
            r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
            r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
            r"nov(?:ember)?|dec(?:ember)?)\b",
            re.IGNORECASE,
        ),
    )
    _TIME_PATTERNS = (
        re.compile(r"\b\d{1,2}:\d{2}\s?(?:am|pm)?\b", re.IGNORECASE),
        re.compile(r"\b\d{1,2}\s?(?:am|pm)\b", re.IGNORECASE),
        re.compile(r"\b(?:morning|afternoon|evening|night)\b", re.IGNORECASE),
    )
    _PERSONS_PATTERN = re.compile(
        r"\b(\d{1,2})\s*(?:persons?|people|pax|guests?)\b",
        re.IGNORECASE,
    )

    def analyze(self, message_text: str) -> Dict[str, Any]:
        """Return intent classification and extracted structured fields."""
        normalized = self._normalize(message_text)
        intent, confidence = self._classify_intent(normalized)
        fields = self._extract_fields(message_text, intent)

        return {
            "intent": intent,
            "confidence": confidence,
            "fields": fields,
            "raw_text": message_text,
        }

    def _classify_intent(self, normalized_text: str) -> tuple[str, float]:
        """Classify message intent using deterministic keyword heuristics."""
        if self._contains_any(normalized_text, self._CALLBACK_KEYWORDS):
            return CALLBACK_INTENT, 0.91

        if self._contains_any(normalized_text, self._DEMO_KEYWORDS):
            return DEMO_SCHEDULING_INTENT, 0.9

        if self._contains_any(normalized_text, self._BOOKING_LOOKUP_KEYWORDS):
            return BOOKING_LOOKUP_INTENT, 0.85

        if self._contains_any(normalized_text, self._BOOKING_KEYWORDS):
            return BOOKING_INTENT, 0.88

        if "?" in normalized_text or self._contains_any(normalized_text, self._FAQ_HINTS):
            return FAQ_INTENT, 0.76

        return UNKNOWN_INTENT, 0.5

    def _extract_fields(self, raw_text: str, intent: str) -> Dict[str, Any]:
        """Extract date/time/persons/type fields from inbound message text."""
        extracted: Dict[str, Any] = {}

        date_value = self._first_match(raw_text, self._DATE_PATTERNS)
        if date_value:
            extracted["date"] = date_value

        time_value = self._first_match(raw_text, self._TIME_PATTERNS)
        if time_value:
            extracted["time"] = time_value

        persons_match = self._PERSONS_PATTERN.search(raw_text)
        if persons_match:
            extracted["persons"] = int(persons_match.group(1))

        extracted_type = self._extract_type(raw_text, intent)
        if extracted_type:
            extracted["type"] = extracted_type

        return extracted

    def _extract_type(self, raw_text: str, intent: str) -> Optional[str]:
        lowered = raw_text.lower()

        if intent == DEMO_SCHEDULING_INTENT:
            return "demo"
        if intent == CALLBACK_INTENT:
            return "callback"

        if "table" in lowered:
            return "table"
        if "service" in lowered:
            return "service"
        if "appointment" in lowered:
            return "appointment"
        if intent == BOOKING_INTENT:
            return "booking"

        return None

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().strip().split())

    @staticmethod
    def _contains_any(text: str, words: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in words)

    @staticmethod
    def _first_match(text: str, patterns: tuple[re.Pattern, ...]) -> Optional[str]:
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return match.group(0)
        return None
