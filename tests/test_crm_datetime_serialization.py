"""
Tests: CRM Pydantic response models serialize naive UTC datetimes with +00:00 suffix.
"""
from datetime import datetime

from app.api.crm import ContactResponse, LeadBookingResponse


def test_contact_response_adds_utc_marker():
    naive_dt = datetime(2025, 6, 1, 12, 0, 0)
    resp = ContactResponse(
        id="c1",
        tenant_id="t1",
        phone_number="+1111111111",
        created_at=naive_dt,
        updated_at=naive_dt,
        first_message_at=naive_dt,
        last_message_at=naive_dt,
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["created_at"].endswith("+00:00")
    assert dumped["updated_at"].endswith("+00:00")
    assert dumped["first_message_at"].endswith("+00:00")
    assert dumped["last_message_at"].endswith("+00:00")


def test_lead_booking_response_adds_utc_marker():
    naive_dt = datetime(2025, 6, 1, 12, 0, 0)
    resp = LeadBookingResponse(
        id="b1",
        contact_id="c1",
        intent_type="booking",
        status="tentative",
        created_at=naive_dt,
        updated_at=naive_dt,
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["created_at"].endswith("+00:00")
    assert dumped["updated_at"].endswith("+00:00")


def test_contact_response_naive_none_handled():
    resp = ContactResponse(
        id="c2",
        tenant_id="t1",
        phone_number="+2222222222",
        created_at=None,
        updated_at=None,
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["created_at"] is None
    assert dumped["updated_at"] is None


def test_lead_booking_response_already_tz_aware():
    aware_dt = datetime(2025, 6, 1, 12, 0, 0).isoformat() + "+00:00"
    naive_dt = datetime(2025, 6, 1, 12, 0, 0)
    resp = LeadBookingResponse(
        id="b2",
        contact_id="c2",
        intent_type="booking",
        status="confirmed",
        created_at=naive_dt,
        updated_at=naive_dt,
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["created_at"] == aware_dt
