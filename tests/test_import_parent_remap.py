"""Within-file parent_id remapping on epic import (Refs #194).

An epics export carries each row's own source-system `id` plus `parent_id`,
so the file is self-describing: parents are created first and children link
through the source_id → new_id map. Cross-root imports never trust raw
target-id matches — an equal id on a different system is coincidence.
"""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin
from mixins.bootstrap import BootstrapMixin

pytestmark = pytest.mark.unit

ROOT_PATH = "ns/target"


def _grp(full_path):
    g = MagicMock()
    g.full_path = full_path
    return g


class RemapHarness(ImportExportMixin, BootstrapMixin):
    """Real parent resolution + ordering; GitLab faked at the group level."""

    def __init__(self, rows, target_epic_ids=None, existing_by_title=None):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "target"
        self._rows = rows
        self.root = _grp(ROOT_PATH)
        self._existing = existing_by_title or {}
        self._target_ids = target_epic_ids or set()
        self.created = []            # payloads in creation order
        self._next_id = iter(range(9001, 9999))

        def _create(payload):
            e = MagicMock()
            e.id  = next(self._next_id)
            e.iid = e.id - 9000
            e.title = payload["title"]
            self.created.append(dict(payload, _new_id=e.id))
            return e
        self.root.epics.create.side_effect = _create
        self.root.epics.list.return_value = list(self._existing.values())

    # plumbing stubs
    def _load_file(self, path):                              return self._rows
    def _resolve_import_target(self, create_missing, dry_run): return self.root
    def _build_group_cache(self, root_group):                return {ROOT_PATH: self.root}
    def _build_valid_epic_ids(self, root_group):             return set(self._target_ids)
    def _set_epic_weight(self, epic, weight):                pass


def _run(h, tmp_path, **kw):
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(h._rows))
    h._import_epics(input_path=str(f), **kw)
    return {p["title"]: p for p in h.created}


def _row(id=None, title=None, parent_id=None, group_path=ROOT_PATH, source_root=None):
    r = {"title": title or f"Epic {id}", "group_path": group_path}
    if id is not None:          r["id"] = id
    if parent_id is not None:   r["parent_id"] = parent_id
    if source_root is not None: r["source_root"] = source_root
    return r


