"""Cross-root relative-path reconciliation on import (Refs #139).

When epics/issues are exported from one group hierarchy and imported into another
(the airgapped enclave-to-enclave case), the row paths still carry the *source*
root, so they don't resolve directly under the target root. This feature strips
the source root — from the export's ``source_root`` stamp, an explicit override,
or a longest-common-prefix fallback — and re-resolves the structural remainder
under the target root, landing each item in its structurally-corresponding
container instead of dumping epics at the root / skipping issues.

Covers:
  * the string helpers (_strip_source_root, _infer_source_root, _reconcile_path);
  * placement precedence — own-direct > relative reconcile > #138 picker > root/skip;
  * safety: whole-relative-path matching, never a bare leaf name, so ambiguous
    leaf names can't cause silent misplacement;
  * the export stamps source_root; the import registers a source_root override
    param as a plain optional string (CLI contract).
"""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import (
    ImportExportMixin,
    EPIC_EXPORT_FIELDS,
    ISSUE_EXPORT_FIELDS,
    EPIC_ONLY_COLS,
    ISSUE_ONLY_COLS,
)
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
    """Stubs the heavy pre-flight helpers so the creation loop runs against
    controlled group/project caches (mirrors test_import_placement_dest_group)."""

    def __init__(self, rows, root, cache):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns-b"
        self.parent_group = "Configured Group"
        self._rows = rows
        self._root = root
        self._cache = cache

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


# ─── String helpers ────────────────────────────────────────────────────────────

def _h():
    return PlacementHarness([], _grp("x"), {})


def test_strip_source_root_whole_segment_match():
    h = _h()
    assert h._strip_source_root("ns-a/port/vs-01/team-03", "ns-a/port") == "vs-01/team-03"
    # equal path → the root itself
    assert h._strip_source_root("ns-a/port", "ns-a/port") == ""
    # tolerant of stray slashes
    assert h._strip_source_root("/ns-a/port/vs-01/", "ns-a/port/") == "vs-01"


def test_strip_source_root_rejects_partial_segment():
    h = _h()
    # 'ns-a/port' must not partially strip 'ns-a/portfolio'
    assert h._strip_source_root("ns-a/portfolio/vs-01", "ns-a/port") is None
    # not under the root at all
    assert h._strip_source_root("other/vs-01", "ns-a/port") is None
    # empties
    assert h._strip_source_root("", "ns-a/port") is None
    assert h._strip_source_root("ns-a/port/vs", "") is None


def test_infer_source_root_prefers_override_then_stamp_then_lcp():
    h = _h()
    rows = [
        {"group_path": "ns-a/port/vs-01/team-03", "source_root": "ns-a/port"},
        {"group_path": "ns-a/port/vs-02/team-09", "source_root": "ns-a/port"},
    ]
    # 1. override wins verbatim, and is trusted
    assert h._infer_source_root(rows, "group_path", override="ns-x/root") == ("ns-x/root", True)
    # 2. stamp used when no override, trusted
    assert h._infer_source_root(rows, "group_path") == ("ns-a/port", True)
    # 3. LCP fallback when no stamp — common prefix of the two paths, NOT trusted
    unstamped = [{"group_path": r["group_path"]} for r in rows]
    assert h._infer_source_root(unstamped, "group_path") == ("ns-a/port", False)


def test_infer_source_root_ignores_conflicting_stamps():
    # If rows disagree on the stamp (shouldn't happen from one export), don't
    # trust it — fall through to LCP (untrusted).
    h = _h()
    rows = [
        {"group_path": "ns-a/port/vs-01", "source_root": "ns-a/port"},
        {"group_path": "ns-a/port/vs-02", "source_root": "ns-a/OTHER"},
    ]
    assert h._infer_source_root(rows, "group_path") == ("ns-a/port", False)


def test_reconcile_path_resolves_under_target_root():
    h = _h()
    cache = {"ns-b/port/vs-01/team-03": object()}
    assert h._reconcile_path(
        "ns-a/port/vs-01/team-03", "ns-a/port", "ns-b/port", cache
    ) == "ns-b/port/vs-01/team-03"
    # relative path not present in target → None (no misplacement)
    assert h._reconcile_path(
        "ns-a/port/vs-99/ghost", "ns-a/port", "ns-b/port", cache
    ) is None


