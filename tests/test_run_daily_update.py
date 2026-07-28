"""
Tests for run-daily-update.py's Drive-sync wiring.

Regression coverage for a real bug: the headless daily job wrote the local
report but never actually called the Drive upload function — it only ever
built a URL string for the desktop notification. These tests exercise
_sync_to_drive() directly so that gap can't silently reappear.

Run with:  python3 -m pytest tests/test_run_daily_update.py -q
"""
import sys
import types
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
spec = importlib.util.spec_from_file_location("rdu", APP_DIR / "run-daily-update.py")
rdu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rdu)


@pytest.fixture
def state_file(tmp_path):
    def _write(**overrides):
        settings = {
            "drive_folder": "https://drive.google.com/drive/folders/abc",
            "google_client_secrets": "app/google-oauth-client-secrets.json",
            "local_only": False,
        }
        settings.update(overrides)
        path = tmp_path / "roadmap-settings.local.json"
        path.write_text(json.dumps(settings))
        return path
    return _write


@pytest.fixture(autouse=True)
def fake_drive_module(monkeypatch):
    mock_upload = MagicMock(return_value={"webViewLink": "https://drive.google.com/file/x"})
    fake_mod = types.ModuleType("google_drive_sync")
    fake_mod.upload_or_update = mock_upload
    monkeypatch.setitem(sys.modules, "google_drive_sync", fake_mod)
    return mock_upload


def test_syncs_when_fully_configured(state_file, fake_drive_module):
    rdu.STATE = state_file()
    assert rdu._sync_to_drive("report/roadmap 2026.xlsx") is True
    fake_drive_module.assert_called_once_with(
        "report/roadmap 2026.xlsx",
        "https://drive.google.com/drive/folders/abc",
        "roadmap 2026.xlsx",
        "app/google-oauth-client-secrets.json",
    )


def test_skips_when_local_only(state_file, fake_drive_module):
    rdu.STATE = state_file(local_only=True)
    assert rdu._sync_to_drive("report/roadmap 2026.xlsx") is None
    fake_drive_module.assert_not_called()


def test_skips_when_no_drive_folder(state_file, fake_drive_module):
    rdu.STATE = state_file(drive_folder="")
    assert rdu._sync_to_drive("report/roadmap 2026.xlsx") is None
    fake_drive_module.assert_not_called()


def test_skips_when_no_client_secrets_configured(state_file, fake_drive_module):
    rdu.STATE = state_file(google_client_secrets="")
    assert rdu._sync_to_drive("report/roadmap 2026.xlsx") is None
    fake_drive_module.assert_not_called()


def test_upload_failure_does_not_raise(state_file, fake_drive_module):
    fake_drive_module.side_effect = RuntimeError("network down")
    rdu.STATE = state_file()
    assert rdu._sync_to_drive("report/roadmap 2026.xlsx") is False  # must not raise


def test_ensure_openpyxl_already_importable_does_not_attempt_install():
    with patch.object(rdu, "_openpyxl_importable", return_value=True), \
         patch.object(rdu.subprocess, "run") as fake_run:
        assert rdu._ensure_openpyxl() is True
    fake_run.assert_not_called()


def test_ensure_openpyxl_missing_installs_silently_no_prompt():
    # This runs headless via launchd — there's no one to answer a y/n
    # prompt, so it must just attempt the install directly.
    success = MagicMock(returncode=0, stdout="", stderr="")
    with patch.object(rdu, "_openpyxl_importable", return_value=False), \
         patch.object(rdu.subprocess, "run", return_value=success) as fake_run:
        assert rdu._ensure_openpyxl() is True
    args = fake_run.call_args[0][0]
    assert args == [rdu.sys.executable, "-m", "pip", "install", "openpyxl"]


def test_ensure_openpyxl_missing_install_fails_returns_false():
    fail = MagicMock(returncode=1, stdout="", stderr="no network")
    with patch.object(rdu, "_openpyxl_importable", return_value=False), \
         patch.object(rdu.subprocess, "run", return_value=fail):
        assert rdu._ensure_openpyxl() is False