class TestInFileRemap:
    def test_child_links_to_parents_new_id(self, tmp_path):
        h = RemapHarness([
            _row(id=100, title="Parent"),
            _row(id=101, title="Child", parent_id=100),
        ])
        by = _run(h, tmp_path)
        assert by["Child"]["parent_id"] == by["Parent"]["_new_id"]

    def test_child_before_parent_in_file_still_links(self, tmp_path):
        """Topological order: the parent row appears AFTER the child row."""
        h = RemapHarness([
            _row(id=101, title="Child", parent_id=100),
            _row(id=100, title="Parent"),
        ])
        by = _run(h, tmp_path)
        titles_in_order = [p["title"] for p in h.created]
        assert titles_in_order.index("Parent") < titles_in_order.index("Child")
        assert by["Child"]["parent_id"] == by["Parent"]["_new_id"]

    def test_three_level_chain(self, tmp_path):
        h = RemapHarness([
            _row(id=3, title="Leaf",   parent_id=2),
            _row(id=1, title="Top"),
            _row(id=2, title="Middle", parent_id=1),
        ])
        by = _run(h, tmp_path)
        assert by["Middle"]["parent_id"] == by["Top"]["_new_id"]
        assert by["Leaf"]["parent_id"]   == by["Middle"]["_new_id"]

    def test_no_needs_parent_label_when_resolved_in_file(self, tmp_path):
        h = RemapHarness([
            _row(id=100, title="Parent"),
            _row(id=101, title="Child", parent_id=100),
        ])
        by = _run(h, tmp_path)
        assert "import::needs-parent" not in by["Child"].get("labels", [])

    def test_parent_skipped_as_existing_still_maps(self, tmp_path):
        """on_existing=skip: the parent already lives on the target — the
        child must link to the EXISTING epic's id."""
        existing = MagicMock()
        existing.id, existing.iid, existing.title = 7777, 42, "Parent"
        h = RemapHarness(
            [_row(id=100, title="Parent"), _row(id=101, title="Child", parent_id=100)],
            existing_by_title={"Parent": existing},
        )
        by = _run(h, tmp_path, on_existing="skip")
        assert "Parent" not in by                      # skipped, not recreated
        assert by["Child"]["parent_id"] == 7777

    def test_failed_parent_degrades_child_to_label(self, tmp_path):
        h = RemapHarness([
            _row(id=100, title="Parent"),
            _row(id=101, title="Child", parent_id=100),
        ])
        created = []
        def _create(payload):
            if payload["title"] == "Parent":
                raise Exception("boom")
            e = MagicMock(); e.id, e.iid = 9001, 1
            created.append(dict(payload))
            return e
        h.root.epics.create.side_effect = _create
        f = tmp_path / "epics.json"; f.write_text(json.dumps(h._rows))
        h._import_epics(input_path=str(f))
        child = next(p for p in created if p["title"] == "Child")
        assert "import::needs-parent" in child.get("labels", [])
        assert "parent_id" not in child

    def test_failed_parent_with_skip_mode_skips_child(self, tmp_path, capsys):
        """unresolved_parent=skip is honored for runtime orphans too."""
        h = RemapHarness([
            _row(id=100, title="Parent"),
            _row(id=101, title="Child", parent_id=100),
        ])
        created = []
        def _create(payload):
            if payload["title"] == "Parent":
                raise Exception("boom")
            created.append(dict(payload))
            return MagicMock(id=9001, iid=1)
        h.root.epics.create.side_effect = _create
        f = tmp_path / "epics.json"; f.write_text(json.dumps(h._rows))
        h._import_epics(input_path=str(f), unresolved_parent="skip")
        assert created == []
        assert "SKIP — in-file parent" in capsys.readouterr().out


class TestCrossRootDistrust:
    def test_raw_target_id_not_trusted_cross_root(self, tmp_path, capsys):
        """parent_id 5555 exists on the target but the file's root differs —
        attaching would link to an unrelated epic. Must label instead."""
        h = RemapHarness(
            [_row(id=101, title="Child", parent_id=5555,
                  group_path="ns/source/team", source_root="ns/source")],
            target_epic_ids={5555},
        )
        by = _run(h, tmp_path)
        assert "parent_id" not in by["Child"]
        assert "import::needs-parent" in by["Child"]["labels"]
        assert "not trusted cross-root" in capsys.readouterr().out

    def test_raw_target_id_trusted_same_root(self, tmp_path):
        h = RemapHarness(
            [_row(id=101, title="Child", parent_id=5555, source_root=ROOT_PATH)],
            target_epic_ids={5555},
        )
        by = _run(h, tmp_path)
        assert by["Child"]["parent_id"] == 5555

    def test_legacy_unstamped_subtree_export_keeps_live_ids(self, tmp_path):
        """Regression: an un-stamped same-system subtree export makes the LCP
        guess a deeper path than the target root. A guess must never trigger
        cross-root distrust — the live parent id stays valid."""
        h = RemapHarness(
            [{"title": "Legacy", "group_path": f"{ROOT_PATH}/sub/team",
              "parent_id": 5555}],
            target_epic_ids={5555},
        )
        by = _run(h, tmp_path)
        assert by["Legacy"]["parent_id"] == 5555
        assert "import::needs-parent" not in by["Legacy"].get("labels", [])

    def test_stamped_overlapping_roots_keep_live_ids(self, tmp_path):
        """A trusted stamp naming a subtree of the target root (or an
        ancestor) is the same group tree — same id space, ids trusted."""
        h = RemapHarness(
            [_row(id=101, title="SubExport", parent_id=5555,
                  group_path=f"{ROOT_PATH}/sub", source_root=f"{ROOT_PATH}/sub"),
             _row(id=102, title="AncestorExport", parent_id=5555,
                  group_path="ns", source_root="ns")],
            target_epic_ids={5555},
        )
        by = _run(h, tmp_path)
        assert by["SubExport"]["parent_id"] == 5555
        assert by["AncestorExport"]["parent_id"] == 5555

    def test_in_file_beats_target_id_collision(self, tmp_path):
        """The dangerous case: parent_id matches BOTH a row in the file and a
        live target epic. The in-file parent must win."""
        h = RemapHarness(
            [_row(id=100, title="Parent"),
             _row(id=101, title="Child", parent_id=100)],
            target_epic_ids={100},          # collision with an unrelated target epic
        )
        by = _run(h, tmp_path)
        assert by["Child"]["parent_id"] == by["Parent"]["_new_id"]
        assert by["Child"]["parent_id"] != 100


