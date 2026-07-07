"""create_missing_groups on epic import (Refs #195).

When the target mirrors the source structure incompletely, the importer can
recreate the missing subgroup chain along each row's reconciled path —
instead of flattening rows into the fallback group / target root. Creation
only happens from a TRUSTED source root (export stamp or explicit override);
an LCP-guessed root never creates groups.
"""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin
from mixins.bootstrap import BootstrapMixin

pytestmark = pytest.mark.unit

ROOT_PATH = "ns/target"


class CMGHarness(ImportExportMixin, BootstrapMixin):
    def __init__(self, rows, extra_cache=None):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "target"
        self._rows = rows
        self.root = MagicMock()
        self.root.full_path = ROOT_PATH
        self.root.id = 1
        self.root.epics.list.return_value = []
        self.cache = {ROOT_PATH: self.root}
        for path, grp in (extra_cache or {}).items():
            self.cache[path] = grp
        self.created_groups = []      # payloads passed to gl.groups.create
        self.created_epics = {}       # group full_path -> [epic payloads]
        self._next_gid = iter(range(500, 599))

        def _mk_group(payload):
            g = MagicMock()
            g.id = next(self._next_gid)
            parent_path = next(
                (p for p, gr in list(self.cache.items()) if gr.id == payload["parent_id"]),
                ROOT_PATH)
            g.full_path = f"{parent_path}/{payload['path']}"
            g.epics.list.return_value = []
            g.epics.create.side_effect = lambda ep, _g=g: self._epic(_g, ep)
            self.created_groups.append(dict(payload, _full_path=g.full_path, _id=g.id))
            return g
        self.gl.groups.create.side_effect = _mk_group
        self.root.epics.create.side_effect = lambda ep: self._epic(self.root, ep)

    def _epic(self, grp, payload):
        e = MagicMock()
        e.id, e.iid = 9001 + len(self.created_epics), 1
        self.created_epics.setdefault(grp.full_path, []).append(dict(payload))
        return e

    def _load_file(self, path):                               return self._rows
    def _resolve_import_target(self, create_missing, dry_run): return self.root
    def _build_group_cache(self, root_group):                 return self.cache
    def _build_valid_epic_ids(self, root_group):              return set()
    def _find_epic_by_title(self, group, title):              return None
    def _set_epic_weight(self, epic, weight):                 pass


def _run(h, tmp_path, **kw):
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(h._rows))
    h._import_epics(input_path=str(f), **kw)


def _row(title, group_path, source_root="ns/source"):
    r = {"title": title, "group_path": group_path}
    if source_root is not None:
        r["source_root"] = source_root
    return r


class TestChainCreation:
    def test_missing_chain_created_and_epic_placed(self, tmp_path):
        h = CMGHarness([_row("E1", "ns/source/vs-01/art-02")])
        _run(h, tmp_path, create_missing_groups=True)
        chain = [g["_full_path"] for g in h.created_groups]
        assert chain == [f"{ROOT_PATH}/vs-01", f"{ROOT_PATH}/vs-01/art-02"]
        assert "E1" in [e["title"] for e in h.created_epics[f"{ROOT_PATH}/vs-01/art-02"]]

    def test_parent_ids_chain_correctly(self, tmp_path):
        h = CMGHarness([_row("E1", "ns/source/a/b")])
        _run(h, tmp_path, create_missing_groups=True)
        first, second = h.created_groups
        assert first["parent_id"] == h.root.id       # a under root
        assert second["parent_id"] == first["_id"]   # b under the just-created a

    def test_second_row_reuses_created_chain(self, tmp_path):
        h = CMGHarness([
            _row("E1", "ns/source/vs-01"),
            _row("E2", "ns/source/vs-01"),
        ])
        _run(h, tmp_path, create_missing_groups=True)
        assert len(h.created_groups) == 1
        assert len(h.created_epics[f"{ROOT_PATH}/vs-01"]) == 2

    def test_existing_prefix_only_missing_tail_created(self, tmp_path):
        vs = MagicMock()
        vs.id = 400
        vs.full_path = f"{ROOT_PATH}/vs-01"
        vs.epics.list.return_value = []
        h = CMGHarness([_row("E1", "ns/source/vs-01/art-02")],
                       extra_cache={f"{ROOT_PATH}/vs-01": vs})
        _run(h, tmp_path, create_missing_groups=True)
        assert [g["path"] for g in h.created_groups] == ["art-02"]
        assert h.created_groups[0]["parent_id"] == 400

    def test_same_root_incomplete_mirror_recreated(self, tmp_path):
        """Same-system import where the subgroup was deleted: stamp equals the
        target root and the chain is recreated under it."""
        h = CMGHarness([_row("E1", f"{ROOT_PATH}/vs-09", source_root=ROOT_PATH)])
        _run(h, tmp_path, create_missing_groups=True)
        assert [g["_full_path"] for g in h.created_groups] == [f"{ROOT_PATH}/vs-09"]


class TestGuardrails:
    def test_flag_off_falls_back_to_root(self, tmp_path, capsys):
        h = CMGHarness([_row("E1", "ns/source/vs-01")])
        _run(h, tmp_path)
        assert h.created_groups == []
        assert "E1" in [e["title"] for e in h.created_epics.get(ROOT_PATH, [])]

    def test_guessed_root_never_creates_groups(self, tmp_path):
        """Un-stamped file → LCP guess → untrusted → no group creation."""
        h = CMGHarness([
            {"title": "E1", "group_path": "ns/elsewhere/vs-01/art-01"},
            {"title": "E2", "group_path": "ns/elsewhere/vs-01/art-02"},
        ])
        _run(h, tmp_path, create_missing_groups=True)
        assert h.created_groups == []

    def test_fallback_dest_group_still_wins_without_trusted_root(self, tmp_path):
        dest = MagicMock()
        dest.id = 401
        dest.full_path = f"{ROOT_PATH}/landing"
        dest.epics.list.return_value = []
        dest.epics.create.side_effect = lambda ep: h._epic(dest, ep)
        h = CMGHarness([{"title": "E1", "group_path": "ns/elsewhere/x"}],
                       extra_cache={f"{ROOT_PATH}/landing": dest})
        _run(h, tmp_path, create_missing_groups=True, dest_group=f"{ROOT_PATH}/landing")
        assert h.created_groups == []
        assert "E1" in [e["title"] for e in h.created_epics[f"{ROOT_PATH}/landing"]]

    def test_dry_run_plans_but_creates_nothing(self, tmp_path, capsys):
        h = CMGHarness([_row("E1", "ns/source/vs-01/art-02")])
        _run(h, tmp_path, create_missing_groups=True, dry_run=True)
        out = capsys.readouterr().out
        assert h.created_groups == []
        h.gl.groups.create.assert_not_called()
        assert f"[dry] would create group '{ROOT_PATH}/vs-01'" in out
        assert f"[dry] would create group '{ROOT_PATH}/vs-01/art-02'" in out
        assert f"group={ROOT_PATH}/vs-01/art-02" in out       # preview shows intended placement
        assert "2 missing subgroup(s) would be created" in out

    def test_summary_line_reports_created_count(self, tmp_path, capsys):
        h = CMGHarness([_row("E1", "ns/source/vs-01/art-02")])
        _run(h, tmp_path, create_missing_groups=True)
        assert "2 missing subgroup(s) created" in capsys.readouterr().out