def test_ensure_openpyxl_retries_with_break_system_packages_on_pep668():
    # Regression: Homebrew's python3.11+ refuses a plain `pip install`
    # under PEP 668 ("externally-managed-environment") — a real scheduled
    # run hit exactly this and silently failed every day with nobody
    # noticing, since the only visible trace was a line in a /tmp log file.
    pep668_fail = MagicMock(returncode=1, stdout="", stderr="error: externally-managed-environment\n...")
    success = MagicMock(returncode=0, stdout="", stderr="")
    with patch.object(rdu, "_openpyxl_importable", return_value=False), \
         patch.object(rdu.subprocess, "run", side_effect=[pep668_fail, success]) as fake_run:
        assert rdu._ensure_openpyxl() is True
    assert fake_run.call_count == 2
    second_call_args = fake_run.call_args_list[1][0][0]
    assert second_call_args == [rdu.sys.executable, "-m", "pip", "install", "--break-system-packages", "openpyxl"]


def test_ensure_openpyxl_pep668_retry_still_fails_returns_false():
    pep668_fail = MagicMock(returncode=1, stdout="", stderr="error: externally-managed-environment\n...")
    still_fails = MagicMock(returncode=1, stdout="", stderr="permission denied")
    with patch.object(rdu, "_openpyxl_importable", return_value=False), \
         patch.object(rdu.subprocess, "run", side_effect=[pep668_fail, still_fails]) as fake_run:
        assert rdu._ensure_openpyxl() is False
    assert fake_run.call_count == 2


def test_ensure_openpyxl_non_pep668_failure_does_not_retry():
    fail = MagicMock(returncode=1, stdout="", stderr="no network")
    with patch.object(rdu, "_openpyxl_importable", return_value=False), \
         patch.object(rdu.subprocess, "run", return_value=fail) as fake_run:
        assert rdu._ensure_openpyxl() is False
    assert fake_run.call_count == 1


def _tripwire(name):
    def _raise(*a, **kw):
        raise AssertionError(f"{name} should not have been called")
    return _raise


def test_main_skips_silently_when_already_updated_today(tmp_path, monkeypatch):
    # This is the exact guard that made a correctly-firing scheduled job
    # look like nothing happened: if today's report already updated once,
    # main() returns immediately with zero notification and zero log
    # output. Confirmed real: editing the schedule time to a near-future
    # minute, the job fired right on time, hit this guard, and exited
    # clean — which looked indistinguishable from "the schedule is broken"
    # until the stamp file was checked.
    state_path = tmp_path / "roadmap-settings.local.json"
    state_path.write_text(json.dumps({"update_time": "08:00", "update_timezone": "UTC"}))
    monkeypatch.setattr(rdu, "STATE", state_path)
    stamp_path = tmp_path / ".last-daily-run-utc"
    today_key = rdu.local_now("UTC").strftime("%Y-%m-%d")
    stamp_path.write_text(today_key)
    monkeypatch.setattr(rdu, "STAMP", stamp_path)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_settings", lambda: None)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_external_config", lambda: None)
    monkeypatch.setattr(rdu, "_ensure_openpyxl", _tripwire("_ensure_openpyxl"))
    monkeypatch.setattr(rdu, "_run_update", _tripwire("_run_update"))
    monkeypatch.setattr(rdu, "_notify", _tripwire("_notify"))
    monkeypatch.setattr(sys, "argv", ["run-daily-update.py"])

    rdu.main()  # must return without touching any of the tripwires above


def test_main_force_flag_bypasses_the_already_ran_today_guard(tmp_path, monkeypatch):
    state_path = tmp_path / "roadmap-settings.local.json"
    state_path.write_text(json.dumps({"update_time": "08:00", "update_timezone": "UTC"}))
    monkeypatch.setattr(rdu, "STATE", state_path)
    stamp_path = tmp_path / ".last-daily-run-utc"
    stamp_path.write_text(rdu.local_now("UTC").strftime("%Y-%m-%d"))
    monkeypatch.setattr(rdu, "STAMP", stamp_path)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_settings", lambda: None)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_external_config", lambda: None)
    monkeypatch.setattr(rdu, "_ensure_openpyxl", lambda: True)
    monkeypatch.setattr(rdu, "_run_update", lambda cmd: ("Report updated.", False, None))
    monkeypatch.setattr(sys, "argv", ["run-daily-update.py", "--force"])
    notified = []
    monkeypatch.setattr(rdu, "_notify", lambda message: notified.append(message))

    rdu.main()

    assert notified == ["Fetching updates from Jira… ☕", "Report updated."]


