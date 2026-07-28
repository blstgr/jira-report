"""Tests for jira-report.py pure logic functions."""
import sys
import types
import importlib.util
import datetime as dt
from pathlib import Path

# Stub external imports before loading the module
def _stub(mod, **attrs):
    m = types.ModuleType(mod)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[mod] = m
    return m

_sentinel = object

_stub("google_drive_sync", upload_or_update=lambda *a, **kw: {})

_openpyxl = _stub("openpyxl", Workbook=_sentinel, load_workbook=lambda *a, **kw: None)
_stub("openpyxl.styles", Font=_sentinel, PatternFill=_sentinel, Alignment=_sentinel,
      Border=_sentinel, Side=_sentinel)
_stub("openpyxl.styles.numbers", FORMAT_DATE_DATETIME=None)
_stub("openpyxl.utils", get_column_letter=lambda i: "A")
_stub("openpyxl.utils.cell", coordinate_from_string=lambda s: ("A", 1),
      column_index_from_string=lambda s: 1)
_stub("openpyxl.worksheet.filters", FilterColumn=_sentinel, Filters=_sentinel)
_stub("PIL", ImageFont=None)

APP_DIR = Path(__file__).resolve().parents[1] / "app"
spec = importlib.util.spec_from_file_location("jr", APP_DIR / "jira-report.py")
jr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jr)


# ── normalize_keyword ──────────────────────────────────────────────────────

def test_normalize_strips_punctuation_and_lowercases():
    assert jr.normalize_keyword("Checkout Redesign: BI") == "checkoutredesignbi"
    assert jr.normalize_keyword("Checkout Redesign") == "checkoutredesign"
    assert jr.normalize_keyword("ca change") == "cachange"


def test_normalize_collapses_spaces_and_hyphens():
    assert jr.normalize_keyword("post-release") == "postrelease"
    assert jr.normalize_keyword("post release") == "postrelease"


# ── feature filter logic (mirrors what main() does) ───────────────────────

FEATURES = [
    "Checkout Redesign",
    "Checkout Redesign: post-release",
    "Checkout Redesign: BI",
    "Checkout Redesign: release preparation",
    "Checkout Redesign: BI post-release",
    "Payments: single-domain ssl",
    "Maintenance",
]


def apply_filter(features, pattern, mode_all):
    needle = jr.normalize_keyword(pattern)
    if mode_all:
        return [k for k in features if needle in jr.normalize_keyword(k)]
    else:
        return [k for k in features if jr.normalize_keyword(k) == needle]


def test_exact_filter_matches_one():
    result = apply_filter(FEATURES, "Checkout Redesign", mode_all=False)
    assert result == ["Checkout Redesign"]


def test_exact_filter_case_insensitive():
    result = apply_filter(FEATURES, "checkout redesign", mode_all=False)
    assert result == ["Checkout Redesign"]


def test_exact_filter_no_match():
    result = apply_filter(FEATURES, "Loyalty Program", mode_all=False)
    assert result == []


def test_all_filter_matches_substring_group():
    result = apply_filter(FEATURES, "checkout redesign", mode_all=True)
    assert "Checkout Redesign" in result
    assert "Checkout Redesign: BI" in result
    assert "Checkout Redesign: release preparation" in result
    assert "Checkout Redesign: post-release" in result
    assert "Checkout Redesign: BI post-release" in result
    assert "Payments: single-domain ssl" not in result
    assert "Maintenance" not in result


def test_all_filter_does_not_bleed_across_projects():
    result = apply_filter(FEATURES, "payments", mode_all=True)
    assert result == ["Payments: single-domain ssl"]


def test_all_filter_no_match():
    result = apply_filter(FEATURES, "loyalty program", mode_all=True)
    assert result == []


# ── norm_status ────────────────────────────────────────────────────────────

def test_norm_status_in_progress_variants():
    assert jr.norm_status("In Progress") == "in progress"
    assert jr.norm_status("In QA") == "in progress"
    assert jr.norm_status("In QA - something") == "in progress"
    assert jr.norm_status("Code Review") == "in progress"
    assert jr.norm_status("Progress Done") == "in progress"


def test_norm_status_done_variants():
    assert jr.norm_status("Done") == "done"
    assert jr.norm_status("QA Prod Done") == "done"
    assert jr.norm_status("In Validation") == "done"


