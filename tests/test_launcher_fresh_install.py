"""
End-to-end simulation of a brand-new user's first run through
roadmap-launcher.py: no settings file, nothing configured, answering the
interactive wizard's prompts from scratch.

This exists to catch exactly the class of regression our "make it generic"
cleanup could introduce — e.g. a stage silently depending on a real Jira
host/token/keychain entry that a fresh clone won't have. Jira connectivity
and the actual report-generation subprocess are stubbed out (those are
either covered elsewhere or require real infra); everything else — the
wizard's stage flow, prompt parsing, and the settings file it writes — runs
for real.

Run with:  python3 -m pytest tests/test_launcher_fresh_install.py -q
"""
import builtins
import json
import sys
import types
import importlib.util
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
spec = importlib.util.spec_from_file_location("launcher_fresh", APP_DIR / "roadmap-launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class ScriptedInput:
    """Feeds a fixed sequence of answers to input(); fails loudly (instead of
    hanging) if the wizard asks more questions than the script anticipated —
    that's a sign the stage flow changed and the script needs updating."""

    def __init__(self, answers):
        self._answers = list(answers)

    def __call__(self, prompt=""):
        if not self._answers:
            raise AssertionError(f"Wizard asked another question with no scripted answer left: {prompt!r}")
        return self._answers.pop(0)


@pytest.fixture
def sandboxed_launcher(tmp_path, monkeypatch):
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    reports_dir = tmp_path / "report"
    template = settings_dir / "roadmap-settings.json"
    # Mirror the real generic template a fresh clone actually ships with.
    real_template = APP_DIR.parent / "settings" / "roadmap-settings.json"
    template.write_text(real_template.read_text())

    monkeypatch.setattr(launcher, "SETTINGS_DIR", settings_dir)
    monkeypatch.setattr(launcher, "SETTINGS_TEMPLATE", template)
    monkeypatch.setattr(launcher, "STATE_PATH", settings_dir / "roadmap-settings.local.json")
    monkeypatch.setattr(launcher, "REPORTS_DIR", reports_dir)

    # Never let this test read (or, via main()'s JIRA_HOST fallback, mutate
    # os.environ from) the real machine's ~/.atlassian-dc-mcp/jira.env.
    monkeypatch.setattr(launcher, "_ATLASSIAN_DC_MCP_CONFIG", tmp_path / "does-not-exist" / "jira.env")
    monkeypatch.delenv("JIRA_HOST", raising=False)

    # Jira token/setup requires real keychain + network — not what this test
    # is verifying (that's test_install_launchd.py's job for the scheduler
    # side); a fresh install must reach this point without crashing first.
    monkeypatch.setattr(launcher, "ensure_jira_token", lambda: None)

    # The only subprocess call this scripted path reaches is the final
    # jira-report.py invocation (Drive sync and auto-update are both
    # declined below, so their subprocess calls are never made). Return the
    # "ran fine, nothing changed" exit code so main() completes normally.
    monkeypatch.setattr(launcher, "_run_streaming_and_capture", lambda cmd, cwd, env, **kw: (88, ""))

    # _send_notification() shells out to the REAL terminal-notifier with no
    # test-mode guard — a prior test here genuinely fired live macOS
    # notifications on every `pytest` run (spoofed as coming from Script
    # Editor, since that's the sender id the code impersonates). Mock it
    # defensively even though this specific path doesn't currently reach it.
    monkeypatch.setattr(launcher, "_send_notification", lambda message: None)

    return launcher, settings_dir


def test_fresh_install_writes_settings_without_any_hardcoded_company_default(sandboxed_launcher, monkeypatch):
    launcher, settings_dir = sandboxed_launcher
    answers = ScriptedInput([
        "Checkout Redesign",  # stage 0: keywords to include (required — no default exists)
        "",                   # stage 1: keywords to exclude — skip
        "",                   # stage 11: Jira project keys — skip
        "",                   # stage 12: done statuses — keep shipped default
        "",                   # stage 2: expected pace/ETA for "Checkout Redesign" — skip
        "n",                  # stage 3: sync with Google Drive? — no
        "n",                  # stage 5: automatic updates? — no
    ])
    monkeypatch.setattr(builtins, "input", answers)
    monkeypatch.setattr(sys, "argv", ["roadmap-launcher.py"])

    launcher.main()

    written = json.loads((settings_dir / "roadmap-settings.local.json").read_text())
    assert written["features"] == [{"keyword": "Checkout Redesign"}]
    assert written["exclude"] == []
    assert written["project_keys"] == []
    assert written["done_statuses"] == launcher.DEFAULT_DONE_STATUSES
    assert written["local_only"] is True
    assert written["auto_update"] is False

    # The whole point: nothing about Example ever appears anywhere in what
    # a brand-new user's fresh install produces.
    dump = json.dumps(written).lower()
    assert "example" not in dump
    assert "abc" not in dump
    assert "legacy cleanup" not in dump


@pytest.fixture
def sandboxed_launcher_with_existing_settings(tmp_path, monkeypatch):
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    reports_dir = tmp_path / "report"
    template = settings_dir / "roadmap-settings.json"
    real_template = APP_DIR.parent / "settings" / "roadmap-settings.json"
    template.write_text(real_template.read_text())

    local = settings_dir / "roadmap-settings.local.json"
    local.write_text(json.dumps({
        "features": [{"keyword": "checkout redesign", "expected_pace": 15.0}],
        "exclude": ["legacy cleanup"],
        "project_keys": [],
        "output": "report/roadmap 2026.xlsx",
        "drive_folder": "",
        "google_client_secrets": None,
        "local_only": True,
        "update_time": "11:00",
        "update_timezone": "Europe/Kiev",
    }))

    monkeypatch.setattr(launcher, "SETTINGS_DIR", settings_dir)
    monkeypatch.setattr(launcher, "SETTINGS_TEMPLATE", template)
    monkeypatch.setattr(launcher, "STATE_PATH", local)
    monkeypatch.setattr(launcher, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(launcher, "_ATLASSIAN_DC_MCP_CONFIG", tmp_path / "does-not-exist" / "jira.env")
    monkeypatch.delenv("JIRA_HOST", raising=False)
    monkeypatch.setattr(launcher, "ensure_jira_token", lambda: "fake-token")

    captured_cmds = []
    monkeypatch.setattr(
        launcher, "_run_streaming_and_capture",
        lambda cmd, cwd, env, **kw: (captured_cmds.append(cmd) or 88, "")
    )

    # Regression: this test drives the "edit" action, which sets
    # update_run=True — combined with the mocked returncode 88 above, that
    # reaches _send_notification("All quiet on the Jira front..."), which
    # shells out to the REAL terminal-notifier with no test-mode guard.
    # Every run of this test fired a live macOS notification (spoofed as
    # coming from Script Editor) until this was mocked.
    monkeypatch.setattr(launcher, "_send_notification", lambda message: None)

    return launcher, settings_dir, captured_cmds


def test_editing_keywords_routes_through_update_not_a_bare_rebuild(sandboxed_launcher_with_existing_settings, monkeypatch):
    # Regression: edit_run was initialized False and never set True anywhere
    # (dead code) — "edit" fell through with neither --fresh nor --update
    # set. jira-report.py's non-fresh task query excludes status NOT IN
    # (done, rejected) with no fallback to preserve existing Done rows for a
    # feature that isn't already fully done, so any epic whose tasks were
    # ALL Done silently returned zero child tasks and vanished from the
    # report. Routing through --update (task-level refresh against the
    # existing file) is what actually preserves that completed work.
    launcher, settings_dir, captured_cmds = sandboxed_launcher_with_existing_settings
    answers = ScriptedInput([
        "edit",     # menu: has_settings -> prompt_existing_report_action
        "keyword",  # _prompt_edit_section
        "",         # keywords to include — keep default ("checkout redesign")
        "",         # keywords to exclude — keep default ("legacy cleanup")
        "",         # Jira project keys — keep default (empty)
    ])
    monkeypatch.setattr(builtins, "input", answers)
    monkeypatch.setattr(sys, "argv", ["roadmap-launcher.py"])

    launcher.main()

    assert len(captured_cmds) == 1
    assert "--update" in captured_cmds[0]
    assert "--fresh" not in captured_cmds[0]


def test_resync_bare_shows_picker_and_runs_update_with_new_features(
    sandboxed_launcher_with_existing_settings, monkeypatch
):
    # This is what exposes --update --new-features "<keyword>" (see
    # jira-report.py's _existing_feature_by_key relabeling) from the
    # interactive menu — previously only reachable by invoking
    # jira-report.py directly on the command line. Bare "resync" at the
    # main prompt shows a picker over configured keywords.
    launcher, settings_dir, captured_cmds = sandboxed_launcher_with_existing_settings
    answers = ScriptedInput([
        "resync",             # menu: bare resync -> picker
        "checkout redesign",  # keyword to resync — matches the fixture's configured feature
    ])
    monkeypatch.setattr(builtins, "input", answers)
    monkeypatch.setattr(sys, "argv", ["roadmap-launcher.py"])

    with pytest.raises(SystemExit) as exc_info:
        launcher.main()

    assert exc_info.value.code == 0
    assert len(captured_cmds) == 1
    assert "--update" in captured_cmds[0]
    assert "--new-features" in captured_cmds[0]
    assert "checkout redesign" in captured_cmds[0]
    assert "--fresh" not in captured_cmds[0]


def test_resync_uploads_to_drive_when_configured(
    sandboxed_launcher_with_existing_settings, monkeypatch
):
    # Regression: resync built its own jira-report.py invocation from
    # scratch and never called _do_drive_upload() at all — unlike the main
    # update/new flow, a successful resync never synced the refreshed
    # report to Drive even when Drive sync was fully configured.
    launcher, settings_dir, captured_cmds = sandboxed_launcher_with_existing_settings
    local_path = settings_dir / "roadmap-settings.local.json"
    settings = json.loads(local_path.read_text())
    settings["local_only"] = False
    settings["drive_folder"] = "https://drive.google.com/drive/folders/abc"
    settings["google_client_secrets"] = "app/google-oauth-client-secrets.json"
    local_path.write_text(json.dumps(settings))

    drive_calls = []
    monkeypatch.setattr(launcher, "_do_drive_upload", lambda *a: drive_calls.append(a))
    answers = ScriptedInput(["resync checkout redesign"])
    monkeypatch.setattr(builtins, "input", answers)
    monkeypatch.setattr(sys, "argv", ["roadmap-launcher.py"])

    with pytest.raises(SystemExit) as exc_info:
        launcher.main()

    assert exc_info.value.code == 0
    assert len(drive_calls) == 1
    _output, _local_only, _drive_folder, _google_client_secrets = drive_calls[0]
    assert _local_only is False
    assert _drive_folder == "https://drive.google.com/drive/folders/abc"
    assert _google_client_secrets.endswith("app/google-oauth-client-secrets.json")


def test_resync_with_keyword_skips_the_picker_entirely(
    sandboxed_launcher_with_existing_settings, monkeypatch
):
    # "resync [keyword]" at the main prompt — same as "update [keyword]" —
    # passes the typed keyword straight through without validating it
    # against configured keywords first; jira-report.py's own epic matching
    # is the source of truth, not a second copy of it here.
    launcher, settings_dir, captured_cmds = sandboxed_launcher_with_existing_settings
    answers = ScriptedInput(["resync checkout redesign: post-release"])
    monkeypatch.setattr(builtins, "input", answers)
    monkeypatch.setattr(sys, "argv", ["roadmap-launcher.py"])

    with pytest.raises(SystemExit) as exc_info:
        launcher.main()

    assert exc_info.value.code == 0
    assert len(captured_cmds) == 1
    assert "--new-features" in captured_cmds[0]
    assert "checkout redesign: post-release" in captured_cmds[0]


def test_resync_bare_reprompts_on_unknown_keyword_in_picker(
    sandboxed_launcher_with_existing_settings, monkeypatch
):
    launcher, settings_dir, captured_cmds = sandboxed_launcher_with_existing_settings
    answers = ScriptedInput([
        "resync",
        "not a real keyword",
        "checkout redesign",
    ])
    monkeypatch.setattr(builtins, "input", answers)
    monkeypatch.setattr(sys, "argv", ["roadmap-launcher.py"])

    with pytest.raises(SystemExit) as exc_info:
        launcher.main()

    assert exc_info.value.code == 0
    assert len(captured_cmds) == 1
    assert "checkout redesign" in captured_cmds[0]


def test_resync_bare_cancel_does_not_run_anything(
    sandboxed_launcher_with_existing_settings, monkeypatch
):
    launcher, settings_dir, captured_cmds = sandboxed_launcher_with_existing_settings
    answers = ScriptedInput(["resync", ""])  # Enter with nothing = cancel
    monkeypatch.setattr(builtins, "input", answers)
    monkeypatch.setattr(sys, "argv", ["roadmap-launcher.py"])

    with pytest.raises(SystemExit) as exc_info:
        launcher.main()

    assert exc_info.value.code == 0
    assert captured_cmds == []


def test_editing_keywords_sends_notification_through_the_mock_not_the_real_notifier(
    sandboxed_launcher_with_existing_settings, monkeypatch
):
    # This exercises the exact code path that used to fire a real, live
    # macOS notification on every test run (update_run=True + returncode 88
    # -> _send_notification("All quiet on the Jira front...") -> real
    # terminal-notifier, spoofed as sent by Script Editor). Asserting the
    # mock was called (instead of just letting it no-op silently) keeps this
    # honest — if _send_notification's monkeypatch above is ever removed or
    # broken, this test would still pass without noticing the leak back to
    # a real notification, so the assertion has to be on the spy itself.
    launcher, settings_dir, captured_cmds = sandboxed_launcher_with_existing_settings
    sent = []
    monkeypatch.setattr(launcher, "_send_notification", lambda message: sent.append(message))
    answers = ScriptedInput(["edit", "keyword", "", "", ""])
    monkeypatch.setattr(builtins, "input", answers)
    monkeypatch.setattr(sys, "argv", ["roadmap-launcher.py"])

    launcher.main()

    assert sent == ["All quiet on the Jira front. Come back when someone actually does something."]
