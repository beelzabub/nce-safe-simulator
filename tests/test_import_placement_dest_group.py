"""Placement tests for import destination pickers (Refs #138).

Covers the per-row fallback placement rule:
  * a row whose own ``group_path`` / ``project_path`` resolves under the target
    root is created THERE — structure the file carried is preserved;
  * a row whose path does NOT resolve falls back to the user-picked destination
    (``dest_group`` / ``target_project_path``) instead of being silently
    root-dumped (epics) or skipped (issues);
  * a destination that is set but does not resolve is a HARD ERROR — the import
    aborts before anything is created (no silent misplacement);
  * with no destination, an unresolvable epic row still falls back to the target
    ROOT (a valid epic container) while an unresolvable issue row is SKIPPED
    (the root is not a project) — the one remaining structural asymmetry;
  * tool payloads expose the new destination widgets while the raw registry
    keeps them as ``type: str, optional: True`` (CLI contract).
"""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin
from mixins.bootstrap import BootstrapMixin
from server.app import _tool_payload
from mixins.tools import TOOLS

pytestmark = pytest.mark.unit


# ─── Harness ───────────────────────────────────────────────────────────────────

def _grp(full_path):
    g = MagicMock()
    g.full_path = full_path
    return g


def _proj(path_with_namespace):
    p = MagicMock()
    p.path_with_namespace = path_with_namespace
    return p


class PlacementHarness(ImportExportMixin, BootstrapMixin):
    """Concrete mixin host that stubs the heavy pre-flight helpers so the
    creation loop runs against controlled group/project caches."""

    def __init__(self, rows, root, cache):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "Configured Group"
        self._rows = rows
        self._root = root
        self._cache = cache

    # heavy helpers → controlled stubs
    def _load_file(self, path):
        return self._rows

    def _resolve_import_target(self, create_missing, dry_run):
        return self._root

    def _build_group_cache(self, root_group):
        return self._cache

    def _build_project_cache(self, root_group):
        return self._cache

    def _build_valid_epic_ids(self, root_group):
        return set()

    def _resolve_parent_ids(self, cleaned, valid_ids, root_group, unresolved_parent):
        return ({}, set())

    def _validate_epics(self, rows):
        return rows, 0

    def _validate_issues(self, rows, target_project_path):
        return rows, 0


# ─── Epics: dest_group is a fallback, not an override ──────────────────────────

def test_import_epics_dest_group_is_fallback_for_unresolvable_rows(tmp_path):
    root = _grp("ns/root")
    team_a = _grp("ns/root/team-a")
    dest = _grp("ns/root/dest")
    cache = {"ns/root": root, "ns/root/team-a": team_a, "ns/root/dest": dest}

    rows = [
        {"title": "Epic 1", "group_path": "ns/root/team-a"},   # resolves → team-a
        {"title": "Epic 2", "group_path": ""},                 # blank      → dest
        {"title": "Epic 3", "group_path": "ns/root/ghost"},    # unresolved → dest
    ]
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_epics(input_path=str(f), dest_group="ns/root/dest")

    # resolvable row keeps its own path; only unresolvable rows fall back to dest
    assert team_a.epics.create.call_count == 1
    assert dest.epics.create.call_count == 2
    assert root.epics.create.call_count == 0


def test_import_epics_unresolvable_dest_group_aborts(tmp_path, capsys):
    root = _grp("ns/root")
    team_a = _grp("ns/root/team-a")
    cache = {"ns/root": root, "ns/root/team-a": team_a}  # 'ns/root/ghost' absent

    rows = [{"title": "Epic 1", "group_path": "ns/root/team-a"}]
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_epics(input_path=str(f), dest_group="ns/root/ghost")

    # a bad destination must fail loudly BEFORE creating anything — no silent
    # root-dump, and the resolvable row is not created either
    out = capsys.readouterr().out
    assert "ERROR: destination group 'ns/root/ghost' not found" in out
    assert team_a.epics.create.call_count == 0
    assert root.epics.create.call_count == 0


def test_import_epics_blank_dest_uses_row_path(tmp_path):
    root = _grp("ns/root")
    team_a = _grp("ns/root/team-a")
    cache = {"ns/root": root, "ns/root/team-a": team_a}

    rows = [{"title": "Epic 1", "group_path": "ns/root/team-a"}]
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_epics(input_path=str(f), dest_group="")

    assert team_a.epics.create.call_count == 1
    assert root.epics.create.call_count == 0