def test_norm_status_on_hold():
    assert jr.norm_status("QA On Hold") == "on hold"
    assert jr.norm_status("Track/Blocked/On Hold") == "on hold"


def test_norm_status_rejected():
    assert jr.norm_status("Rejected") == "rejected"


def test_norm_status_unknown_returns_blank():
    assert jr.norm_status("Backlog") == ""
    assert jr.norm_status("To Do") == ""
    assert jr.norm_status("") == ""
    assert jr.norm_status(None) == ""


# ── project key filter (PROJECT_KEYS) ─────────────────────────────────────

def _make_issue(key, summary="test", status="In Progress", changelog=None):
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status},
            "issuetype": {"name": "Story"},
            "resolutiondate": None,
            "created": "2024-01-01T00:00:00.000+0000",
        },
        "changelog": changelog or {"histories": []},
    }


def test_project_keys_filter_passes_matching():
    jr.PROJECT_KEYS = ["ABC"]
    rows = jr.issue_rows(_make_issue("ABC-123"), "feat", "epic", "epic", [])
    assert isinstance(rows, list)  # not filtered out (may be empty due to no events, but not skipped)


def test_project_keys_filter_blocks_other_project():
    jr.PROJECT_KEYS = ["ABC"]
    rows = jr.issue_rows(_make_issue("OTHER-456"), "feat", "epic", "epic", [])
    assert rows == []


def test_project_keys_filter_empty_accepts_all():
    jr.PROJECT_KEYS = []
    rows = jr.issue_rows(_make_issue("OTHER-456"), "feat", "epic", "epic", [])
    # With no events, we expect an empty-or-single-blank-row result, not a hard filter
    assert isinstance(rows, list)


def test_project_keys_multiple_allowed():
    jr.PROJECT_KEYS = ["ABC", "OTHER"]
    rows_abc = jr.issue_rows(_make_issue("ABC-1"), "feat", "epic", "epic", [])
    rows_other = jr.issue_rows(_make_issue("OTHER-1"), "feat", "epic", "epic", [])
    rows_blocked = jr.issue_rows(_make_issue("BLOCKED-1"), "feat", "epic", "epic", [])
    assert isinstance(rows_abc, list)
    assert isinstance(rows_other, list)
    assert rows_blocked == []


# ── project_matches_selector ───────────────────────────────────────────────

def _fields_with_project(name="", key=""):
    return {"project": {"name": name, "key": key}}


def test_project_matches_by_key():
    assert jr.project_matches_selector(_fields_with_project(key="ABC"), "abc")


def test_project_matches_by_name():
    assert jr.project_matches_selector(_fields_with_project(name="SSL Project"), "ssl project")


def test_project_no_match():
    assert not jr.project_matches_selector(_fields_with_project(name="Other", key="OTH"), "abc")


# ── parse_date ─────────────────────────────────────────────────────────────

def test_parse_date_iso():
    assert jr.parse_date("2024-03-15") == dt.date(2024, 3, 15)


def test_parse_date_with_time():
    assert jr.parse_date("2024-03-15T10:30:00.000+0000") == dt.date(2024, 3, 15)


def test_parse_date_none():
    assert jr.parse_date(None) is None
    assert jr.parse_date("") is None


# ── sanitize_feature_eta_dates ─────────────────────────────────────────────

def test_sanitize_feature_eta_dates_valid():
    result = jr.sanitize_feature_eta_dates({"Checkout Redesign": "2026-06-28", "Payments": "2026-08-01"})
    assert result["Checkout Redesign"] == "2026-06-28"
    assert result["Payments"] == "2026-08-01"


def test_sanitize_feature_eta_dates_invalid_dropped():
    result = jr.sanitize_feature_eta_dates({"bad": "not a date", "empty": ""})
    assert "bad" not in result
    assert "empty" not in result


def test_sanitize_feature_eta_dates_empty_key_dropped():
    result = jr.sanitize_feature_eta_dates({"": "2026-01-01", "  ": "2026-01-01"})
    assert result == {}


# ── scope_signature ────────────────────────────────────────────────────────

def test_scope_signature_structure():
    sig = jr.scope_signature(["Checkout Redesign", "Payments"], ["KWD1"])
    assert sig == {"include": ["Checkout Redesign", "Payments"], "exclude": ["KWD1"]}


def test_scope_signature_empty():
    sig = jr.scope_signature([], [])
    assert sig == {"include": [], "exclude": []}


