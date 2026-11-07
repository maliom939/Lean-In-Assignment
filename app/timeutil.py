"""Timestamp helpers.

Timestamps are stored as ISO 8601 UTC strings with millisecond precision, the same format the
dataset uses. String order then matches time order, so SQLite range filters can use indexes.
"""

from datetime import datetime, timezone


def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime. Naive values are taken as UTC."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ts(dt: datetime) -> str:
    """Format a datetime in the storage format, with millisecond precision."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def days_between(later: datetime, earlier: datetime) -> float:
    """Fractional days from `earlier` to `later`."""
    return (later - earlier).total_seconds() / 86400
