"""Use the project's Moscow calendar consistently in Windows and Linux."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")


def calendar_date(moment: datetime) -> date:
    """Convert an aware instant to the calendar date used by expiry policies."""
    if moment.tzinfo is None:
        raise ValueError("An aware instant is required")
    return moment.astimezone(MOSCOW).date()


def current_date() -> date:
    """Return today's date without depending on the operating system timezone."""
    return datetime.now(MOSCOW).date()
