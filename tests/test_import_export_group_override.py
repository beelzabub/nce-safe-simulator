"""Tests for the per-run active-group override in import/export tools (Refs #128).

Covers:
  * the override is threaded into export_epics / export_issues / import_epics /
    import_issues (the configured group is retargeted only for that run and then
    restored — config.json is never mutated);
  * the create-if-missing path on import (creates when checked + missing, errors
    when unchecked + missing, never creates under dry run);
  * the CLI / no-override path is unchanged (configured group is used);
  * the tool payloads expose the group-widget indicator + create-missing bool.
"""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin
from mixins.bootstrap import BootstrapMixin
from server.app import _tool_payload
from mixins.tools import TOOLS

pytestmark = pytest.mark.unit


# ─── Harness ──────────────────────────────────────────────────────────────────

class IEHarness(ImportExportMixin, BootstrapMixin):
    """Minimal concrete mixin host that records group resolution."""

    def __init__(self):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "Configured Group"
        self.seen = []          # (name, namespace, parent_group) at resolution time
        self._group_obj = None  # what get_group_by_name returns

    def get_group_by_name(self, name):
        self.seen.append((name, self.gitlab_namespace, self.parent_group))
        return self._group_obj

    def sanitize_name(self, s):
        return s.lower().replace(" ", "-")


# ─── _group_override threading (export reads the override group) ───────────────

def test_export_epics_uses_override_group():
    h = IEHarness()  # group not found → bails after recording resolution
    h.export_epics(group="other-ns/Override Group")
    assert h.seen[0] == ("Override Group", "other-ns", "Override Group")
    # restored — config untouched
    assert h.parent_group == "Configured Group"
    assert h.gitlab_namespace == "ns"


def test_export_issues_override_group_only_keeps_namespace():
    h = IEHarness()
    h.export_issues(group="Just A Name")
    assert h.seen[0] == ("Just A Name", "ns", "Just A Name")
    assert h.parent_group == "Configured Group"
    assert h.gitlab_namespace == "ns"


# ─── full URL-slug path override (#256 follow-up) ─────────────────────────────
# A path pasted from a group URL / the UI picker must be resolved WHOLE, not
# split into an ambiguous slug leaf. get_group_by_name's full-path branch then
# disambiguates it.

def test_override_full_url_path_resolved_whole():
    h = IEHarness()
    full = "gl-demo-ultimate-lmwilliams/twa-pompass/twa-122-testdashboard/vs-01"
    h.export_epics(group=full)
    # resolved by the WHOLE path (not the leaf 'vs-01'), namespace left as configured
    assert h.seen[0] == (full, "ns", full)
    assert h.parent_group == "Configured Group"   # restored
    assert h.gitlab_namespace == "ns"


def test_override_display_name_path_still_splits():
    # The namespace/DisplayName form (#202) keeps splitting — the leaf has a space.
    h = IEHarness()
    h.export_epics(group="other-ns/Override Group")
    assert h.seen[0] == ("Override Group", "other-ns", "Override Group")


@pytest.mark.parametrize("value,is_path", [
    ("gl-demo/twa-pompass/vs-01", True),     # all slug segments
    ("group-a/sub-b", True),
    ("vs-01", False),                        # single segment (no '/') — not a path
    ("other-ns/Override Group", False),      # display-name leaf (space)
    ("TWA-122 - PlatformEngineering/Jamie", False),  # display-name namespace (space/case)
    ("Ns/Group", False),                     # mixed-case segments
])
def test_looks_like_group_path(value, is_path):
    from mixins.importexport import _looks_like_group_path
    assert _looks_like_group_path(value) is is_path


def test_export_epics_no_override_uses_config():
    h = IEHarness()
    h.export_epics()
    assert h.seen[0][0] == "Configured Group"
    assert h.parent_group == "Configured Group"


def test_group_override_restores_even_on_error():
    h = IEHarness()

    def boom(name):
        raise RuntimeError("kaboom")

    h.get_group_by_name = boom
    with pytest.raises(RuntimeError):
        with h._group_override("x-ns/Temp Group"):
            h.get_group_by_name("Temp Group")
    assert h.parent_group == "Configured Group"
    assert h.gitlab_namespace == "ns"


# ─── create-if-missing target resolution (import only) ────────────────────────

