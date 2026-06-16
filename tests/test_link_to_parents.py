"""Unit tests for bootstrap._link_to_parents cross-program guard (Refs #16)."""
import sys
import pytest
from unittest.mock import MagicMock



from mixins.bootstrap import _link_to_parents


def _epic(id, group_id, title="Epic"):
    e = MagicMock()
    e.id       = id
    e.group_id = group_id
    e.title    = title
    return e


def _pair(epic):
    return (epic, "Capability")


class TestLinkToParentsGuard:
    def test_links_child_to_same_program_parent(self):
        child  = _epic(id=1, group_id=10, title="Child")
        parent = _epic(id=2, group_id=20, title="Parent")

        _link_to_parents([_pair(child)], [_pair(parent)],
                         scope_by_group={10: [_pair(parent)]})

        assert child.parent_id == parent.id
        child.save.assert_called_once()

    def test_skips_and_warns_when_scope_list_is_empty(self, capsys):
        child  = _epic(id=1, group_id=10, title="Orphaned Child")
        parent = _epic(id=2, group_id=20, title="Cross-Program Parent")

        _link_to_parents([_pair(child)], [_pair(parent)],
                         scope_by_group={10: []})

        child.save.assert_not_called()
        assert "Warning" in capsys.readouterr().out

    def test_skips_and_warns_when_group_id_absent_from_scope(self, capsys):
        child  = _epic(id=1, group_id=99, title="Unknown Group Child")
        parent = _epic(id=2, group_id=20, title="Some Parent")

        _link_to_parents([_pair(child)], [_pair(parent)],
                         scope_by_group={10: [_pair(parent)]})

        child.save.assert_not_called()
        assert "Warning" in capsys.readouterr().out

    def test_never_links_cross_program(self):
        pmw_cap    = _epic(id=1, group_id=101, title="PMW ART Cap")
        bmw_cap    = _epic(id=2, group_id=102, title="BMW ART Cap")
        pmw_vs_cap = _epic(id=3, group_id=201, title="PMW VS Cap")
        bmw_vs_cap = _epic(id=4, group_id=202, title="BMW VS Cap")

        scope = {101: [_pair(pmw_vs_cap)], 102: [_pair(bmw_vs_cap)]}
        _link_to_parents(
            [_pair(pmw_cap), _pair(bmw_cap)],
            [_pair(pmw_vs_cap), _pair(bmw_vs_cap)],
            scope_by_group=scope,
        )

        assert pmw_cap.parent_id == pmw_vs_cap.id
        assert bmw_cap.parent_id == bmw_vs_cap.id

    def test_without_scope_picks_any_parent(self):
        child   = _epic(id=1, group_id=10, title="Child")
        parent1 = _epic(id=2, group_id=20, title="Parent A")
        parent2 = _epic(id=3, group_id=30, title="Parent B")

        _link_to_parents([_pair(child)], [_pair(parent1), _pair(parent2)])

        assert child.parent_id in (parent1.id, parent2.id)
        child.save.assert_called_once()

    def test_no_op_when_parents_empty(self):
        child = _epic(id=1, group_id=10)
        _link_to_parents([_pair(child)], [])
        child.save.assert_not_called()

    def test_no_op_when_children_empty(self):
        parent = _epic(id=2, group_id=20)
        _link_to_parents([], [_pair(parent)])
        parent.save.assert_not_called()

    def test_save_exception_is_caught_and_printed(self, capsys):
        child  = _epic(id=1, group_id=10, title="Failing Child")
        parent = _epic(id=2, group_id=20, title="Parent")
        child.save.side_effect = Exception("API error")

        _link_to_parents([_pair(child)], [_pair(parent)],
                         scope_by_group={10: [_pair(parent)]})

        assert "Failed" in capsys.readouterr().out