# ─── Epics: relative reconcile lands items in the mirrored subgroup ────────────

def test_import_epics_cross_root_reconciles_by_relative_path(tmp_path):
    root = _grp("ns-b/port")
    team3 = _grp("ns-b/port/vs-01/team-03")
    team9 = _grp("ns-b/port/vs-02/team-09")
    cache = {"ns-b/port": root,
             "ns-b/port/vs-01/team-03": team3,
             "ns-b/port/vs-02/team-09": team9}

    rows = [
        {"title": "E1", "group_path": "ns-a/port/vs-01/team-03", "source_root": "ns-a/port"},
        {"title": "E2", "group_path": "ns-a/port/vs-02/team-09", "source_root": "ns-a/port"},
    ]
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_epics(input_path=str(f))

    # each epic lands in its structurally-mirrored subgroup, NOT at the root
    assert team3.epics.create.call_count == 1
    assert team9.epics.create.call_count == 1
    assert root.epics.create.call_count == 0


def test_import_epics_reconcile_beats_dest_group_but_own_direct_wins(tmp_path):
    root = _grp("ns-b/port")
    team3 = _grp("ns-b/port/vs-01/team-03")
    dest = _grp("ns-b/port/dest")
    cache = {"ns-b/port": root, "ns-b/port/vs-01/team-03": team3, "ns-b/port/dest": dest}

    rows = [
        # own path already resolves under target → own wins (same-root)
        {"title": "E1", "group_path": "ns-b/port/vs-01/team-03", "source_root": "ns-a/port"},
        # cross-root path reconciles → mirrored subgroup, NOT the picked dest
        {"title": "E2", "group_path": "ns-a/port/vs-01/team-03", "source_root": "ns-a/port"},
        # cross-root path with no mirror → falls back to the #138 picked dest
        {"title": "E3", "group_path": "ns-a/port/vs-77/ghost", "source_root": "ns-a/port"},
    ]
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_epics(input_path=str(f), dest_group="ns-b/port/dest")

    assert team3.epics.create.call_count == 2   # E1 (direct) + E2 (reconciled)
    assert dest.epics.create.call_count == 1    # E3 (fallback)
    assert root.epics.create.call_count == 0


def test_import_epics_leaf_name_ambiguity_does_not_misplace(tmp_path, capsys):
    # Two different subgroups share the leaf 'backend'. A bare leaf match would
    # be ambiguous; whole-relative-path matching resolves each to exactly one.
    root = _grp("ns-b/port")
    a_backend = _grp("ns-b/port/vs-01/backend")
    b_backend = _grp("ns-b/port/vs-02/backend")
    cache = {"ns-b/port": root,
             "ns-b/port/vs-01/backend": a_backend,
             "ns-b/port/vs-02/backend": b_backend}

    rows = [{"title": "E1", "group_path": "ns-a/port/vs-02/backend", "source_root": "ns-a/port"}]
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_epics(input_path=str(f))

    # resolves to the vs-02 backend only — never the vs-01 one
    assert b_backend.epics.create.call_count == 1
    assert a_backend.epics.create.call_count == 0


def test_import_epics_override_source_root_for_unstamped_file(tmp_path):
    root = _grp("ns-b/port")
    team3 = _grp("ns-b/port/vs-01/team-03")
    cache = {"ns-b/port": root, "ns-b/port/vs-01/team-03": team3}

    # No source_root stamp — the user supplies the override explicitly.
    rows = [{"title": "E1", "group_path": "ns-a/port/vs-01/team-03"}]
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_epics(input_path=str(f), source_root="ns-a/port")

    assert team3.epics.create.call_count == 1


# ─── Issues: relative reconcile lands items in the mirrored project ────────────

def test_import_issues_cross_root_reconciles_by_relative_path(tmp_path):
    root = _grp("ns-b/port")
    backlog3 = _proj("ns-b/port/vs-01/team-03/backlog")
    backlog9 = _proj("ns-b/port/vs-02/team-09/backlog")
    cache = {"ns-b/port/vs-01/team-03/backlog": backlog3,
             "ns-b/port/vs-02/team-09/backlog": backlog9}

    rows = [
        {"title": "I1", "project_path": "ns-a/port/vs-01/team-03/backlog", "source_root": "ns-a/port"},
        {"title": "I2", "project_path": "ns-a/port/vs-02/team-09/backlog", "source_root": "ns-a/port"},
    ]
    f = tmp_path / "issues.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_issues(input_path=str(f))

    # each issue lands in its mirrored project, NOT skipped
    assert backlog3.issues.create.call_count == 1
    assert backlog9.issues.create.call_count == 1


