from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .models import (
    CalendarEventSnapshot,
    CalendarMutation,
    SyncAction,
    SyncOperation,
    SyncResult,
)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

TAG_PATTERN = re.compile(
    r"(?:gs-assignment-id|canvas-event-id|pensieve-event-id|partiful-event-id|gcal-event-id):[^\s]+"
)


def _get_credentials(client_secret_path: Path, token_path: Path) -> Credentials:
    creds: Credentials | None = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secret_path), SCOPES
            )
            flow.redirect_uri = "http://localhost"
            auth_url, _ = flow.authorization_url(
                access_type="offline",
                prompt="consent",
            )
            print("Open this URL in a browser and approve access:")
            print(auth_url)
            print()
            print(
                "Then paste the full redirect URL (http://localhost/?code=...) or just the code:"
            )
            auth_input = input().strip()

            if auth_input.startswith("http://") or auth_input.startswith("https://"):
                parsed = urlparse(auth_input)
                code = parse_qs(parsed.query).get("code", [""])[0]
            else:
                code = auth_input

            if not code:
                raise ValueError("No authorization code found in input.")

            flow.fetch_token(code=code)
            creds = flow.credentials

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def _to_rfc3339(dt: datetime) -> str:
    return dt.isoformat()


def _tag_from_description(description: str | None) -> str | None:
    if not description:
        return None
    match = TAG_PATTERN.search(description)
    return match.group(0) if match else None


class CalendarClient:
    def __init__(self, client_secret_path: Path, token_path: Path) -> None:
        creds = _get_credentials(client_secret_path, token_path)
        self._service = build("calendar", "v3", credentials=creds)

    def get_or_create_calendar(self, name: str) -> str:
        calendars = self._service.calendarList().list().execute()
        for item in calendars.get("items", []):
            if item.get("summary") == name:
                return item["id"]

        created = self._service.calendars().insert(body={"summary": name}).execute()
        return created["id"]

    def list_tagged_events(self, calendar_id: str) -> list[CalendarEventSnapshot]:
        snapshots: list[CalendarEventSnapshot] = []
        page_token = None

        while True:
            result = (
                self._service.events()
                .list(
                    calendarId=calendar_id,
                    pageToken=page_token,
                    singleEvents=True,
                    maxResults=2500,
                )
                .execute()
            )

            for event in result.get("items", []):
                description = event.get("description", "")
                tag = _tag_from_description(description)
                if tag is None:
                    continue

                start_raw = event.get("start", {}).get("dateTime")
                end_raw = event.get("end", {}).get("dateTime")
                if not start_raw or not end_raw:
                    continue

                snapshots.append(
                    CalendarEventSnapshot(
                        identifier=event["id"],
                        title=event.get("summary", ""),
                        start=datetime.fromisoformat(start_raw),
                        end=datetime.fromisoformat(end_raw),
                        description=description,
                        tag=tag,
                    )
                )

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        return snapshots

    def apply(self, result: SyncResult) -> tuple[int, int]:
        calendar_id = self.get_or_create_calendar(result.calendar_name)
        created = updated = 0

        for action in result.actions:
            m = action.mutation
            body = {
                "summary": m.title,
                "description": m.description,
                "start": {"dateTime": _to_rfc3339(m.start)},
                "end": {"dateTime": _to_rfc3339(m.end)},
            }

            if action.operation == SyncOperation.create:
                self._service.events().insert(
                    calendarId=calendar_id, body=body
                ).execute()
                created += 1
            elif action.operation == SyncOperation.update and m.existing_event_id:
                self._service.events().update(
                    calendarId=calendar_id,
                    eventId=m.existing_event_id,
                    body=body,
                ).execute()
                updated += 1

        return created, updated
