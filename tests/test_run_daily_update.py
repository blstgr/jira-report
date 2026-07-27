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
    rdu._sync_to_drive("report/roadmap 2026.xlsx")
    fake_drive_module.assert_called_once_with(
        "report/roadmap 2026.xlsx",
        "https://drive.google.com/drive/folders/abc",
        "roadmap 2026.xlsx",
        "app/google-oauth-client-secrets.json",
    )


def test_skips_when_local_only(state_file, fake_drive_module):
    rdu.STATE = state_file(local_only=True)
    rdu._sync_to_drive("report/roadmap 2026.xlsx")
    fake_drive_module.assert_not_called()


def test_skips_when_no_drive_folder(state_file, fake_drive_module):
    rdu.STATE = state_file(drive_folder="")
    rdu._sync_to_drive("report/roadmap 2026.xlsx")
    fake_drive_module.assert_not_called()


def test_skips_when_no_client_secrets_configured(state_file, fake_drive_module):
    rdu.STATE = state_file(google_client_secrets="")
    rdu._sync_to_drive("report/roadmap 2026.xlsx")
    fake_drive_module.assert_not_called()


def test_upload_failure_does_not_raise(state_file, fake_drive_module):
    fake_drive_module.side_effect = RuntimeError("network down")
    rdu.STATE = state_file()
    rdu._sync_to_drive("report/roadmap 2026.xlsx")  # must not raise


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
    monkeypatch.setattr(rdu, "_notify", lambda message, open_url="": notified.append(message))

    rdu.main()

    assert len(notified) == 1
    assert "openpyxl" in notified[0]


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