def test_main_happy_path_notifies_fetching_then_result(tmp_path, monkeypatch):
    # Plain successful run, no Drive, no VPN trouble — the baseline case
    # that must keep working underneath all the edge-case handling above.
    state_path = tmp_path / "roadmap-settings.local.json"
    state_path.write_text(json.dumps({"update_time": "08:00", "update_timezone": "UTC"}))
    monkeypatch.setattr(rdu, "STATE", state_path)
    stamp_path = tmp_path / ".last-daily-run-utc"
    monkeypatch.setattr(rdu, "STAMP", stamp_path)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_settings", lambda: None)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_external_config", lambda: None)
    monkeypatch.setattr(rdu, "_ensure_openpyxl", lambda: True)
    monkeypatch.setattr(
        rdu, "_run_update",
        lambda cmd: ("All quiet on the Jira front. Come back when someone actually does something.", False, None),
    )
    monkeypatch.setattr(sys, "argv", ["run-daily-update.py"])
    notified = []
    monkeypatch.setattr(rdu, "_notify", lambda message: notified.append(message))

    rdu.main()

    assert notified == [
        "Fetching updates from Jira… ☕",
        "All quiet on the Jira front. Come back when someone actually does something.",
    ]


def test_main_vpn_retry_loop_succeeds_once_vpn_reconnects(tmp_path, monkeypatch):
    # The retry-until-midnight loop: first attempt hits a VPN error, then
    # _vpn_connected() reports back up, then the retried _run_update call
    # succeeds. Uses a fake clock/sleep so this doesn't actually wait.
    state_path = tmp_path / "roadmap-settings.local.json"
    state_path.write_text(json.dumps({"update_time": "08:00", "update_timezone": "UTC"}))
    monkeypatch.setattr(rdu, "STATE", state_path)
    stamp_path = tmp_path / ".last-daily-run-utc"
    monkeypatch.setattr(rdu, "STAMP", stamp_path)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_settings", lambda: None)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_external_config", lambda: None)
    monkeypatch.setattr(rdu, "_ensure_openpyxl", lambda: True)
    monkeypatch.setattr(rdu.time, "sleep", lambda seconds: None)

    call_results = iter([
        (None, True, None),              # initial attempt: VPN down
        ("Report updated.", False, None),  # retry after VPN reconnects: succeeds
    ])
    monkeypatch.setattr(rdu, "_run_update", lambda cmd: next(call_results))
    monkeypatch.setattr(rdu, "_vpn_connected", lambda: True)  # reconnected on first poll
    monkeypatch.setattr(sys, "argv", ["run-daily-update.py"])
    notified = []
    monkeypatch.setattr(rdu, "_notify", lambda message: notified.append(message))

    rdu.main()

    assert notified == [
        "Fetching updates from Jira… ☕",
        "Can't reach Jira — check your VPN connection.",
        "Fetching updates from Jira… ☕",
        "Report updated.",
    ]


def test_main_vpn_retry_loop_gives_up_if_still_unreachable(tmp_path, monkeypatch):
    state_path = tmp_path / "roadmap-settings.local.json"
    state_path.write_text(json.dumps({"update_time": "08:00", "update_timezone": "UTC"}))
    monkeypatch.setattr(rdu, "STATE", state_path)
    stamp_path = tmp_path / ".last-daily-run-utc"
    monkeypatch.setattr(rdu, "STAMP", stamp_path)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_settings", lambda: None)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_external_config", lambda: None)
    monkeypatch.setattr(rdu, "_ensure_openpyxl", lambda: True)
    monkeypatch.setattr(rdu.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rdu, "_run_update", lambda cmd: (None, True, None))  # always VPN error
    monkeypatch.setattr(rdu, "_vpn_connected", lambda: True)
    monkeypatch.setattr(sys, "argv", ["run-daily-update.py"])
    notified = []
    monkeypatch.setattr(rdu, "_notify", lambda message: notified.append(message))

    rdu.main()

    assert notified[-1] == "Connected to VPN but can't reach Jira — try running manually."


