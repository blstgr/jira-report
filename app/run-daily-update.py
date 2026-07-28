#!/usr/bin/env python3
import datetime as dt
import json
import os
import re
import socket
import subprocess
import time
import sys
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception


ROOT = Path(__file__).resolve().parent
_SETTINGS_DIR = ROOT.parent / "settings"
_LOCAL = _SETTINGS_DIR / "roadmap-settings.local.json"
_TEMPLATE = _SETTINGS_DIR / "roadmap-settings.json"
STATE = _LOCAL if _LOCAL.exists() else _TEMPLATE
STAMP = ROOT / ".last-daily-run-utc"
_ATLASSIAN_DC_MCP_CONFIG = Path.home() / ".atlassian-dc-mcp" / "jira.env"


def _openpyxl_importable():
    try:
        import openpyxl  # noqa: F401
        return True
    except ImportError:
        return False


def _ensure_openpyxl():
    """jira-report.py needs openpyxl but fails at its own top-level import
    if it's missing, so check here first, under the same python executable
    it'll run under. This runs headless (launchd, no one watching) — unlike
    roadmap-launcher.py's interactive y/n version, there's no one to ask, so
    just attempt the install and log the outcome."""
    if _openpyxl_importable():
        return True
    print("[setup] openpyxl not found — installing automatically for this scheduled run...", flush=True)
    result = subprocess.run([sys.executable, "-m", "pip", "install", "openpyxl"], capture_output=True, text=True)
    if result.returncode != 0 and "externally-managed-environment" in (result.stderr or ""):
        # Homebrew's python3.11+ refuses a plain `pip install` (PEP 668) —
        # this runs unattended via launchd with no one to pick a venv/pipx
        # path instead, and this install is scoped to one pure-Python
        # package this tool already depends on, so overriding is safe here.
        print("[setup] externally-managed-environment — retrying with --break-system-packages...", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--break-system-packages", "openpyxl"],
            capture_output=True, text=True,
        )
    print(f"[setup] pip install openpyxl: rc={result.returncode}", flush=True)
    if result.returncode != 0:
        print((result.stdout or "") + (result.stderr or ""), flush=True)
        return False
    return True


def load_update_schedule():
    """Return (hour, minute, tz_name) from settings, defaulting to 08:00 UTC."""
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


def _restore_jira_host_from_settings():
    """Belt-and-suspenders: the installed launchd plist already bakes in
    JIRA_HOST directly, but if this is ever invoked another way (manually,
    or an older plist), fall back to whatever roadmap-launcher.py last
    persisted to settings rather than failing with an empty host."""
    if os.environ.get("JIRA_HOST"):
        return
    try:
        saved_host = json.loads(STATE.read_text()).get("jira_host")
    except Exception:
        saved_host = None
    if saved_host:
        os.environ["JIRA_HOST"] = saved_host


def _restore_jira_host_from_external_config():
    """Settings live inside the project folder and get wiped by a project
    re-clone; ~/.atlassian-dc-mcp/jira.env lives outside it and survives
    that, the same way the Keychain-stored token does — same reasoning as
    roadmap-launcher.py's own version of this fallback."""
    if os.environ.get("JIRA_HOST"):
        return
    try:
        for line in _ATLASSIAN_DC_MCP_CONFIG.read_text().splitlines():
            if line.startswith("JIRA_HOST="):
                host = line.split("=", 1)[1].strip()
                if host:
                    os.environ["JIRA_HOST"] = host
                return
    except Exception:
        pass


def main():
    if not STATE.exists():
        return

    _restore_jira_host_from_settings()
    _restore_jira_host_from_external_config()

    _, _, tz_name = load_update_schedule()
    today_key = local_now(tz_name).strftime("%Y-%m-%d")

    force = "--force" in sys.argv
    if not force and STAMP.exists() and STAMP.read_text().strip() == today_key:
        return

    if not _ensure_openpyxl():
        print("[setup] couldn't install openpyxl — skipping this run.", flush=True)
        # This runs headless with nobody watching ~/Library/Logs/jira-report/daily-update.log
        # — without a notification, a scheduled update can silently stop
        # working indefinitely (this exact failure mode sat unnoticed across
        # multiple days before anyone realized the report had gone stale).
        _notify("Scheduled update couldn't install a required package (openpyxl) — check the log.")
        return

    cmd = [
        sys.executable,
        str(ROOT / "jira-report.py"),
        "--state", str(STATE),
        "--update",
    ]

    _notify("Fetching updates from Jira… ☕")
    message, vpn_error, output_path = _run_update(cmd)

    if vpn_error:
        _notify("Can't reach Jira — check your VPN connection.")
        # Retry silently every 20s until midnight — fires as soon as VPN connects
        now = local_now(tz_name)
        midnight = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        deadline = midnight.timestamp()
        while dt.datetime.now().timestamp() < deadline:
            time.sleep(20)
            if not _vpn_connected():
                continue
            # VPN just came up — give it a moment to stabilize
            time.sleep(5)
            _notify("Fetching updates from Jira… ☕")
            # Try up to 3 times in case VPN is still settling
            for _attempt in range(3):
                message, vpn_error, output_path = _run_update(cmd)
                if not vpn_error:
                    break
                if _attempt < 2:
                    time.sleep(15)
            break
        if vpn_error:
            _notify("Connected to VPN but can't reach Jira — try running manually.")
            return

    drive_sync_failed = False
    if output_path:
        drive_sync_failed = _sync_to_drive(output_path) is False

    if drive_sync_failed:
        # _sync_to_drive() only ever logged this to a /tmp file nobody
        # watches — the report itself updated fine, but the user would have
        # no idea Drive was left stale until they noticed by hand.
        message = f"{message} (Drive sync failed — check the log.)"
    _notify(message)


