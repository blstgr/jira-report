# Jira Report Project

This project generates an Excel roadmap report from Jira and optionally syncs it to Google Drive.

## Structure

- `app/` — Python scripts and OS wrappers
  - `jira-report.py` — core report generator (fetches Jira epics, writes roadmap.xlsx)
  - `roadmap-launcher.py` — interactive setup launcher
  - `google_drive_sync.py` — Google Drive upload/update logic
  - `run-daily-update.py` — headless daily runner (called by the scheduled job)
  - `install-daily-update.py` / `uninstall-daily-update.py` — manage the OS scheduler
- `data/` — raw Jira snapshots (JSON)
- `report/` — output Excel files (roadmap.xlsx)
- `settings/` — saved run settings (roadmap-settings.json)
- `prompts/` — roadmap spec JSON used by the generator
- `roadmap/` — additional roadmap assets

## Key env vars / config

- `JIRA_HOST` — your Jira hostname (e.g. `track.yourcompany.com`); no default, must be set
- `JIRA_KEYCHAIN_SERVICE` / `JIRA_KEYCHAIN_ACCOUNT` — keychain entry for the API token
- Settings are persisted in `settings/roadmap-settings.json` between runs

## Running the report

```bash
python app/roadmap-launcher.py   # interactive: prompts for keyword, Drive options, etc.
python app/run-daily-update.py   # headless: uses saved settings
```

## Daily scheduler

- macOS: LaunchAgent (`app/launchd/`)
- Windows: Task Scheduler

Install: `python app/install-daily-update.py`
Uninstall: `python app/uninstall-daily-update.py`

## Tests

`tests/` has two kinds of coverage:

- `test_jira_report.py`, `test_launcher.py` — pure-logic tests (keyword matching, status normalization, date parsing, `issue_rows()` lifecycle reconstruction). These stub out `openpyxl`/`PIL` entirely, so they run with the plain system `python3`:
  ```bash
  python3 -m pytest tests/
  ```
- `test_report_sheets.py` — regression tests for `build_summary_sheet` and `build_weekly_sheet` (TTM/Hold/pace math, weekly-tab week selection and sorting, the "All" feature aggregation). These call real openpyxl Workbook/Worksheet APIs that a stub can't stand in for, so they need a real openpyxl install. Use the project virtualenv (`.venv/`, gitignored — create it once with `python3 -m venv .venv && .venv/bin/pip install pytest openpyxl`):
  ```bash
  .venv/bin/python -m pytest tests/
  ```
  (this also runs the stub-based tests fine, since a stubbed-then-restored `sys.modules["openpyxl"]` doesn't affect them)

When touching `build_summary_sheet`/`build_weekly_sheet` — especially TTM/Hold/pace calculations, the on-hold row date-range semantics (a row's Start/End is the work *before* it paused, not the pause itself — see the comment in `build_summary_sheet` where `feature_active_work_dates` is built), or weekly-tab week selection/sorting — always run `test_report_sheets.py` before considering the change done. This exact set of behaviors has regressed silently multiple times.

## Jira connection

Uses Atlassian Data Center MCP (`atlassian-dc-mcp` keychain entry). If not set up, the launcher guides through OAuth setup.

## Google Drive

OAuth2 credentials live in `app/google-oauth-client-secrets.json` (not committed). Token cached in `app/google-drive-token.json`.
