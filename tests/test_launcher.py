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
from unittest.mock import patch

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


def test_run_jira_setup_ctrl_c_exits_cleanly_not_a_traceback():
    # Regression: Ctrl-C during the interactive `npx @atlassian-dc-mcp/jira
    # setup` subprocess used to bubble up as an unhandled CalledProcessError
    # (exit 130) all the way out of main(), printing a raw traceback instead
    # of a clean message telling the user what happened.
    import subprocess as _subprocess
    with patch.object(launcher, "_resolve_npx", return_value="/fake/npx"), \
         patch.object(launcher.subprocess, "run",
                      side_effect=_subprocess.CalledProcessError(130, launcher.JIRA_SETUP_CMD)):
        with pytest.raises(SystemExit) as exc_info:
            launcher.run_jira_setup()
    assert "cancelled" in str(exc_info.value).lower()


def test_run_jira_setup_other_failure_exits_cleanly():
    import subprocess as _subprocess
    with patch.object(launcher, "_resolve_npx", return_value="/fake/npx"), \
         patch.object(launcher.subprocess, "run",
                      side_effect=_subprocess.CalledProcessError(1, launcher.JIRA_SETUP_CMD)):
        with pytest.raises(SystemExit) as exc_info:
            launcher.run_jira_setup()
    assert "code 1" in str(exc_info.value).lower()


def test_run_jira_setup_missing_npx_declined_exits_cleanly():
    # Regression: a real user's `npx` wasn't found at all (no Node.js
    # installed, or installed but not on the restricted PATH a
    # double-clicked/Xcode-stub-python3 launch gets) — this used to crash
    # with an unhandled FileNotFoundError traceback instead of a clear,
    # actionable message. Here the user declines the install offer.
    with patch.object(launcher, "_resolve_npx", return_value=None), \
         patch("builtins.input", return_value="n"):
        with pytest.raises(SystemExit) as exc_info:
            launcher.run_jira_setup()
    assert "node.js" in str(exc_info.value).lower()


def test_ensure_node_already_present_skips_all_prompts():
    with patch.object(launcher, "_resolve_npx", return_value="/fake/npx"), \
         patch("builtins.input", side_effect=AssertionError("should not prompt")):
        assert launcher._ensure_node() is True


def test_ensure_node_user_declines_node_install():
    with patch.object(launcher, "_resolve_npx", return_value=None), \
         patch("builtins.input", return_value="n"):
        assert launcher._ensure_node() is False


def test_ensure_node_skips_prompts_on_non_mac():
    # There's no Windows/Linux equivalent of the Homebrew auto-install path
    # yet — asking "install Node.js? (y/n)" there would be a consent
    # question with no action behind it, so it must skip straight through
    # instead of prompting at all.
    with patch.object(launcher, "_resolve_npx", return_value=None), \
         patch.object(launcher.sys, "platform", "win32"), \
         patch("builtins.input", side_effect=AssertionError("should not prompt on non-Mac")):
        assert launcher._ensure_node() is False


def test_ensure_node_installs_via_brew_when_already_present():
    success_result = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    with patch.object(launcher, "_resolve_npx", side_effect=[None, "/fake/npx"]), \
         patch.object(launcher, "_resolve_brew", return_value="/fake/brew"), \
         patch.object(launcher.subprocess, "run", return_value=success_result) as fake_run, \
         patch("builtins.input", return_value="y"):
        assert launcher._ensure_node() is True
    fake_run.assert_called_once_with(["/fake/brew", "install", "node"], capture_output=True, text=True)


