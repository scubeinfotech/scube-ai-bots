"""
Step 3 – WhatsApp Booking & Callback Conversation State Machine

WhatsApp-specific optimizations:
1. Phone number already known via WhatsApp contact — never ask for it
2. Crisp, short messages — respect user's time on mobile
3. Quick closure — clear value for both user and business owner
4. Different from web chat: web chat needs lead form, WhatsApp already has identity

State flow
──────────
idle  ──(intent detected)──►  collecting  ──(fields complete)──►  confirming  ──(yes)──►  completed
"""

from __future__ import annotations
import re
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

# ── State constants ────────────────────────────────────────────────────────────
BOOKING_STATES = {
    "idle": "idle",
    "collecting": "collecting",
    "confirming": "confirming",
    "completed": "completed",
}

# WhatsApp: Phone already known. Minimize fields for quick mobile interaction.
REQUIRED_BOOKING_FIELDS = ["date", "time"]  # persons is optional now
REQUIRED_CALLBACK_FIELDS = ["time"]  # callback just needs time preference (date=asap)
OPTIONAL_BOOKING_FIELDS = ["persons", "type"]

CONFIRM_WORDS = {"yes", "yeah", "yep", "confirm", "confirmed", "ok", "okay", "sure", "correct", "done"}
CANCEL_WORDS = {"no", "nope", "cancel", "stop", "wrong", "restart", "start over", "later", "not now"}

# ── Crisp WhatsApp Questions ───────────────────────────────────────────────────
# Short, clear, mobile-friendly. Phone already known via WhatsApp contact.
FIELD_QUESTIONS: Dict[str, str] = {
    "date": "When? (today/tomorrow/Monday)",
    "time": "What time?",
    "persons": "How many people?",
    "type": "Preference? (window/private/standard) or skip",
}

# ── Confirmation Templates ───────────────────────────────────────────────────
CALLBACK_SUMMARY = (
    "Confirm callback:\n"
    "� Call you at: *{time}*\n"
    "Reply *Yes* to confirm"
)

BOOKING_SUMMARY = (
    "Confirm booking:\n"
    "� {date} at {time}\n"
    "{persons_line}"
    "Reply *Yes* to confirm"
)

# Legacy template for compatibility
SUMMARY_TEMPLATE = BOOKING_SUMMARY


