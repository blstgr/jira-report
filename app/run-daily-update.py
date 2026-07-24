#!/usr/bin/env python3
import datetime as dt
import json
import os
import re
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


def main():
    if not STATE.exists():
        return

    _, _, tz_name = load_update_schedule()
    today_key = local_now(tz_name).strftime("%Y-%m-%d")

    force = "--force" in sys.argv
    if not force and STAMP.exists() and STAMP.read_text().strip() == today_key:
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

    if output_path:
        _sync_to_drive(output_path)

    drive_url = _drive_url()
    _notify(message, open_url=drive_url)


def _sync_to_drive(output_path: str) -> None:
    try:
        settings = json.loads(STATE.read_text())
    except Exception:
        return
    drive_folder = settings.get("drive_folder")
    google_client_secrets = settings.get("google_client_secrets")
    if settings.get("local_only") or not drive_folder or not google_client_secrets:
        return
    sys.path.insert(0, str(ROOT))
    try:
        from google_drive_sync import upload_or_update
        upload_or_update(output_path, drive_folder, Path(output_path).name, google_client_secrets)
        print(f"[drive] synced {output_path} to {drive_folder}", flush=True)
    except Exception as exc:
        print(f"[drive] upload failed: {exc}", flush=True)


def _drive_url() -> str:
    try:
        settings = json.loads(STATE.read_text())
        return settings.get("drive_folder") or ""
    except Exception:
        return ""


def _notify(message: str, open_url: str = "") -> None:
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
    ]
    if open_url:
        cmd += ["-open", open_url]
    else:
        cmd += ["-sender", "com.apple.ScriptEditor2"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"[notify] exit={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}", flush=True)
    if r.returncode != 0:
        subprocess.run([
            "launchctl", "asuser", uid,
            "/usr/bin/osascript", "-e",
            f'display notification "{message}" with title "Jira Roadmap"'
        ])


def _vpn_connected() -> bool:
    """Check local interfaces for an active VPN tunnel — no outbound traffic."""
    try:
        r = subprocess.run(["ifconfig"], capture_output=True, text=True)
        # utunN interfaces appear when a VPN tunnel is active on macOS
        import re as _re
        for block in _re.split(r'\n(?=\S)', r.stdout):
            if not _re.match(r'(utun|ppp)\d+:', block):
                continue
            if "inet " in block:
                return True
        return False
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
        return "Update finished with errors — check the log.", False, output_path
    return "Report updated.", False, output_path


if __name__ == "__main__":
    main()
