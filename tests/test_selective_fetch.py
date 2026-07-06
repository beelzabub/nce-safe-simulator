"""Selective data fetch — derive minimal snapshot phases from selected reports (#183).

Covers the registry `data` mapping, phase skipping in `_write_report_data`,
loader tolerance for absent files, selective `write_report_json`, the
partial-snapshot manifest/completion guard, the reuse coverage warning, and
`_last_data_dir` requiring a complete snapshot.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mixins.reports import (
    REPORTS,
    SNAPSHOT_FILES,
    snapshot_needs,
)


def _report(key):
    return next(r for r in REPORTS if r["key"] == key)


# ---------------------------------------------------------------------------
# Registry + derivation
# ---------------------------------------------------------------------------

def test_every_report_has_valid_data_field():
    assert len(REPORTS) == 23
    for r in REPORTS:
        assert "data" in r, r["key"]
        assert set(r["data"]) <= set(SNAPSHOT_FILES), (r["key"], r["data"])


@pytest.mark.parametrize("key, expected", [
    ("portfolio",          {"epics"}),
    ("flow-metrics",       {"epics"}),
    ("epic-lifecycle",     {"epics", "groups"}),
    ("wsjf",               {"epics", "blocking_graph"}),
    ("portfolio-explorer", {"epics", "blocking_graph"}),
    ("blocking",           {"epics", "blocking_graph", "groups"}),
    ("team-backlog",       {"epics", "issues", "groups", "projects"}),
    ("orphan-issues",      {"issues", "projects"}),
    ("issue-blocking",     {"issue_blocking"}),
    ("wiki-index",         set()),
    ("diagnostics",        set()),
])
def test_registry_matches_issue_table(key, expected):
    assert set(_report(key)["data"]) == expected


def test_snapshot_needs_unions():
    # Acceptance: blocking + orphan-issues fetches A+B+D, skips C (issue_blocking).
    got = snapshot_needs([_report("blocking"), _report("orphan-issues")])
    assert got == {"epics", "issues", "blocking_graph", "groups", "projects"}
    assert "issue_blocking" not in got
    # issue-blocking alone → only C.
    assert snapshot_needs([_report("issue-blocking")]) == {"issue_blocking"}
    # All reports → every snapshot file.
    assert snapshot_needs(REPORTS) == set(SNAPSHOT_FILES)


# ---------------------------------------------------------------------------
# _write_report_data phase skipping
# ---------------------------------------------------------------------------

def _fetch_harness():
    from conftest import ReportsHarness
    h = ReportsHarness()
    h.calculate_portfolio_metrics   = MagicMock(return_value={"Epic": [], "Capability": [], "Feature": []})
    h._fetch_blocking_graph         = MagicMock(return_value={"summary": {"total_blocked": 0}})
    h._fetch_issue_blocking_graph   = MagicMock(return_value={"summary": {"total_blocked": 0}})
    h._collect_snapshot_groups_projects = MagicMock(return_value=([], []))
    return h


def _files(d):
    return {p.stem for p in d.glob("*.json")}


def test_write_report_data_portfolio_skips_bcd(tmp_path):
    h = _fetch_harness()
    written = h._write_report_data(tmp_path, needed={"epics"})
    assert written == {"epics", "issues"}
    assert _files(tmp_path) == {"epics", "issues"}
    h._fetch_blocking_graph.assert_not_called()
    h._fetch_issue_blocking_graph.assert_not_called()
    h._collect_snapshot_groups_projects.assert_not_called()


def test_write_report_data_runs_only_blocking(tmp_path):
    h = _fetch_harness()
    written = h._write_report_data(tmp_path, needed={"epics", "blocking_graph"})
    assert written == {"epics", "issues", "blocking_graph"}
    h._fetch_blocking_graph.assert_called_once()
    h._fetch_issue_blocking_graph.assert_not_called()
    h._collect_snapshot_groups_projects.assert_not_called()


def test_write_report_data_runs_only_hierarchy(tmp_path):
    h = _fetch_harness()
    written = h._write_report_data(tmp_path, needed={"epics", "groups"})
    assert written == {"epics", "issues", "groups", "projects"}
    h._collect_snapshot_groups_projects.assert_called_once()
    h._fetch_blocking_graph.assert_not_called()
    h._fetch_issue_blocking_graph.assert_not_called()


def test_write_report_data_full_fetches_everything(tmp_path):
    h = _fetch_harness()
    written = h._write_report_data(tmp_path, needed=None)
    assert written == set(SNAPSHOT_FILES)
    assert _files(tmp_path) == set(SNAPSHOT_FILES)
    h._fetch_blocking_graph.assert_called_once()
    h._fetch_issue_blocking_graph.assert_called_once()
    h._collect_snapshot_groups_projects.assert_called_once()


def test_partial_snapshot_round_trip(tmp_path):
    """A `--report portfolio`-style partial snapshot writes, is left incomplete,
    and loads back into a fresh harness without crashing."""
    from conftest import ReportsHarness
    h = _fetch_harness()
    written = h._write_report_data(tmp_path, needed={"epics"})
    is_full = h._write_snapshot_manifest(tmp_path, [_report("portfolio")])
    assert written == {"epics", "issues"}
    assert is_full is False
    assert not (tmp_path / "snapshot.complete").exists()
    ReportsHarness()._load_report_data(tmp_path)   # must not raise


# ---------------------------------------------------------------------------
# _load_report_data tolerance
# ---------------------------------------------------------------------------

def test_load_report_data_tolerates_missing_files(tmp_path):
    from conftest import ReportsHarness
    # Only Phase A files present (a --report portfolio snapshot).
    (tmp_path / "epics.json").write_text(json.dumps({"epics": [], "all_epics_raw": []}))
    (tmp_path / "issues.json").write_text(json.dumps({"issues": []}))
    h = ReportsHarness()
    h._load_report_data(tmp_path)   # must not raise
    assert h._rd_blocking.get("relationships") == []
    assert h._rd_groups_by_id == {}
    assert dict(h._rd_projects_by_nsid) == {}
    assert h._rd_issue_blocking.get("relationships") == []


def test_load_report_data_survives_empty_dir(tmp_path):
    from conftest import ReportsHarness
    ReportsHarness()._load_report_data(tmp_path)   # nothing present, must not raise


# ---------------------------------------------------------------------------
# Selective write_report_json
# ---------------------------------------------------------------------------

def test_write_report_json_selective(tmp_path):
    from conftest import ReportsHarness
    ReportsHarness().write_report_json(tmp_path, keys={"portfolio"})
    assert _files(tmp_path) == {"portfolio"}


def test_write_report_json_all_when_keys_none(tmp_path):
    from conftest import ReportsHarness
    ReportsHarness().write_report_json(tmp_path)
    # 21 data-layer files (wiki-index and diagnostics have no builder).
    assert len(list(tmp_path.glob("*.json"))) == 21
    assert "wiki-index" not in _files(tmp_path)


# ---------------------------------------------------------------------------
# Manifest + completion marker
# ---------------------------------------------------------------------------

def _touch_snapshot(d, stems):
    for s in stems:
        (d / f"{s}.json").write_text("{}")


def test_manifest_full_marks_complete(tmp_path):
    from conftest import ReportsHarness
    _touch_snapshot(tmp_path, SNAPSHOT_FILES)
    is_full = ReportsHarness()._write_snapshot_manifest(tmp_path, [_report("portfolio")])
    assert is_full is True
    assert (tmp_path / "snapshot.complete").is_file()
    manifest = json.loads((tmp_path / "snapshot.manifest.json").read_text())
    assert manifest["full"] is True
    assert set(manifest["files"]) == set(SNAPSHOT_FILES)
    assert manifest["reports"] == ["portfolio"]


def test_manifest_partial_is_not_complete(tmp_path):
    from conftest import ReportsHarness
    _touch_snapshot(tmp_path, ["epics", "issues"])
    is_full = ReportsHarness()._write_snapshot_manifest(tmp_path, [_report("portfolio")])
    assert is_full is False
    assert not (tmp_path / "snapshot.complete").exists()
    manifest = json.loads((tmp_path / "snapshot.manifest.json").read_text())
    assert manifest["full"] is False
    assert set(manifest["files"]) == {"epics", "issues"}


# ---------------------------------------------------------------------------
# Reuse coverage warning
# ---------------------------------------------------------------------------

def _write_manifest(d, full, files):
    (d / "snapshot.manifest.json").write_text(json.dumps({"full": full, "files": files}))


def test_warn_when_partial_snapshot_uncovered(tmp_path, capsys):
    from conftest import ReportsHarness
    _write_manifest(tmp_path, full=False, files=["epics", "issues"])
    ReportsHarness()._warn_if_snapshot_incomplete(tmp_path, [_report("blocking")])
    out = capsys.readouterr().out
    assert "PARTIAL" in out
    assert "blocking_graph" in out or "groups" in out


def test_no_warn_when_partial_snapshot_covers_selection(tmp_path, capsys):
    from conftest import ReportsHarness
    _write_manifest(tmp_path, full=False, files=["epics", "issues"])
    ReportsHarness()._warn_if_snapshot_incomplete(tmp_path, [_report("portfolio")])
    assert "PARTIAL" not in capsys.readouterr().out


def test_no_warn_for_full_or_legacy_snapshot(tmp_path, capsys):
    from conftest import ReportsHarness
    h = ReportsHarness()
    _write_manifest(tmp_path, full=True, files=list(SNAPSHOT_FILES))
    h._warn_if_snapshot_incomplete(tmp_path, [_report("blocking")])
    # No manifest at all (pre-#183 snapshot) → assumed full, silent.
    (tmp_path / "snapshot.manifest.json").unlink()
    h._warn_if_snapshot_incomplete(tmp_path, [_report("blocking")])
    assert "PARTIAL" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _last_data_dir requires a complete snapshot
# ---------------------------------------------------------------------------

def test_last_data_dir_requires_snapshot_complete(tmp_path, monkeypatch):
    from NceGitLab import _last_data_dir
    monkeypatch.chdir(tmp_path)

    partial = tmp_path / "reports" / "20260101" / "120000" / "data"
    partial.mkdir(parents=True)
    (partial / "epics.json").write_text("{}")
    assert _last_data_dir() is None   # partial snapshot must be ignored

    full = tmp_path / "reports" / "20260101" / "130000" / "data"
    full.mkdir(parents=True)
    (full / "epics.json").write_text("{}")
    (full / "snapshot.complete").touch()
    found = _last_data_dir()                       # returned relative to cwd
    assert found is not None
    assert (tmp_path / found).resolve() == full.resolve()
