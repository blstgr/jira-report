"""
Tests for roadmap-launcher.py flows and pure logic.

Run with:  python3 tests/test_launcher.py
"""
import sys
import types
import importlib.util
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── stub external deps before loading the module ──────────────────────────
for mod in ["google_drive_sync"]:
    m = types.ModuleType(mod)
    m.authorize = lambda *a, **kw: None
    m.is_placeholder_client_config = lambda *a, **kw: False
    m.upload_or_update = lambda *a, **kw: {}
    sys.modules[mod] = m

APP_DIR = Path(__file__).resolve().parents[1] / "app"
spec = importlib.util.spec_from_file_location("launcher", APP_DIR / "roadmap-launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.fixture(autouse=True)
def _isolate_atlassian_dc_mcp_config(tmp_path, monkeypatch):
    # run_jira_setup() calls _preseed_jira_setup_config(), which writes to
    # this path if absent — never let any test touch the real home
    # directory's copy, regardless of whether that specific test cares
    # about pre-seeding.
    monkeypatch.setattr(launcher, "_ATLASSIAN_DC_MCP_CONFIG", tmp_path / ".atlassian-dc-mcp" / "jira.env")

TEMPLATE_CONTENT = json.dumps({
    "features": [{"keyword": "Your feature name or epic keyword", "eta": "2026-01-01", "expected_pace": 5}],
    "exclude": ["keyword to exclude"],
    "project_keys": ["SSLP"],
    "output": "report/roadmap 2026.xlsx",
    "drive_folder": "",
    "google_client_secrets": "app/google-oauth-client-secrets.json",
    "local_only": True,
    "update_time": "08:00",
    "update_timezone": "UTC",
    "_auto_generated": {}
}, indent=2)

REAL_SETTINGS = json.dumps({
    "features": [{"keyword": "CA switch", "eta": "2026-07-11"}],
    "exclude": [],
    "project_keys": ["SSLP"],
    "output": "report/roadmap 2026.xlsx",
    "drive_folder": "",
    "local_only": True,
    "update_time": "15:00",
    "update_timezone": "Europe/Kyiv",
    "auto_update": True,
}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# has_settings detection
# ═══════════════════════════════════════════════════════════════════════════

def test_has_settings_no_file():
    """No local file → go straight to wizard, no menu."""
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "roadmap-settings.local.json"
        template_path = Path(tmp) / "roadmap-settings.json"
        template_path.write_text(TEMPLATE_CONTENT)
        local_content = state_path.read_text().strip() if state_path.exists() else None
        template_content = template_path.read_text().strip()
        has_settings = bool(local_content and local_content != template_content)
        assert not has_settings, "Should be False when local file doesn't exist"


def test_has_settings_file_equals_template():
    """Local file = template (just copied on startup) → no menu, go to wizard."""
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "roadmap-settings.local.json"
        template_path = Path(tmp) / "roadmap-settings.json"
        template_path.write_text(TEMPLATE_CONTENT)
        state_path.write_text(TEMPLATE_CONTENT)
        local_content = state_path.read_text().strip()
        template_content = template_path.read_text().strip()
        has_settings = bool(local_content and local_content != template_content)
        assert not has_settings, "Template-seeded file should not count as real settings"


def test_has_settings_real_settings():
    """Local file differs from template → show menu."""
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "roadmap-settings.local.json"
        template_path = Path(tmp) / "roadmap-settings.json"
        template_path.write_text(TEMPLATE_CONTENT)
        state_path.write_text(REAL_SETTINGS)
        local_content = state_path.read_text().strip()
        template_content = template_path.read_text().strip()
        has_settings = bool(local_content and local_content != template_content)
        assert has_settings, "Real settings should show the menu"


# ═══════════════════════════════════════════════════════════════════════════
# prompt_existing_report_action
# ═══════════════════════════════════════════════════════════════════════════

def _action(inputs):
    """Run prompt_existing_report_action with fake stdin inputs."""
    with patch("builtins.input", side_effect=inputs):
        return launcher.prompt_existing_report_action()


def test_action_new():
    assert _action(["new"]) == ("new", False, None)


def test_action_edit():
    assert _action(["edit"]) == ("edit", False, None)


def test_action_update():
    assert _action(["update"]) == ("update", False, None)


def test_action_update_with_keyword():
    action, cache, pattern = _action(["update ca switch"])
    assert action == "update"
    assert pattern == "ca switch"
    assert not cache


def test_action_update_cache_flag():
    action, cache, pattern = _action(["update --cache"])
    assert action == "update"
    assert cache is True


def test_action_quit():
    assert _action(["q"]) == ("quit", False, None)
    assert _action(["quit"]) == ("quit", False, None)
    assert _action(["exit"]) == ("quit", False, None)


def test_action_invalid_then_valid():
    """Invalid input should loop until valid — not crash."""
    action, _, _ = _action(["nonsense", "banana 42", "new"])
    assert action == "new"


def test_action_upd_shorthand():
    action, _, _ = _action(["upd"])
    assert action == "update"


# ═══════════════════════════════════════════════════════════════════════════
# _prompt_edit_section
# ═══════════════════════════════════════════════════════════════════════════

def _edit_section(inputs):
    with patch("builtins.input", side_effect=inputs):
        return launcher._prompt_edit_section()


def test_edit_section_all_explicit():
    assert _edit_section(["all"]) == "all"


def test_edit_section_all_empty_default():
    assert _edit_section([""]) == "all"


def test_edit_section_keyword():
    assert _edit_section(["keyword"]) == "keyword"
    assert _edit_section(["keywords"]) == "keyword"


def test_edit_section_jira_key():
    assert _edit_section(["jira key"]) == "jira key"
    assert _edit_section(["jira"]) == "jira key"


def test_edit_section_eta():
    assert _edit_section(["eta"]) == "keyword eta"
    assert _edit_section(["keyword eta"]) == "keyword eta"


def test_edit_section_url():
    assert _edit_section(["url"]) == "url"
    assert _edit_section(["drive"]) == "url"


def test_edit_section_time():
    assert _edit_section(["time"]) == "time"
    assert _edit_section(["timezone"]) == "time"


def test_edit_section_invalid_then_valid():
    """Unknown section should re-prompt, not crash."""
    assert _edit_section(["vibes", "time"]) == "time"


# ═══════════════════════════════════════════════════════════════════════════
# parse_freeform_date
# ═══════════════════════════════════════════════════════════════════════════

import datetime as dt

def test_date_iso():
    assert launcher.parse_freeform_date("2026-07-11") == dt.date(2026, 7, 11)


def test_date_dd_mmm_yyyy():
    """11-Jul-2026 — the format shown in the prompt hint, must parse."""
    assert launcher.parse_freeform_date("11-Jul-2026") == dt.date(2026, 7, 11)


def test_date_dd_mmm_yy():
    assert launcher.parse_freeform_date("11-Jul-26") == dt.date(2026, 7, 11)


def test_date_natural():
    assert launcher.parse_freeform_date("Jul 11, 2026") == dt.date(2026, 7, 11)


def test_date_space_separated():
    assert launcher.parse_freeform_date("11 Jul 2026") == dt.date(2026, 7, 11)


def test_date_garbage():
    assert launcher.parse_freeform_date("not a date") is None
    assert launcher.parse_freeform_date("") is None
    assert launcher.parse_freeform_date(None) is None


def test_date_number_only():
    assert launcher.parse_freeform_date("42") is None


# ═══════════════════════════════════════════════════════════════════════════
# sanitize helpers
# ═══════════════════════════════════════════════════════════════════════════

def test_sanitize_keyword_values_strips_and_dedupes():
    result = launcher.sanitize_keyword_values(["CA switch ", " ca switch", "Edge"])
    assert result == ["CA switch", "ca switch", "Edge"]


def test_sanitize_keyword_values_removes_empty():
    result = launcher.sanitize_keyword_values(["", "  ", "valid"])
    assert result == ["valid"]


def test_sanitize_keyword_values_none():
    assert launcher.sanitize_keyword_values(None) == []


def test_sanitize_expected_tasks_per_week_valid():
    result = launcher.sanitize_expected_tasks_per_week({"CA switch": "3.5", "Edge": 2})
    assert result == {"CA switch": 3.5, "Edge": 2.0}


def test_sanitize_expected_tasks_per_week_rejects_zero_and_negative():
    result = launcher.sanitize_expected_tasks_per_week({"bad": "0", "worse": "-1", "good": "1"})
    assert "bad" not in result
    assert "worse" not in result
    assert result["good"] == 1.0


def test_sanitize_expected_tasks_per_week_rejects_non_numeric():
    result = launcher.sanitize_expected_tasks_per_week({"x": "abc", "y": None})
    assert result == {}


# ═══════════════════════════════════════════════════════════════════════════
# parse_update_time
# ═══════════════════════════════════════════════════════════════════════════

def test_parse_update_time_hhmm():
    assert launcher.parse_update_time("15:00") == (15, 0)
    assert launcher.parse_update_time("08:30") == (8, 30)


def test_parse_update_time_invalid():
    assert launcher.parse_update_time("banana") is None
    assert launcher.parse_update_time("25:00") is None
    assert launcher.parse_update_time("") is None


def test_detect_system_timezone_uses_iana_name_from_localtime():
    with patch("os.path.realpath", return_value="/usr/share/zoneinfo/Europe/Kyiv"):
        assert launcher._detect_system_timezone() == "Europe/Kyiv"


def test_detect_system_timezone_falls_back_to_utc_offset():
    fake_now = launcher.dt.datetime(2026, 1, 1, tzinfo=launcher.dt.timezone(launcher.dt.timedelta(hours=3)))
    with patch("os.path.realpath", return_value="/etc/localtime"), \
         patch.object(launcher.dt, "datetime") as fake_datetime:
        fake_datetime.now.return_value.astimezone.return_value = fake_now
        assert launcher._detect_system_timezone() == "+03:00"


def test_trim_to_hostname_bare_hostname_unchanged():
    assert launcher._trim_to_hostname("track.namecheap.net") == "track.namecheap.net"


def test_trim_to_hostname_strips_scheme_and_path():
    assert launcher._trim_to_hostname("https://track.namecheap.net/browse/SSLP-123") == "track.namecheap.net"


def test_trim_to_hostname_strips_query_string_via_path_split():
    assert launcher._trim_to_hostname("https://track.namecheap.net/secure/Dashboard.jspa?x=1") == "track.namecheap.net"


def test_trim_to_hostname_empty_input():
    assert launcher._trim_to_hostname("") == ""
    assert launcher._trim_to_hostname(None) == ""


def test_write_jira_setup_config_writes_all_three_fields(tmp_path, monkeypatch):
    config_path = tmp_path / ".atlassian-dc-mcp" / "jira.env"
    monkeypatch.setattr(launcher, "_ATLASSIAN_DC_MCP_CONFIG", config_path)
    launcher._write_jira_setup_config("track.namecheap.net")
    content = config_path.read_text()
    assert "JIRA_HOST=track.namecheap.net" in content
    assert "JIRA_API_BASE_PATH=/rest" in content
    assert "JIRA_DEFAULT_PAGE_SIZE=25" in content


def test_write_jira_setup_config_overwrites_existing_file(tmp_path, monkeypatch):
    # Unlike the old pre-seed behavior, this always writes — the user just
    # went through setup and entered a (possibly new) host, so a stale
    # existing file must not be left in place.
    config_path = tmp_path / ".atlassian-dc-mcp" / "jira.env"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("JIRA_HOST=some-other-host.example.com\n")
    monkeypatch.setattr(launcher, "_ATLASSIAN_DC_MCP_CONFIG", config_path)
    launcher._write_jira_setup_config("track.namecheap.net")
    assert "JIRA_HOST=track.namecheap.net" in config_path.read_text()


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    settings_dir = tmp_path / "settings"
    monkeypatch.setattr(launcher, "SETTINGS_DIR", settings_dir)
    monkeypatch.setattr(launcher, "STATE_PATH", settings_dir / "roadmap-settings.local.json")
    monkeypatch.setattr(launcher, "SETTINGS_TEMPLATE", settings_dir / "roadmap-settings.json")
    return settings_dir


def test_persist_jira_host_saves_to_settings(isolated_settings):
    # Regression: a real user's Jira host silently reverted to empty on the
    # next run because it only ever lived in os.environ for that one
    # process — this is what makes it survive across fresh runs instead.
    launcher._persist_jira_host("track.namecheap.net")
    saved = json.loads((isolated_settings / "roadmap-settings.local.json").read_text())
    assert saved["jira_host"] == "track.namecheap.net"


def test_persist_jira_host_preserves_other_existing_settings(isolated_settings):
    isolated_settings.mkdir(parents=True, exist_ok=True)
    (isolated_settings / "roadmap-settings.local.json").write_text(
        json.dumps({"include": ["Checkout Redesign"], "jira_host": "old-host.example.com"})
    )
    launcher._persist_jira_host("track.namecheap.net")
    saved = json.loads((isolated_settings / "roadmap-settings.local.json").read_text())
    assert saved["jira_host"] == "track.namecheap.net"
    assert saved["include"] == ["Checkout Redesign"]


def test_persist_jira_host_never_raises_on_failure(monkeypatch):
    monkeypatch.setattr(launcher, "load_state", MagicMock(side_effect=OSError("disk full")))
    launcher._persist_jira_host("track.namecheap.net")  # must not raise


def test_restore_jira_host_from_settings_when_env_unset(monkeypatch):
    monkeypatch.delenv("JIRA_HOST", raising=False)
    launcher._restore_jira_host_from_settings({"jira_host": "track.namecheap.net"})
    assert launcher.os.environ["JIRA_HOST"] == "track.namecheap.net"


def test_restore_jira_host_from_settings_does_not_override_existing_env(monkeypatch):
    monkeypatch.setenv("JIRA_HOST", "already-set.example.com")
    launcher._restore_jira_host_from_settings({"jira_host": "track.namecheap.net"})
    assert launcher.os.environ["JIRA_HOST"] == "already-set.example.com"


def test_restore_jira_host_from_settings_no_op_when_nothing_saved(monkeypatch):
    monkeypatch.delenv("JIRA_HOST", raising=False)
    launcher._restore_jira_host_from_settings({})
    assert "JIRA_HOST" not in launcher.os.environ


def test_store_jira_token_in_keychain_calls_security_with_update_flag():
    with patch.object(launcher.subprocess, "run") as fake_run:
        launcher._store_jira_token_in_keychain("secret-token-value")
    args = fake_run.call_args[0][0]
    assert args[:2] == ["security", "add-generic-password"]
    assert "secret-token-value" in args
    assert "-U" in args  # update in place if the entry already exists


def test_check_jira_reachability_ok():
    ok_response = type("R", (), {"status": 200})()
    with patch.object(launcher.urllib.request, "urlopen") as fake_urlopen:
        fake_urlopen.return_value.__enter__ = lambda self: ok_response
        fake_urlopen.return_value.__exit__ = lambda *a: False
        assert launcher._check_jira_reachability("track.namecheap.net", "tok") == "ok"


def test_check_jira_reachability_invalid_token():
    with patch.object(launcher.urllib.request, "urlopen",
                       side_effect=launcher.urllib.error.HTTPError("url", 401, "unauthorized", {}, None)):
        assert launcher._check_jira_reachability("track.namecheap.net", "bad-tok") == "invalid_token"


def test_check_jira_reachability_unreachable_means_vpn():
    # Regression: this exact case (no VPN) used to surface as a raw
    # "network error (UND_ERR_CONNECT_TIMEOUT ...)" from the third-party
    # tool. Our own check must clearly distinguish it from a bad token.
    with patch.object(launcher.urllib.request, "urlopen",
                       side_effect=launcher.urllib.error.URLError("timed out")):
        assert launcher._check_jira_reachability("track.namecheap.net", "tok") == "unreachable"


def test_run_jira_setup_prompts_host_and_token_then_succeeds(monkeypatch):
    # Pre-touch JIRA_HOST via monkeypatch so its fixture teardown restores
    # whatever this key was before, even though run_jira_setup() itself
    # mutates os.environ directly (not through monkeypatch) — otherwise
    # this test would leak JIRA_HOST into every test that runs after it.
    monkeypatch.delenv("JIRA_HOST", raising=False)
    with patch("builtins.input", side_effect=["https://track.namecheap.net/browse/X", "my-token"]), \
         patch.object(launcher, "_write_jira_setup_config") as fake_write_config, \
         patch.object(launcher, "_persist_jira_host") as fake_persist_host, \
         patch.object(launcher, "_store_jira_token_in_keychain") as fake_store_token, \
         patch.object(launcher, "_check_jira_reachability", return_value="ok"):
        launcher.run_jira_setup()
    # The pasted full URL must be trimmed to a bare hostname before use.
    fake_write_config.assert_called_once_with("track.namecheap.net")
    fake_persist_host.assert_called_once_with("track.namecheap.net")
    fake_store_token.assert_called_once_with("my-token")
    assert launcher.os.environ["JIRA_HOST"] == "track.namecheap.net"


def test_run_jira_setup_unreachable_tells_user_to_connect_vpn(monkeypatch):
    monkeypatch.delenv("JIRA_HOST", raising=False)
    with patch("builtins.input", side_effect=["track.namecheap.net", "my-token"]), \
         patch.object(launcher, "_write_jira_setup_config"), \
         patch.object(launcher, "_persist_jira_host"), \
         patch.object(launcher, "_store_jira_token_in_keychain"), \
         patch.object(launcher, "_check_jira_reachability", return_value="unreachable"):
        with pytest.raises(SystemExit) as exc_info:
            launcher.run_jira_setup()
    assert "vpn" in str(exc_info.value).lower()


def test_run_jira_setup_invalid_token_exits_cleanly(monkeypatch):
    monkeypatch.delenv("JIRA_HOST", raising=False)
    with patch("builtins.input", side_effect=["track.namecheap.net", "bad-token"]), \
         patch.object(launcher, "_write_jira_setup_config"), \
         patch.object(launcher, "_persist_jira_host"), \
         patch.object(launcher, "_store_jira_token_in_keychain"), \
         patch.object(launcher, "_check_jira_reachability", return_value="invalid_token"):
        with pytest.raises(SystemExit) as exc_info:
            launcher.run_jira_setup()
    assert "token" in str(exc_info.value).lower()


def test_ensure_openpyxl_already_importable_skips_prompt():
    with patch.object(launcher, "_openpyxl_importable", return_value=True), \
         patch("builtins.input", side_effect=AssertionError("should not prompt")):
        assert launcher._ensure_openpyxl() is True


def test_ensure_openpyxl_declined_returns_false():
    with patch.object(launcher, "_openpyxl_importable", return_value=False), \
         patch("builtins.input", return_value="n"):
        assert launcher._ensure_openpyxl() is False


def test_ensure_openpyxl_accepted_install_succeeds():
    success = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    with patch.object(launcher, "_openpyxl_importable", return_value=False), \
         patch("builtins.input", return_value="y"), \
         patch.object(launcher.subprocess, "run", return_value=success) as fake_run:
        assert launcher._ensure_openpyxl() is True
    args, kwargs = fake_run.call_args
    assert args[0] == [launcher.sys.executable, "-m", "pip", "install", "openpyxl"]
    # Must NOT be captured — pip's own live download progress should stream
    # straight to the terminal, not get hidden until the process finishes.
    assert "capture_output" not in kwargs


def test_ensure_openpyxl_accepted_install_fails():
    fail = type("R", (), {"returncode": 1, "stdout": "", "stderr": "network error"})()
    with patch.object(launcher, "_openpyxl_importable", return_value=False), \
         patch("builtins.input", return_value="y"), \
         patch.object(launcher.subprocess, "run", return_value=fail):
        assert launcher._ensure_openpyxl() is False


def test_write_crash_log_creates_logs_dir_and_writes_content(tmp_path, monkeypatch):
    log_path = tmp_path / "logs" / "roadmap-crash-log.txt"
    monkeypatch.setattr(launcher, "_CRASH_LOG_PATH", log_path)
    result_path = launcher._write_crash_log("some traceback text here")
    assert result_path == log_path
    content = log_path.read_text()
    assert "some traceback text here" in content
    assert "Python:" in content
    assert "Platform:" in content


def test_main_with_crash_log_saves_traceback_for_unexpected_errors(tmp_path, monkeypatch, capsys):
    # There's no other log file for the interactive launcher (see the
    # earlier "are there log files" discussion) — any genuinely unexpected
    # exception must be saved somewhere the user can actually send, not
    # just scroll past in the terminal. Lives in a repo-relative logs/
    # folder, not the home directory, so it's always in a predictable spot
    # next to the tool itself.
    log_path = tmp_path / "logs" / "roadmap-crash-log.txt"
    monkeypatch.setattr(launcher, "_CRASH_LOG_PATH", log_path)
    with patch.object(launcher, "main", side_effect=RuntimeError("boom, unexpected")):
        with pytest.raises(SystemExit) as exc_info:
            launcher._main_with_crash_log()
    assert exc_info.value.code == 1
    assert log_path.exists()
    content = log_path.read_text()
    assert "boom, unexpected" in content
    assert str(log_path) in capsys.readouterr().out


def test_main_with_crash_log_lets_our_own_system_exit_through_unchanged():
    # A deliberate, friendly SystemExit (e.g. from run_jira_setup's own
    # error handling) must NOT be caught and turned into a crash log —
    # SystemExit isn't an Exception subclass, so this should just pass
    # through untouched.
    with patch.object(launcher, "main", side_effect=SystemExit("friendly message")):
        with pytest.raises(SystemExit) as exc_info:
            launcher._main_with_crash_log()
    assert str(exc_info.value) == "friendly message"


def test_run_streaming_and_capture_relays_output_and_returncode():
    # Regression: jira-report.py's own crash tracebacks used to just print
    # to the terminal and vanish — nothing captured them for the crash log.
    # This is what makes that possible: live-relay AND capture at once.
    proc = MagicMock()
    proc.stdout = [b"line one\n", b"line two\n"]
    proc.returncode = 1
    with patch.object(launcher.subprocess, "Popen", return_value=proc) as fake_popen:
        returncode, captured = launcher._run_streaming_and_capture(["cmd"], "/some/cwd", {"X": "1"})
    fake_popen.assert_called_once_with(
        ["cmd"], cwd="/some/cwd", env={"X": "1"},
        stdout=launcher.subprocess.PIPE, stderr=launcher.subprocess.STDOUT,
    )
    assert returncode == 1
    assert captured == "line one\nline two\n"
    proc.wait.assert_called_once()


def test_jira_token_is_valid_returns_false_when_host_is_empty(monkeypatch):
    # Regression: a real user's account had a cached token but no recorded
    # JIRA_HOST. The empty-host request raised urllib.error.URLError
    # ("no host given"), which the generic exception handler below used to
    # treat as "probably a VPN hiccup, assume the token's fine" — letting
    # ensure_jira_token() skip run_jira_setup() forever, so jira-report.py's
    # own subprocess kept crashing with the same empty-host error downstream.
    monkeypatch.delenv("JIRA_HOST", raising=False)
    assert launcher.jira_token_is_valid("some-cached-token-value") is False


def test_jira_token_is_valid_still_optimistic_on_genuine_network_error(monkeypatch):
    # Confirms the fix is scoped to the empty-host case specifically — a
    # real VPN/network hiccup with a host actually configured should still
    # optimistically assume the token is fine (existing, intentional
    # behavior elsewhere relies on this).
    monkeypatch.setenv("JIRA_HOST", "track.namecheap.net")
    with patch.object(launcher.urllib.request, "urlopen", side_effect=launcher.urllib.error.URLError("timed out")):
        assert launcher.jira_token_is_valid("some-token") is True


def test_ensure_jira_token_does_not_wrap_interactive_setup_in_spinner():
    # Regression: run_jira_setup() must NOT run inside run_spinner()'s
    # background-thread animation — the spinner redraws over stdout every
    # 120ms and erases the interactive setup subprocess's own prompts,
    # making a working setup wizard look hung. Confirm the spinner is only
    # ever invoked with the token-check function, never with run_jira_setup.
    spinner_targets = []

    def fake_spinner(message, work_fn):
        spinner_targets.append(work_fn)
        return work_fn()

    with patch.object(launcher, "run_spinner", side_effect=fake_spinner), \
         patch.object(launcher, "read_jira_token", return_value=None), \
         patch.object(launcher, "run_jira_setup") as fake_setup:
        with pytest.raises(SystemExit):
            launcher.ensure_jira_token()

    assert fake_setup not in spinner_targets
    assert fake_setup.called


# ═══════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback
    PASS = "\033[32m✓\033[0m"
    FAIL = "\033[31m✗\033[0m"
    FUNNY = [
        "no settings found, going straight to wizard like it owns the place",
        "template = settings? nice try",
        "real settings detected, menu incoming",
        "user typed 'new', wizard activated",
        "user typed 'edit', wizard activated",
        "user typed 'update', skipping wizard like a pro",
        "update with keyword — targeting specific feature",
        "update --cache, living on the edge",
        "quit — user rage-quit before even starting",
        "invalid input handled gracefully, not thrown at the user",
        "upd shorthand works, we're not monsters",
        "edit all — full wizard, here we go",
        "edit section empty = all, enter key is a choice",
        "keyword section selected",
        "keywords (plural) also works, we forgive you",
        "jira key section",
        "jira shorthand",
        "eta section",
        "keyword eta — full form",
        "url section",
        "drive — same as url, aliases matter",
        "time section",
        "timezone — same thing, different word",
        "invalid section → re-prompts, no panic",
        "ISO date parsed correctly",
        "11-Jul-2026 parses — this was literally the bug we fixed",
        "two-digit year also works",
        "Jul 11, 2026 — natural format",
        "space-separated date",
        "garbage in, None out",
        "number-only is not a date",
        "keywords strip whitespace",
        "empty keywords removed",
        "None → empty list",
        "pace 3.5 saved correctly",
        "zero and negative pace rejected (jira is hard enough)",
        "non-numeric pace rejected",
        "HH:MM time parses",
        "invalid time returns None",
    ]
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for i, t in enumerate(tests):
        desc = FUNNY[i] if i < len(FUNNY) else t.__name__
        try:
            t()
            print(f"  {PASS} {desc}")
            passed += 1
        except Exception as e:
            print(f"  {FAIL} {desc}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        print("something is broken. fix it before touching the launcher.")
    else:
        print("all good. now you may touch the launcher.")
    sys.exit(failed)
