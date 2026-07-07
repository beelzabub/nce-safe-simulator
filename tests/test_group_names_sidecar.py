"""Group/project display names across systems (Refs #200).

Exports write a `<export>-group-names.json` sidecar (relative path → display
name); create_missing_groups / create_missing_projects consume it so
recreated containers are named like the source ("Value Stream 01") instead
of their slug ("vs-01").
"""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin
from mixins.bootstrap import BootstrapMixin

pytestmark = pytest.mark.unit

ROOT_PATH = "ns/target"

NAMES = {"groups": {"vs-01": "Value Stream 01", "vs-01/art-01": "ART 01"},
         "projects": {"vs-01/art-01/team-01-backlog": "Team 01 — Team Backlog"}}


def _names_file(tmp_path, data=None):
    f = tmp_path / "epics-export-group-names.json"
    f.write_text(json.dumps(NAMES if data is None else data))
    return str(f)


# ─── Sidecar emission on export ───────────────────────────────────────────────

class SidecarExportHarness(ImportExportMixin, BootstrapMixin):
    def __init__(self):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "source"
        self.root = MagicMock()
        self.root.full_path = "ns/source"
        epic = MagicMock()
        epic.id, epic.iid, epic.title = 1, 1, "E"
        epic.description, epic.state, epic.labels = "", "opened", []
        epic.web_url, epic.author, epic.group_id = "https://x/1", {"name": "a"}, 5
        self.root.epics.list.return_value = [epic]
        sub = MagicMock()
        sub.full_path, sub.name = "ns/source/vs-01", "Value Stream 01"
        self._descendants = [sub]
        proj = MagicMock()
        proj.path_with_namespace = "ns/source/vs-01/team-01-backlog"
        proj.name = "Team 01 — Team Backlog"
        self.root.projects.list.return_value = [proj]

    def get_group_by_name(self, name):            return self.root
    def list_descendant_groups(self, root):       return self._descendants
    def _build_gid_path_map(self, group):         return {5: "ns/source/vs-01"}
    def _fetch_epic_weights(self, epics):         return {}
    def _fetch_epic_business_values(self, epics, root_namespace=None): return {}
    def _write_file(self, path, fmt, rows, order): pass


class TestSidecarEmission:
    def test_export_writes_sidecar_with_names(self, tmp_path, capsys):
        h = SidecarExportHarness()
        out = tmp_path / "epics.json"
        h._export_epics(output_path=str(out))
        sidecar = tmp_path / "epics-group-names.json"
        assert sidecar.exists()
        data = json.loads(sidecar.read_text())
        assert data["groups"] == {"vs-01": "Value Stream 01"}
        assert data["projects"] == {"vs-01/team-01-backlog": "Team 01 — Team Backlog"}
        assert "Group names sidecar" in capsys.readouterr().out

    def test_sidecar_failure_never_breaks_export(self, tmp_path, capsys):
        h = SidecarExportHarness()
        h.list_descendant_groups = MagicMock(side_effect=RuntimeError("boom"))
        h._export_epics(output_path=str(tmp_path / "epics.json"))
        out = capsys.readouterr().out
        assert "WARN: could not write the group-names sidecar" in out
        assert "Exported 1 epic(s)" in out


# ─── Named creation on import (epics side) ────────────────────────────────────

