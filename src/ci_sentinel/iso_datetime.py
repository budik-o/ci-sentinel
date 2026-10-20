"""Parse GitHub-style ISO-8601 timestamps (including ``Z`` suffix)."""

from __future__ import annotations

from datetime import datetime


def parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO 8601 timestamp, requiring an explicit timezone."""
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO 8601 datetime: {value!r}") from exc

    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"ISO 8601 datetime must include a timezone: {value!r}")

    return result
