from app.api.admin import create_tenant_user_token
from app.models import Tenant, TenantUser
from app.models.whatsapp import WhatsAppContact, WhatsAppTentativeBooking
from datetime import datetime, timedelta


def _create_tenant_token(db, tenant: Tenant) -> str:
    user = TenantUser(
        tenant_id=tenant.id,
        username="handoff-admin",
        email="handoff-admin@example.com",
        hashed_password="not-used-in-test",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return create_tenant_user_token(user, tenant)


def test_step5_tenant_stats_include_pending_handoff_count(test_client, db):
    tenant = Tenant(name="Handoff Tenant", slug="handoff-tenant", domain="handoff.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    token = _create_tenant_token(db, tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+15550000101")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    db.add_all([
        WhatsAppTentativeBooking(
            tenant_id=tenant.id,
            contact_id=contact.id,
            intent_type="booking",
            status="tentative",
            requested_date="Friday",
            requested_time="7 pm",
            requested_persons=2,
            requested_type="table",
            raw_text="book friday 7 pm",
            extracted_fields={"date": "Friday", "time": "7 pm"},
        ),
        WhatsAppTentativeBooking(
            tenant_id=tenant.id,
            contact_id=contact.id,
            intent_type="booking",
            status="confirmed",
            requested_date="Saturday",
            requested_time="8 pm",
            requested_persons=4,
            requested_type="table",
            raw_text="book saturday 8 pm",
            extracted_fields={"date": "Saturday", "time": "8 pm"},
        ),
    ])
    db.commit()

    response = test_client.get(
        "/api/admin/tenant-portal/stats",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stats"]["pending_whatsapp_queue"] == 1
    assert payload["stats"]["handoff_required"] is True


def test_step5_admin_handoff_summary_returns_pending_totals(test_client, db):
    tenant_a = Tenant(name="Tenant A", slug="tenant-a", domain="tenant-a.example")
    tenant_b = Tenant(name="Tenant B", slug="tenant-b", domain="tenant-b.example")
    db.add_all([tenant_a, tenant_b])
    db.commit()
    db.refresh(tenant_a)
    db.refresh(tenant_b)

    contact_a = WhatsAppContact(tenant_id=tenant_a.id, phone_number="+15550000102")
    contact_b = WhatsAppContact(tenant_id=tenant_b.id, phone_number="+15550000103")
    db.add_all([contact_a, contact_b])
    db.commit()
    db.refresh(contact_a)
    db.refresh(contact_b)

    db.add_all([
        WhatsAppTentativeBooking(
            tenant_id=tenant_a.id,
            contact_id=contact_a.id,
            intent_type="booking",
            status="tentative",
            requested_date="Monday",
            requested_time="6 pm",
            requested_persons=2,
            requested_type="table",
            raw_text="book monday",
            extracted_fields={"date": "Monday"},
        ),
        WhatsAppTentativeBooking(
            tenant_id=tenant_a.id,
            contact_id=contact_a.id,
            intent_type="booking",
            status="tentative",
            requested_date="Tuesday",
            requested_time="7 pm",
            requested_persons=3,
            requested_type="table",
            raw_text="book tuesday",
            extracted_fields={"date": "Tuesday"},
        ),
        WhatsAppTentativeBooking(
            tenant_id=tenant_b.id,
            contact_id=contact_b.id,
            intent_type="booking",
            status="tentative",
            requested_date="Wednesday",
            requested_time="8 pm",
            requested_persons=4,
            requested_type="table",
            raw_text="book wednesday",
            extracted_fields={"date": "Wednesday"},
        ),
        WhatsAppTentativeBooking(
            tenant_id=tenant_b.id,
            contact_id=contact_b.id,
            intent_type="booking",
            status="confirmed",
            requested_date="Thursday",
            requested_time="9 pm",
            requested_persons=5,
            requested_type="table",
            raw_text="book thursday",
            extracted_fields={"date": "Thursday"},
        ),
    ])
    db.commit()

    response = test_client.get("/api/admin/whatsapp/handoff-summary?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_pending"] == 3
    assert payload["requires_handoff"] is True

    by_tenant = {item["tenant_id"]: item["pending_count"] for item in payload["tenants"]}
    assert by_tenant[tenant_a.id] == 2
    assert by_tenant[tenant_b.id] == 1


def test_step5_admin_handoff_actions_claim_reassign_note_escalate_close(test_client, db):
    tenant = Tenant(name="Action Tenant", slug="action-tenant", domain="action.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+15550000104")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    booking = WhatsAppTentativeBooking(
        tenant_id=tenant.id,
        contact_id=contact.id,
        intent_type="booking",
        status="tentative",
        requested_date="Friday",
        requested_time="8 pm",
        requested_persons=2,
        requested_type="table",
        raw_text="book friday",
        extracted_fields={"date": "Friday"},
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    claim = test_client.post(
        f"/api/admin/whatsapp/tentative-bookings/{booking.id}/claim",
        json={"assigned_to": "agent-a"},
    )
    assert claim.status_code == 200
    assert claim.json()["assigned_to"] == "agent-a"

    reassign = test_client.post(
        f"/api/admin/whatsapp/tentative-bookings/{booking.id}/reassign",
        json={"assigned_to": "agent-b", "note": "handoff to evening shift"},
    )
    assert reassign.status_code == 200
    assert reassign.json()["assigned_to"] == "agent-b"

    note = test_client.post(
        f"/api/admin/whatsapp/tentative-bookings/{booking.id}/note",
        json={"note": "customer prefers window seat"},
    )
    assert note.status_code == 200
    assert "window seat" in (note.json()["handoff_notes"] or "")

    escalate = test_client.post(
        f"/api/admin/whatsapp/tentative-bookings/{booking.id}/escalate",
        json={"note": "SLA at risk", "priority": "urgent"},
    )
    assert escalate.status_code == 200
    assert escalate.json()["escalation_level"] == 1
    assert escalate.json()["priority"] == "urgent"

    close = test_client.post(
        f"/api/admin/whatsapp/tentative-bookings/{booking.id}/close",
        json={"note": "resolved by call"},
    )
    assert close.status_code == 200
    assert close.json()["status"] == "closed"
    assert close.json()["resolved_at"] is not None


def test_step5_sla_auto_escalates_overdue_tentative_booking(test_client, db):
    tenant = Tenant(name="SLA Tenant", slug="sla-tenant", domain="sla.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+15550000105")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    old_created_at = datetime.utcnow() - timedelta(minutes=45)
    booking = WhatsAppTentativeBooking(
        tenant_id=tenant.id,
        contact_id=contact.id,
        intent_type="callback",
        status="tentative",
        priority="urgent",
        requested_date="today",
        requested_time="10 am",
        raw_text="need callback",
        extracted_fields={},
        created_at=old_created_at,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    summary = test_client.get(f"/api/admin/whatsapp/handoff-summary?tenant_id={tenant.id}&limit=10")
    assert summary.status_code == 200
    payload = summary.json()

    assert payload["total_pending"] == 1
    assert payload["sla_auto_escalated_now"] >= 1
    assert payload["escalated_pending"] >= 1

    db.expire_all()
    refreshed = db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.id == booking.id).first()
    assert refreshed is not None
    assert refreshed.escalation_level >= 1


def test_step5_tenant_stats_include_overdue_and_escalated_counts(test_client, db):
    tenant = Tenant(name="SLA Stats Tenant", slug="sla-stats-tenant", domain="sla-stats.example")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    token = _create_tenant_token(db, tenant)

    contact = WhatsAppContact(tenant_id=tenant.id, phone_number="+15550000106")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    overdue_due_by = datetime.utcnow() - timedelta(minutes=10)
    db.add(
        WhatsAppTentativeBooking(
            tenant_id=tenant.id,
            contact_id=contact.id,
            intent_type="booking",
            status="tentative",
            priority="normal",
            due_by=overdue_due_by,
            requested_date="tomorrow",
            requested_time="8 pm",
            requested_persons=3,
            requested_type="table",
            raw_text="book tomorrow",
            extracted_fields={},
        )
    )
    db.commit()

    response = test_client.get(
        "/api/admin/tenant-portal/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    stats = response.json()["stats"]
    assert stats["pending_whatsapp_queue"] >= 1
    assert stats["overdue_whatsapp_queue"] >= 1
    assert stats["escalated_whatsapp_queue"] >= 1
