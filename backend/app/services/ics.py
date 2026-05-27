"""
Reusable iCalendar (.ics) generator for booking confirmations.
Supports in-person events and online meetings (with Google Meet URL).
"""

import re
from datetime import datetime, timedelta
from typing import Optional


def _parse_date(date_str: str) -> Optional[str]:
    """Parse a date string like '2026-05-27' or 'tomorrow' into YYYYMMDD."""
    if not date_str:
        return None
    raw = date_str.strip().lower()
    if raw == "today":
        return datetime.utcnow().strftime("%Y%m%d")
    if raw == "tomorrow":
        return (datetime.utcnow() + timedelta(days=1)).strftime("%Y%m%d")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return None


def _parse_time(time_str: str) -> Optional[str]:
    """Parse a time string like '13:00', '1pm' into HHMMSS."""
    if not time_str:
        return None
    raw = time_str.strip().lower()
    m = re.match(r"(\d{1,2}):?(\d{2})?\s*(am|pm)", raw)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        if hour > 12 or minute >= 60:
            return None
        if m.group(3) == "pm" and hour != 12:
            hour += 12
        elif m.group(3) == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}{minute:02d}00"
    m = re.match(r"(\d{1,2}):(\d{2})", raw)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour >= 24 or minute >= 60:
            return None
        return f"{hour:02d}{minute:02d}00"
    if raw in ("noon", "midday"):
        return "120000"
    if raw == "midnight":
        return "000000"
    return None


def generate_ics(
    *,
    date: str,
    time: str,
    summary: str,
    description: str = "",
    location: str = "",
    duration_minutes: int = 60,
    contact_name: str = "",
    contact_phone: str = "",
    meet_url: str = "",
) -> str:
    """
    Generate an iCalendar (.ics) string.
    All date/time strings are treated as UTC (appended with Z).
    """
    dtstart_date = _parse_date(date)
    dtstart_time = _parse_time(time)
    if not dtstart_date or not dtstart_time:
        return ""

    dtstart_utc = f"{dtstart_date}T{dtstart_time}Z"
    dtend = _add_minutes(dtstart_utc, duration_minutes)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Centralized LLM Platform//Booking//EN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{dtstart_utc}-{contact_phone or 'anon'}@centralized-llm-platform",
        f"DTSTART:{dtstart_utc}",
        f"DTEND:{dtend}",
        f"SUMMARY:{_escape(summary)}",
        f"DESCRIPTION:{_escape(description)}",
    ]

    if location:
        lines.append(f"LOCATION:{_escape(location)}")

    if meet_url:
        lines.append(f"X-GOOGLE-CONFERENCE:{meet_url}")

    lines.append("STATUS:CONFIRMED")
    if contact_name:
        lines.append(f"ORGANIZER;CN={_escape(contact_name)}:mailto:{contact_phone or 'noreply@example.com'}")
    lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    return "\r\n".join(lines) + "\r\n"


def generate_booking_ics(
    booking_id: str,
    date: str,
    time: str,
    service_type: str,
    contact_name: str = "",
    contact_phone: str = "",
    persons: int = 1,
    tenant_name: str = "",
    tenant_address: str = "",
    is_online: bool = False,
    meet_url: str = "",
) -> str:
    """Convenience wrapper: generates an .ics for a booking record."""
    title = f"{'Online Meeting' if is_online else 'Booking'} - {tenant_name or service_type}"
    desc_parts = [
        f"Service: {service_type}",
        f"Guests: {persons}",
        f"Contact: {contact_name} ({contact_phone})" if contact_name else "",
    ]
    if meet_url:
        desc_parts.append(f"Meeting link: {meet_url}")
    description = "\n".join(p for p in desc_parts if p)

    location = tenant_address if not is_online else ""
    duration = 10 if is_online else 60

    return generate_ics(
        date=date,
        time=time,
        summary=title,
        description=description,
        location=location,
        duration_minutes=duration,
        contact_name=contact_name,
        contact_phone=contact_phone,
        meet_url=meet_url,
    )


def _add_minutes(dtstart_utc: str, minutes: int) -> str:
    """Add minutes to an ICS datetime string (YYYYMMDDTHHMMSSZ)."""
    try:
        dt = datetime.strptime(dtstart_utc, "%Y%m%dT%H%M%SZ")
        dt += timedelta(minutes=minutes)
        return dt.strftime("%Y%m%dT%H%M%SZ")
    except ValueError:
        return dtstart_utc


def _escape(text: str) -> str:
    """Escape special characters for ICS text fields."""
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\n", "\\n")
    return text
