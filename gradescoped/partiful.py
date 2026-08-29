from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from .models import PartifulEvent

# ICS line folding: continuation lines start with a space or tab
_FOLD_RE = re.compile(r"\r?\n[ \t]")
_SUMMARY_SUFFIX_RE = re.compile(r"\s*\|\s*Partiful\s*$")
_DURATION_RE = re.compile(r"^P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")
DEFAULT_DURATION = timedelta(hours=1)


def _unfold(text: str) -> str:
    return _FOLD_RE.sub("", text)


def _parse_dt(value: str) -> datetime:
    if len(value) == 8 and value.isdigit():
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)

    value = value.rstrip("Z")
    dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    return dt.replace(tzinfo=timezone.utc)


def _parse_duration(value: str) -> Optional[timedelta]:
    match = _DURATION_RE.match(value.strip())
    if not match:
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def fetch_events(ics_url: str) -> list[PartifulEvent]:
    url = re.sub(r"^webcal://", "https://", ics_url, flags=re.IGNORECASE)
    response = httpx.get(url, follow_redirects=True, timeout=30)
    response.raise_for_status()
    text = _unfold(response.text)

    events: list[PartifulEvent] = []
    in_event = False
    props: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "BEGIN:VEVENT":
            in_event = True
            props = {}
        elif line == "END:VEVENT":
            in_event = False
            event = _parse_event(props)
            if event is not None:
                events.append(event)
        elif in_event and ":" in line:
            key_part, _, value = line.partition(":")
            key = key_part.split(";")[0].upper()
            props[key] = value

    return events


def _parse_event(props: dict[str, str]) -> Optional[PartifulEvent]:
    uid = props.get("UID", "")
    dtstart_raw = props.get("DTSTART")
    if not uid or not dtstart_raw:
        return None

    start = _parse_dt(dtstart_raw)

    if props.get("DTEND"):
        end = _parse_dt(props["DTEND"])
    elif props.get("DURATION"):
        end = start + (_parse_duration(props["DURATION"]) or DEFAULT_DURATION)
    else:
        end = start + DEFAULT_DURATION

    summary = props.get("SUMMARY", "")
    name = _SUMMARY_SUFFIX_RE.sub("", summary).strip()
    description = props.get("DESCRIPTION", "").replace("\\n", "\n").replace("\\,", ",")

    return PartifulEvent(
        uid=uid,
        name=name,
        start=start,
        end=end,
        location=props.get("LOCATION", "").replace("\\,", ","),
        url=props.get("URL", ""),
        description=description,
    )
