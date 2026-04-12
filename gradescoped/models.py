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
    def is_upcoming(self) -> bool:
        if self.due_at is None:
            return False
        return self.due_at > datetime.now(tz=timezone.utc)


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