class NamedCMGHarness(ImportExportMixin, BootstrapMixin):
    """Mirror of the #195 harness, capturing creation payloads."""

    def __init__(self, rows):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "target"
        self._rows = rows
        self.root = MagicMock()
        self.root.full_path = ROOT_PATH
        self.root.id = 1
        self.root.epics.list.return_value = []
        self.cache = {ROOT_PATH: self.root}
        self.created_groups = []
        self._next = iter(range(500, 599))

        def _mk_group(payload):
            g = MagicMock()
            g.id = next(self._next)
            parent_path = next(
                (p for p, gr in list(self.cache.items()) if gr.id == payload["parent_id"]),
                ROOT_PATH)
            g.full_path = f"{parent_path}/{payload['path']}"
            g.epics.list.return_value = []
            g.epics.create.return_value = MagicMock(id=9001, iid=1)
            self.created_groups.append(dict(payload, _full_path=g.full_path))
            return g
        self.gl.groups.create.side_effect = _mk_group
        self.root.epics.create.return_value = MagicMock(id=9002, iid=2)

    def _load_file(self, path):                                return self._rows
    def _resolve_import_target(self, create_missing, dry_run): return self.root
    def _build_group_cache(self, root_group):                  return self.cache
    def _build_valid_epic_ids(self, root_group):               return set()
    def _find_epic_by_title(self, group, title):               return None
    def _set_epic_weight(self, epic, weight):                  pass
    def sanitize_name(self, s):                                return s.lower()
    def _default_export_name(self, stem, fmt):
        import tempfile, pathlib
        return pathlib.Path(tempfile.mkdtemp()) / f"{stem}.{fmt}"


def _run_epics(h, tmp_path, **kw):
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(h._rows))
    h._import_epics(input_path=str(f), **kw)


EPIC_ROW = {"title": "E1", "group_path": "ns/source/vs-01/art-01",
            "source_root": "ns/source"}


class TestNamedGroupCreation:
    def test_created_groups_use_sidecar_names(self, tmp_path):
        h = NamedCMGHarness([dict(EPIC_ROW)])
        _run_epics(h, tmp_path, create_missing_groups=True,
                   group_names=_names_file(tmp_path))
        assert [(g["path"], g["name"]) for g in h.created_groups] == [
            ("vs-01", "Value Stream 01"), ("art-01", "ART 01")]

    def test_missing_key_falls_back_to_slug(self, tmp_path):
        h = NamedCMGHarness([{"title": "E1", "group_path": "ns/source/vs-09",
                              "source_root": "ns/source"}])
        _run_epics(h, tmp_path, create_missing_groups=True,
                   group_names=_names_file(tmp_path))
        assert h.created_groups[0]["name"] == "vs-09"

    def test_no_file_keeps_slug_behavior(self, tmp_path):
        h = NamedCMGHarness([dict(EPIC_ROW)])
        _run_epics(h, tmp_path, create_missing_groups=True)
        assert [g["name"] for g in h.created_groups] == ["vs-01", "art-01"]

    def test_corrupt_file_warns_and_falls_back(self, tmp_path, capsys):
        bad = tmp_path / "bad.json"
        bad.write_text("{nope")
        h = NamedCMGHarness([dict(EPIC_ROW)])
        _run_epics(h, tmp_path, create_missing_groups=True, group_names=str(bad))
        assert "could not be loaded" in capsys.readouterr().out
        assert [g["name"] for g in h.created_groups] == ["vs-01", "art-01"]

    def test_dry_run_previews_display_name(self, tmp_path, capsys):
        h = NamedCMGHarness([dict(EPIC_ROW)])
        _run_epics(h, tmp_path, create_missing_groups=True,
                   group_names=_names_file(tmp_path), dry_run=True)
        out = capsys.readouterr().out
        assert h.created_groups == []
        assert f"would create group '{ROOT_PATH}/vs-01' (name 'Value Stream 01')" in out


# ─── Named creation on import (issues side) ───────────────────────────────────

class TestNamedProjectCreation:
    def test_created_project_uses_sidecar_name(self, tmp_path):
        from tests.test_import_full_fidelity import CMPHarness
        h = CMPHarness([{"title": "I1",
                         "project_path": "ns/source/vs-01/art-01/team-01-backlog",
                         "source_root": "ns/source"}])
        f = tmp_path / "issues.json"
        f.write_text(json.dumps(h._rows))
        h._import_issues(input_path=str(f), create_missing_projects=True,
                         group_names=_names_file(tmp_path))
        assert h.created_projects[0]["name"] == "Team 01 — Team Backlog"
        assert h.created_projects[0]["path"] == "team-01-backlog"
        assert [(g["path"], g["name"]) for g in h.created_groups] == [
            ("vs-01", "Value Stream 01"), ("art-01", "ART 01")]