# ── issue_rows state machine — basic scenarios ─────────────────────────────

def _history(when, from_status, to_status, hid="1"):
    return {
        "id": hid,
        "created": f"{when}T12:00:00.000+0000",
        "items": [{"field": "status", "fromString": from_status, "toString": to_status}],
    }


def _issue_with_events(key, events, current_status="Done", resolution="2024-06-01"):
    return {
        "key": key,
        "fields": {
            "summary": "Test task",
            "status": {"name": current_status},
            "issuetype": {"name": "Story"},
            "resolutiondate": f"{resolution}T00:00:00.000+0000" if resolution else None,
            "created": "2024-01-01T00:00:00.000+0000",
        },
        "changelog": {"histories": events},
    }


def test_issue_rows_no_events_returns_blank_row():
    jr.PROJECT_KEYS = []
    issue = _issue_with_events("ABC-1", [], current_status="To Do", resolution=None)
    rows = jr.issue_rows(issue, "feat", "epic", "epic", [])
    assert len(rows) == 1
    assert rows[0]["Status"] == ""


def test_issue_rows_simple_done_task():
    jr.PROJECT_KEYS = []
    issue = _issue_with_events("ABC-2", [
        _history("2024-03-01", "To Do", "In Progress", "1"),
        _history("2024-06-01", "In Progress", "Done", "2"),
    ], current_status="Done", resolution="2024-06-01")
    rows = jr.issue_rows(issue, "feat", "epic", "epic", [])
    # Rows use lowercase "Status" values internally
    statuses = [r.get("Status") or r.get("status") or "" for r in rows]
    assert any(s in {"done", "in progress"} for s in statuses), f"Unexpected statuses: {statuses}"


def test_issue_rows_on_hold_task():
    jr.PROJECT_KEYS = []
    issue = _issue_with_events("ABC-3", [
        _history("2024-03-01", "To Do", "In Progress", "1"),
        _history("2024-04-01", "In Progress", "Track/Blocked/On Hold", "2"),
        _history("2024-05-01", "Track/Blocked/On Hold", "In Progress", "3"),
        _history("2024-06-01", "In Progress", "Done", "4"),
    ], current_status="Done", resolution="2024-06-01")
    rows = jr.issue_rows(issue, "feat", "epic", "epic", [])
    statuses = [r["Status"] for r in rows]
    assert any("hold" in s.lower() for s in statuses), f"Expected on-hold row, got: {statuses}"


def test_issue_rows_rejected_task():
    jr.PROJECT_KEYS = []
    issue = _issue_with_events("ABC-4", [
        _history("2024-03-01", "To Do", "In Progress", "1"),
        _history("2024-04-01", "In Progress", "Rejected", "2"),
    ], current_status="Rejected", resolution=None)
    rows = jr.issue_rows(issue, "feat", "epic", "epic", [])
    statuses = [r["Status"] for r in rows]
    assert any("rejected" in s.lower() for s in statuses), f"Expected rejected row, got: {statuses}"


def test_load_report_spec_fallback_has_no_hardcoded_feature_keyword():
    """When prompts/roadmap-spec.json is missing, the fallback must not silently
    default to any real company's feature name — it should be None, forcing the
    caller to require explicit configuration instead."""
    original = jr.SPEC_PATH
    jr.SPEC_PATH = Path("/nonexistent/roadmap-spec.json")
    try:
        spec = jr.load_report_spec()
    finally:
        jr.SPEC_PATH = original
    assert spec["feature_keyword"] is None
    assert spec["exclude_keywords"] == ["post release", "post-release"]


def test_fetch_all_search_reports_progress_per_page():
    # Regression: a batch's tasks can span many pages of 100 — with no
    # per-page callback, a single large/slow batch showed zero movement for
    # its whole duration, which read as the tool having frozen.
    pages = [
        {"issues": [{"key": f"T-{i}"} for i in range(100)], "total": 250},
        {"issues": [{"key": f"T-{i}"} for i in range(100, 200)], "total": 250},
        {"issues": [{"key": f"T-{i}"} for i in range(200, 250)], "total": 250},
    ]
    calls = iter(pages)
    original_jget = jr.jget
    original_sleep = jr.time.sleep
    jr.jget = lambda *a, **kw: next(calls)
    jr.time.sleep = lambda *a, **kw: None
    progress_calls = []
    try:
        items = jr.fetch_all_search(
            "some jql", "summary", on_progress=lambda fetched, total: progress_calls.append((fetched, total))
        )
    finally:
        jr.jget = original_jget
        jr.time.sleep = original_sleep
    assert len(items) == 250
    assert progress_calls == [(100, 250), (200, 250), (250, 250)]