def _sync_to_drive(output_path: str):
    """Returns True on success, False on failure, None if intentionally
    skipped (local_only, or Drive not configured)."""
    try:
        settings = json.loads(STATE.read_text())
    except Exception:
        return None
    drive_folder = settings.get("drive_folder")
    google_client_secrets = settings.get("google_client_secrets")
    if settings.get("local_only") or not drive_folder or not google_client_secrets:
        return None
    sys.path.insert(0, str(ROOT))
    try:
        from google_drive_sync import upload_or_update
        upload_or_update(output_path, drive_folder, Path(output_path).name, google_client_secrets)
        print(f"[drive] synced {output_path} to {drive_folder}", flush=True)
        return True
    except Exception as exc:
        print(f"[drive] upload failed: {exc}", flush=True)
        return False


def _notify(message: str) -> None:
    print(f"[notify] {message}", flush=True)
    uid = str(os.getuid())
    import shutil
    notifier = shutil.which("terminal-notifier") or "/opt/homebrew/bin/terminal-notifier"
    # Use launchctl asuser only when running from launchd (no controlling terminal)
    from_launchd = not sys.stdout.isatty()
    cmd = ([
        "launchctl", "asuser", uid,
    ] if from_launchd else []) + [
        notifier,
        "-message", message,
        "-title", "Jira Roadmap",
        # terminal-notifier's own identity (fr.julienxx.oss.terminal-notifier)
        # has never been granted Notification Center permission on a typical
        # Mac, so a notification posted under it is silently dropped — no
        # error, exit code still 0, it just never appears. Spoofing the
        # sender as the system's own Script Editor bundle is what actually
        # gets it displayed. This used to only apply when there was no
        # -open url (on the assumption -sender and -open didn't mix), but
        # confirmed live: the un-spoofed -open variant never even displays,
        # and -open combined with -sender displays but the click no longer
        # opens the URL (sender spoofing breaks click-through) — so there's
        # no configuration where -open actually works here. Always spoofing
        # the sender and dropping -open trades away the "click notification
        # to jump to Drive" nicety for the message reliably showing up at
        # all, which is the one that actually matters.
        "-sender", "com.apple.ScriptEditor2",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"[notify] exit={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}", flush=True)
    if r.returncode != 0:
        subprocess.run([
            "launchctl", "asuser", uid,
            "/usr/bin/osascript", "-e",
            f'display notification "{message}" with title "Jira Roadmap"'
        ])


def _vpn_connected() -> bool:
    """Check actual reachability to the configured Jira host, rather than
    inferring VPN status from network interfaces. utun/ppp interfaces can
    exist for reasons that have nothing to do with the corporate VPN —
    Personal Hotspot, iCloud Private Relay, other network extensions — and
    on one real machine a Personal Hotspot utun interface (recognizable by
    its 172.20.10.0/28 address) had an inet address the whole time, so the
    old interface-sniffing check reported "VPN connected" long before the
    real VPN was actually up. That made the retry loop below fire
    immediately, fail against the real Jira host, and give up within about
    a minute — well before the user actually finished connecting."""
    host = os.environ.get("JIRA_HOST", "").strip()
    if not host:
        return False
    try:
        with socket.create_connection((host, 443), timeout=3):
            return True
    except Exception:
        return False


def _run_update(cmd: list) -> tuple:
    """Run jira-report --update. Returns (message, vpn_error, output_path)."""
    result = subprocess.run(cmd, cwd=ROOT.parent, capture_output=True, text=True)
    output = (result.stdout or "") + (result.stderr or "")
    print(f"[update] rc={result.returncode} out={output[-300:]!r}", flush=True)
    vpn_keywords = ("timed out", "connection refused", "Operation timed out",
                    "VPN", "Cannot connect", "network is unreachable", "dropped")
    if result.returncode == 87 or any(k.lower() in output.lower() for k in vpn_keywords):
        return None, True, None  # vpn error, no message yet
    STAMP.write_text(dt.datetime.now().strftime("%Y-%m-%d"))
    path_match = re.search(r"Wrote (.+\.xlsx) —", output)
    output_path = path_match.group(1) if path_match else None
    m = re.search(r"(\d+) tasks? updated their status", output)
    if m and int(m.group(1)) > 0:
        return f"{m.group(1)} task(s) updated their status.", False, output_path
    if "All quiet" in output or result.returncode == 88 or (m and int(m.group(1)) == 0):
        return "All quiet on the Jira front. Come back when someone actually does something.", False, output_path
    if result.returncode != 0:
        # jira-report.py's own "run 'new'"/"start fresh" messages (empty
        # report, no report found, or nothing left after an edited
        # include/exclude scope) already say exactly what's wrong and what
        # to do — surfacing the generic "check the log" instead threw that
        # away and left the user digging through a /tmp log file for it.
        if "run 'new'" in output.lower() or "start fresh" in output.lower():
            return (
                "Your report file looks empty or out of sync — launch Roadmap "
                "and choose 'new' to regenerate it.",
                False, output_path,
            )
        return "Update finished with errors — check the log.", False, output_path
    return "Report updated.", False, output_path


if __name__ == "__main__":
    main()
