# gradescoped

Syncs upcoming Gradescope assignment due dates to a Google Calendar.

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

[calendar]
name = "My Calendar"
term = "Spring 2026"                        # optional: only sync courses from this term
excluded_courses = ["PHYSICS 7B-LEC-002"]   # optional: skip by short name, full name, or course ID

[google]
client_secret = "~/.config/gradescoped/client_secret.json"
token = "~/.config/gradescoped/token.json"  # optional: defaults to this path
```

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

1. Logs in to Gradescope via form POST (CSRF token + session cookie)
2. Scrapes `/account` for courses, `/courses/{id}` for assignments
3. Filters to upcoming assignments (due date in the future), applying `term` and `excluded_courses` from config
4. Reads all existing events in the target calendar that contain a `gs-assignment-id:` tag in their description
5. Diffs against scraped assignments — creates new events, updates changed ones, leaves unchanged events alone
6. Each event is 1 hour long ending at the due time; the description contains the assignment URL and the dedup tag

## Project layout

```
gradescoped/
  __init__.py
  __main__.py        # entry point
  config.py          # config.toml loader
  models.py          # data types
  scraper.py         # Gradescope HTTP + HTML scraper
  sync.py            # diff logic (create/update planning)
  calendar_client.py # Google Calendar API client
gradescoped.service  # systemd one-shot unit
gradescoped.timer    # systemd timer (daily)
```