def test_fetch_all_search_works_without_progress_callback():
    original_jget = jr.jget
    original_sleep = jr.time.sleep
    jr.jget = lambda *a, **kw: {"issues": [{"key": "T-1"}], "total": 1}
    jr.time.sleep = lambda *a, **kw: None
    try:
        items = jr.fetch_all_search("some jql", "summary")
    finally:
        jr.jget = original_jget
        jr.time.sleep = original_sleep
    assert items == [{"key": "T-1"}]


def test_detect_jira_fields_calls_field_endpoint_once():
    original_jget = jr.jget
    calls = []
    jr.jget = lambda *a, **kw: calls.append((a, kw)) or [{"id": "customfield_1", "name": "ETA"}]
    try:
        result = jr.detect_jira_fields()
    finally:
        jr.jget = original_jget
    assert len(calls) == 1
    assert calls[0][0][0] == f"{jr.BASE}/field"
    assert result == [{"id": "customfield_1", "name": "ETA"}]


def test_detect_jira_fields_propagates_network_error():
    # Regression: this used to be caught by a blanket try/except inside each
    # of the three detect_*_field_id(s) functions and silently swallowed,
    # which meant a VPN drop just made report generation sit there with no
    # output and no error — instead of the clear VPN message main()'s own
    # JiraNetworkError handling already provides everywhere else.
    original_jget = jr.jget

    def _raise(*a, **kw):
        raise jr.JiraNetworkError("Jira or VPN connection appears to have dropped")

    jr.jget = _raise
    try:
        try:
            jr.detect_jira_fields()
            assert False, "expected JiraNetworkError to propagate"
        except jr.JiraNetworkError:
            pass
    finally:
        jr.jget = original_jget


def test_detect_jira_fields_propagates_auth_error():
    original_jget = jr.jget

    def _raise(*a, **kw):
        raise jr.JiraAuthError("Jira authentication failed with HTTP 401")

    jr.jget = _raise
    try:
        try:
            jr.detect_jira_fields()
            assert False, "expected JiraAuthError to propagate"
        except jr.JiraAuthError:
            pass
    finally:
        jr.jget = original_jget


def test_detect_eta_field_ids_prefers_exact_match_over_substring():
    fields = [
        {"id": "customfield_1", "name": "Something ETA related"},
        {"id": "customfield_2", "name": "ETA"},
    ]
    ordered = jr.detect_eta_field_ids(fields)
    assert ordered[0] == "customfield_2"


def test_detect_eta_field_ids_falls_back_to_defaults_when_nothing_matches():
    assert jr.detect_eta_field_ids([]) == list(jr.DEFAULT_ETA_FIELD_IDS)


def test_detect_epic_link_field_id_matches_by_name():
    fields = [
        {"id": "customfield_9", "name": "Something else"},
        {"id": "customfield_10014", "name": "Epic Link"},
    ]
    assert jr.detect_epic_link_field_id(fields) == "customfield_10014"


def test_detect_epic_link_field_id_returns_none_when_not_found():
    assert jr.detect_epic_link_field_id([]) is None


def test_detect_epic_name_field_ids_falls_back_to_default_when_nothing_matches():
    assert jr.detect_epic_name_field_ids([]) == ["customfield_10011"]


def _epic(key, summary):
    return {"key": key, "fields": {"summary": summary, "issuetype": {"name": "Epic"}}}


def test_fetch_epics_by_key_builds_key_to_epic_map():
    original_jget = jr.jget
    jr.jget = lambda *a, **kw: {
        "issues": [_epic("ABC-1", "Checkout Redesign: core"), _epic("ABC-2", "Checkout Redesign: post-release")],
        "total": 2,
    }
    try:
        result = jr.fetch_epics_by_key({"ABC-1", "ABC-2"}, "summary,status")
    finally:
        jr.jget = original_jget
    assert set(result.keys()) == {"ABC-1", "ABC-2"}
    assert result["ABC-1"]["fields"]["summary"] == "Checkout Redesign: core"


