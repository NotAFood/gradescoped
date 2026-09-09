from __future__ import annotations

import logging
import sys

from . import config as cfg
from .calendar_client import CalendarClient
from .canvas import fetch_assignments as fetch_canvas_assignments
from .gcal_ics import fetch_events as fetch_gcal_events
from .partiful import fetch_events as fetch_partiful_events
from .pensieve import fetch_assignments as fetch_pensieve_assignments
from .scraper import GradescopeClient, GradescopeError
from .sync import (
    plan_canvas_sync,
    plan_external_calendar_sync,
    plan_partiful_sync,
    plan_pensieve_sync,
    plan_sync,
)

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

    pensieve_assignments: list = []
    pensieve_result = None
    pensieve_skipped = 0
    if conf.pensieve:
        log.info("Fetching Pensieve assignments…")
        try:
            pensieve_assignments = fetch_pensieve_assignments(
                conf.pensieve.ics_url, conf.pensieve.name
            )
            log.info("  %d total Pensieve event(s)", len(pensieve_assignments))
        except Exception as e:
            log.warning("Pensieve sync failed: %s", e)

    partiful_events: list = []
    partiful_result = None
    partiful_skipped = 0
    if conf.partiful:
        log.info("Fetching Partiful events…")
        try:
            partiful_events = fetch_partiful_events(conf.partiful.ics_url)
            log.info("  %d total Partiful event(s)", len(partiful_events))
        except Exception as e:
            log.warning("Partiful sync failed: %s", e)

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

    if conf.pensieve and pensieve_assignments:
        try:
            pensieve_result, pensieve_skipped = plan_pensieve_sync(
                calendar_name=conf.calendar.name,
                assignments=pensieve_assignments,
                existing_events=existing,
                excluded_patterns=conf.pensieve.excluded_patterns,
            )
            if pensieve_skipped:
                log.info("  %d skipped (matched excluded_patterns)", pensieve_skipped)
        except Exception as e:
            log.warning("Pensieve sync failed: %s", e)

    if conf.partiful and partiful_events:
        try:
            partiful_result, partiful_skipped = plan_partiful_sync(
                calendar_name=conf.calendar.name,
                events=partiful_events,
                existing_events=existing,
                excluded_patterns=conf.partiful.excluded_patterns,
            )
            if partiful_skipped:
                log.info("  %d skipped (matched excluded_patterns)", partiful_skipped)
        except Exception as e:
            log.warning("Partiful sync failed: %s", e)

    primary_actions = (
        gs_result.actions
        + (canvas_result.actions if canvas_result else [])
        + (pensieve_result.actions if pensieve_result else [])
        + (partiful_result.actions if partiful_result else [])
    )

    # External calendars can target calendars other than [calendar].name, so
    # each is planned against its own target calendar's existing events.
    external_results = []
    for ext in conf.external_calendars:
        log.info("Fetching external calendar '%s'…", ext.name)
        try:
            events = fetch_gcal_events(ext.ics_url, source_slug=ext.slug)
            log.info("  %d upcoming event(s)", len(events))
            ext_calendar_id = calendar_client.get_or_create_calendar(
                ext.target_calendar
            )
            ext_existing = calendar_client.list_tagged_events(ext_calendar_id)
            ext_result, ext_skipped = plan_external_calendar_sync(
                calendar_name=ext.target_calendar,
                events=events,
                existing_events=ext_existing,
                excluded_patterns=ext.excluded_patterns,
            )
            if ext_skipped:
                log.info("  %d skipped (matched excluded_patterns)", ext_skipped)
            external_results.append((ext.target_calendar, ext_result))
        except Exception as e:
            log.warning("External calendar '%s' sync failed: %s", ext.name, e)

    all_actions = primary_actions + [
        a for _, r in external_results for a in r.actions
    ]

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

    total_created = total_updated = 0

    if primary_actions:
        primary_result = gs_result.__class__(
            calendar_name=conf.calendar.name,
            actions=primary_actions,
        )
        created, updated = calendar_client.apply(primary_result)
        total_created += created
        total_updated += updated

    for _, ext_result in external_results:
        if not ext_result.actions:
            continue
        created, updated = calendar_client.apply(ext_result)
        total_created += created
        total_updated += updated

    log.info("Done: %d created, %d updated.", total_created, total_updated)


if __name__ == "__main__":
    main()
