"""_collect_snapshot_groups_projects must support arbitrary hierarchy depth.

The snapshot previously walked a hardcoded 4 levels (portfolio/vs/art/team) and
collected projects only at the team level, so groups nested deeper — and their
projects/issues — were silently dropped from groups.json / projects.json. Report
placement resolves by walking parent_id, so a missing deep group means its epics
misgroup to the root. The walk is now recursive.
"""
import pytest
from unittest.mock import MagicMock

from mixins.reports import ReportsMixin

pytestmark = pytest.mark.unit


class SnapshotHarness(ReportsMixin):
    def __init__(self, gl):
        self.gl = gl


def _mk_group(gid, name, full_path, subgroup_ids, project_ids):
    g = MagicMock()
    g.id = gid
    g.name = name
    g.path = name
    g.full_path = full_path
    g.web_url = f"http://gl/{full_path}"
    g.subgroups.list.return_value = [MagicMock(id=s) for s in subgroup_ids]
    g.projects.list.return_value = [MagicMock(id=p, name=f"proj-{p}") for p in project_ids]
    return g


def _mk_project(pid):
    p = MagicMock()
    p.id = pid
    p.name = f"proj-{pid}"
    p.path = f"proj-{pid}"
    p.path_with_namespace = f"ns/proj-{pid}"
    p.name_with_namespace = f"ns / proj-{pid}"
    p.namespace = {"id": 99}
    p.web_url = f"http://gl/proj-{pid}"
    p.issues_enabled = True
    return p


def test_snapshot_walks_arbitrary_depth():
    # A 5-level chain: root → vs → art → team → subteam, one project per group.
    g1 = _mk_group(1, "root",    "ns/root",                          [2], [11])
    g2 = _mk_group(2, "vs",      "ns/root/vs",                       [3], [12])
    g3 = _mk_group(3, "art",     "ns/root/vs/art",                   [4], [13])
    g4 = _mk_group(4, "team",    "ns/root/vs/art/team",              [5], [14])
    g5 = _mk_group(5, "subteam", "ns/root/vs/art/team/subteam",      [],  [15])
    groups = {g.id: g for g in (g1, g2, g3, g4, g5)}

    gl = MagicMock()
    gl.groups.get.side_effect = lambda gid: groups[gid]
    gl.projects.get.side_effect = lambda pid: _mk_project(pid)

    all_groups, all_projects = SnapshotHarness(gl)._collect_snapshot_groups_projects(g1)

    by_id = {g["id"]: g for g in all_groups}
    # every group present at every depth — nothing dropped past level 4
    assert set(by_id) == {1, 2, 3, 4, 5}
    # parent_id chain is intact so _group_path can walk up from any depth
    assert by_id[1]["parent_id"] is None
    assert by_id[2]["parent_id"] == 1
    assert by_id[3]["parent_id"] == 2
    assert by_id[4]["parent_id"] == 3
    assert by_id[5]["parent_id"] == 4
    # informational level: named for depths 0-3, capped at "team" beyond
    assert [by_id[i]["level"] for i in (1, 2, 3, 4, 5)] == \
        ["portfolio", "vs", "art", "team", "team"]
    # projects collected from every group, including the deep ones
    assert {p["id"] for p in all_projects} == {11, 12, 13, 14, 15}