def test_resolve_import_target_existing_returns_group():
    h = IEHarness()
    sentinel = object()
    h._group_obj = sentinel
    assert h._resolve_import_target(create_missing=False, dry_run=False) is sentinel


def test_resolve_import_target_missing_unchecked_errors(capsys):
    h = IEHarness()
    h._group_obj = None
    result = h._resolve_import_target(create_missing=False, dry_run=False)
    assert result is None
    out = capsys.readouterr().out
    assert "does not exist" in out
    assert "Create target group if missing" in out


def test_resolve_import_target_missing_checked_creates():
    h = IEHarness()
    h._group_obj = None
    created = object()
    h._get_or_create_root_group = MagicMock(return_value=created)
    result = h._resolve_import_target(create_missing=True, dry_run=False)
    assert result is created
    h._get_or_create_root_group.assert_called_once()


def test_resolve_import_target_missing_checked_dry_run_does_not_create(capsys):
    h = IEHarness()
    h._group_obj = None
    h._get_or_create_root_group = MagicMock()
    result = h._resolve_import_target(create_missing=True, dry_run=True)
    assert result is None
    h._get_or_create_root_group.assert_not_called()
    assert "dry run" in capsys.readouterr().out.lower()


# ─── import wrappers thread group + create_missing into the impl ───────────────

def test_import_epics_wrapper_threads_override_and_create_missing():
    h = IEHarness()
    captured = {}

    def fake_impl(input_path, unresolved_parent, dry_run, create_missing, dest_group,
                  on_existing, source_root, create_missing_groups, group_names,
                  on_missing_bv_field):
        captured["args"] = (input_path, unresolved_parent, dry_run, create_missing,
                            dest_group, on_existing, source_root, create_missing_groups,
                            group_names, on_missing_bv_field)
        captured["parent_group"] = h.parent_group
        captured["ns"] = h.gitlab_namespace

    h._import_epics = fake_impl
    h.import_epics(input_path="x.json", unresolved_parent="skip", dry_run=True,
                   group="ns2/Group B", create_missing=True, dest_group="ns2/Group B/team",
                   on_existing="update", source_root="ns-a/port", create_missing_groups=True,
                   group_names="names.json", on_missing_bv_field="ignore")
    assert captured["args"] == ("x.json", "skip", True, True, "ns2/Group B/team", "update",
                                "ns-a/port", True, "names.json", "ignore")
    assert captured["parent_group"] == "Group B"      # override active during call
    assert captured["ns"] == "ns2"
    assert h.parent_group == "Configured Group"        # restored after
    assert h.gitlab_namespace == "ns"


def test_import_issues_wrapper_threads_override_and_create_missing():
    h = IEHarness()
    captured = {}

    def fake_impl(input_path, target_project_path, dry_run, create_missing, on_existing,
                  source_root, epic_id_map, create_missing_projects, group_names):
        captured["args"] = (input_path, target_project_path, dry_run, create_missing,
                            on_existing, source_root, epic_id_map, create_missing_projects,
                            group_names)
        captured["parent_group"] = h.parent_group

    h._import_issues = fake_impl
    h.import_issues(input_path="i.csv", target_project_path="team/backlog",
                    dry_run=False, group="Group C", create_missing=True, on_existing="skip",
                    source_root="ns-a/port", epic_id_map="map.json",
                    create_missing_projects=True, group_names="names.json")
    assert captured["args"] == ("i.csv", "team/backlog", False, True, "skip", "ns-a/port",
                                "map.json", True, "names.json")
    assert captured["parent_group"] == "Group C"
    assert h.parent_group == "Configured Group"


# ─── End-to-end import: missing group + unchecked aborts before any creation ───

def test_import_epics_missing_group_unchecked_aborts(tmp_path, capsys):
    h = IEHarness()
    h._group_obj = None  # target group does not exist
    h._get_or_create_root_group = MagicMock()
    f = tmp_path / "epics.json"
    f.write_text(json.dumps([{"title": "Epic A"}]))

    h.import_epics(input_path=str(f), group="x-ns/Ghost Group", create_missing=False)

    out = capsys.readouterr().out
    assert "does not exist" in out
    h._get_or_create_root_group.assert_not_called()  # nothing created
    assert h.parent_group == "Configured Group"        # restored


