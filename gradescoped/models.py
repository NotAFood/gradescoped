from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class GradescopeCourse:
    id: str
    name: str
    short_name: str
    term: str
    year: str

    @property
    def term_year(self) -> str:
        return f"{self.term} {self.year}"


class SubmissionStatus(str, Enum):
    unsubmitted = "unsubmitted"
    submitted = "submitted"
    graded = "graded"


@dataclass(frozen=True)
class GradescopeAssignment:
    id: str
    course_id: str
    course_name: str
    name: str
    status: SubmissionStatus
    released_at: Optional[datetime]
    due_at: Optional[datetime]
    late_due_at: Optional[datetime]

    @property
    def url(self) -> str:
        return (
            f"https://www.gradescope.com/courses/{self.course_id}/assignments/{self.id}"
        )

    @property
    def calendar_tag(self) -> str:
        return f"gs-assignment-id:{self.id}@{self.course_id}"

    @property
    def late_calendar_tag(self) -> str:
        return f"gs-assignment-id:{self.id}@{self.course_id}:late"

    @property
    def is_upcoming(self) -> bool:
        now = datetime.now(tz=timezone.utc)
        if self.late_due_at is not None and self.late_due_at > now:
            return True
        if self.due_at is None:
            return False
        return self.due_at > now


@dataclass(frozen=True)
class CanvasAssignment:
    uid: str
    name: str
    course_name: str
    due_at: datetime
    is_all_day: bool
    url: str
    description: str

    @property
    def calendar_tag(self) -> str:
        return f"canvas-event-id:{self.uid}"

    @property
    def is_upcoming(self) -> bool:
        return self.due_at > datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class PensieveAssignment:
    uid: str
    name: str
    course_name: str
    due_at: datetime
    url: str
    description: str

    @property
    def calendar_tag(self) -> str:
        return f"pensieve-event-id:{self.uid}"

    @property
    def is_upcoming(self) -> bool:
        return self.due_at > datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class PartifulEvent:
    uid: str
    name: str
    start: datetime
    end: datetime
    location: str
    url: str
    description: str

    @property
    def calendar_tag(self) -> str:
        return f"partiful-event-id:{self.uid}"

    @property
    def is_upcoming(self) -> bool:
        return self.start > datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class GCalEvent:
    source_slug: str
    uid: str
    recurrence_id: Optional[str]
    name: str
    start: datetime
    end: datetime
    location: str
    description: str

    @property
    def calendar_tag(self) -> str:
        suffix = f":{self.recurrence_id}" if self.recurrence_id else ""
        return f"gcal-event-id:{self.source_slug}:{self.uid}{suffix}"

    @property
    def is_upcoming(self) -> bool:
        return self.start > datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class CalendarEventSnapshot:
    identifier: str
    title: str
    start: datetime
    end: datetime
    description: Optional[str]
    tag: str


@dataclass(frozen=True)
class CalendarMutation:
    tag: str
    title: str
    start: datetime
    end: datetime
    description: str
    existing_event_id: Optional[str] = None


class SyncOperation(str, Enum):
    create = "create"
    update = "update"


@dataclass(frozen=True)
class SyncAction:
    operation: SyncOperation
    mutation: CalendarMutation


@dataclass(frozen=True)
class SyncResult:
    calendar_name: str
    actions: list[SyncAction]
