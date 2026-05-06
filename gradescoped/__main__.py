from __future__ import annotations

import logging
import sys

from . import config as cfg
from .calendar_client import CalendarClient
from .canvas import fetch_assignments as fetch_canvas_assignments
from .scraper import GradescopeClient, GradescopeError
from .sync import plan_canvas_sync, plan_sync

log = logging.getLogger("gradescoped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.WARNING)

    conf = cfg.load()

    log.info("Logging in to Gradescope…")
    with GradescopeClient() as gs:
        try:
            gs.login(conf.gradescope.email, conf.gradescope.password)
        except GradescopeError as e:
            log.error("Error: %s", e)
            sys.exit(1)

        log.info("Fetching courses…")
        try:
            courses = gs.get_courses()
        except GradescopeError as e:
            log.error("Error fetching courses: %s", e)
            sys.exit(1)

        excluded = set(conf.calendar.excluded_courses)
        courses = [
            c
            for c in courses
            if c.id not in excluded
            and c.short_name not in excluded
            and c.name not in excluded
            and (conf.calendar.term is None or c.term_year == conf.calendar.term)
        ]
        term_note = f" (term: {conf.calendar.term})" if conf.calendar.term else ""
        log.info("  %d course(s) after exclusions%s", len(courses), term_note)

        log.info("Fetching assignments…")
        all_assignments = []
        for course in courses:
            try:
                assignments = gs.get_assignments(course)
                upcoming = [a for a in assignments if a.is_upcoming]
                all_assignments.extend(upcoming)
                label = (
                    f"{course.short_name} — {course.name}"
                    if course.short_name and course.name
                    else course.short_name or course.name
                )
                log.info("  %s: %d upcoming", label, len(upcoming))
            except GradescopeError as e:
                log.warning("  Could not fetch assignments for %s: %s", course.name, e)

    log.info("Connecting to Google Calendar…")
    calendar_client = CalendarClient(
        client_secret_path=conf.google.client_secret,
        token_path=conf.google.token,
    )

    calendar_id = calendar_client.get_or_create_calendar(conf.calendar.name)
    log.info("  Calendar: '%s'", conf.calendar.name)

    log.info("Reading existing events…")
    existing = calendar_client.list_tagged_events(calendar_id)
    log.info("  %d existing tagged event(s)", len(existing))

    canvas_assignments: list = []
    canvas_result = None
    canvas_skipped = 0
    if conf.canvas:
        log.info("Fetching Canvas assignments…")
        try:
            canvas_assignments = fetch_canvas_assignments(conf.canvas.ics_url)
            log.info("  %d total Canvas event(s)", len(canvas_assignments))
        except Exception as e:
            log.warning("Canvas sync failed: %s", e)

    # Auto-populate config with any newly discovered course names
    all_course_names = list(
        {a.course_name for a in all_assignments}
        | {a.course_name for a in canvas_assignments}
    )
    cfg.update_course_abbreviations(all_course_names)

    abbrevs = conf.calendar.course_abbreviations

    gs_result = plan_sync(
        calendar_name=conf.calendar.name,
        assignments=all_assignments,
        existing_events=existing,
        course_abbreviations=abbrevs,
    )

    if conf.canvas and canvas_assignments:
        try:
            canvas_result, canvas_skipped = plan_canvas_sync(
                calendar_name=conf.calendar.name,
                assignments=canvas_assignments,
                existing_events=existing,
                excluded_patterns=conf.calendar.excluded_patterns,
                course_abbreviations=abbrevs,
            )
            if canvas_skipped:
                log.info("  %d skipped (matched excluded_patterns)", canvas_skipped)
        except Exception as e:
            log.warning("Canvas sync failed: %s", e)

    all_actions = gs_result.actions + (canvas_result.actions if canvas_result else [])

    creates = sum(1 for a in all_actions if a.operation.value == "create")
    updates = sum(1 for a in all_actions if a.operation.value == "update")
    log.info("Plan: %d to create, %d to update", creates, updates)
    for action in all_actions:
        verb = "+" if action.operation.value == "create" else "~"
        m = action.mutation
        log.info("  %s %s  (due %s)", verb, m.title, m.end.strftime("%b %d %H:%M"))

    if not all_actions:
        log.info("Nothing to do.")
        return

    gs_result_with_canvas = gs_result.__class__(
        calendar_name=conf.calendar.name,
        actions=all_actions,
    )
    created, updated = calendar_client.apply(gs_result_with_canvas)
    log.info("Done: %d created, %d updated.", created, updated)


if __name__ == "__main__":
    main()
