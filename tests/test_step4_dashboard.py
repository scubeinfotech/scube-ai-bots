import pytest

from app.api.admin import create_tenant_user_token
from app.models import ChatMessage, ChatSession, Tenant, TenantUser
from app.models.whatsapp import (
    WhatsAppContact,
    WhatsAppMessage,
    WhatsAppSession,
    WhatsAppTentativeBooking,
)


def _create_tenant_token(db, tenant: Tenant) -> str:
    user = TenantUser(
        tenant_id=tenant.id,
        username="tenant-admin",
        email="tenant-admin@example.com",
        hashed_password="not-used-in-test",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return create_tenant_user_token(user, tenant)


def test_step4_unified_conversations_include_web_and_whatsapp(test_client, db):
    tenant = Tenant(name="Step4 Tenant", slug="step4-tenant", domain="step4.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    standalone_web = ChatSession(tenant_id=tenant.id, user_id="web-user")
    linked_llm = ChatSession(tenant_id=tenant.id, user_id="wa-user")
    db.add_all([standalone_web, linked_llm])
    db.commit()
    db.refresh(standalone_web)
    db.refresh(linked_llm)

    db.add_all([
        ChatMessage(session_id=standalone_web.id, tenant_id=tenant.id, role="user", content="Need pricing info"),
        ChatMessage(session_id=standalone_web.id, tenant_id=tenant.id, role="assistant", content="Here is pricing info"),
        ChatMessage(session_id=linked_llm.id, tenant_id=tenant.id, role="user", content="WhatsApp linked session"),
    ])

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+15550000001")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    wa_session = WhatsAppSession(
        tenant_id=tenant.id,
        contact_id=contact.id,
        status="active",
        current_intent="booking",
        llm_session_id=linked_llm.id,
    )
    db.add(wa_session)
    db.commit()
    db.refresh(wa_session)

    db.add_all([
        WhatsAppMessage(
            tenant_id=tenant.id,
            contact_id=contact.id,
            direction="inbound",
            message_type="text",
            content="Book a table tomorrow",
            delivery_status="received",
        ),
        WhatsAppMessage(
            tenant_id=tenant.id,
            contact_id=contact.id,
            chat_session_id=linked_llm.id,
            direction="outbound",
            message_type="text",
            content="Sure, what time would you like?",
            delivery_status="sent",
        ),
    ])
    db.commit()

    response = test_client.get(f"/api/admin/conversations-unified/{tenant.id}?limit=10&offset=0")
    assert response.status_code == 200
    payload = response.json()

    assert payload["total"] == 2
    thread_types = {item["thread_type"] for item in payload["conversations"]}
    assert thread_types == {"web", "whatsapp"}


def test_step4_tenant_can_edit_and_confirm_booking(test_client, db):
    tenant = Tenant(name="Booking Tenant", slug="booking-tenant", domain="booking.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    token = _create_tenant_token(db, tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+15550000002")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    booking = WhatsAppTentativeBooking(
        tenant_id=tenant.id,
        contact_id=contact.id,
        intent_type="booking",
        status="tentative",
        requested_date="tomorrow",
        requested_time="8 pm",
        requested_persons=2,
        requested_type="table",
        raw_text="Book a table tomorrow at 8 pm for 2",
        extracted_fields={"date": "tomorrow", "time": "8 pm", "persons": 2, "type": "table"},
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    response = test_client.patch(
        f"/api/admin/tenant-portal/whatsapp-leads/{booking.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "requested_date": "Friday",
            "requested_time": "7 pm",
            "requested_persons": 4,
            "requested_type": "private room",
            "status": "confirmed",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "confirmed"
    assert payload["requested_date"] == "Friday"
    assert payload["requested_persons"] == 4
    assert payload["human_reviewed"] is True
    assert payload["calendar_sync"] == "queued"


def test_step4_analytics_summary_reports_queue_and_conversion(test_client, db):
    tenant = Tenant(name="Metrics Tenant", slug="metrics-tenant", domain="metrics.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    web_session = ChatSession(tenant_id=tenant.id, user_id="site-user")
    db.add(web_session)
    db.commit()
    db.refresh(web_session)

    db.add_all([
        ChatMessage(session_id=web_session.id, tenant_id=tenant.id, role="user", content="Need a quote"),
        ChatMessage(session_id=web_session.id, tenant_id=tenant.id, role="assistant", content="We can help with that"),
    ])

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+15550000003")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    wa_session = WhatsAppSession(tenant_id=tenant.id, contact_id=contact.id, status="active")
    db.add(wa_session)
    db.commit()
    db.refresh(wa_session)

    db.add_all([
        WhatsAppMessage(
            tenant_id=tenant.id,
            contact_id=contact.id,
            direction="inbound",
            message_type="text",
            content="Book me for tomorrow",
            delivery_status="received",
        ),
        WhatsAppMessage(
            tenant_id=tenant.id,
            contact_id=contact.id,
            direction="outbound",
            message_type="text",
            content="Please confirm the time",
            delivery_status="sent",
        ),
        WhatsAppTentativeBooking(
            tenant_id=tenant.id,
            contact_id=contact.id,
            whatsapp_session_id=wa_session.id,
            intent_type="booking",
            status="confirmed",
            requested_date="tomorrow",
            requested_time="7 pm",
            requested_persons=3,
            requested_type="table",
            raw_text="Book me for tomorrow",
            google_calendar_event_id="evt_123",
            extracted_fields={"crm_sync": {"status": "synced"}},
        ),
    ])
    db.commit()

    response = test_client.get(f"/api/analytics/tenant/{tenant.id}/step4?days=30")
    assert response.status_code == 200
    payload = response.json()

    assert payload["conversations"]["unified_threads"] == 2.0
    assert payload["queue"]["confirmed_bookings"] == 1.0
    assert payload["queue"]["pending_queue"] == 0.0
    assert payload["automation"]["calendar_sync_rate_percent"] == 100.0
    assert payload["automation"]["crm_sync_rate_percent"] == 100.0
    assert payload["conversions"]["conversion_rate_percent"] == 100.0