def test_main_appends_drive_sync_failure_note_to_notification(tmp_path, monkeypatch):
    # Regression: _sync_to_drive()'s failures only ever got logged to
    # /tmp/jira-report-launchd.log — a file nobody watches. The report
    # itself updates fine, but Drive silently goes stale with zero visible
    # signal unless the user happens to check the log by hand.
    state_path = tmp_path / "roadmap-settings.local.json"
    state_path.write_text(json.dumps({"update_time": "08:00", "update_timezone": "UTC"}))
    monkeypatch.setattr(rdu, "STATE", state_path)
    stamp_path = tmp_path / ".last-daily-run-utc"
    monkeypatch.setattr(rdu, "STAMP", stamp_path)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_settings", lambda: None)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_external_config", lambda: None)
    monkeypatch.setattr(rdu, "_ensure_openpyxl", lambda: True)
    monkeypatch.setattr(rdu, "_run_update", lambda cmd: ("Report updated.", False, "report/roadmap 2026.xlsx"))
    monkeypatch.setattr(rdu, "_sync_to_drive", lambda output_path: False)
    monkeypatch.setattr(sys, "argv", ["run-daily-update.py"])
    notified = []
    monkeypatch.setattr(rdu, "_notify", lambda message: notified.append(message))

    rdu.main()

    assert "Drive sync failed" in notified[-1]


def test_main_does_not_append_drive_note_when_sync_skipped_intentionally(tmp_path, monkeypatch):
    # _sync_to_drive() returns None (not False) when Drive isn't configured
    # or local_only is set — that's an intentional skip, not a failure, and
    # must not get flagged as one.
    state_path = tmp_path / "roadmap-settings.local.json"
    state_path.write_text(json.dumps({"update_time": "08:00", "update_timezone": "UTC"}))
    monkeypatch.setattr(rdu, "STATE", state_path)
    stamp_path = tmp_path / ".last-daily-run-utc"
    monkeypatch.setattr(rdu, "STAMP", stamp_path)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_settings", lambda: None)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_external_config", lambda: None)
    monkeypatch.setattr(rdu, "_ensure_openpyxl", lambda: True)
    monkeypatch.setattr(rdu, "_run_update", lambda cmd: ("Report updated.", False, "report/roadmap 2026.xlsx"))
    monkeypatch.setattr(rdu, "_sync_to_drive", lambda output_path: None)
    monkeypatch.setattr(sys, "argv", ["run-daily-update.py"])
    notified = []
    monkeypatch.setattr(rdu, "_notify", lambda message: notified.append(message))

    rdu.main()

    assert "Drive sync failed" not in notified[-1]


def test_main_notifies_when_openpyxl_cannot_be_installed(tmp_path, monkeypatch):
    # Regression: this used to just print to a log file nobody watches and
    # return — a scheduled update could silently stop working indefinitely.
    state_path = tmp_path / "roadmap-settings.local.json"
    state_path.write_text(json.dumps({"update_time": "08:00", "update_timezone": "UTC"}))
    monkeypatch.setattr(rdu, "STATE", state_path)
    stamp_path = tmp_path / ".last-daily-run-utc"
    monkeypatch.setattr(rdu, "STAMP", stamp_path)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_settings", lambda: None)
    monkeypatch.setattr(rdu, "_restore_jira_host_from_external_config", lambda: None)
    monkeypatch.setattr(rdu, "_ensure_openpyxl", lambda: False)
    monkeypatch.setattr(sys, "argv", ["run-daily-update.py"])
    notified = []
    monkeypatch.setattr(rdu, "_notify", lambda message: notified.append(message))

    rdu.main()

    assert len(notified) == 1
    assert "openpyxl" in notified[0]


