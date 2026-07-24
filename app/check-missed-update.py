#!/usr/bin/env python3
"""
Runs hourly. If the daily report was not updated by its scheduled time,
shows a macOS dialog with a Try Again button.
"""
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

ROOT = Path(__file__).resolve().parent
_SETTINGS_DIR = ROOT / "settings"
_LOCAL = _SETTINGS_DIR / "roadmap-settings.local.json"
_TEMPLATE = _SETTINGS_DIR / "roadmap-settings.json"
STATE = _LOCAL if _LOCAL.exists() else _TEMPLATE
STAMP = ROOT / ".last-daily-run-utc"


def load_schedule():
    try:
        settings = json.loads(STATE.read_text())
        time_str = (settings.get("update_time") or "08:00").strip()
        tz_name = (settings.get("update_timezone") or "UTC").strip()
        h, m = (int(x) for x in time_str.split(":", 1))
        return h, m, tz_name
    except Exception:
        return 8, 0, "UTC"


def parse_timezone(tz_name):
    """Accept IANA names (Europe/Kyiv) or offset strings (GMT+3, UTC-5, +03:00)."""
    name = (tz_name or "UTC").strip()
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, KeyError, Exception):
            pass
    m = re.match(r'^(?:GMT|UTC)?([+-])(\d{1,2})(?::(\d{2}))?$', name, re.IGNORECASE)
    if m:
        sign = 1 if m.group(1) == '+' else -1
        hours = int(m.group(2))
        minutes = int(m.group(3) or 0)
        return dt.timezone(dt.timedelta(hours=hours, minutes=minutes) * sign)
    return dt.timezone.utc


def local_now(tz_name):
    return dt.datetime.now(parse_timezone(tz_name))


def notify_and_maybe_retry():
    script = """
        set btn to button returned of (display dialog ¬
            "The roadmap report was not updated at the scheduled time." & return & ¬
            "Make sure you are connected to VPN, then try again." ¬
            buttons {"Dismiss", "Try Again"} ¬
            default button "Try Again" ¬
            with title "Jira Roadmap Update")
        if btn is "Try Again" then
            return "retry"
        end if
        return "dismiss"
    """
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True,
    )
    return result.stdout.strip() == "retry"


def run_update():
    cmd = ["python3", str(ROOT / "run-daily-update.py")]
    # Temporarily write a stale stamp so run-daily-update.py won't skip due to time check
    backup = None
    if STAMP.exists():
        backup = STAMP.read_text()
    STAMP.write_text("")
    try:
        subprocess.run(cmd, cwd=ROOT)
    finally:
        if backup is not None:
            STAMP.write_text(backup)


def main():
    if not STATE.exists():
        return

    hour, minute, tz_name = load_schedule()
    now = local_now(tz_name)
    today_key = now.strftime("%Y-%m-%d")

    # Only check if we're past the scheduled time today
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled:
        return

    # Already ran today — no alert needed
    if STAMP.exists() and STAMP.read_text().strip() == today_key:
        return

    # Missed — show the dialog
    retry = notify_and_maybe_retry()
    if retry:
        # Force run-daily-update to execute by running jira-report directly
        cmd = ["python3", str(ROOT / "jira-report.py"), "--state", str(STATE)]
        result = subprocess.run(cmd, cwd=ROOT)
        if result.returncode == 0:
            STAMP.write_text(today_key)


if __name__ == "__main__":
    main()
