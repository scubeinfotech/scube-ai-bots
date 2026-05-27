"""
CRM Phase 2 tests: Follow-up templates, scheduling, rendering, dispatch
"""
from datetime import datetime, timedelta

from app.models import Tenant
from app.models.whatsapp import (
    WhatsAppContact, WhatsAppTentativeBooking,
    FollowUpTemplate, ScheduledMessage, ContactActivity,
)
from app.services.followup_scheduler import (
    _render_template, _find_template,
    schedule_follow_up, dispatch_pending_messages,
)


def test_followup_template_creation(db):
    """Step 2a: FollowUpTemplate stores correctly with industry and trigger"""
    tpl = FollowUpTemplate(
        trigger_event="lead_created",
        template_text="Hi {{name}}, regarding your {{service}}.",
        industry="services",
        delay_hours=24,
        is_active=True,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)

    assert tpl.trigger_event == "lead_created"
    assert tpl.industry == "services"
    assert tpl.delay_hours == 24
    assert tpl.is_active is True


def test_scheduled_message_creation(db):
    """Step 2b: ScheduledMessage stores and queries correctly"""
    msg = ScheduledMessage(
        tenant_id="t1",
        contact_id="c1",
        trigger_event="lead_created",
        scheduled_at=datetime.utcnow() + timedelta(hours=24),
        status="pending",
        message_text="Hi John, your booking is noted.",
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    assert msg.status == "pending"
    assert msg.trigger_event == "lead_created"
    assert msg.sent_at is None


def test_template_rendering():
    """Step 2d: Template placeholders are replaced correctly"""
    rendered = _render_template(
        "Hi {{name}}, your {{service}} on {{date}} at {{time}}.",
    )
    assert "{{name}}" not in rendered
    assert "Valued Customer" in rendered
    assert rendered.count("{{") == 0


def test_find_template_priority(db):
    """Step 2d: Template resolution follows priority: tenant → industry → global"""
    tenant = Tenant(name="Find Tpl", slug="find-tpl", domain="find.example", industry="services")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    # Global generic
    db.add(FollowUpTemplate(
        id="global_generic", trigger_event="lead_created",
        template_text="Global generic", is_active=True,
    ))
    # Global + industry match
    db.add(FollowUpTemplate(
        id="global_services", industry="services", trigger_event="lead_created",
        template_text="Global services", is_active=True,
    ))
    db.commit()

    # Should find industry-specific over global
    result = _find_template(db, tenant.id, "services", "lead_created")
    assert result is not None, f"Expected global_services, got None. Industry={tenant.industry}"
    assert result.id == "global_services"

    # Tenant-specific should win
    db.add(FollowUpTemplate(
        id="tenant_specific", tenant_id=tenant.id, trigger_event="lead_created",
        template_text="Tenant specific", is_active=True,
    ))
    db.commit()
    result = _find_template(db, tenant.id, "services", "lead_created")
    assert result.id == "tenant_specific"


def test_schedule_follow_up_creates_record(db):
    """Step 2d/e: schedule_follow_up creates ScheduledMessage + ContactActivity"""
    tenant = Tenant(name="Schedule Tenant", slug="schedule-t", domain="schedule.example", industry="services")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+1234567890", contact_name="Test User")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    # Seed a global template
    db.add(FollowUpTemplate(
        id="fu_sched_test", trigger_event="lead_created",
        template_text="Hi {{name}}, your {{service}} is noted.",
        delay_hours=24, is_active=True,
    ))
    db.commit()

    msg = schedule_follow_up(db, tenant.id, contact.id, "lead_created")
    assert msg is not None
    assert msg.status == "pending"
    assert msg.trigger_event == "lead_created"
    assert "Test User" in msg.message_text
    assert msg.scheduled_at > datetime.utcnow()

    # ContactActivity logged
    activities = db.query(ContactActivity).filter(
        ContactActivity.contact_id == contact.id,
        ContactActivity.activity_type == "followup_scheduled",
    ).all()
    assert len(activities) >= 1


def test_dispatch_pending_messages(db):
    """Step 2f: dispatch_pending_messages processes only due messages"""
    tenant = Tenant(name="Dispatch Tenant", slug="dispatch-t", domain="dispatch.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+9999999999")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    # Past-due pending message
    db.add(ScheduledMessage(
        tenant_id=tenant.id, contact_id=contact.id,
        trigger_event="lead_created",
        scheduled_at=datetime.utcnow() - timedelta(hours=1),
        status="pending",
        message_text="Test message",
    ))
    # Future message (should NOT be dispatched)
    db.add(ScheduledMessage(
        tenant_id=tenant.id, contact_id=contact.id,
        trigger_event="lead_created",
        scheduled_at=datetime.utcnow() + timedelta(days=7),
        status="pending",
        message_text="Future message",
    ))
    # Already sent (should NOT be dispatched)
    db.add(ScheduledMessage(
        tenant_id=tenant.id, contact_id=contact.id,
        trigger_event="lead_created",
        scheduled_at=datetime.utcnow() - timedelta(hours=2),
        status="sent",
        message_text="Already sent",
        sent_at=datetime.utcnow(),
    ))
    db.commit()

    # Dispatch should find 1 pending due message
    sent = dispatch_pending_messages(db, batch_size=10)
    assert sent == 0  # No WhatsApp provider configured, so it will cancel, not send

    # Check the pending due message was handled
    due_msg = db.query(ScheduledMessage).filter(
        ScheduledMessage.message_text == "Test message"
    ).first()
    assert due_msg is not None
    # Without a valid WhatsApp config, it gets cancelled
    assert due_msg.status == "cancelled"