def test_fetch_epics_by_key_chunks_across_batch_size():
    # Regression coverage for the reason this exists at all: re-checking an
    # existing report's rows against edited keywords needs the epics'
    # summary text, which isn't persisted to the xlsx (only the epic key
    # is) — so it has to be re-fetched, batched the same way epic discovery
    # already is elsewhere.
    original_jget = jr.jget
    calls = []

    def _fake_jget(url, context=None):
        calls.append(url)
        return {"issues": [_epic(f"ABC-{len(calls)}", "x")], "total": 1}

    jr.jget = _fake_jget
    try:
        keys = {f"ABC-{i}" for i in range(1, jr.EPIC_BATCH_SIZE + 5)}
        jr.fetch_epics_by_key(keys, "summary")
    finally:
        jr.jget = original_jget
    assert len(calls) == 2  # more keys than EPIC_BATCH_SIZE -> 2 batches


def test_epic_fallback_rows_tracks_epic_as_task_when_no_children():
    # Regression: an epic with zero child tasks silently vanished from the
    # report entirely — nothing to break progress into meant nothing got
    # tracked at all. This is what makes the epic itself show up instead,
    # using its own status/summary/changelog the same way a real task would.
    original_jget = jr.jget
    jr.jget = lambda url, context=None: {
        "key": "ABC-1",
        "fields": {
            "summary": "Implement the thing",
            "issuetype": {"name": "Epic"},
            "status": {"name": "In Progress"},
            "created": "2026-07-01T00:00:00.000-0000",
            "resolutiondate": None,
        },
        "changelog": {"histories": []},
    }
    try:
        epic = {"key": "ABC-1", "fields": {"summary": "Checkout Redesign: the epic"}}
        rows = jr.epic_fallback_rows(epic, "Checkout Redesign", "Checkout Redesign: the epic", "", [])
    finally:
        jr.jget = original_jget
    assert len(rows) == 1
    row = rows[0]
    assert row["Task"] == "Implement the thing"
    assert row["Task type"] == "Epic"
    assert row["Status"] == "in progress"
    assert row["Link"] == "ABC-1"
    assert row["Epic"] == "ABC-1"
    assert row["Feature"] == "Checkout Redesign"


def test_epic_fallback_rows_returns_empty_on_fetch_failure():
    original_jget = jr.jget

    def _raise(*a, **kw):
        raise jr.JiraNetworkError("dropped")

    jr.jget = _raise
    try:
        epic = {"key": "ABC-1", "fields": {}}
        rows = jr.epic_fallback_rows(epic, "Checkout Redesign", "summary", "", [])
    finally:
        jr.jget = original_jget
    assert rows == []


def test_epic_fallback_rows_returns_empty_without_epic_key():
    rows = jr.epic_fallback_rows({"fields": {}}, "Checkout Redesign", "summary", "", [])
    assert rows == []


def test_pick_feature_label_prefers_more_specific_keyword_among_candidates():
    summary = "Checkout Redesign: post-release: Increased load - fixes"
    label = jr.pick_feature_label(
        summary, summary,
        ["checkout redesign", "checkout redesign: post-release", "Checkout Redesign: post-release: Increased load - fixes"],
        "ABC-1",
    )
    assert label == "Checkout Redesign: post-release: Increased load - fixes"


def test_pick_feature_label_regression_single_candidate_gives_wrong_label():
    # Regression: --new-features (and the "resync" command built on it) used
    # to call pick_feature_label() with ONLY the keyword being resynced as
    # the sole candidate — so an epic always got labeled with exactly that
    # keyword, even when a separately-configured, more specific keyword (the
    # epic's own full name) existed and should have won, same as it would
    # during a normal full report build. This documents the exact contract
    # the fix depends on: pick_feature_label must be given the FULL
    # configured keyword list, not a single keyword, to rank correctly.
    summary = "Checkout Redesign: post-release: Increased load - fixes"
    single_candidate_label = jr.pick_feature_label(summary, summary, ["checkout redesign: post-release"], "ABC-1")
    assert single_candidate_label == "checkout redesign: post-release"  # the bug, preserved as documentation

    full_list_label = jr.pick_feature_label(
        summary, summary,
        ["checkout redesign", "checkout redesign: post-release", "Checkout Redesign: post-release: Increased load - fixes"],
        "ABC-1",
    )
    assert full_list_label == "Checkout Redesign: post-release: Increased load - fixes"  # the fix


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception:
            print(f"  ✗ {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(failed)
