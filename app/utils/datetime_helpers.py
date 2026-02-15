"""UTC-aware datetime utilities replacing deprecated datetime.utcnow().

All datetimes in the system are stored as UTC. Display conversion to the
user's preferred timezone happens at the API/frontend boundary.
"""

import datetime
from typing import Optional
from zoneinfo import ZoneInfo, available_timezones


# Common timezone aliases for user-friendly display
TIMEZONE_ALIASES = {
    "EST": "America/New_York",
    "CST": "America/Chicago",
    "MST": "America/Denver",
    "PST": "America/Los_Angeles",
    "IST": "Asia/Kolkata",
    "GMT": "Europe/London",
    "CET": "Europe/Berlin",
    "JST": "Asia/Tokyo",
    "AEST": "Australia/Sydney",
    "UTC": "UTC",
}


def utcnow() -> datetime.datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


def ensure_utc(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """Ensure a datetime is UTC-aware. If naive, assume UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def to_timezone(dt: Optional[datetime.datetime], tz_name: str) -> Optional[datetime.datetime]:
    """Convert a UTC datetime to the specified timezone.

    Accepts IANA timezone names (e.g. 'America/New_York') or common
    abbreviations (e.g. 'EST', 'IST', 'PST').
    Returns None if dt is None.
    """
    if dt is None:
        return None
    dt = ensure_utc(dt)
    iana_name = TIMEZONE_ALIASES.get(tz_name.upper(), tz_name)
    try:
        target_tz = ZoneInfo(iana_name)
    except (KeyError, ValueError):
        return dt  # Unknown timezone — return UTC
    return dt.astimezone(target_tz)


def is_valid_timezone(tz_name: str) -> bool:
    """Check if a timezone name is valid (IANA or alias)."""
    if tz_name.upper() in TIMEZONE_ALIASES:
        return True
    return tz_name in available_timezones()


def format_datetime(dt: Optional[datetime.datetime], tz_name: str = "UTC") -> Optional[str]:
    """Format a datetime as ISO 8601 string in the given timezone."""
    if dt is None:
        return None
    converted = to_timezone(dt, tz_name)
    return converted.isoformat()
