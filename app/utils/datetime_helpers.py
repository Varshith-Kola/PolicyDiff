"""UTC-aware datetime utilities replacing deprecated datetime.utcnow()."""

import datetime


def utcnow() -> datetime.datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


def ensure_utc(dt: datetime.datetime) -> datetime.datetime:
    """Ensure a datetime is UTC-aware. If naive, assume UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)
