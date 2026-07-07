"""Issue → epic link resolution on import (Refs #197).

An issues export carries the SOURCE system's epic_id; applying it verbatim
either loses the link or — on an id collision — silently attaches the issue
to an unrelated target epic. Resolution now runs: ① paired-import id map →
② exact epic_title match → ③ raw id (same-root imports only).
"""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin, ISSUE_EXPORT_FIELDS
from mixins.bootstrap import BootstrapMixin

pytestmark = pytest.mark.unit

ROOT_PATH = "ns/target"
PROJ_PATH = f"{ROOT_PATH}/team/backlog"


class LinkHarness(ImportExportMixin, BootstrapMixin):
    def __init__(self, rows, target_epics=None):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "target"
        self._rows = rows
        self.root = MagicMock()
        self.root.full_path = ROOT_PATH
        self.root.id = 1
        eps = []
        for eid, title in (target_epics or []):
            e = MagicMock()
            e.id, e.title = eid, title
            eps.append(e)
        self.root.epics.list.return_value = eps
        self.proj = MagicMock()
        self.proj.path_with_namespace = PROJ_PATH
        self.proj.issues.list.return_value = []
        self.created = []      # created issue mocks

        def _create(payload):
            iss = MagicMock()
            iss.iid = len(self.created) + 1
            iss.title = payload["title"]
            iss.epic_id = None
            self.created.append(iss)
            return iss
        self.proj.issues.create.side_effect = _create

    def _load_file(self, path):                                return self._rows
    def _resolve_import_target(self, create_missing, dry_run): return self.root
    def _build_project_cache(self, root_group):                return {PROJ_PATH: self.proj}
    def _find_issue_by_title(self, project, title, cache=None):            return None


def _run(h, tmp_path, **kw):
    f = tmp_path / "issues.json"
    f.write_text(json.dumps(h._rows))
    h._import_issues(input_path=str(f), **kw)


def _row(title="I1", epic_id=None, epic_title=None, source_root="ns/source",
         project_path=PROJ_PATH):
    r = {"title": title, "project_path": project_path}
    if source_root is not None: r["source_root"] = source_root
    if epic_id is not None:     r["epic_id"] = epic_id
    if epic_title is not None:  r["epic_title"] = epic_title
    return r


class TestExportCarriesEpicTitle:
    def test_field_present(self):
        assert "epic_title" in ISSUE_EXPORT_FIELDS


class TestIdMapTier:
    def test_id_map_resolves_to_new_epic(self, tmp_path):
        h = LinkHarness([_row(epic_id=5196381)])
        m = tmp_path / "map.json"
        m.write_text(json.dumps({"5196381": 9042}))
        _run(h, tmp_path, epic_id_map=str(m))
        assert h.created[0].epic_id == 9042

    def test_id_map_beats_title_and_raw(self, tmp_path):
        h = LinkHarness([_row(epic_id=100, epic_title="Twin")],
                        target_epics=[(100, "Unrelated"), (7, "Twin")])
        m = tmp_path / "map.json"
        m.write_text(json.dumps({"100": 555}))
        _run(h, tmp_path, epic_id_map=str(m))
        assert h.created[0].epic_id == 555

    def test_unreadable_map_warns_and_degrades(self, tmp_path, capsys):
        h = LinkHarness([_row(epic_id=100, epic_title="Epic X")],
                        target_epics=[(9, "Epic X")])
        _run(h, tmp_path, epic_id_map=str(tmp_path / "missing.json"))
        assert "could not be loaded" in capsys.readouterr().out
        assert h.created[0].epic_id == 9        # title tier still resolves


class TestTitleTier:
    def test_title_match_resolves_cross_root(self, tmp_path):
        h = LinkHarness([_row(epic_id=5196381, epic_title="Payments Platform")],
                        target_epics=[(9042, "Payments Platform")])
        _run(h, tmp_path)
        assert h.created[0].epic_id == 9042

    def test_ambiguous_title_warns_first_wins(self, tmp_path, capsys):
        h = LinkHarness([_row(epic_title="Twin")],
                        target_epics=[(11, "Twin"), (12, "Twin")])
        _run(h, tmp_path)
        assert h.created[0].epic_id == 11
        assert "2 target epics titled 'Twin'" in capsys.readouterr().out


class TestRawIdTier:
    def test_same_root_raw_id_kept(self, tmp_path):
        h = LinkHarness([_row(epic_id=4242, source_root=ROOT_PATH)])
        _run(h, tmp_path)
        assert h.created[0].epic_id == 4242

    def test_cross_root_raw_id_dropped_with_warn(self, tmp_path, capsys):
        """The collision hazard: epic 4242 exists on the target but the file
        is from a disjoint root — the link must be dropped, not mis-attached."""
        h = LinkHarness([_row(epic_id=4242)], target_epics=[(4242, "Unrelated")])
        _run(h, tmp_path)
        assert h.created[0].epic_id is None
        out = capsys.readouterr().out
        assert "epic link dropped" in out
        assert "created #1" in out              # issue itself still imports

    def test_unstamped_file_keeps_legacy_raw_id(self, tmp_path):
        """No stamp → LCP guess → untrusted → same-root behavior preserved."""
        h = LinkHarness([{"title": "I1", "project_path": PROJ_PATH, "epic_id": 4242}])
        _run(h, tmp_path)
        assert h.created[0].epic_id == 4242


class TestUpdatePath:
    def test_update_applies_resolved_epic(self, tmp_path):
        existing = MagicMock()
        existing.iid, existing.title = 42, "I1"
        h = LinkHarness([_row(epic_title="Epic X")], target_epics=[(9, "Epic X")])
        h._find_issue_by_title = lambda project, title, cache=None: existing
        _run(h, tmp_path, on_existing="update")
        assert existing.epic_id == 9
        existing.save.assert_called()


class TestPairedMapEmission:
    def test_epics_import_writes_id_map_file(self, tmp_path, monkeypatch):
        """A real epics import persists source_id → new id for pairing."""
        from tests.test_import_parent_remap import RemapHarness, _row as _erow
        h = RemapHarness([_erow(id=100, title="Parent"),
                          _erow(id=101, title="Child", parent_id=100)])
        out_map = tmp_path / "epic-id-map.json"
        monkeypatch.setattr(h, "_default_export_name",
                            lambda stem, fmt: out_map)
        f = tmp_path / "epics.json"
        f.write_text(json.dumps(h._rows))
        h._import_epics(input_path=str(f))
        data = json.loads(out_map.read_text())
        assert set(data) == {"100", "101"}
        assert all(isinstance(v, int) for v in data.values())

    def test_dry_run_writes_no_map(self, tmp_path, monkeypatch):
        from tests.test_import_parent_remap import RemapHarness, _row as _erow
        h = RemapHarness([_erow(id=100, title="Parent")])
        out_map = tmp_path / "epic-id-map.json"
        monkeypatch.setattr(h, "_default_export_name", lambda stem, fmt: out_map)
        f = tmp_path / "epics.json"
        f.write_text(json.dumps(h._rows))
        h._import_epics(input_path=str(f), dry_run=True)
        assert not out_map.exists()
