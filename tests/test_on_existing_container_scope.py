"""on_existing epic matching is scoped to the exact container (Refs #199).

GitLab's group-epics endpoint includes descendant groups' epics, which made
same-titled epics in different containers collide on re-import: the
2026-07-07 JamieGroup run recreated the tree perfectly but skipped all 23
root-level twins because their team-08 copies matched through descendant
inclusion (108/131 instead of 131/131).
"""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin
from mixins.bootstrap import BootstrapMixin

pytestmark = pytest.mark.unit


class Host(ImportExportMixin, BootstrapMixin):
    def __init__(self):
        self.gl = MagicMock()


def _epic(title, group_id, iid=1):
    e = MagicMock()
    e.title, e.group_id, e.iid = title, group_id, iid
    return e


def _group(gid, epics):
    g = MagicMock()
    g.id = gid
    g.full_path = "ns/root"
    g.epics.list.return_value = epics
    return g


class TestContainerScope:
    def test_descendant_epic_does_not_match(self):
        """The twin lives in a subgroup (group_id 99) — a root-targeted row
        must NOT see it as existing."""
        root = _group(1, [_epic("Twin", group_id=99)])
        assert Host()._find_epic_by_title(root, "Twin") is None

    def test_same_container_epic_matches(self):
        root = _group(1, [_epic("Twin", group_id=1)])
        found = Host()._find_epic_by_title(root, "Twin")
        assert found is not None and found.group_id == 1

    def test_mixed_results_only_container_match_wins(self):
        sub, own = _epic("Twin", 99, iid=5), _epic("Twin", 1, iid=7)
        root = _group(1, [sub, own])
        found = Host()._find_epic_by_title(root, "Twin")
        assert found is own

    def test_in_container_ambiguity_still_warns(self, capsys):
        a, b = _epic("Twin", 1, iid=1), _epic("Twin", 1, iid=2)
        root = _group(1, [a, b])
        found = Host()._find_epic_by_title(root, "Twin")
        assert found is a
        assert "2 epics titled 'Twin'" in capsys.readouterr().out

    def test_whole_tree_lookup_unaffected(self):
        """import-links endpoint resolution deliberately searches the whole
        tree — _target_epic_titles must keep descendant epics."""
        e = _epic("Twin", 99, iid=5)
        e.id = 5005
        root = _group(1, [e])
        titles = Host()._target_epic_titles(root)
        assert titles["Twin"] == [5005]


class TestEndToEndDupTwins:
    def test_root_twin_imports_when_subgroup_twin_exists(self, tmp_path):
        """The JamieGroup reproduction in miniature: same title in a subgroup
        and at the root — both rows must create, in their own containers."""
        from tests.test_import_parent_remap import RemapHarness

        h = RemapHarness([
            {"title": "Twin", "group_path": "ns/target/sub", "source_root": "ns/target"},
            {"title": "Twin", "group_path": "ns/target",     "source_root": "ns/target"},
        ])
        sub = MagicMock()
        sub.id, sub.full_path = 99, "ns/target/sub"
        created_in = []
        def _sub_create(payload):
            e = MagicMock(); e.id, e.iid, e.title = 8001, 1, payload["title"]
            e.group_id = 99
            created_in.append(("sub", payload["title"]))
            return e
        sub.epics.create.side_effect = _sub_create
        sub.epics.list.return_value = []
        h._build_group_cache = lambda root_group: {"ns/target": h.root,
                                                   "ns/target/sub": sub}
        # after the sub-twin is created, the root listing surfaces it the way
        # GitLab does — through descendant inclusion, with its real group_id
        def _root_list(**kw):
            if not created_in:
                return []
            twin = MagicMock()
            twin.title, twin.group_id, twin.iid, twin.id = "Twin", 99, 1, 8001
            return [twin]
        h.root.epics.list.side_effect = _root_list
        h.root.id = 1
        def _root_create(payload):
            e = MagicMock(); e.id, e.iid, e.title = 8002, 2, payload["title"]
            e.group_id = 1
            created_in.append(("root", payload["title"]))
            return e
        h.root.epics.create.side_effect = _root_create

        f = tmp_path / "epics.json"
        f.write_text(json.dumps(h._rows))
        h._import_epics(input_path=str(f), on_existing="skip")
        assert ("sub", "Twin") in created_in
        assert ("root", "Twin") in created_in     # previously skipped (#199)