class BookingConversationManager:
    """
    Manages multi-step booking conversation state stored on WhatsAppSession.
    Stateless service – reads/writes booking_flow_state and booking_data
    on the session object passed in by the caller.
    """

    # ── Public API ─────────────────────────────────────────────────────────────

    def handle(
        self,
        message_text: str,
        session,                     # WhatsAppSession ORM object
        intent_result: Dict[str, Any],
        contact_phone: Optional[str] = None,  # WhatsApp already has this
        tenant_id: Optional[str] = None,  # For calendar validation
    ) -> Optional[str]:
        """
        Process one inbound message within the booking flow.
        WhatsApp-specific: Phone already known, keep it crisp.

        Returns:
            str  – the bot's follow-up reply (do NOT call LLM for this turn)
            None – no special handling needed; let LLM process normally
        """
        state = session.booking_flow_state or "idle"
        fields = dict(session.booking_data or {})
        text_low = message_text.strip().lower()
        intent_type = intent_result.get("intent", "")

        # ── 1. Fresh booking/callback/demo intent ──────────────────────────────
        if intent_type in ("booking", "callback", "demo_scheduling"):
            # Merge any fields already extracted from this message
            extracted = intent_result.get("fields", {})
            fields = {**fields, **{k: v for k, v in extracted.items() if v is not None}}

            # For callback: auto-fill date as "asap" if not provided
            if intent_type == "callback" and not fields.get("date"):
                fields["date"] = "asap"

            self._save(session, "collecting", fields, intent_type)

            missing = self._missing_required(fields, intent_type)
            if not missing:
                return self._ask_confirmation(session, fields, intent_type, tenant_id)
            return FIELD_QUESTIONS[missing[0]]

        # ── 2. Collecting fields ────────────────────────────────────────────────
        if state == "collecting":
            if any(w in text_low for w in CANCEL_WORDS):
                self._save(session, "idle", {}, None)
                return "No problem. Reply anytime to schedule."

            # Try to fill the next missing field from the current message
            filled = self._extract_field_from_reply(text_low, message_text, fields, session.current_intent)
            if filled:
                fields.update(filled)
                self._save(session, "collecting", fields, session.current_intent)

            missing = self._missing_required(fields, session.current_intent)
            if missing:
                return FIELD_QUESTIONS[missing[0]]

            # All required fields present → ask for confirmation
            return self._ask_confirmation(session, fields, session.current_intent, tenant_id)

        # ── 3. Confirming ───────────────────────────────────────────────────────
        if state == "confirming":
            if any(w in text_low for w in CONFIRM_WORDS):
                self._save(session, "completed", fields, session.current_intent)
                return self._get_closure_message(fields, session.current_intent, contact_phone)

            if any(w in text_low for w in CANCEL_WORDS):
                self._save(session, "idle", {}, None)
                return "Cancelled. Reply 'book' or 'callback' to start over."

            return "Reply *Yes* to confirm or *No* to cancel."

        # ── 4. No active booking flow ─────────────────────────────────────────
        return None

    def is_in_booking_flow(self, session) -> bool:
        return (session.booking_flow_state or "idle") in ("collecting", "confirming")

    def is_completed(self, session) -> bool:
        return (session.booking_flow_state or "idle") == "completed"

    # ── Private helpers ────────────────────────────────────────────────────────

    def _save(self, session, state: str, fields: dict, intent: Optional[str] = None) -> None:
        session.booking_flow_state = state
        session.booking_data = fields
        if intent:
            session.current_intent = intent

    def _missing_required(self, fields: dict, intent: str = "") -> list[str]:
        if intent == "callback":
            return [f for f in REQUIRED_CALLBACK_FIELDS if not fields.get(f)]
        return [f for f in REQUIRED_BOOKING_FIELDS if not fields.get(f)]

    def _ask_confirmation(self, session, fields: dict, intent: str = "", tenant_id: str = None) -> str:
        """
        Show confirmation summary with calendar validation.
        Crisp for WhatsApp mobile.
        """
        # Store validation info in session for later use
        validation = {"valid": True, "issues": [], "alternatives": []}
        
        # Validate against calendar if tenant_id provided
        if tenant_id and intent in ("booking", "callback", "demo_scheduling"):
            validation = self._validate_booking(tenant_id, fields, intent)
            session.booking_validation = validation
        
        self._save(session, "confirming", fields, intent)

        # If there are issues, show them
        if not validation["valid"]:
            if validation["alternatives"]:
                alt_text = "\n".join([f"  • {a['display']}" for a in validation["alternatives"][:3]])
                return (
                    f"⚠️ {validation['issues'][0]}\n\n"
                    f"Available alternatives:\n{alt_text}\n\n"
                    f"Reply with your preferred time or *No* to cancel."
                )
            else:
                return f"⚠️ {validation['issues'][0]}\n\nReply *No* to cancel or suggest another time."

        if intent == "callback":
            return CALLBACK_SUMMARY.format(time=fields.get("time", "—"))

        # Booking or demo
        persons_line = f"👥 {fields.get('persons', '2')} guests\n" if fields.get("persons") else ""
        return BOOKING_SUMMARY.format(
            date=fields.get("date", "—"),
            time=fields.get("time", "—"),
            persons_line=persons_line,
        )

    def _validate_booking(self, tenant_id: str, fields: dict, intent: str) -> dict:
        """
        Validate booking against calendar availability.
        Returns validation result with issues and alternatives.
        """
        # Lazy import to avoid circular dependency
        from app.database import SessionLocal
        from app.services.calendar_service import CalendarService
        
        result = {"valid": True, "issues": [], "alternatives": []}
        
        # Parse date and time
        date_str = fields.get("date", "")
        time_str = fields.get("time", "")
        
        if not date_str or not time_str:
            return result  # Let it pass, will be handled later
        
        # Normalize date
        parsed_date = self._normalize_date(date_str)
        if not parsed_date:
            return result
        
        # Normalize time
        parsed_time = self._normalize_time(time_str)
        if not parsed_time:
            return result
        
        db = SessionLocal()
        try:
            # Use the smart booking check
            check = CalendarService.smart_booking_check(
                tenant_id=tenant_id,
                date=parsed_date,
                time_str=parsed_time,
                db=db,
                contact_name=fields.get("name", "")
            )
            
            if check["action"] == "reject":
                result["valid"] = False
                result["issues"].append(check["reason"])
            elif check["action"] == "suggest_alternative":
                result["valid"] = False
                result["issues"].append(check["reason"])
                result["alternatives"] = check["alternatives"]
            # else: confirm - no issues
            
        finally:
            db.close()
        
        return result

    def _normalize_date(self, date_str: str) -> Optional[str]:
        """Convert relative dates to YYYY-MM-DD format."""
        today = datetime.now().date()
        date_str = date_str.lower().strip()
        
        if date_str == "today":
            return today.strftime("%Y-%m-%d")
        elif date_str == "tomorrow":
            return (today + timedelta(days=1)).strftime("%Y-%m-%d")
        elif date_str == "asap":
            return today.strftime("%Y-%m-%d")
        
        # If already in YYYY-MM-DD format
        if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
            return date_str
        
        return None

    def _normalize_time(self, time_str: str) -> Optional[str]:
        """Convert various time formats to HH:MM. Returns None for invalid times."""
        time_str = time_str.lower().strip()
        
        # Handle "4pm", "2:30pm", etc.
        m = re.match(r"(\d{1,2}):?(\d{2})?\s*(am|pm)", time_str)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
            period = m.group(3)
            
            if hour > 12 or minute >= 60:
                return None
            if period == "pm" and hour != 12:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0
            
            return f"{hour:02d}:{minute:02d}"
        
        # Handle "14:00", "2:30", etc.
        m = re.match(r"(\d{1,2}):(\d{2})", time_str)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            if hour >= 24 or minute >= 60:
                return None
            return f"{hour:02d}:{minute:02d}"
        
        # Handle "noon", "midnight"
        if time_str in ("noon", "midday"):
            return "12:00"
        if time_str == "midnight":
            return "00:00"
        
        return None

    def _get_closure_message(self, fields: dict, intent: str, phone: Optional[str]) -> str:
        """
        Final confirmation message with clear value for both user and owner.
        WhatsApp: Phone already known, so we reference it for clarity.
        """
        phone_display = phone[-4:] if phone and len(phone) >= 4 else "your number"

        if intent == "callback":
            return (
                f"✅ Callback confirmed!\n"
                f"📞 We'll call you at {fields.get('time', 'soon')} "
                f"(ending {phone_display})\n\n"
                f"Need to reschedule? Reply 'change time'."
            )

        # Booking closure
        persons = fields.get("persons", "2")
        return (
            f"✅ Booking confirmed!\n"
            f"📅 {fields.get('date', 'TBD')} at {fields.get('time', 'TBD')}\n"
            f"👥 {persons} guests\n\n"
            f"Questions? Reply here anytime."
        )

    def _extract_field_from_reply(
        self,
        text_low: str,
        original: str,
        current_fields: dict,
        intent: str = "",
    ) -> dict:
        """
        Attempt to extract whichever required field is currently missing
        from a free-text reply.
        """
        missing = self._missing_required(current_fields, intent)
        if not missing:
            return {}

        next_field = missing[0]
        extracted: dict = {}

        if next_field == "date":
            extracted.update(self._extract_date(original))
        elif next_field == "time":
            extracted.update(self._extract_time(original))
        elif next_field == "persons":
            extracted.update(self._extract_persons(text_low))

        # Also opportunistically pick up optional field if not yet set
        if not current_fields.get("type"):
            type_val = self._extract_type(text_low)
            if type_val and text_low != "skip":
                extracted["type"] = type_val

        return extracted

    # ── Field extractors (mirrors intent_middleware but standalone) ────────────

    def _extract_date(self, text: str) -> dict:
        patterns = [
            r"\b(tomorrow|today|tonight)\b",
            r"\b(next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
            r"\b(\d{1,2}(?:st|nd|rd|th)?\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?))\b",
            r"\b(\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?)\b",
            r"\b(april|may|june|july|august|september|october|november|december|january|february|march)\s+\d{1,2}\b",
        ]
        text_l = text.lower()
        for p in patterns:
            m = re.search(p, text_l, re.IGNORECASE)
            if m:
                return {"date": m.group(1)}
        return {}

    def _extract_time(self, text: str) -> dict:
        patterns = [
            r"\b(\d{1,2}:\d{2}\s*(?:am|pm)?)\b",
            r"\b(\d{1,2}\s*(?:am|pm))\b",
            r"\b(noon|midnight|midday)\b",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return {"time": m.group(1)}
        return {}

    def _extract_persons(self, text: str) -> dict:
        m = re.search(r"\b(\d+)\s*(?:people|persons?|guests?|pax|adults?)?\b", text)
        if m:
            return {"persons": int(m.group(1))}
        words = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10}
        for w, n in words.items():
            if re.search(rf"\b{w}\b", text):
                return {"persons": n}
        return {}

    def _extract_type(self, text: str) -> Optional[str]:
        types = ["window", "private", "outdoor", "indoor", "standard", "vip", "terrace", "booth"]
        for t in types:
            if t in text:
                return t
        return None
