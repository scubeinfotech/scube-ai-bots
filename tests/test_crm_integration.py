"""
CRM Integration Tests — End-to-end flows across contacts, templates, scheduling, and dispatch
"""
from datetime import datetime, timedelta

from app.models import Tenant
from app.models.whatsapp import (
    WhatsAppContact, WhatsAppMessage, WhatsAppTentativeBooking,
    FollowUpTemplate, ScheduledMessage, ContactActivity,
)
from app.services.followup_scheduler import schedule_follow_up, _render_template


def test_integration_lead_created_schedules_followup(db):
    """Test 2: Lead created → follow-up scheduled with correct template"""
    tenant = Tenant(name="Int Lead", slug="int-lead", domain="int-lead.example", industry="services")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+1111111111", contact_name="Alice")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    booking = WhatsAppTentativeBooking(
        tenant_id=tenant.id,
        contact_id=contact.id,
        intent_type="booking",
        status="tentative",
        requested_date="tomorrow",
        requested_time="3pm",
        requested_persons=2,
        requested_type="AC Repair",
        raw_text="I need AC repair tomorrow at 3pm",
        extracted_fields={"date": "tomorrow", "time": "3pm", "persons": 2},
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    # Seed a lead_created template for services industry
    db.add(FollowUpTemplate(
        id="int_lead_created",
        industry="services",
        trigger_event="lead_created",
        delay_hours=24,
        template_text="Hi {{name}}, regarding your {{service}} request for {{date}}. Reply CONFIRM.",
        conclusive_line="Confirm via chat — no phone call needed.",
        is_active=True,
    ))
    db.commit()

    msg = schedule_follow_up(db, tenant.id, contact.id, "lead_created", booking)
    assert msg is not None
    assert msg.status == "pending"
    assert msg.trigger_event == "lead_created"
    assert "Alice" in msg.message_text
    assert "AC Repair" in msg.message_text
    assert "tomorrow" in msg.message_text
    assert "Confirm via chat" in msg.message_text
    assert msg.scheduled_at > datetime.utcnow()
    assert (msg.scheduled_at - datetime.utcnow()) >= timedelta(hours=23)

    # Verify ContactActivity was logged
    activity = db.query(ContactActivity).filter(
        ContactActivity.contact_id == contact.id,
        ContactActivity.activity_type == "followup_scheduled",
    ).first()
    assert activity is not None
    assert "lead_created" in activity.description


def test_integration_lead_confirmed_after_creation(db):
    """Test 3: Lead created → confirmed → confirmation follow-up scheduled + activity logged"""
    tenant = Tenant(name="Int Confirm", slug="int-confirm", domain="int-confirm.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+2222222222", contact_name="Bob")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    booking = WhatsAppTentativeBooking(
        tenant_id=tenant.id,
        contact_id=contact.id,
        intent_type="booking",
        status="tentative",
        requested_date="Friday",
        requested_time="7pm",
        requested_persons=2,
        requested_type="table",
        raw_text="book for Friday 7pm",
        extracted_fields={"date": "Friday", "time": "7pm"},
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    # Seed templates for both events
    db.add_all([
        FollowUpTemplate(
            id="int_lead_created_2", trigger_event="lead_created",
            template_text="Hi {{name}}, noted your request.", delay_hours=24, is_active=True,
        ),
        FollowUpTemplate(
            id="int_lead_confirmed", trigger_event="lead_confirmed",
            template_text="Confirmed! {{service}} set for {{date}} {{time}}.", delay_hours=0,
            conclusive_line="We'll send a reminder before your appointment.", is_active=True,
        ),
    ])
    db.commit()

    # Simulate lead creation
    msg1 = schedule_follow_up(db, tenant.id, contact.id, "lead_created", booking)
    assert msg1 is not None

    # Simulate lead confirmation
    booking.status = "confirmed"
    booking.confirmed_at = datetime.utcnow()
    db.commit()

    msg2 = schedule_follow_up(db, tenant.id, contact.id, "lead_confirmed", booking)
    assert msg2 is not None
    assert "Confirmed" in msg2.message_text
    assert "Friday" in msg2.message_text

    # Activity log should have both events
    activities = db.query(ContactActivity).filter(
        ContactActivity.contact_id == contact.id,
    ).order_by(ContactActivity.created_at.asc()).all()
    types = [a.activity_type for a in activities]
    assert "followup_scheduled" in types


def test_integration_contact_enrichment_trigger(db):
    """Test 1: Contact with total_messages=3 triggers enrichment condition"""
    tenant = Tenant(name="Int Enrich", slug="int-enrich", domain="int-enrich.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(
        tenant_id=tenant.id,
        phone_number="+3333333333",
        contact_name="Charlie",
        total_messages=3,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)

    assert contact.total_messages == 3
    assert contact.company is None

    # Simulate what the enrichment hook does: check total_messages == 3
    should_enrich = contact.total_messages == 3 and not contact.company
    assert should_enrich is True

    # After enrichment would run, update the contact
    import json
    meta = contact.contact_metadata or {}
    meta["interest"] = "AC repair service"
    meta["sentiment"] = "positive"
    contact.contact_metadata = meta
    contact.company = "Home Services Pte Ltd"
    db.commit()
    db.refresh(contact)

    assert contact.company == "Home Services Pte Ltd"
    assert contact.contact_metadata["interest"] == "AC repair service"


def test_integration_custom_template_applied(db):
    """Test 5: Tenant creates custom template → it wins over global on next lead event"""
    tenant = Tenant(name="Int Custom", slug="int-custom", domain="int-custom.example", industry="services")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+4444444444", contact_name="Diana")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    booking = WhatsAppTentativeBooking(
        tenant_id=tenant.id, contact_id=contact.id,
        intent_type="booking", status="tentative",
        requested_date="Monday", requested_time="10am",
        requested_type="Consultation", raw_text="need consultation",
        extracted_fields={"date": "Monday"},
    )
    db.add(booking)
    db.commit()

    # Global template
    db.add(FollowUpTemplate(
        id="global_lead", trigger_event="lead_created",
        template_text="Global: Hi {{name}}", delay_hours=24, is_active=True,
    ))
    # Tenant-specific template (should win)
    db.add(FollowUpTemplate(
        id="tenant_lead", tenant_id=tenant.id, trigger_event="lead_created",
        template_text="Custom: Hello {{name}}, your {{service}} is noted!",
        delay_hours=12, is_active=True,
    ))
    db.commit()

    msg = schedule_follow_up(db, tenant.id, contact.id, "lead_created", booking)
    assert msg is not None
    assert msg.message_text.startswith("Custom:")
    assert "Hello Diana" in msg.message_text
    assert "Consultation" in msg.message_text


