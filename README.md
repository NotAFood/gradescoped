# gradescoped

Syncs upcoming assignment due dates from Gradescope, Canvas, and Pensieve, and upcoming events from Partiful, to a Google Calendar.

## Setup

### 1. Install

```bash
uv tool install .
```

This installs the `gradescoped` binary to `~/.local/bin`, which is where the systemd service looks for it.

### 2. Create a Google Cloud OAuth client

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a project
2. Enable the **Google Calendar API**
3. Under **APIs & Services → Credentials**, create an **OAuth 2.0 Client ID** (Desktop app)
4. Download the JSON and save it somewhere, e.g. `~/.config/gradescoped/client_secret.json`

### 3. Create config

```bash
mkdir -p ~/.config/gradescoped
```

Create `~/.config/gradescoped/config.toml`:

```toml
[gradescope]
email = "you@example.com"
password = "your_password"

[canvas]
ics_url = "https://canvas.instructure.com/feeds/calendars/user_YOURTOKEN.ics"  # optional

[pensieve]
ics_url = "https://api.pensieve.co/api/calendar/YOURID.ics"  # optional
name = "CS 189"                        # short course label, prefixed onto event titles
excluded_patterns = ["Pre-Semester Survey"]  # optional

[partiful]
ics_url = "webcal://calendars.partiful.com/getCalendar?id=YOURID"  # optional
excluded_patterns = ["Weekly Standup"]  # optional: skip Partiful events whose title matches (regex)

# Optional, repeatable: sync any ICS feed (e.g. a public Google Calendar) into
# a Google Calendar of your choosing, independent of [calendar] below.
[[external_calendar]]
name = "CS 189 Instructors"
ics_url = "https://calendar.google.com/calendar/ical/cs189-instructors%40berkeley.edu/public/basic.ics"
target_calendar = "context"           # writes into this calendar, not [calendar].name
excluded_patterns = ["Office Hours"]  # optional

[calendar]
name = "My Calendar"
term = "Spring 2026"                          # optional: only sync courses from this term
excluded_courses = ["PHYSICS 7B-LEC-002"]     # optional: skip by short name, full name, or course ID
excluded_patterns = ["Final Project Week \\d+"]  # optional: skip Canvas events whose title matches (regex)

[google]
client_secret = "~/.config/gradescoped/client_secret.json"
token = "~/.config/gradescoped/token.json"    # optional: defaults to this path
```

#### Finding your Canvas ICS URL

In Canvas, go to **Calendar → Calendar Feed** (bottom-left gear icon) and copy the feed URL. It looks like `https://<institution>.instructure.com/feeds/calendars/user_<token>.ics`.

#### Filtering noisy Canvas events

Canvas publishes every assignment, including recurring weekly check-ins and milestone entries. Use `excluded_patterns` to suppress events by title using regex. For example:

```toml
excluded_patterns = ["Final Project Week \\d+", "Discussion"]
```

Patterns are case-insensitive and matched against the event title (without the course name suffix). The same mechanism works for `[pensieve] excluded_patterns`, `[partiful] excluded_patterns`, and `[[external_calendar]] excluded_patterns`.

#### Finding your Pensieve ICS URL

In Pensieve, find the calendar feed / iCal export link for the class (e.g. `https://api.pensieve.co/api/calendar/<uuid>.ics`). Unlike Canvas, Pensieve's feed doesn't include a course name on each event, so `[pensieve] name` sets the label prefixed onto every synced event's title (e.g. `[CS 189] ...`). Assignments the feed marks `STATUS:CANCELLED` (Pensieve's way of flagging something already submitted/done) are skipped automatically.

#### Finding your Partiful ICS URL

In the Partiful app, go to **Settings → Sync to Calendar** and copy the `webcal://` feed URL. It's automatically converted to `https://` when fetched.

#### Syncing an external Google Calendar (or any ICS feed) into a specific calendar