def test_import_issues_reconcile_beats_target_project_fallback(tmp_path):
    root = _grp("ns-b/port")
    backlog3 = _proj("ns-b/port/vs-01/team-03/backlog")
    target = _proj("ns-b/port/inbox/backlog")
    cache = {"ns-b/port/vs-01/team-03/backlog": backlog3,
             "ns-b/port/inbox/backlog": target}

    rows = [
        # reconciles → mirrored project, not the picked target
        {"title": "I1", "project_path": "ns-a/port/vs-01/team-03/backlog", "source_root": "ns-a/port"},
        # no mirror → falls back to the #138 picked target project
        {"title": "I2", "project_path": "ns-a/port/vs-77/ghost/backlog", "source_root": "ns-a/port"},
    ]
    f = tmp_path / "issues.json"
    f.write_text(json.dumps(rows))

    h = PlacementHarness(rows, root, cache)
    h._import_issues(input_path=str(f), target_project_path="ns-b/port/inbox/backlog")

    assert backlog3.issues.create.call_count == 1   # reconciled
    assert target.issues.create.call_count == 1      # fallback


# ─── Export stamps the source root ─────────────────────────────────────────────

def test_source_root_column_is_in_export_fields():
    assert "source_root" in EPIC_EXPORT_FIELDS
    assert "source_root" in ISSUE_EXPORT_FIELDS


def test_source_root_is_shared_column_not_a_wrong_file_marker():
    # source_root is present in BOTH importers' KNOWN sets, so it must cancel out
    # of the epic-only / issue-only marker sets — else it would trip the
    # wrong-file guard on every cross-type check.
    assert "source_root" not in EPIC_ONLY_COLS
    assert "source_root" not in ISSUE_ONLY_COLS


class _ExportHarness(ImportExportMixin):
    def __init__(self, group, epics, gid_map, weights):
        self.gl = MagicMock()
        self.parent_group = "P"
        self._group = group
        self._epics = epics
        self._gid_map = gid_map
        self._weights = weights
        self.written = None

    def get_group_by_name(self, name):
        return self._group

    def _build_gid_path_map(self, group):
        return self._gid_map

    def _fetch_epic_weights(self, epics):
        return self._weights

    def _write_file(self, path, fmt, rows, field_order):
        self.written = rows


def test_export_epics_stamps_source_root(tmp_path):
    group = _grp("ns-a/port")
    group.full_path = "ns-a/port"
    epic = MagicMock()
    epic.iid, epic.id, epic.title = 1, 100, "E1"
    epic.description = epic.state = ""
    epic.labels = []
    epic.group_id = 7
    epic.web_url = "http://x/1"
    epic.author = {"name": "a"}
    group.epics.list.return_value = [epic]

    h = _ExportHarness(group, [epic], {7: "ns-a/port/vs-01"}, {})
    h._export_epics(output_path=str(tmp_path / "e.csv"))

    assert h.written[0]["source_root"] == "ns-a/port"
    assert h.written[0]["group_path"] == "ns-a/port/vs-01"


# ─── Tool params (CLI contract) ────────────────────────────────────────────────

def _tool(key):
    return next(t for t in TOOLS if t["key"] == key)


def _gl_stub():
    gl = MagicMock()
    gl.gitlab_namespace = "ns-b"
    gl.parent_group = "Portfolio"
    return gl


def test_import_epics_registers_source_root_param():
    epics = _tool("import-epics")
    sr = next(p for p in epics["params"] if p["name"] == "source_root")
    assert sr["type"] is str
    assert sr["optional"] is True
    # payload keeps the CLI contract (type-only string, optional)
    payload = _tool_payload(epics, _gl_stub())
    psr = next(p for p in payload["params"] if p["name"] == "source_root")
    assert psr["type"] == "str"
    assert psr["optional"] is True


def test_import_issues_registers_source_root_param():
    issues = _tool("import-issues")
    sr = next(p for p in issues["params"] if p["name"] == "source_root")
    assert sr["type"] is str
    assert sr["optional"] is True
