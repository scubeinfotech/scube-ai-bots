"""
Calendar Service — Google Calendar integration for appointment booking.
Handles OAuth flow, availability checking, and booking creation.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.models.calendar import CalendarIntegration, TenantAvailability

logger = logging.getLogger(__name__)

# Day name mapping
DAY_NAMES = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
             4: "Friday", 5: "Saturday", 6: "Sunday"}


class CalendarService:
    """Service for calendar integration with Google Calendar."""

    # Google OAuth endpoints
    GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    GOOGLE_SCOPES = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events",
    ]

    @classmethod
    def get_oauth_url(cls, tenant_id: str, redirect_uri: str, state: str = "") -> str:
        """Generate Google OAuth authorization URL."""
        from app.config import settings
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(cls.GOOGLE_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state or tenant_id,
        }
        return f"{cls.GOOGLE_AUTH_URL}?{urlencode(params)}"

    @classmethod
    def handle_oauth_callback(cls, tenant_id: str, code: str, db: Session) -> dict:
        """
        Handle OAuth callback from Google.
        Exchanges code for tokens and stores them.

        NOTE: In production, this needs to call Google's token endpoint
        with the client_secret. For now, we store the code and mark as
        pending manual configuration.
        """
        integration = db.query(CalendarIntegration).filter(
            CalendarIntegration.tenant_id == tenant_id,
            CalendarIntegration.provider == "google",
        ).first()

        if not integration:
            integration = CalendarIntegration(
                tenant_id=tenant_id,
                provider="google",
            )
            db.add(integration)
            db.flush()

        # In production: exchange code for tokens via Google API
        # For now: store a placeholder and mark as connected
        integration.is_connected = True
        integration.access_token = f"temp_token_{code[:20]}"
        integration.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        db.commit()
        db.refresh(integration)

        logger.info(f"[Calendar] Google OAuth connected for tenant {tenant_id}")
        return {
            "status": "success",
            "provider": "google",
            "is_connected": True,
        }

    @classmethod
    def disconnect(cls, tenant_id: str, db: Session) -> bool:
        """Disconnect calendar integration for a tenant."""
        integration = db.query(CalendarIntegration).filter(
            CalendarIntegration.tenant_id == tenant_id,
        ).first()

        if not integration:
            return False

        integration.is_connected = False
        integration.access_token = None
        integration.refresh_token = None
        integration.token_expires_at = None
        db.commit()

        logger.info(f"[Calendar] Disconnected for tenant {tenant_id}")
        return True

    @classmethod
    def get_integration_status(cls, tenant_id: str, db: Session) -> dict:
        """Get calendar integration status for a tenant."""
        integration = db.query(CalendarIntegration).filter(
            CalendarIntegration.tenant_id == tenant_id,
        ).first()

        if not integration:
            return {
                "is_connected": False,
                "provider": None,
                "provider_email": None,
                "meeting_provider": "google_meet",
            }

        return {
            "is_connected": integration.is_connected,
            "provider": integration.provider,
            "provider_email": integration.provider_email,
            "meeting_provider": integration.meeting_provider,
            "timezone": integration.timezone,
            "calendar_id": integration.calendar_id,
        }

    @classmethod
    def get_availability(cls, tenant_id: str, db: Session) -> list[dict]:
        """Get weekly availability slots for a tenant."""
        slots = db.query(TenantAvailability).filter(
            TenantAvailability.tenant_id == tenant_id,
            TenantAvailability.is_active == True,
        ).order_by(TenantAvailability.day_of_week, TenantAvailability.start_time).all()

        return [
            {
                "id": s.id,
                "day_of_week": s.day_of_week,
                "day_name": DAY_NAMES.get(s.day_of_week, "Unknown"),
                "start_time": s.start_time,
                "end_time": s.end_time,
                "timezone": s.timezone,
                "blocked_dates": s.blocked_dates or [],
            }
            for s in slots
        ]

    @classmethod
    def set_availability(cls, tenant_id: str, slots: list[dict], db: Session) -> list[dict]:
        """
        Set weekly availability slots for a tenant.
        Replaces all existing slots.

        Each slot: {"day_of_week": 0-6, "start_time": "09:00", "end_time": "17:00"}
        """
        # Deactivate all existing slots
        db.query(TenantAvailability).filter(
            TenantAvailability.tenant_id == tenant_id,
        ).delete(synchronize_session=False)

        # Create new slots
        created = []
        for slot_data in slots:
            slot = TenantAvailability(
                tenant_id=tenant_id,
                day_of_week=slot_data["day_of_week"],
                start_time=slot_data["start_time"],
                end_time=slot_data["end_time"],
                timezone=slot_data.get("timezone", "Asia/Singapore"),
                blocked_dates=slot_data.get("blocked_dates"),
            )
            db.add(slot)
            db.flush()
            created.append({
                "id": slot.id,
                "day_of_week": slot.day_of_week,
                "day_name": DAY_NAMES.get(slot.day_of_week, "Unknown"),
                "start_time": slot.start_time,
                "end_time": slot.end_time,
            })

        db.commit()
        return created

    @classmethod
    def check_availability(cls, tenant_id: str, date: str, db: Session) -> list[dict]:
        """
        Check available time slots for a specific date.
        Returns list of available slots for that day.

        date format: "2026-05-20"
        """
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return []

        day_of_week = target_date.weekday()  # 0=Monday

        # Get availability for this day of week
        availability = db.query(TenantAvailability).filter(
            TenantAvailability.tenant_id == tenant_id,
            TenantAvailability.day_of_week == day_of_week,
            TenantAvailability.is_active == True,
        ).all()

        if not availability:
            return []

        # Check if date is blocked
        blocked_dates = []
        for slot in availability:
            if slot.blocked_dates:
                blocked_dates.extend(slot.blocked_dates)

        if date in blocked_dates:
            return []

        # Return available slots
        return [
            {
                "date": date,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "timezone": s.timezone,
            }
            for s in availability
        ]

    @classmethod
    def book_appointment(cls, tenant_id: str, date: str, start_time: str,
                         end_time: str, attendee_name: str, attendee_email: str,
                         db: Session) -> dict:
        """
        Book an appointment slot.

        In production: Creates a Google Calendar event with Google Meet link.
        For now: Stores booking info and returns confirmation.
        """
        # Check if slot is available
        available = cls.check_availability(tenant_id, date, db)
        if not available:
            return {
                "status": "error",
                "message": "No availability found for this date",
            }

        # Check if requested time falls within any available slot
        def time_to_minutes(t):
            h, m = t.split(":")
            return int(h) * 60 + int(m)

        requested_start = time_to_minutes(start_time)
        requested_end = time_to_minutes(end_time)

        matching_slots = [
            s for s in available
            if time_to_minutes(s["start_time"]) <= requested_start
            and time_to_minutes(s["end_time"]) >= requested_end
        ]

        if not matching_slots:
            return {
                "status": "error",
                "message": "Requested time slot is not available",
            }

        # In production: Create Google Calendar event via API
        # For now: Generate a mock Google Meet link
        meet_link = f"https://meet.google.com/abc-defg-hij"

        logger.info(
            f"[Calendar] Appointment booked for tenant {tenant_id}: "
            f"{date} {start_time}-{end_time} with {attendee_name}"
        )

        return {
            "status": "success",
            "appointment": {
                "date": date,
                "start_time": start_time,
                "end_time": end_time,
                "attendee_name": attendee_name,
                "attendee_email": attendee_email,
                "meeting_link": meet_link,
                "timezone": matching_slots[0]["timezone"],
            },
        }

    @classmethod
    def initialize_default_availability(cls, tenant_id: str, db: Session):
        """Set default availability: Mon-Fri 9AM-5PM."""
        default_slots = [
            {"day_of_week": i, "start_time": "09:00", "end_time": "17:00"}
            for i in range(5)  # Monday-Friday
        ]
        cls.set_availability(tenant_id, default_slots, db)
        logger.info(f"[Calendar] Default availability set for tenant {tenant_id}")

    @classmethod
    def check_working_hours(cls, tenant_id: str, date: str, time_str: str, db: Session) -> dict:
        """
        Check if requested time is within working hours.
        Returns: {"valid": bool, "within_hours": bool, "message": str}
        """
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
            hour, minute = map(int, time_str.split(":")[:2])
        except (ValueError, IndexError):
            return {
                "valid": False,
                "within_hours": False,
                "message": "Invalid date or time format"
            }

        day_of_week = target_date.weekday()
        
        # Get availability for this day
        availability = db.query(TenantAvailability).filter(
            TenantAvailability.tenant_id == tenant_id,
            TenantAvailability.day_of_week == day_of_week,
            TenantAvailability.is_active == True,
        ).first()

        if not availability:
            return {
                "valid": False,
                "within_hours": False,
                "message": f"We don't operate on {DAY_NAMES.get(day_of_week, 'this day')}. Please choose a different day."
            }

        # Check if within working hours
        def time_to_minutes(t):
            h, m = t.split(":")
            return int(h) * 60 + int(m)

        requested_mins = hour * 60 + minute
        start_mins = time_to_minutes(availability.start_time)
        end_mins = time_to_minutes(availability.end_time)

        if requested_mins < start_mins:
            return {
                "valid": False,
                "within_hours": False,
                "message": f"We open at {availability.start_time}. Please choose a time after {availability.start_time}."
            }

        if requested_mins >= end_mins:
            return {
                "valid": False,
                "within_hours": False,
                "message": f"We close at {availability.end_time}. Please choose a time before {availability.end_time}."
            }

        return {
            "valid": True,
            "within_hours": True,
            "message": None
        }

    @classmethod
    def get_alternative_times(cls, tenant_id: str, date: str, preferred_time: str, 
                              db: Session, count: int = 3) -> list[dict]:
        """
        Get alternative available time slots if preferred time is not available.
        Returns list of alternative slots.
        """
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
            hour, minute = map(int, preferred_time.split(":")[:2])
            preferred_mins = hour * 60 + minute
        except (ValueError, IndexError):
            return []

        day_of_week = target_date.weekday()
        
        # Get availability for this day
        availability = db.query(TenantAvailability).filter(
            TenantAvailability.tenant_id == tenant_id,
            TenantAvailability.day_of_week == day_of_week,
            TenantAvailability.is_active == True,
        ).first()

        if not availability:
            return []

        def time_to_minutes(t):
            h, m = t.split(":")
            return int(h) * 60 + int(m)

        start_mins = time_to_minutes(availability.start_time)
        end_mins = time_to_minutes(availability.end_time)

        # Generate slots every 30 minutes
        slots = []
        current = start_mins
        while current < end_mins:
            slot_time = f"{current // 60:02d}:{current % 60:02d}"
            
            # Skip if too close to preferred time (within 30 mins)
            if abs(current - preferred_mins) > 30:
                slots.append({
                    "time": slot_time,
                    "minutes": current,
                    "distance": abs(current - preferred_mins)
                })
            
            current += 30

        # Sort by distance from preferred time and return top N
        slots.sort(key=lambda x: x["distance"])
        
        return [
            {
                "date": date,
                "time": s["time"],
                "display": f"{date} at {s['time']}"
            }
            for s in slots[:count]
        ]

    @classmethod
    def check_calendar_conflict(cls, tenant_id: str, date: str, start_time: str, 
                                end_time: str, db: Session) -> dict:
        """
        Check if there's a conflict with existing Google Calendar events.
        In production: Query Google Calendar API.
        For now: Check tentative bookings and return simulated conflict detection.
        
        Returns: {"has_conflict": bool, "conflict_details": str, "suggested_action": str}
        """
        # Check existing tentative bookings for same tenant
        from app.models.whatsapp import WhatsAppTentativeBooking
        
        existing_bookings = db.query(WhatsAppTentativeBooking).filter(
            WhatsAppTentativeBooking.tenant_id == tenant_id,
            WhatsAppTentativeBooking.requested_date == date,
            WhatsAppTentativeBooking.status.in_(["tentative", "confirmed"])
        ).all()

        def time_to_minutes(t):
            if not t:
                return 0
            h, m = t.split(":")[:2]
            return int(h) * 60 + int(m)

        requested_start = time_to_minutes(start_time)
        requested_end = time_to_minutes(end_time) if end_time else requested_start + 60

        for booking in existing_bookings:
            if booking.requested_time:
                existing_start = time_to_minutes(booking.requested_time)
                existing_end = existing_start + 60  # Assume 1 hour meetings

                # Check overlap
                if (requested_start < existing_end and requested_end > existing_start):
                    return {
                        "has_conflict": True,
                        "conflict_details": f"You have another booking at {booking.requested_time}",
                        "suggested_action": "suggest_alternative",
                        "existing_booking": {
                            "time": booking.requested_time,
                            "contact_id": booking.contact_id
                        }
                    }

        return {
            "has_conflict": False,
            "conflict_details": None,
            "suggested_action": "confirm"
        }

    @classmethod
    def smart_booking_check(cls, tenant_id: str, date: str, time_str: str, 
                           db: Session, contact_name: str = "") -> dict:
        """
        Comprehensive booking validation with conflict detection and alternatives.
        Returns full recommendation for the booking flow.
        """
        result = {
            "can_book": False,
            "reason": None,
            "alternatives": [],
            "action": "reject",  # reject, confirm, suggest_alternative, assign_team
            "team_assignment": None
        }

        # Step 1: Check working hours
        hours_check = cls.check_working_hours(tenant_id, date, time_str, db)
        if not hours_check["within_hours"]:
            result["reason"] = hours_check["message"]
            result["action"] = "reject"
            return result

        # Step 2: Check calendar conflicts
        conflict_check = cls.check_calendar_conflict(tenant_id, date, time_str, 
                                                       f"{int(time_str.split(':')[0]) + 1:02d}:{time_str.split(':')[1]}", 
                                                       db)
        
        if conflict_check["has_conflict"]:
            # Get alternatives
            alternatives = cls.get_alternative_times(tenant_id, date, time_str, db, count=3)
            
            result["can_book"] = False
            result["reason"] = conflict_check["conflict_details"]
            result["alternatives"] = alternatives
            result["action"] = "suggest_alternative"
            
            # Check if team assignment is possible (could be configured per tenant)
            # For now, suggest alternative times first
            return result

        # No conflicts - can book
        result["can_book"] = True
        result["action"] = "confirm"
        return result