def test_notify_always_spoofs_a_registered_sender(monkeypatch):
    # Regression, confirmed live on a real machine: terminal-notifier's own
    # identity (fr.julienxx.oss.terminal-notifier) has never been granted
    # Notification Center permission, so a notification posted under it is
    # silently dropped — exit code still 0, it just never displays. This
    # used to only spoof -sender when there was no click-to-open URL;
    # dropping that URL feature entirely (see below) means -sender must
    # always be present or notifications silently stop appearing again.
    captured_cmds = []
    monkeypatch.setattr(
        rdu.subprocess, "run",
        lambda cmd, **kw: (captured_cmds.append(cmd) or MagicMock(returncode=0, stdout="", stderr="")),
    )
    monkeypatch.setattr(rdu.sys.stdout, "isatty", lambda: True)
    rdu._notify("hello")
    assert "-sender" in captured_cmds[0]
    assert "com.apple.ScriptEditor2" in captured_cmds[0]


def test_notify_no_longer_passes_open_url():
    # Regression: -open combined with the spoofed -sender does display, but
    # confirmed live it no longer opens the URL on click (sender spoofing
    # breaks click-through), and without spoofing it never displays at all
    # — no configuration makes -open actually work, so _notify() no longer
    # accepts it at all instead of silently ignoring a dead parameter.
    import inspect
    assert "open_url" not in inspect.signature(rdu._notify).parameters


def test_restore_jira_host_from_settings_when_env_unset(state_file, monkeypatch):
    monkeypatch.delenv("JIRA_HOST", raising=False)
    rdu.STATE = state_file(jira_host="track.example.com")
    rdu._restore_jira_host_from_settings()
    assert rdu.os.environ["JIRA_HOST"] == "track.example.com"


def test_restore_jira_host_from_settings_does_not_override_existing_env(state_file, monkeypatch):
    monkeypatch.setenv("JIRA_HOST", "already-set.example.com")
    rdu.STATE = state_file(jira_host="track.example.com")
    rdu._restore_jira_host_from_settings()
    assert rdu.os.environ["JIRA_HOST"] == "already-set.example.com"


def test_restore_jira_host_from_settings_handles_missing_or_bad_state(monkeypatch, tmp_path):
    monkeypatch.delenv("JIRA_HOST", raising=False)
    rdu.STATE = tmp_path / "does-not-exist.json"
    rdu._restore_jira_host_from_settings()  # must not raise
    assert "JIRA_HOST" not in rdu.os.environ


def test_restore_jira_host_from_external_config_when_settings_missing(tmp_path, monkeypatch):
    # Same fallback as roadmap-launcher.py's version: settings live inside
    # the project folder and get wiped by a re-clone, but this file lives
    # under the user's home directory and survives that.
    monkeypatch.delenv("JIRA_HOST", raising=False)
    config_path = tmp_path / ".atlassian-dc-mcp" / "jira.env"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("JIRA_HOST=track.example.com\n")
    monkeypatch.setattr(rdu, "_ATLASSIAN_DC_MCP_CONFIG", config_path)
    rdu._restore_jira_host_from_external_config()
    assert rdu.os.environ["JIRA_HOST"] == "track.example.com"


def test_restore_jira_host_from_external_config_does_not_override_existing_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JIRA_HOST", "already-set.example.com")
    config_path = tmp_path / ".atlassian-dc-mcp" / "jira.env"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("JIRA_HOST=track.example.com\n")
    monkeypatch.setattr(rdu, "_ATLASSIAN_DC_MCP_CONFIG", config_path)
    rdu._restore_jira_host_from_external_config()
    assert rdu.os.environ["JIRA_HOST"] == "already-set.example.com"


def test_restore_jira_host_from_external_config_no_op_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("JIRA_HOST", raising=False)
    monkeypatch.setattr(rdu, "_ATLASSIAN_DC_MCP_CONFIG", tmp_path / "does-not-exist" / "jira.env")
    rdu._restore_jira_host_from_external_config()
    assert "JIRA_HOST" not in rdu.os.environ


