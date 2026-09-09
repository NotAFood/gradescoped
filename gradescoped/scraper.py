from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote, urlencode

import httpx
from lxml import html

from .models import GradescopeAssignment, GradescopeCourse, SubmissionStatus

BASE_URL = "https://www.gradescope.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S %z"


class GradescopeError(Exception):
    pass


class LoginFailed(GradescopeError):
    pass


class InvalidCredentials(GradescopeError):
    pass


class HtmlParseError(GradescopeError):
    pass


def _parse_date(text: str) -> Optional[datetime]:
    text = text.strip()
    if not text:
        return None
    try:
        dt = datetime.strptime(text, DATE_FORMAT)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


class GradescopeClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GradescopeClient:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def login(self, email: str, password: str) -> None:
        home = self._get("/")
        auth_token = self._extract_authenticity_token(home)

        form_data = [
            ("utf8", "✓"),
            ("session[email]", email),
            ("session[password]", password),
            ("session[remember_me]", "0"),
            ("commit", "Log In"),
            ("session[remember_me_sso]", "0"),
            ("authenticity_token", auth_token),
        ]
        body = urlencode(form_data, quote_via=lambda s, safe, *_: quote(s, safe="-._*"))

        response = self._client.post(
            "/login",
            content=body.encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE_URL,
                "Referer": f"{BASE_URL}/login",
            },
        )

        if response.status_code != 302:
            raise LoginFailed(
                f"Expected 302 from login POST, got {response.status_code}"
            )

        account_html = self._get("/account")
        if "Course Dashboard" not in account_html:
            raise InvalidCredentials(
                "Login appeared to succeed but session is invalid."
            )

    def get_courses(self) -> list[GradescopeCourse]:
        data = self._get("/account")
        return self._parse_courses(data)

    def get_assignments(self, course: GradescopeCourse) -> list[GradescopeAssignment]:
        data = self._get(f"/courses/{course.id}")
        return self._parse_assignments(
            data, course_id=course.id, course_name=course.name
        )

    def _get(self, path: str) -> str:
        response = self._client.get(path)
        response.raise_for_status()
        return response.text

    def _extract_authenticity_token(self, page_html: str) -> str:
        doc = html.fromstring(page_html)
        nodes = doc.xpath(
            "//form[@action='/login']//input[@name='authenticity_token']/@value"
        )
        if not nodes:
            raise HtmlParseError("authenticity_token input not found on login page")
        return nodes[0]

    def _parse_courses(self, page_html: str) -> list[GradescopeCourse]:
        doc = html.fromstring(page_html)
        course_boxes = doc.xpath(
            "//h1[contains(@class,'pageHeading') and normalize-space(text())='Course Dashboard']"
            "/following-sibling::*[1]"
            "//a[contains(concat(' ', normalize-space(@class), ' '), ' courseBox ')]"
        )

        seen_hrefs: set[str] = set()
        courses: list[GradescopeCourse] = []

        for el in course_boxes:
            href = el.get("href", "")
            if not href or href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            parts = href.strip("/").split("/")
            course_id = parts[-1] if parts else ""
            if not course_id:
                continue

            short_name = ""
            name = ""
            for child in el:
                cls = child.get("class", "")
                if "courseBox--shortname" in cls:
                    short_name = (child.text_content() or "").strip()
                elif "courseBox--name" in cls:
                    name = (child.text_content() or "").strip()

            term, year = self._term_year_for(el)

            courses.append(
                GradescopeCourse(
                    id=course_id,
                    name=name,
                    short_name=short_name,
                    term=term,
                    year=year,
                )
            )

        return courses

    def _term_year_for(self, course_box_el) -> tuple[str, str]:
        node = course_box_el.getparent()
        while node is not None:
            cls = node.get("class", "")
            if "courseList--coursesForTerm" in cls:
                for sib in node.itersiblings(preceding=True):
                    sib_cls = sib.get("class", "")
                    if "courseList--term" in sib_cls:
                        text = (sib.text_content() or "").strip()
                        parts = text.split()
                        if len(parts) >= 2:
                            return parts[0], parts[1]
                        return text, ""
                return "", ""
            node = node.getparent()
        return "", ""

    def _parse_assignments(
        self, page_html: str, course_id: str, course_name: str
    ) -> list[GradescopeAssignment]:
        doc = html.fromstring(page_html)
        rows = doc.xpath("//table[@id='assignments-student-table']//tbody/tr")

        assignments: list[GradescopeAssignment] = []
        for row in rows:
            th_cells = row.xpath("th")
            if not th_cells:
                continue
            name_cell = th_cells[0]
            td_cells = row.xpath("td")

            assignment_name = (name_cell.text_content() or "").strip()

            assignment_id = self._extract_assignment_id(name_cell)
            if not assignment_id:
                continue

            status_class = ""
            if td_cells:
                status_class = td_cells[0].get("class", "")
            if (
                "submissionStatus--score" in status_class
                or "submissionStatus--graded" in status_class
            ):
                status = SubmissionStatus.graded
            elif "submissionStatus--submitted" in status_class:
                status = SubmissionStatus.submitted
            else:
                status = SubmissionStatus.unsubmitted

            hidden_dates: list[datetime] = []
            for td in td_cells:
                if "hidden-column" in td.get("class", ""):
                    dt = _parse_date(td.text_content())
                    if dt:
                        hidden_dates.append(dt)

            released_at = hidden_dates[0] if len(hidden_dates) > 0 else None

            # The hidden-column due-date <td> is unreliable while a late window is
            # currently open: Gradescope swaps its value to the late deadline instead
            # of the original one. The visible <time class="...dueDate"> elements
            # don't have this problem, so prefer those.
            due_time_nodes = row.xpath(
                ".//time[contains(@class, 'submissionTimeChart--dueDate')"
                " and not(contains(text(), 'Late Due Date'))]/@datetime"
            )
            due_at = (
                _parse_date(due_time_nodes[0])
                if due_time_nodes
                else (hidden_dates[1] if len(hidden_dates) > 1 else None)
            )

            late_time_nodes = row.xpath(
                ".//time[contains(text(), 'Late Due Date')]/@datetime"
            )
            late_due_at = _parse_date(late_time_nodes[0]) if late_time_nodes else None

            assignments.append(
                GradescopeAssignment(
                    id=assignment_id,
                    course_id=course_id,
                    course_name=course_name,
                    name=assignment_name,
                    status=status,
                    released_at=released_at,
                    due_at=due_at,
                    late_due_at=late_due_at,
                )
            )

        return assignments

    def _extract_assignment_id(self, name_cell) -> Optional[str]:
        anchors = name_cell.xpath(".//a[@href]")
        for a in anchors:
            href = a.get("href", "")
            parts = href.split("/")
            if "assignments" in parts:
                idx = parts.index("assignments")
                if idx + 1 < len(parts):
                    return parts[idx + 1]

        buttons = name_cell.xpath(".//button[@data-assignment-id]")
        for btn in buttons:
            val = btn.get("data-assignment-id", "").strip()
            if val:
                return val

        return None


if __name__ == "__main__":
    import sys
    from . import config as cfg

    target = sys.argv[1].lower() if len(sys.argv) > 1 else None

    conf = cfg.load()
    with GradescopeClient() as gs:
        gs.login(conf.gradescope.email, conf.gradescope.password)
        courses = gs.get_courses()
        courses = [
            c for c in courses
            if conf.calendar.term is None or c.term_year == conf.calendar.term
        ]
        for course in courses:
            assignments = gs.get_assignments(course)
            for a in assignments:
                if target and target not in a.name.lower():
                    continue
                print(f"{course.short_name} | {a.name}")
                print(f"  due_at:      {a.due_at}")
                print(f"  late_due_at: {a.late_due_at}")
