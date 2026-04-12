# gradescoped

Syncs upcoming assignment due dates from Gradescope and Canvas to a Google Calendar.

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

Patterns are case-insensitive and matched against the event title (without the course name suffix).

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

Both sources write to the same calendar using a dedup tag embedded in each event's description (`gs-assignment-id:` for Gradescope, `canvas-event-id:` for Canvas). Events are created or updated on each run; nothing is ever deleted.

Each event is 1 hour long ending at the due time.

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
  sync.py            # diff logic (create/update planning)
  calendar_client.py # Google Calendar API client
gradescoped.service  # systemd one-shot unit
gradescoped.timer    # systemd timer (daily)
```
