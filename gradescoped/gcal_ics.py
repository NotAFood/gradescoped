from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import icalendar
import recurring_ical_events

from .models import GCalEvent

DEFAULT_WINDOW_DAYS = 90
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def _as_utc_datetime(value: datetime | date) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.combine(
        value, time(23, 59, 59), tzinfo=LOCAL_TZ
    ).astimezone(timezone.utc)


def fetch_events(
    ics_url: str, source_slug: str, window_days: int = DEFAULT_WINDOW_DAYS
) -> list[GCalEvent]:
    response = httpx.get(ics_url, follow_redirects=True, timeout=30)
    response.raise_for_status()

    calendar = icalendar.Calendar.from_ical(response.text)

    now = datetime.now(tz=timezone.utc)
    window_end = now + timedelta(days=window_days)
    occurrences = recurring_ical_events.of(calendar).between(now, window_end)

    events: list[GCalEvent] = []
    for occurrence in occurrences:
        uid = str(occurrence.get("UID", ""))
        if not uid:
            continue

        recurrence_id = occurrence.get("RECURRENCE-ID")
        recurrence_id_str = (
            _as_utc_datetime(recurrence_id.dt).isoformat() if recurrence_id else None
        )

        start = _as_utc_datetime(occurrence["DTSTART"].dt)
        end_prop = occurrence.get("DTEND")
        end = _as_utc_datetime(end_prop.dt) if end_prop else start

        events.append(
            GCalEvent(
                source_slug=source_slug,
                uid=uid,
                recurrence_id=recurrence_id_str,
                name=str(occurrence.get("SUMMARY", "")),
                start=start,
                end=end,
                location=str(occurrence.get("LOCATION", "")),
                description=str(occurrence.get("DESCRIPTION", "")),
            )
        )

    return events