# ─── Tool payloads: indicator + create-missing checkbox ───────────────────────

def _gl_stub():
    gl = MagicMock()
    gl.gitlab_namespace = "saic-study-group"
    gl.parent_group = "Portfolio"
    return gl


def _tool(key):
    return next(t for t in TOOLS if t["key"] == key)


@pytest.mark.parametrize("key", ["export-epics", "export-issues",
                                 "import-epics", "import-issues",
                                 "export-bundle", "import-bundle"])
def test_group_widget_param_prefilled_with_active_group(key):
    payload = _tool_payload(_tool(key), _gl_stub())
    grp = next(p for p in payload["params"] if p["name"] == "group")
    assert grp["widget"] == "group"
    assert grp["optional"] is True
    assert grp["default"] == "saic-study-group/Portfolio"


@pytest.mark.parametrize("key", ["import-epics", "import-issues"])
def test_import_has_create_missing_bool(key):
    payload = _tool_payload(_tool(key), _gl_stub())
    cm = next(p for p in payload["params"] if p["name"] == "create_missing")
    assert cm["type"] == "bool"
    assert cm["default"] is False


@pytest.mark.parametrize("key", ["export-epics", "export-issues"])
def test_export_has_no_create_missing(key):
    payload = _tool_payload(_tool(key), _gl_stub())
    assert all(p["name"] != "create_missing" for p in payload["params"])


# ─── namespace resolution in _get_or_create_root_group (#202) ─────────────────

def test_create_missing_namespace_falls_back_to_full_path():
    """A namespace given as a URL-slug path (no display-name match) must still
    resolve — the CLI form 'a/b/c/Group' aborted here in the #202 field test."""
    h = IEHarness()
    h.gitlab_namespace = "a/b/c"          # full path, not a display name
    parent = MagicMock()
    parent.id, parent.visibility = 42, "private"
    h.gl.groups.get.return_value = parent
    group = h._get_or_create_root_group()
    h.gl.groups.get.assert_called_once_with("a/b/c")
    h.gl.groups.create.assert_called_once()
    assert h.gl.groups.create.call_args[0][0]["parent_id"] == 42
    assert group is h.gl.groups.create.return_value


def test_create_missing_namespace_unresolvable_aborts(capsys):
    h = IEHarness()
    h.gitlab_namespace = "no/such/path"
    h.gl.groups.get.side_effect = Exception("404")
    assert h._get_or_create_root_group() is None
    out = capsys.readouterr().out
    assert "Root namespace 'no/such/path' not found" in out
    assert "full-path lookup failed: 404" in out
    h.gl.groups.create.assert_not_called()


def test_display_name_without_slash_never_tries_path_lookup():
    """The path fallback is gated on '/' (illegal in display names): a stale or
    ambiguous display name must abort, not silently resolve to some unrelated
    group whose URL path happens to equal the string."""
    h = IEHarness()
    h.gitlab_namespace = "Sandbox"        # no slash → display name only
    assert h._get_or_create_root_group() is None
    h.gl.groups.get.assert_not_called()
    h.gl.groups.create.assert_not_called()


def test_display_name_resolution_wins_over_path_lookup():
    """Display-name resolution is tried first; the path fallback must not fire
    when it succeeds (pins the documented order)."""
    h = IEHarness()
    h.gitlab_namespace = "a/b/c"
    parent = MagicMock()
    parent.id, parent.visibility = 42, "private"
    root = MagicMock()

    def _by_name(name):
        # parent_group misses (forcing creation); the namespace resolves.
        return parent if name == "a/b/c" else None
    h.get_group_by_name = _by_name
    h._get_or_create_root_group()
    h.gl.groups.get.assert_not_called()
    h.gl.groups.create.assert_called_once()
    assert h.gl.groups.create.call_args[0][0]["parent_id"] == 42


def test_import_bundle_create_missing_defaults_on():
    """The bundle is a full-mirror transfer (#206) — unlike the standalone
    importers, create_missing defaults ON."""
    payload = _tool_payload(_tool("import-bundle"), _gl_stub())
    cm = next(p for p in payload["params"] if p["name"] == "create_missing")
    assert cm["type"] == "bool"
    assert cm["default"] is True