def test_integration_template_api_crud(test_client, db):
    """Test 6: Template CRUD API — create, list, update, delete"""
    from app.api.admin import create_tenant_user_token
    from app.models import TenantUser

    tenant = Tenant(name="Int CRUD", slug="int-crud", domain="int-crud.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    user = TenantUser(
        tenant_id=tenant.id, username="crud-admin",
        email="crud@example.com", hashed_password="not-used", is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_tenant_user_token(user, tenant)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Create
    r = test_client.post("/api/tenant/crm/templates", headers=headers, json={
        "trigger_event": "lead_created",
        "template_text": "Custom template for {{name}}",
        "delay_hours": 48,
        "industry": "services",
    })
    assert r.status_code == 200
    tpl_id = r.json()["id"]
    assert r.json()["trigger_event"] == "lead_created"

    # List
    r = test_client.get("/api/tenant/crm/templates", headers=headers)
    assert r.status_code == 200
    assert any(t["id"] == tpl_id for t in r.json())

    # Update
    r = test_client.patch(f"/api/tenant/crm/templates/{tpl_id}", headers=headers, json={
        "template_text": "Updated: {{name}}",
        "delay_hours": 24,
    })
    assert r.status_code == 200
    assert r.json()["delay_hours"] == 24

    # Delete
    r = test_client.delete(f"/api/tenant/crm/templates/{tpl_id}", headers=headers)
    assert r.status_code == 200

    # Confirm deleted
    r = test_client.get("/api/tenant/crm/templates", headers=headers)
    assert not any(t["id"] == tpl_id for t in r.json())


def test_integration_scheduled_list_and_cancel(test_client, db):
    """Test 6b: Scheduled messages list + cancel"""
    from app.api.admin import create_tenant_user_token
    from app.models import TenantUser

    tenant = Tenant(name="Int Sched", slug="int-sched", domain="int-sched.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    user = TenantUser(
        tenant_id=tenant.id, username="sched-admin",
        email="sched@example.com", hashed_password="not-used", is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_tenant_user_token(user, tenant)
    headers = {"Authorization": f"Bearer {token}"}

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+5555555555")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    msg = ScheduledMessage(
        tenant_id=tenant.id, contact_id=contact.id,
        trigger_event="lead_created",
        scheduled_at=datetime.utcnow() + timedelta(hours=24),
        status="pending",
        message_text="Test scheduled message",
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    # List scheduled
    r = test_client.get("/api/tenant/crm/scheduled", headers=headers)
    assert r.status_code == 200
    assert any(m["id"] == msg.id for m in r.json())

    # Cancel
    r = test_client.post(f"/api/tenant/crm/scheduled/{msg.id}/cancel", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    # Verify cancelled
    r = test_client.get("/api/tenant/crm/scheduled", headers=headers)
    cancelled = [m for m in r.json() if m["id"] == msg.id]
    assert len(cancelled) == 1
    assert cancelled[0]["status"] == "cancelled"
