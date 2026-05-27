"""
Tests for Phase 2: Calendar Integration
"""
import pytest
from datetime import datetime, timedelta, timezone
from conftest import client, db, TestingSessionLocal
from app.models import Tenant, TenantUser, SubscriptionPlan
from app.models.calendar import CalendarIntegration, TenantAvailability


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def trial_plan(db):
    """Create a trial subscription plan."""
    plan = SubscriptionPlan(
        name="trial", display_name="Free Trial", description="7-day free trial",
        price_monthly=0, trial_days=7, is_active=True,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    yield plan
    db.delete(plan)
    db.commit()


@pytest.fixture
def registered_tenant(trial_plan):
    """Register a tenant via the public API."""
    response = client.post("/api/public/register", json={
        "business_name": "Calendar Test Business",
        "contact_email": "calendar@test.com",
        "website_url": "https://calendartest.com",
        "password": "testpass123",
    })
    assert response.status_code == 200
    return response.json()


# --------------------------------------------------------------------------- #
# Calendar Status Tests
# --------------------------------------------------------------------------- #

class TestCalendarStatus:
    def test_status_not_connected(self, registered_tenant):
        """Calendar status should show not connected by default."""
        tenant_id = registered_tenant["tenant_id"]
        response = client.get(f"/api/calendar/status/{tenant_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["is_connected"] is False
        assert data["provider"] is None

    def test_status_nonexistent_tenant(self):
        """Calendar status for non-existent tenant should return 404."""
        response = client.get("/api/calendar/status/nonexistent")
        assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Availability Tests
# --------------------------------------------------------------------------- #

class TestAvailability:
    def test_get_availability_empty(self, registered_tenant):
        """Get availability when no slots set."""
        tenant_id = registered_tenant["tenant_id"]
        response = client.get(f"/api/calendar/availability/{tenant_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["slots"] == []

    def test_set_availability(self, registered_tenant):
        """Set weekly availability slots."""
        tenant_id = registered_tenant["tenant_id"]
        slots = [
            {"day_of_week": 0, "start_time": "09:00", "end_time": "17:00"},
            {"day_of_week": 1, "start_time": "09:00", "end_time": "17:00"},
            {"day_of_week": 2, "start_time": "09:00", "end_time": "17:00"},
        ]
        response = client.post(
            f"/api/calendar/availability/{tenant_id}",
            json={"slots": slots},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert len(data["slots"]) == 3

    def test_set_availability_replaces_existing(self, registered_tenant):
        """Setting availability should replace all existing slots."""
        tenant_id = registered_tenant["tenant_id"]

        # Set initial slots
        client.post(
            f"/api/calendar/availability/{tenant_id}",
            json={"slots": [
                {"day_of_week": 0, "start_time": "09:00", "end_time": "12:00"},
            ]},
        )

        # Replace with new slots
        response = client.post(
            f"/api/calendar/availability/{tenant_id}",
            json={"slots": [
                {"day_of_week": 1, "start_time": "14:00", "end_time": "18:00"},
                {"day_of_week": 2, "start_time": "10:00", "end_time": "16:00"},
            ]},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["slots"]) == 2

        # Verify old slots are gone
        get_response = client.get(f"/api/calendar/availability/{tenant_id}")
        assert len(get_response.json()["slots"]) == 2

    def test_set_availability_with_blocked_dates(self, registered_tenant):
        """Set availability with blocked dates."""
        tenant_id = registered_tenant["tenant_id"]
        slots = [
            {
                "day_of_week": 0,
                "start_time": "09:00",
                "end_time": "17:00",
                "blocked_dates": ["2026-12-25", "2027-01-01"],
            },
        ]
        response = client.post(
            f"/api/calendar/availability/{tenant_id}",
            json={"slots": slots},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["slots"][0]["day_of_week"] == 0

    def test_get_availability_nonexistent_tenant(self):
        """Get availability for non-existent tenant should return 404."""
        response = client.get("/api/calendar/availability/nonexistent")
        assert response.status_code == 404

    def test_set_availability_nonexistent_tenant(self):
        """Set availability for non-existent tenant should return 404."""
        response = client.post(
            "/api/calendar/availability/nonexistent",
            json={"slots": []},
        )
        assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Check Availability Tests
# --------------------------------------------------------------------------- #

class TestCheckAvailability:
    def test_check_available_date(self, registered_tenant):
        """Check availability for a date that has slots."""
        tenant_id = registered_tenant["tenant_id"]

        # Set Monday availability
        client.post(
            f"/api/calendar/availability/{tenant_id}",
            json={"slots": [
                {"day_of_week": 0, "start_time": "09:00", "end_time": "17:00"},
            ]},
        )

        # 2026-05-18 is a Monday
        response = client.get(
            f"/api/calendar/availability/{tenant_id}/check?date=2026-05-18"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["available_slots"]) == 1
        assert data["available_slots"][0]["start_time"] == "09:00"

    def test_check_unavailable_date(self, registered_tenant):
        """Check availability for a date with no slots."""
        tenant_id = registered_tenant["tenant_id"]

        # Set Monday availability only
        client.post(
            f"/api/calendar/availability/{tenant_id}",
            json={"slots": [
                {"day_of_week": 0, "start_time": "09:00", "end_time": "17:00"},
            ]},
        )

        # 2026-05-19 is a Tuesday (no availability set)
        response = client.get(
            f"/api/calendar/availability/{tenant_id}/check?date=2026-05-19"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["available_slots"]) == 0

    def test_check_blocked_date(self, registered_tenant):
        """Check availability for a blocked date."""
        tenant_id = registered_tenant["tenant_id"]

        # Set Monday availability with blocked date
        client.post(
            f"/api/calendar/availability/{tenant_id}",
            json={"slots": [
                {
                    "day_of_week": 0,
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "blocked_dates": ["2026-05-18"],
                },
            ]},
        )

        # 2026-05-18 is a Monday but blocked
        response = client.get(
            f"/api/calendar/availability/{tenant_id}/check?date=2026-05-18"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["available_slots"]) == 0

    def test_check_invalid_date_format(self, registered_tenant):
        """Check availability with invalid date format."""
        tenant_id = registered_tenant["tenant_id"]
        response = client.get(
            f"/api/calendar/availability/{tenant_id}/check?date=invalid-date"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["available_slots"]) == 0


# --------------------------------------------------------------------------- #
# Booking Tests
# --------------------------------------------------------------------------- #

class TestBooking:
    def test_book_appointment_success(self, registered_tenant):
        """Book an appointment successfully."""
        tenant_id = registered_tenant["tenant_id"]

        # Set Monday availability
        client.post(
            f"/api/calendar/availability/{tenant_id}",
            json={"slots": [
                {"day_of_week": 0, "start_time": "09:00", "end_time": "17:00"},
            ]},
        )

        # Book appointment (2026-05-18 is Monday)
        response = client.post(
            f"/api/calendar/book/{tenant_id}",
            json={
                "date": "2026-05-18",
                "start_time": "10:00",
                "end_time": "11:00",
                "attendee_name": "John Doe",
                "attendee_email": "john@example.com",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["appointment"]["attendee_name"] == "John Doe"
        assert "meeting_link" in data["appointment"]

    def test_book_unavailable_slot(self, registered_tenant):
        """Booking outside available hours should fail."""
        tenant_id = registered_tenant["tenant_id"]

        # Set Monday 9AM-5PM availability
        client.post(
            f"/api/calendar/availability/{tenant_id}",
            json={"slots": [
                {"day_of_week": 0, "start_time": "09:00", "end_time": "17:00"},
            ]},
        )

        # Try to book at 8AM (outside availability)
        response = client.post(
            f"/api/calendar/book/{tenant_id}",
            json={
                "date": "2026-05-18",
                "start_time": "08:00",
                "end_time": "09:00",
                "attendee_name": "John Doe",
                "attendee_email": "john@example.com",
            },
        )
        assert response.status_code == 400

    def test_book_nonexistent_tenant(self):
        """Booking for non-existent tenant should return 404."""
        response = client.post(
            "/api/calendar/book/nonexistent",
            json={
                "date": "2026-05-18",
                "start_time": "10:00",
                "end_time": "11:00",
                "attendee_name": "John Doe",
                "attendee_email": "john@example.com",
            },
        )
        assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Disconnect Tests
# --------------------------------------------------------------------------- #

class TestDisconnect:
    def test_disconnect_no_integration(self, registered_tenant):
        """Disconnect when no integration exists should return 404."""
        tenant_id = registered_tenant["tenant_id"]
        response = client.post(f"/api/calendar/disconnect/{tenant_id}")
        assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Initialize Defaults Tests
# --------------------------------------------------------------------------- #

class TestInitializeDefaults:
    def test_initialize_default_availability(self, registered_tenant):
        """Initialize default availability (Mon-Fri 9AM-5PM)."""
        tenant_id = registered_tenant["tenant_id"]
        response = client.post(f"/api/calendar/initialize-defaults/{tenant_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        # Verify 5 slots were created (Mon-Fri)
        get_response = client.get(f"/api/calendar/availability/{tenant_id}")
        assert len(get_response.json()["slots"]) == 5

    def test_initialize_default_nonexistent_tenant(self):
        """Initialize defaults for non-existent tenant should return 404."""
        response = client.post("/api/calendar/initialize-defaults/nonexistent")
        assert response.status_code == 404
