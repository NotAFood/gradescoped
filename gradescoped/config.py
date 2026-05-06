from __future__ import annotations

import logging
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path.home() / ".config" / "gradescoped" / "config.toml"

log = logging.getLogger("gradescoped")

EXAMPLE_CONFIG = """\
[gradescope]
email = "you@example.com"
password = "your_password"

[calendar]
name = "Gradescope"

# Optional: list course IDs or short names to skip
# excluded_courses = ["12345", "CS 101"]

# Short display names for courses in calendar event titles.
# Run the daemon once to auto-populate discovered courses, then fill in values.
# [calendar.course_abbreviations]
# "Discrete Mathematics and Probability Theory (Spring 2026)" = "CS 70"
"""


@dataclass
class GradescopeConfig:
    email: str
    password: str


@dataclass
class CalendarConfig:
    name: str
    term: Optional[str] = None
    excluded_courses: list[str] = field(default_factory=list)
    excluded_patterns: list[str] = field(default_factory=list)
    course_abbreviations: dict[str, str] = field(default_factory=dict)


@dataclass
class CanvasConfig:
    ics_url: str


@dataclass
class GoogleConfig:
    client_secret: Path
    token: Path


@dataclass
class Config:
    gradescope: GradescopeConfig
    calendar: CalendarConfig
    google: GoogleConfig
    canvas: Optional[CanvasConfig] = None


_SECTION_HEADER = "[calendar.course_abbreviations]"


def update_course_abbreviations(
    new_course_names: list[str], path: Optional[Path] = None
) -> None:
    """Append any newly discovered course names (with empty values) to the config."""
    config_path = path or CONFIG_PATH

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    existing = raw.get("calendar", {}).get("course_abbreviations", {})
    missing = [n for n in new_course_names if n and n not in existing]
    if not missing:
        return

    def _toml_quote(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    new_entries = [f"{_toml_quote(n)} = \"\"\n" for n in missing]

    text = config_path.read_text()
    lines = text.splitlines(keepends=True)

    section_idx = next(
        (i for i, l in enumerate(lines) if l.strip() == _SECTION_HEADER), None
    )

    if section_idx is None:
        # Append new section at end of file
        if not text.endswith("\n"):
            lines.append("\n")
        lines.append(f"\n{_SECTION_HEADER}\n")
        lines.extend(new_entries)
    else:
        # Find end of section (next header or EOF) and insert before it
        insert_at = len(lines)
        for i in range(section_idx + 1, len(lines)):
            stripped = lines[i].strip()
            if stripped.startswith("[") and not stripped.startswith("#"):
                insert_at = i
                break
        lines[insert_at:insert_at] = new_entries

    config_path.write_text("".join(lines))
    log.info(
        "Added %d new course(s) to %s in config — fill in short names to use them",
        len(missing),
        _SECTION_HEADER,
    )


def load(path: Optional[Path] = None) -> Config:
    config_path = path or CONFIG_PATH
    if not config_path.exists():
        log.error("Config file not found at %s.", config_path)
        log.error("Create it with the following contents:\n%s", EXAMPLE_CONFIG)
        sys.exit(1)

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    gs = raw.get("gradescope", {})
    cal = raw.get("calendar", {})
    goog = raw.get("google", {})

    missing = [k for k in ("email", "password") if not gs.get(k)]
    if missing:
        log.error(
            "Missing required config keys under [gradescope]: %s", ", ".join(missing)
        )
        sys.exit(1)

    if not cal.get("name"):
        log.error("Missing required config key: [calendar] name")
        sys.exit(1)

    if not goog.get("client_secret"):
        log.error("Missing required config key: [google] client_secret")
        sys.exit(1)

    return Config(
        gradescope=GradescopeConfig(
            email=gs["email"],
            password=gs["password"],
        ),
        calendar=CalendarConfig(
            name=cal["name"],
            term=cal.get("term") or None,
            excluded_courses=cal.get("excluded_courses", []),
            excluded_patterns=cal.get("excluded_patterns", []),
            course_abbreviations=cal.get("course_abbreviations", {}),
        ),
        google=GoogleConfig(
            client_secret=Path(goog["client_secret"]).expanduser(),
            token=Path(
                goog.get("token", "~/.config/gradescoped/token.json")
            ).expanduser(),
        ),
        canvas=CanvasConfig(ics_url=raw["canvas"]["ics_url"])
        if raw.get("canvas", {}).get("ics_url")
        else None,
    )
