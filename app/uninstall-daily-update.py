#!/usr/bin/env python3
import platform
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(cmd):
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    system = platform.system().lower()
    if system == "darwin":
        run(["bash", "uninstall-launchd.sh"])
        print("Daily updates are removed on macOS.")
    elif system == "windows":
        run([
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "uninstall-task.ps1"),
        ])
        print("Daily updates are removed on Windows.")
    else:
        raise SystemExit(f"Unsupported platform: {system}")


if __name__ == "__main__":
    main()
