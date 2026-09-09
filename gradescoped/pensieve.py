from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

from .models import PensieveAssignment

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ICS line folding: continuation lines start with a space or tab
_FOLD_RE = re.compile(r"\r?\n[ \t]")


def _unfold(text: str) -> str:
    return _FOLD_RE.sub("", text)


def _parse_dt(value: str) -> datetime:
    if len(value) == 8 and value.isdigit():
        d = date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        local_end_of_day = datetime(
            d.year, d.month, d.day, 23, 59, 59, tzinfo=LOCAL_TZ
        )
        return local_end_of_day.astimezone(timezone.utc)

    value = value.rstrip("Z")
    dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    return dt.replace(tzinfo=timezone.utc)


def fetch_assignments(ics_url: str, course_name: str) -> list[PensieveAssignment]:
    response = httpx.get(ics_url, follow_redirects=True, timeout=30)
    response.raise_for_status()
    text = _unfold(response.text)

    assignments: list[PensieveAssignment] = []
    in_event = False
    props: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "BEGIN:VEVENT":
            in_event = True
            props = {}
        elif line == "END:VEVENT":
            in_event = False
            assignment = _parse_event(props, course_name)
            if assignment is not None:
                assignments.append(assignment)
        elif in_event and ":" in line:
            key_part, _, value = line.partition(":")
            key = key_part.split(";")[0].upper()
            props[key] = value

    return assignments


def _parse_event(
    props: dict[str, str], course_name: str
) -> Optional[PensieveAssignment]:
    if props.get("STATUS", "").upper() == "CANCELLED":
        return None

    uid = props.get("UID", "")
    summary = props.get("SUMMARY", "")
    url = props.get("URL", "")
    description = props.get("DESCRIPTION", "").replace("\\n", "\n")

    dtstart_raw = props.get("DTSTART")
    if not dtstart_raw or not uid:
        return None

    # SUMMARY is suffixed with the internal class slug (e.g. "HW1 - berkeley_..."),
    # which also appears as "Class: <slug>" in DESCRIPTION.
    class_match = re.search(r"^Class:\s*(\S+)", description, re.MULTILINE)
    if class_match:
        slug = class_match.group(1)
        summary = re.sub(rf"\s*-\s*{re.escape(slug)}$", "", summary)

    due_at = _parse_dt(dtstart_raw)

    return PensieveAssignment(
        uid=uid,
        name=summary,
        course_name=course_name,
        due_at=due_at,
        url=url,
        description=description,
    )