def test_run_update_surfaces_empty_report_as_an_actionable_message(tmp_path, monkeypatch):
    # Regression: jira-report.py's own "Existing report is empty — run 'new'
    # first." already says exactly what's wrong and what to do — the
    # generic "Update finished with errors — check the log." fallback threw
    # that away, leaving the user digging through a /tmp log file to find
    # out their report needed regenerating.
    monkeypatch.setattr(rdu, "STAMP", tmp_path / ".last-daily-run-utc")
    result = MagicMock(
        returncode=1,
        stdout="Existing report is empty — run 'new' first.\n",
        stderr="",
    )
    with patch.object(rdu.subprocess, "run", return_value=result):
        message, vpn_error, output_path = rdu._run_update(["cmd"])
    assert vpn_error is False
    assert "run 'new'" not in message  # rephrased for the user, not just echoed
    assert "new" in message.lower()


def test_run_update_surfaces_no_report_found_as_an_actionable_message(tmp_path, monkeypatch):
    monkeypatch.setattr(rdu, "STAMP", tmp_path / ".last-daily-run-utc")
    result = MagicMock(
        returncode=1,
        stdout="No existing report found — run 'new' first.\n",
        stderr="",
    )
    with patch.object(rdu.subprocess, "run", return_value=result):
        message, vpn_error, output_path = rdu._run_update(["cmd"])
    assert "regenerate" in message.lower()


def test_run_update_surfaces_scope_exhausted_as_an_actionable_message(tmp_path, monkeypatch):
    monkeypatch.setattr(rdu, "STAMP", tmp_path / ".last-daily-run-utc")
    result = MagicMock(
        returncode=1,
        stdout=(
            "Nothing in the existing report matches the current include/exclude "
            "keywords anymore. Double-check your keywords, or run 'new' to start fresh.\n"
        ),
        stderr="",
    )
    with patch.object(rdu.subprocess, "run", return_value=result):
        message, vpn_error, output_path = rdu._run_update(["cmd"])
    assert "regenerate" in message.lower()


def test_run_update_generic_error_still_falls_back_to_check_the_log(tmp_path, monkeypatch):
    # Confirms the fix is scoped to the known "run 'new'"/"start fresh"
    # cases specifically — a genuinely unexpected crash should still point
    # at the log rather than guessing at a specific cause.
    monkeypatch.setattr(rdu, "STAMP", tmp_path / ".last-daily-run-utc")
    result = MagicMock(returncode=1, stdout="Traceback (most recent call last):\nboom\n", stderr="")
    with patch.object(rdu.subprocess, "run", return_value=result):
        message, vpn_error, output_path = rdu._run_update(["cmd"])
    assert message == "Update finished with errors — check the log."


def test_vpn_connected_checks_real_jira_reachability_not_interfaces(monkeypatch):
    # Regression: the old implementation sniffed `ifconfig` for any utun/ppp
    # interface with an inet address — but those exist for reasons that have
    # nothing to do with the corporate VPN (Personal Hotspot's utun has a
    # 172.20.10.0/28 address, iCloud Private Relay, other network
    # extensions), so it reported "VPN connected" long before the real VPN
    # was actually up. This checks real reachability to JIRA_HOST instead.
    monkeypatch.setenv("JIRA_HOST", "track.example.com")
    with patch.object(rdu.socket, "create_connection") as fake_connect:
        fake_connect.return_value.__enter__ = lambda self: self
        fake_connect.return_value.__exit__ = lambda self, *a: None
        assert rdu._vpn_connected() is True
    fake_connect.assert_called_once_with(("track.example.com", 443), timeout=3)


def test_vpn_connected_false_when_host_unreachable(monkeypatch):
    monkeypatch.setenv("JIRA_HOST", "track.example.com")
    with patch.object(rdu.socket, "create_connection", side_effect=OSError("timed out")):
        assert rdu._vpn_connected() is False


def test_vpn_connected_false_when_no_jira_host_configured(monkeypatch):
    monkeypatch.delenv("JIRA_HOST", raising=False)
    assert rdu._vpn_connected() is False
