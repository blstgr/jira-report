#!/usr/bin/env python3
import platform
import subprocess
import sys
import threading
from time import sleep
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SYMBOLS = ["◐", "◓", "◑", "◒", "✦", "✧", "⬣", "⬢"]
TERM_WIDTH = 100
JOB_NAME = "roadmap-jira-report-update"


def spinner_line(symbol, message):
    text = f"{symbol} {message}"
    if len(text) > TERM_WIDTH - 1:
        text = text[: TERM_WIDTH - 4] + "..."
    return f"\r\x1b[2K{text}"


def run(cmd):
    subprocess.run(cmd, cwd=ROOT, check=True)


def mac_job_exists():
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    return JOB_NAME in result.stdout


def windows_job_exists():
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"if (Get-ScheduledTask -TaskName '{JOB_NAME}' -ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 1 }}",
        ],
        cwd=ROOT,
    )
    return result.returncode == 0


def run_spinner(message, work_fn):
    stop = threading.Event()

    def animate():
        idx = 0
        while not stop.is_set():
            sys.stdout.write(spinner_line(SYMBOLS[idx % len(SYMBOLS)], message))
            sys.stdout.flush()
            idx += 1
            stop.wait(0.12)

    thread = threading.Thread(target=animate, daemon=True)
    thread.start()
    try:
        return work_fn()
    finally:
        stop.set()
        thread.join(timeout=1)
        sys.stdout.write(spinner_line("✓", message) + "\n")
        sys.stdout.flush()


def main():
    system = platform.system().lower()
    if system == "darwin":
        if mac_job_exists():
            print(f"Daily updates are already installed for macOS as {JOB_NAME}.")
            return
        run_spinner("Installing daily updates on macOS...", lambda: run(["bash", "install-launchd.sh"]))
        print(f"Daily updates are installed for macOS as {JOB_NAME}.")
    elif system == "windows":
        if windows_job_exists():
            print(f"Daily updates are already installed for Windows as {JOB_NAME}.")
            return
        run_spinner(
            "Installing daily updates on Windows...",
            lambda: run([
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "install-task.ps1"),
            ]),
        )
        print(f"Daily updates are installed for Windows as {JOB_NAME}.")
    else:
        raise SystemExit(f"Unsupported platform: {system}")


if __name__ == "__main__":
    main()
