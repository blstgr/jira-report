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