class TestEdges:
    def test_cycle_broken_at_first_row_rest_still_link(self, tmp_path, capsys):
        """A↔B parent cycle in the file: the cycle is broken once (first row
        orphaned + labeled), and the remaining edge is honored — B links to
        the A that was just created. Minimal structure loss."""
        h = RemapHarness([
            _row(id=1, title="A", parent_id=2),
            _row(id=2, title="B", parent_id=1),
        ])
        by = _run(h, tmp_path)
        out = capsys.readouterr().out
        assert "cycle" in out
        assert "parent_id" not in by["A"]
        assert "import::needs-parent" in by["A"]["labels"]
        assert by["B"]["parent_id"] == by["A"]["_new_id"]
        assert "import::needs-parent" not in by["B"].get("labels", [])

    def test_descendant_of_cycle_keeps_its_link(self, tmp_path):
        """A non-cycle child hanging off a cycle member is emitted after its
        parent and keeps the link — only the break point is orphaned."""
        h = RemapHarness([
            _row(id=1, title="Desc", parent_id=2),   # child of cycle member A
            _row(id=2, title="A", parent_id=3),      # A ↔ B cycle
            _row(id=3, title="B", parent_id=2),
        ])
        by = _run(h, tmp_path)
        assert "parent_id" not in by["A"]                       # break point
        assert by["Desc"]["parent_id"] == by["A"]["_new_id"]    # link kept
        assert by["B"]["parent_id"]    == by["A"]["_new_id"]
        assert "import::needs-parent" not in by["Desc"].get("labels", [])

    def test_duplicate_file_ids_warn_first_wins(self, tmp_path, capsys):
        h = RemapHarness([
            _row(id=100, title="First"),
            _row(id=100, title="Second"),
            _row(id=101, title="Child", parent_id=100),
        ])
        by = _run(h, tmp_path)
        assert "duplicate 'id'" in capsys.readouterr().out
        assert by["Child"]["parent_id"] == by["First"]["_new_id"]

    def test_dry_run_shows_symbolic_parent_and_creates_nothing(self, tmp_path, capsys):
        h = RemapHarness([
            _row(id=100, title="Parent"),
            _row(id=101, title="Child", parent_id=100),
        ])
        _run(h, tmp_path, dry_run=True)
        out = capsys.readouterr().out
        assert h.created == []
        assert "parent=(epic from row 1)" in out
        assert "needs-parent" not in out.split("Orphan summary")[0].replace(
            "'import::needs-parent'", "")  # child not orphaned in preview

    def test_rows_without_ids_keep_legacy_behavior(self, tmp_path):
        """No id column at all — same-root live parent ids still work."""
        h = RemapHarness(
            [{"title": "Plain", "group_path": ROOT_PATH, "parent_id": 5555}],
            target_epic_ids={5555},
        )
        by = _run(h, tmp_path)
        assert by["Plain"]["parent_id"] == 5555


class TestMultiTitleMatchWarn:
    def test_multiple_same_title_epics_warn(self, capsys):
        h = RemapHarness([])
        a, b = MagicMock(), MagicMock()
        a.title = b.title = "Twin"
        a.iid, b.iid = 1, 2
        grp = MagicMock()
        grp.full_path = ROOT_PATH
        grp.epics.list.return_value = [a, b]
        found = h._find_epic_by_title(grp, "Twin")
        assert found is a
        assert "2 epics titled 'Twin'" in capsys.readouterr().out
