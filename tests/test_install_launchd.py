"""Regression test for app/install-launchd.sh.

Both scheduled launchd jobs (the daily update AND the hourly missed-update
checker) must be invoked through a wrapper script living in
~/Library/Application Scripts/jira-report/ — NOT directly out of the
project's app/ directory (which usually lives under ~/Documents or similar).
launchd can't set a working directory or exec a file straight out of a
TCC-protected folder without Full Disk Access; when that access is missing
(or gets revoked, e.g. after a macOS update), it fails silently or with
"Operation not permitted" / "cannot access parent directories" at shell
init, before the wrapped script ever runs.

This exact bug happened in production: the daily-update job was written
correctly (routed through the safe wrapper), but the missed-update-check
job's plist pointed straight at a file inside the project directory, so it
silently failed for days with no user-visible symptom until the daily
update itself was also missed with nothing left to catch it.

Run with the plain system python3 (no special dependencies needed):
    python3 -m pytest tests/test_install_launchd.py -q
"""
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
INSTALL_SCRIPT = APP_DIR / "install-launchd.sh"

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="launchd/plist tooling is macOS-only")


@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "fake-home"
    home.mkdir()
    yield home


def _run_install(fake_home):
    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    env["JIRA_REPORT_TEST_MODE"] = "1"  # skip real launchctl load/unload
    env["JIRA_HOST"] = "test.example.com"
    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"install-launchd.sh failed:\n{result.stdout}\n{result.stderr}"


def _load_plist(fake_home, label):
    path = fake_home / "Library" / "LaunchAgents" / f"{label}.plist"
    assert path.exists(), f"{path} was not generated"
    with open(path, "rb") as f:
        return plistlib.load(f)


def _safe_scripts_dir(fake_home):
    return fake_home / "Library" / "Application Scripts" / "jira-report"


def test_both_jobs_route_through_the_safe_application_scripts_wrapper(fake_home):
    _run_install(fake_home)
    safe_dir = str(_safe_scripts_dir(fake_home))

    for label in ("roadmap-jira-report-update", "roadmap-jira-report-missed-update-check"):
        plist = _load_plist(fake_home, label)

        # WorkingDirectory must be the TCC-safe wrapper dir, never the
        # project's own app/ directory.
        assert plist["WorkingDirectory"] == safe_dir, (
            f"{label}: WorkingDirectory {plist['WorkingDirectory']!r} is not the safe "
            f"Application Scripts dir — launchd can't set a cwd inside a TCC-protected "
            f"folder without Full Disk Access."
        )
        assert str(APP_DIR) not in plist["WorkingDirectory"], (
            f"{label}: WorkingDirectory must not point into the project directory"
        )

        # ProgramArguments must exec bash on a wrapper script that also lives
        # in the safe dir, not a file directly inside the project directory.
        program_args = plist["ProgramArguments"]
        assert program_args[0] == "/bin/bash", f"{label}: expected bash wrapper, got {program_args}"
        wrapper_path = program_args[1]
        assert wrapper_path.startswith(safe_dir), (
            f"{label}: wrapper {wrapper_path!r} must live under the safe Application "
            f"Scripts dir, not directly reference the project app/ directory"
        )
        assert Path(wrapper_path).exists(), f"{label}: wrapper script {wrapper_path!r} was not created"
        assert Path(wrapper_path).stat().st_mode & 0o111, f"{label}: wrapper script {wrapper_path!r} is not executable"

        # Log output must not be written inside the project directory either
        # (writing there needs the same Full Disk Access as exec/cwd do).
        for log_key in ("StandardOutPath", "StandardErrorPath"):
            assert str(APP_DIR) not in plist[log_key], (
                f"{label}: {log_key} {plist[log_key]!r} must not point into the project directory"
            )


def test_monitor_wrapper_execs_check_missed_update_with_preferred_python3(fake_home):
    _run_install(fake_home)
    monitor_path = _safe_scripts_dir(fake_home) / "monitor.sh"
    content = monitor_path.read_text()
    assert "check-missed-update.py" in content
    assert str(APP_DIR / "check-missed-update.py") in content
    # Must prefer Homebrew's python3 over the restricted Xcode-bundled
    # /usr/bin/python3 stub when available — matches the daily-update
    # wrapper's own documented reasoning.
    if Path("/opt/homebrew/bin/python3").exists():
        assert "/opt/homebrew/bin/python3" in content


def test_daily_update_wrapper_execs_run_daily_update(fake_home):
    _run_install(fake_home)
    run_path = _safe_scripts_dir(fake_home) / "run.sh"
    content = run_path.read_text()
    assert str(APP_DIR / "run-daily-update.py") in content


def test_install_does_not_touch_real_launchctl_state_in_test_mode(fake_home, monkeypatch):
    # If install-launchd.sh ever calls launchctl without checking
    # JIRA_REPORT_TEST_MODE, this replacement binary will get invoked and
    # the test fails loudly instead of silently mutating the real machine's
    # launchd state.
    fake_bin = fake_home / "fakebin"
    fake_bin.mkdir()
    launchctl_stub = fake_bin / "launchctl"
    launchctl_stub.write_text("#!/bin/bash\necho 'launchctl should not run in test mode' >&2\nexit 1\n")
    launchctl_stub.chmod(0o755)

    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    env["JIRA_REPORT_TEST_MODE"] = "1"
    env["JIRA_HOST"] = "test.example.com"
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"install-launchd.sh failed:\n{result.stdout}\n{result.stderr}"
    assert "launchctl should not run" not in result.stderr


def test_install_fails_fast_without_jira_host(fake_home):
    # The tool has no hardcoded Jira host default (removed so the public repo
    # stays company-agnostic) — installing without JIRA_HOST set must fail
    # loudly instead of silently shipping a daily job that can never reach Jira.
    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    env["JIRA_REPORT_TEST_MODE"] = "1"
    env.pop("JIRA_HOST", None)
    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "JIRA_HOST" in result.stderr
    assert not (fake_home / "Library" / "LaunchAgents").exists() or not list(
        (fake_home / "Library" / "LaunchAgents").glob("*.plist")
    )


def test_installed_plist_carries_jira_host_through(fake_home):
    _run_install(fake_home)
    plist = _load_plist(fake_home, "roadmap-jira-report-update")
    assert plist["EnvironmentVariables"]["JIRA_HOST"] == "test.example.com"
