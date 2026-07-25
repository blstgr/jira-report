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