Use `[[external_calendar]]` to pull events from any public ICS feed — for example a class calendar shared by an instructor — into a Google Calendar you choose via `target_calendar`, separate from the `[calendar].name` calendar that Gradescope/Canvas/Partiful write to. You can repeat the `[[external_calendar]]` block for multiple feeds.

For a public Google Calendar, the ICS feed URL is:

```
https://calendar.google.com/calendar/ical/<calendar-id-url-encoded>/public/basic.ics
```

You can get `<calendar-id>` from the calendar's "Settings and sharing" page (or from a `cid=` subscribe link — the calendar ID is the value after `cid=`), then URL-encode it (`@` becomes `%40`). This only works for calendars whose owner has made them public.

Unlike Canvas/Partiful, this source expands recurring events (`RRULE`/`EXDATE`/overrides) properly via the `icalendar`/`recurring-ical-events` libraries, since Google's calendar export relies heavily on recurrence rather than one event per occurrence. Only occurrences in the next 90 days are synced.

### 4. Authorize Google Calendar

On first run, gradescoped prints an OAuth URL. Open it in a browser, approve access, then paste the redirect URL (or just the `code=` value) back into the terminal. The token is cached to the `token` path for all future runs.

### 5. Run

```bash
gradescoped
# or
python -m gradescoped
```

## Systemd timer (daily)

```bash
cp gradescoped.service gradescoped.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gradescoped.timer
```

Check status:

```bash
systemctl --user status gradescoped.timer
journalctl --user -u gradescoped.service -f
```

## How it works

**Gradescope:** Logs in via form POST, scrapes courses and assignments, filters to upcoming due dates.

**Canvas:** Fetches your personal ICS calendar feed, parses events, applies `excluded_patterns` to suppress noise.

**Pensieve:** Fetches the class's ICS calendar feed, parses events, skips `STATUS:CANCELLED` (already-submitted) events, prefixes titles with the configured `[pensieve] name`, and applies `excluded_patterns` to suppress noise.

**Partiful:** Fetches your personal ICS calendar feed, parses events, applies `excluded_patterns` to suppress noise.

**External calendars:** Fetches any ICS feed, expands recurring events, applies `excluded_patterns` to suppress noise, and writes to whichever calendar `target_calendar` names.

Gradescope, Canvas, Pensieve, and Partiful all write to the same `[calendar].name` calendar; each `[[external_calendar]]` writes to its own `target_calendar` instead. Every source dedupes using a tag embedded in each event's description (`gs-assignment-id:` for Gradescope, `canvas-event-id:` for Canvas, `pensieve-event-id:` for Pensieve, `partiful-event-id:` for Partiful, `gcal-event-id:` for external calendars). Events are created or updated on each run; nothing is ever deleted.

Gradescope, Canvas, and Pensieve events are 1 hour long ending at the due time. Partiful events use the actual event start/end time from the feed (falling back to a 1-hour block if the feed omits a duration).

## Development

To iterate locally without reinstalling the tool each time, run directly from the repo:

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
python -m gradescoped
```

**Important:** `uv pip install -e .` (editable install) does **not** update the `gradescoped` binary in `~/.local/bin` — that's managed separately by `uv tool install`. If you're testing changes that will run via systemd, you must reinstall after each change:

```bash
uv tool install . --force --no-cache
```

The `--no-cache` flag is required because `uv tool install` caches built wheels and will silently serve stale code otherwise. Plain `--force` alone is not sufficient.

## Project layout

```
gradescoped/
  __init__.py
  __main__.py        # entry point
  config.py          # config.toml loader
  models.py          # data types
  scraper.py         # Gradescope HTTP + HTML scraper
  canvas.py          # Canvas ICS feed fetcher and parser
  pensieve.py        # Pensieve ICS feed fetcher and parser
  partiful.py        # Partiful ICS feed fetcher and parser
  gcal_ics.py        # generic ICS feed fetcher with RRULE expansion
  sync.py            # diff logic (create/update planning)
  calendar_client.py # Google Calendar API client
gradescoped.service  # systemd one-shot unit
gradescoped.timer    # systemd timer (daily)
```
