"""
CRM Phase 1 tests: Contact enrichment, activity timeline, AI auto-enrichment
"""
import json
from datetime import datetime

from app.models import Tenant
from app.models.whatsapp import WhatsAppContact, ContactActivity, WhatsAppMessage


def test_crm_contact_has_new_fields(db):
    """Step 1a: Verify enrichment fields exist on WhatsAppContact"""
    contact = WhatsAppContact(
        tenant_id="test-tenant",
        phone_number="+1234567890",
        contact_name="John Doe",
        company="Acme Corp",
        email="john@acme.com",
        job_title="Engineer",
        notes="Met at trade show",
        tags=["vip", "repeat"],
        source_channel="whatsapp",
        last_lead_status="confirmed",
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)

    assert contact.company == "Acme Corp"
    assert contact.email == "john@acme.com"
    assert contact.job_title == "Engineer"
    assert contact.notes == "Met at trade show"
    assert contact.tags == ["vip", "repeat"]
    assert contact.source_channel == "whatsapp"
    assert contact.last_lead_status == "confirmed"


def test_contact_activity_timeline(db):
    """Step 1b: ContactActivity model stores and retrieves timeline events"""
    tenant = Tenant(name="Timeline Tenant", slug="timeline-tenant", domain="timeline.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(
        tenant_id=tenant.id,
        phone_number="+1234567891",
        contact_name="Jane Doe",
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)

    activities = [
        ContactActivity(
            tenant_id=tenant.id,
            contact_id=contact.id,
            activity_type="message_in",
            description="Hello, I need help",
        ),
        ContactActivity(
            tenant_id=tenant.id,
            contact_id=contact.id,
            activity_type="lead_created",
            description="Booking intent detected",
        ),
        ContactActivity(
            tenant_id=tenant.id,
            contact_id=contact.id,
            activity_type="note_added",
            description="Customer prefers morning calls",
        ),
    ]
    for a in activities:
        db.add(a)
    db.commit()

    stored = db.query(ContactActivity).filter(
        ContactActivity.contact_id == contact.id
    ).order_by(ContactActivity.created_at.asc()).all()

    assert len(stored) == 3
    assert stored[0].activity_type == "message_in"
    assert stored[1].activity_type == "lead_created"
    assert stored[2].activity_type == "note_added"


def test_contact_notes_append(db):
    """Step 1d: Notes append with timestamp on contact"""
    tenant = Tenant(name="Notes Tenant", slug="notes-tenant", domain="notes.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(
        tenant_id=tenant.id,
        phone_number="+1234567892",
        contact_name="Notes Test",
        notes="Initial note",
    )
    db.add(contact)
    db.commit()

    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    contact.notes = f"{contact.notes}\n---\n[{ts}] Follow-up: called customer"
    db.commit()
    db.refresh(contact)

    assert "Initial note" in contact.notes
    assert "Follow-up: called customer" in contact.notes
    assert "UTC]" in contact.notes


def test_crm_api_list_contacts(test_client, db):
    """Step 1d: GET /api/tenant/crm/contacts returns paginated contacts"""
    from app.api.admin import create_tenant_user_token
    from app.models import TenantUser

    tenant = Tenant(name="CRM List", slug="crm-list", domain="crm-list.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    user = TenantUser(
        tenant_id=tenant.id,
        username="crm-admin",
        email="crm@example.com",
        hashed_password="not-used",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_tenant_user_token(user, tenant)

    for i in range(3):
        db.add(WhatsAppContact(
            tenant_id=tenant.id,
            phone_number=f"+12345678{i:02d}",
            contact_name=f"Contact {i}",
        ))
    db.commit()

    response = test_client.get(
        "/api/tenant/crm/contacts?limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["contacts"]) == 3


def test_crm_api_contact_timeline(test_client, db):
    """Step 1d: GET /api/tenant/crm/contacts/{id}/timeline returns activities"""
    from app.api.admin import create_tenant_user_token
    from app.models import TenantUser

    tenant = Tenant(name="CRM Timeline API", slug="crm-timeline-api", domain="crm-timeline-api.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    user = TenantUser(
        tenant_id=tenant.id,
        username="crm-tl-admin",
        email="crm-tl@example.com",
        hashed_password="not-used",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_tenant_user_token(user, tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+1234567899")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    db.add(ContactActivity(
        tenant_id=tenant.id,
        contact_id=contact.id,
        activity_type="message_in",
        description="test activity",
    ))
    db.commit()

    response = test_client.get(
        f"/api/tenant/crm/contacts/{contact.id}/timeline",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    activities = response.json()
    assert len(activities) >= 1
    assert activities[0]["activity_type"] == "message_in"


def test_crm_api_stats(test_client, db):
    """Step 1d: GET /api/tenant/crm/stats returns CRM KPIs"""
    from app.api.admin import create_tenant_user_token
    from app.models import TenantUser
    from app.models.whatsapp import WhatsAppTentativeBooking

    tenant = Tenant(name="CRM Stats", slug="crm-stats", domain="crm-stats.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    user = TenantUser(
        tenant_id=tenant.id,
        username="crm-stats-admin",
        email="crm-stats@example.com",
        hashed_password="not-used",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_tenant_user_token(user, tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+1111111111")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    db.add(WhatsAppTentativeBooking(
        tenant_id=tenant.id,
        contact_id=contact.id,
        intent_type="booking",
        status="confirmed",
        raw_text="book test",
        extracted_fields={},
    ))
    db.add(WhatsAppTentativeBooking(
        tenant_id=tenant.id,
        contact_id=contact.id,
        intent_type="booking",
        status="tentative",
        raw_text="book test 2",
        extracted_fields={},
    ))
    db.commit()

    response = test_client.get(
        "/api/tenant/crm/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    stats = response.json()
    assert stats["total_leads"] == 2
    assert stats["confirmed_leads"] == 1
    assert stats["tentative_leads"] == 1
    assert stats["conversion_rate"] == 50.0
