from __future__ import annotations

from datetime import timedelta

from .models import (
    CalendarMutation,
    GradescopeAssignment,
    SyncAction,
    SyncOperation,
    SyncResult,
    CalendarEventSnapshot,
)


def plan_sync(
    calendar_name: str,
    assignments: list[GradescopeAssignment],
    existing_events: list[CalendarEventSnapshot],
) -> SyncResult:
    existing_by_tag = {e.tag: e for e in existing_events}
    actions: list[SyncAction] = []

    for assignment in assignments:
        if assignment.due_at is None:
            continue

        mutation = _planned_mutation(
            assignment, existing_by_tag.get(assignment.calendar_tag)
        )
        existing = existing_by_tag.get(assignment.calendar_tag)

        if existing is not None:
            if (
                existing.title != mutation.title
                or existing.start != mutation.start
                or existing.end != mutation.end
                or existing.description != mutation.description
            ):
                actions.append(
                    SyncAction(operation=SyncOperation.update, mutation=mutation)
                )
        else:
            actions.append(
                SyncAction(operation=SyncOperation.create, mutation=mutation)
            )

    return SyncResult(calendar_name=calendar_name, actions=actions)


def _planned_mutation(
    assignment: GradescopeAssignment,
    existing: CalendarEventSnapshot | None,
) -> CalendarMutation:
    due_at = assignment.due_at
    title = f"[{assignment.course_name}] {assignment.name}"
    description = f"{assignment.url}\n{assignment.calendar_tag}"
    start = due_at - timedelta(hours=1)
    end = due_at

    return CalendarMutation(
        tag=assignment.calendar_tag,
        title=title,
        start=start,
        end=end,
        description=description,
        existing_event_id=existing.identifier if existing else None,
    )
