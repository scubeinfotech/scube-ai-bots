"""
Step 2 tests: WhatsApp intent classification, field extraction, and tentative booking persistence.
"""
import pytest

from app.models import Tenant
from app.models.whatsapp import WhatsAppSession, WhatsAppTentativeBooking
from app.services.intent_middleware import (
    IntentDetectionMiddleware,
    BOOKING_INTENT,
    BOOKING_LOOKUP_INTENT,
    CALLBACK_INTENT,
    DEMO_SCHEDULING_INTENT,
    FAQ_INTENT,
)
from app.services.whatsapp_service import WhatsAppService


@pytest.fixture
def intent_middleware() -> IntentDetectionMiddleware:
    return IntentDetectionMiddleware()


def test_intent_booking_extracts_structured_fields(intent_middleware: IntentDetectionMiddleware):
    result = intent_middleware.analyze(
        "I want to book a table for 4 people tomorrow at 7:30 pm"
    )

    assert result["intent"] == BOOKING_INTENT
    assert result["fields"]["persons"] == 4
    assert result["fields"]["date"].lower() == "tomorrow"
    assert result["fields"]["time"].lower() == "7:30 pm"
    assert result["fields"]["type"] == "table"


def test_intent_callback_extracts_callback_type(intent_middleware: IntentDetectionMiddleware):
    result = intent_middleware.analyze("Please call me back tomorrow morning")

    assert result["intent"] == CALLBACK_INTENT
    assert result["fields"]["date"].lower() == "tomorrow"
    assert result["fields"]["time"].lower() == "morning"
    assert result["fields"]["type"] == "callback"


def test_intent_demo_scheduling_detected(intent_middleware: IntentDetectionMiddleware):
    result = intent_middleware.analyze("Can you schedule a product demo on 22/04 at 10:00 am?")

    assert result["intent"] == DEMO_SCHEDULING_INTENT
    assert result["fields"]["date"] == "22/04"
    assert result["fields"]["time"].lower() == "10:00 am"
    assert result["fields"]["type"] == "demo"


def test_intent_faq_detected(intent_middleware: IntentDetectionMiddleware):
    result = intent_middleware.analyze("What are your operating hours?")

    assert result["intent"] == FAQ_INTENT


@pytest.mark.asyncio
async def test_whatsapp_service_persists_tentative_booking_and_session_intent(db):
    tenant = Tenant(
        name="Intent Test Tenant",
        slug="intent-test-tenant",
        domain="intent-test.example"
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    service = WhatsAppService(db=db, llm_provider="mock")

    payload = {
        "from": "+14155550123",
        "id": "msg_intent_001",
        "timestamp": "1713182400",
        "type": "text",
        "text": {"body": "Please book a service appointment for 2 persons tomorrow at 11 am"},
    }

    result = await service._process_single_message(tenant.id, payload)

    assert result["success"] is True
    assert result["intent"] == BOOKING_INTENT
    assert result["tentative_booking_id"] is not None

    booking = db.query(WhatsAppTentativeBooking).filter(
        WhatsAppTentativeBooking.id == result["tentative_booking_id"]
    ).first()

    assert booking is not None
    assert booking.intent_type == BOOKING_INTENT
    assert booking.requested_persons == 2
    assert booking.requested_type in {"service", "booking", "appointment"}

    session = db.query(WhatsAppSession).filter(
        WhatsAppSession.id == booking.whatsapp_session_id
    ).first()
    assert session is not None
    assert session.current_intent == BOOKING_INTENT
    assert session.booking_data is not None
    assert session.booking_data.get("persons") == 2


def test_intent_booking_lookup_detected(intent_middleware: IntentDetectionMiddleware):
    for msg in [
        "Can you share the bookings?",
        "Show my bookings",
        "Do I have an existing booking",
        "What are my upcoming bookings",
        "List my reservations",
    ]:
        result = intent_middleware.analyze(msg)
        assert result["intent"] == BOOKING_LOOKUP_INTENT, f"Failed for: {msg}"


def test_intent_booking_lookup_priority(intent_middleware: IntentDetectionMiddleware):
    result = intent_middleware.analyze("Can you share the bookings for me?")
    assert result["intent"] == BOOKING_LOOKUP_INTENT
    assert result["intent"] != BOOKING_INTENT


def test_intent_normal_booking_still_works(intent_middleware: IntentDetectionMiddleware):
    result = intent_middleware.analyze("I want to book a table")
    assert result["intent"] == BOOKING_INTENT
