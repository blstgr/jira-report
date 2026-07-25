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
    assert "ca switch" not in dump
