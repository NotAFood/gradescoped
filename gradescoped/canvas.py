from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Optional

import httpx

from .models import CanvasAssignment

log = logging.getLogger("gradescoped")

# ICS line folding: continuation lines start with a space or tab
_FOLD_RE = re.compile(r"\r?\n[ \t]")


def _unfold(text: str) -> str:
    return _FOLD_RE.sub("", text)


def _parse_dt(value: str, tzid: Optional[str] = None) -> tuple[datetime, bool]:
    """Return (datetime_utc, is_all_day)."""
    if len(value) == 8 and value.isdigit():
        d = date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc), True

    value = value.rstrip("Z")
    dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    return dt.replace(tzinfo=timezone.utc), False


def fetch_assignments(ics_url: str) -> list[CanvasAssignment]:
    response = httpx.get(ics_url, follow_redirects=True, timeout=30)
    response.raise_for_status()
    text = _unfold(response.text)

    assignments: list[CanvasAssignment] = []
    in_event = False
    props: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "BEGIN:VEVENT":
            in_event = True
            props = {}
        elif line == "END:VEVENT":
            in_event = False
            assignment = _parse_event(props)
            if assignment is not None:
                assignments.append(assignment)
        elif in_event and ":" in line:
            key_part, _, value = line.partition(":")
            key = key_part.split(";")[0].upper()
            props[key] = value

    return assignments


def _parse_event(props: dict[str, str]) -> Optional[CanvasAssignment]:
    uid = props.get("UID", "")
    summary = props.get("SUMMARY", "")
    url = props.get("URL", "")
    description = props.get("DESCRIPTION", "").replace("\\n", "\n")

    dtstart_raw = props.get("DTSTART")
    if not dtstart_raw:
        return None

    due_at, is_all_day = _parse_dt(dtstart_raw)

    course_match = re.search(r"\[([^\]]+)\]$", summary)
    course_name = course_match.group(1) if course_match else ""
    name = summary[: course_match.start()].strip() if course_match else summary

    return CanvasAssignment(
        uid=uid,
        name=name,
        course_name=course_name,
        due_at=due_at,
        is_all_day=is_all_day,
        url=url,
        description=description,
    )
