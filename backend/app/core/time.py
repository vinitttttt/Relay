"""UTC timestamp helpers for SQLite-compatible storage and API output."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Interpret legacy naive SQLite timestamps as UTC and normalize aware values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_isoformat(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")
