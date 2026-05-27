"""
Tests: WhatsApp booking duplicate prevention via _handle_existing_bookings.
"""
from datetime import datetime, timedelta
import pytest

from app.models import Tenant
from app.models.whatsapp import WhatsAppContact, WhatsAppTentativeBooking
from app.services.intent_middleware import BOOKING_INTENT, BOOKING_LOOKUP_INTENT
from app.services.whatsapp_service import WhatsAppService


@pytest.mark.asyncio
async def test_handle_existing_booking_found(db):
    tenant = Tenant(name="Dup Test", slug="dup-test", domain="dup-test.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+1111111111", contact_name="Bob")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
    booking = WhatsAppTentativeBooking(
        tenant_id=tenant.id,
        contact_id=contact.id,
        intent_type="booking",
        status="tentative",
        requested_date=tomorrow,
        requested_time="3pm",
        requested_persons=2,
        requested_type="AC Repair",
        raw_text="I need AC repair tomorrow at 3pm",
    )
    db.add(booking)
    db.commit()

    service = WhatsAppService(db=db, llm_provider="mock")
    reply = service._handle_existing_bookings(
        {"intent": BOOKING_INTENT}, contact.id, tenant.id
    )

    assert reply is not None
    assert "upcoming bookings" in reply.lower() or "Here are" in reply
    assert tomorrow in reply
    assert "AC Repair" in reply


@pytest.mark.asyncio
async def test_handle_existing_bookings_no_existing_booking(db):
    tenant = Tenant(name="Dup Test 2", slug="dup-test-2", domain="dup-test2.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+2222222222", contact_name="Alice")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    service = WhatsAppService(db=db, llm_provider="mock")

    reply_intent = service._handle_existing_bookings(
        {"intent": BOOKING_INTENT}, contact.id, tenant.id
    )
    assert reply_intent is None

    reply_lookup = service._handle_existing_bookings(
        {"intent": BOOKING_LOOKUP_INTENT}, contact.id, tenant.id
    )
    assert reply_lookup is not None
    assert "no upcoming bookings" in reply_lookup.lower()


@pytest.mark.asyncio
async def test_create_tentative_booking_reuses_existing(db):
    """_create_tentative_booking_if_needed must reuse existing booking for same session."""
    from app.models.whatsapp import WhatsAppSession

    tenant = Tenant(name="Dedup Test", slug="dedup-test", domain="dedup-test.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+4444444444", contact_name="Dedup")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    session = WhatsAppSession(tenant_id=tenant.id, contact_id=contact.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    service = WhatsAppService(db=db, llm_provider="mock")

    # First call: should create a new booking
    b1 = service._create_tentative_booking_if_needed(
        tenant_id=tenant.id,
        contact_id=contact.id,
        wa_session_id=session.id,
        wa_message_id="msg1",
        message_text="I want to book",
        intent_result={"intent": "booking", "fields": {"date": "tomorrow"}},
    )
    assert b1 is not None
    db.commit()

    # Second call: should return the SAME booking (not create a new one)
    b2 = service._create_tentative_booking_if_needed(
        tenant_id=tenant.id,
        contact_id=contact.id,
        wa_session_id=session.id,
        wa_message_id="msg2",
        message_text="tomorrow at 2pm",
        intent_result={"intent": "booking", "fields": {"time": "2pm"}},
    )
    assert b2 is not None
    assert b2.id == b1.id, "Must reuse existing booking, not create duplicate"

    # Verify only one booking exists for this session
    count = db.query(WhatsAppTentativeBooking).filter(
        WhatsAppTentativeBooking.whatsapp_session_id == session.id,
        WhatsAppTentativeBooking.status.in_(["tentative", "confirmed"]),
    ).count()
    assert count == 1, f"Expected 1 booking, found {count}"


@pytest.mark.asyncio
async def test_handle_existing_bookings_expired_ignored(db):
    tenant = Tenant(name="Dup Test 3", slug="dup-test-3", domain="dup-test3.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+3333333333", contact_name="Charlie")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    booking = WhatsAppTentativeBooking(
        tenant_id=tenant.id,
        contact_id=contact.id,
        intent_type="booking",
        status="tentative",
        requested_date="2020-01-01",
        requested_time="3pm",
        requested_persons=2,
        requested_type="Old Request",
        raw_text="old booking",
    )
    db.add(booking)
    db.commit()

    service = WhatsAppService(db=db, llm_provider="mock")

    reply_intent = service._handle_existing_bookings(
        {"intent": BOOKING_INTENT}, contact.id, tenant.id
    )
    assert reply_intent is None

    reply_lookup = service._handle_existing_bookings(
        {"intent": BOOKING_LOOKUP_INTENT}, contact.id, tenant.id
    )
    assert reply_lookup is not None
    assert "no upcoming bookings" in reply_lookup.lower()