def _fake_completed(returncode=0, stdout="", stderr=""):
    return type("R", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()


def test_install_node_via_brew_declines_permission_fix_falls_back(capsys):
    # Regression: a real user hit `brew install node` failing because
    # /opt/homebrew had broken ownership (a common footgun from a prior
    # `sudo brew ...`). If the user declines the auto-fix offer, the
    # fallback message must still point back at Homebrew's own guidance.
    fail_result = _fake_completed(1, stderr="Error: /opt/homebrew is not writable.\n  sudo chown -R rulz /opt/homebrew")
    with patch.object(launcher.subprocess, "run", return_value=fail_result), \
         patch("builtins.input", return_value="n"):
        result = launcher._install_node_via_brew("/fake/brew")
    assert result is False
    output = capsys.readouterr().out.lower()
    assert "chown" in output
    assert "admin" in output


def test_install_node_via_brew_retries_after_permission_fix_accepted():
    # User accepts the chown fix, it succeeds, and the retried install
    # succeeds too — the whole thing should resolve to True.
    fail_result = _fake_completed(1, stderr="Error: /opt/homebrew is not writable.")
    prefix_result = _fake_completed(0, stdout="/opt/homebrew\n")
    chown_result = _fake_completed(0)
    retry_success = _fake_completed(0)
    with patch.object(launcher.subprocess, "run",
                      side_effect=[fail_result, prefix_result, chown_result, retry_success]), \
         patch.object(launcher, "_resolve_npx", return_value="/fake/npx"), \
         patch("builtins.input", return_value="y"):
        assert launcher._install_node_via_brew("/fake/brew") is True


def test_install_node_via_brew_generic_failure_does_not_offer_chown_fix():
    # A failure with no "not writable"/"chown" signature (e.g. a network
    # error) shouldn't trigger the permission-fix prompt at all.
    fail_result = _fake_completed(1, stderr="Error: Failed to download resource.")
    with patch.object(launcher.subprocess, "run", return_value=fail_result), \
         patch("builtins.input", side_effect=AssertionError("should not prompt")):
        assert launcher._install_node_via_brew("/fake/brew") is False


def test_offer_to_fix_brew_permissions_declined():
    prefix_result = _fake_completed(0, stdout="/opt/homebrew\n")
    with patch.object(launcher.subprocess, "run", return_value=prefix_result), \
         patch("builtins.input", return_value="n"):
        assert launcher._offer_to_fix_brew_permissions("/fake/brew") is False


def test_offer_to_fix_brew_permissions_chown_fails():
    prefix_result = _fake_completed(0, stdout="/opt/homebrew\n")
    chown_fail = _fake_completed(1)
    with patch.object(launcher.subprocess, "run", side_effect=[prefix_result, chown_fail]), \
         patch("builtins.input", return_value="y"):
        assert launcher._offer_to_fix_brew_permissions("/fake/brew") is False


def test_main_with_crash_log_saves_traceback_for_unexpected_errors(tmp_path, monkeypatch, capsys):
    # There's no other log file for the interactive launcher (see the
    # earlier "are there log files" discussion) — any genuinely unexpected
    # exception must be saved somewhere the user can actually send, not
    # just scroll past in the terminal.
    monkeypatch.setattr(launcher.Path, "home", lambda: tmp_path)
    with patch.object(launcher, "main", side_effect=RuntimeError("boom, unexpected")):
        with pytest.raises(SystemExit) as exc_info:
            launcher._main_with_crash_log()
    assert exc_info.value.code == 1

    log_path = tmp_path / "roadmap-crash-log.txt"
    assert log_path.exists()
    content = log_path.read_text()
    assert "boom, unexpected" in content
    assert "Python:" in content
    assert "Platform:" in content
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


def test_ensure_node_declines_homebrew_when_brew_missing():
    with patch.object(launcher, "_resolve_npx", return_value=None), \
         patch.object(launcher, "_resolve_brew", return_value=None), \
         patch("builtins.input", side_effect=["y", "n"]):
        assert launcher._ensure_node() is False


def test_ensure_node_installs_homebrew_then_node():
    success_result = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    with patch.object(launcher, "_resolve_npx", side_effect=[None, "/fake/npx"]), \
         patch.object(launcher, "_resolve_brew", side_effect=[None, "/fake/brew"]), \
         patch.object(launcher, "_install_homebrew", return_value=True) as fake_install_brew, \
         patch.object(launcher.subprocess, "run", return_value=success_result) as fake_run, \
         patch("builtins.input", side_effect=["y", "y"]):
        assert launcher._ensure_node() is True
    fake_install_brew.assert_called_once()
    fake_run.assert_called_once_with(["/fake/brew", "install", "node"], capture_output=True, text=True)


def test_ensure_node_homebrew_install_fails():
    with patch.object(launcher, "_resolve_npx", return_value=None), \
         patch.object(launcher, "_resolve_brew", return_value=None), \
         patch.object(launcher, "_install_homebrew", return_value=False), \
         patch("builtins.input", side_effect=["y", "y"]):
        assert launcher._ensure_node() is False


def test_run_jira_setup_npx_disappears_between_check_and_exec():
    # Belt-and-suspenders: even if _resolve_npx() finds something, the
    # actual subprocess.run() call can still raise FileNotFoundError
    # (e.g. a stale PATH entry) — must not crash with a raw traceback either.
    with patch.object(launcher, "_resolve_npx", return_value="/fake/npx"), \
         patch.object(launcher.subprocess, "run", side_effect=FileNotFoundError()):
        with pytest.raises(SystemExit) as exc_info:
            launcher.run_jira_setup()
    assert "node.js" in str(exc_info.value).lower()


def test_resolve_npx_falls_back_to_homebrew_path():
    # When PATH lookup fails (restricted-context launch) but Node was
    # installed via Homebrew, the explicit fallback locations must be tried.
    with patch("shutil.which", return_value=None), \
         patch("os.path.exists", side_effect=lambda p: p == "/opt/homebrew/bin/npx"):
        assert launcher._resolve_npx() == "/opt/homebrew/bin/npx"


def test_resolve_npx_returns_none_when_truly_absent():
    with patch("shutil.which", return_value=None), \
         patch("os.path.exists", return_value=False):
        assert launcher._resolve_npx() is None


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
