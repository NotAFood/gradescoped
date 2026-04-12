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