def test_import_epics_blank_dest_unresolvable_path_falls_back_to_root(tmp_path, capsys):
    root = _grp("ns/root")
    cache = {"ns/root": root}  # 'ns/root/ghost' is not resolvable

    rows = [{"title": "Epic 1", "group_path": "ns/root/ghost"}]
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_epics(input_path=str(f), dest_group=None)

    # documents current behaviour: unresolvable path → root (root is a valid
    # epic container), with a WARN
    assert root.epics.create.call_count == 1
    out = capsys.readouterr().out
    assert "not found — using root group" in out


# ─── Issues: target_project_path is a fallback, not an override ────────────────

def test_import_issues_target_project_is_fallback_for_unresolvable_rows(tmp_path):
    root = _grp("ns/root")
    backlog = _proj("ns/root/team-a/backlog")
    other = _proj("ns/root/team-b/backlog")
    cache = {"ns/root/team-a/backlog": backlog, "ns/root/team-b/backlog": other}

    rows = [
        {"title": "Issue 1", "project_path": "ns/root/team-b/backlog"},  # resolves → other
        {"title": "Issue 2", "project_path": ""},                        # blank    → target
        {"title": "Issue 3", "project_path": "ns/root/ghost"},           # unresolved → target
    ]
    f = tmp_path / "issues.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_issues(input_path=str(f), target_project_path="ns/root/team-a/backlog")

    # resolvable row keeps its own project; only unresolvable rows fall back
    assert other.issues.create.call_count == 1
    assert backlog.issues.create.call_count == 2


def test_import_issues_unresolvable_target_project_aborts(tmp_path, capsys):
    root = _grp("ns/root")
    backlog = _proj("ns/root/team-a/backlog")
    cache = {"ns/root/team-a/backlog": backlog}  # 'ns/root/ghost' absent

    rows = [{"title": "Issue 1", "project_path": "ns/root/team-a/backlog"}]
    f = tmp_path / "issues.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_issues(input_path=str(f), target_project_path="ns/root/ghost")

    # a bad destination must fail loudly BEFORE creating anything — no silent
    # skip of every row, and the resolvable row is not created either
    out = capsys.readouterr().out
    assert "ERROR: target project 'ns/root/ghost' not found" in out
    assert backlog.issues.create.call_count == 0


def test_import_issues_blank_target_unresolvable_project_skips(tmp_path, capsys):
    root = _grp("ns/root")
    cache = {}  # nothing resolvable

    rows = [{"title": "Issue 1", "project_path": "ns/root/ghost"}]
    f = tmp_path / "issues.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_issues(input_path=str(f), target_project_path=None)

    out = capsys.readouterr().out
    # structural note: root is not a project, so a missing project is skipped
    assert "SKIP" in out


# ─── Tool payloads + CLI contract ──────────────────────────────────────────────

def _tool(key):
    return next(t for t in TOOLS if t["key"] == key)


def _gl_stub():
    gl = MagicMock()
    gl.gitlab_namespace = "saic-study-group"
    gl.parent_group = "Portfolio"
    return gl


def test_import_epics_exposes_dest_group_widget():
    payload = _tool_payload(_tool("import-epics"), _gl_stub())
    dg = next(p for p in payload["params"] if p["name"] == "dest_group")
    assert dg["widget"] == "group-picker"
    assert dg["optional"] is True
    assert dg["type"] == "str"


def test_import_issues_target_project_has_project_widget():
    payload = _tool_payload(_tool("import-issues"), _gl_stub())
    tp = next(p for p in payload["params"] if p["name"] == "target_project_path")
    assert tp["widget"] == "project"
    assert tp["optional"] is True
    assert tp["type"] == "str"


def test_raw_registry_keeps_cli_contract():
    # CLI dispatches on type only; both destination params must remain plain
    # optional strings so _prompt_param prompts for them as free text.
    epics = _tool("import-epics")
    dg = next(p for p in epics["params"] if p["name"] == "dest_group")
    assert dg["type"] is str
    assert dg["optional"] is True

    issues = _tool("import-issues")
    tp = next(p for p in issues["params"] if p["name"] == "target_project_path")
    assert tp["type"] is str
    assert tp["optional"] is True
