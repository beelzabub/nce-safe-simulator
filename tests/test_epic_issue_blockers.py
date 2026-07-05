"""Tests for epic-blocked-by-Issue links in the blocking graph (issue #177).

GitLab's work-items model creates cross-type blocking links; an epic blocked
by an Issue appears in neither the epic->epic REST graph (/related_epics)
nor the issue->issue links. A GraphQL pass over the linked-items widget
merges issue-type blockers into each epic's relationship entry.
"""
from unittest.mock import MagicMock

from tests.conftest import ReportsHarness, make_epic


class _FakeResp:
    def __init__(self, payload, ok=True):
        self._payload = payload
        self.ok = ok

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, by_url):
        self._by_url = by_url

    def get(self, url, *args, **kwargs):
        if url not in self._by_url:
            return _FakeResp([], ok=False)
        return _FakeResp(self._by_url[url])


def _related_url(group_id, iid):
    return f"https://gitlab.com/api/v4/groups/{group_id}/epics/{iid}/related_epics"


def _wi_page(nodes, has_next=False, cursor=None):
    return {"group": {"workItems": {
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
        "nodes": nodes,
    }}}


def _wi_node(iid, ns_path, linked):
    return {
        "iid": str(iid),
        "namespace": {"fullPath": ns_path},
        "widgets": [{}, {"linkedItems": {"nodes": linked}}],
    }


def _blocked_by_issue(id, title, url="https://gitlab.example/i"):
    return {"linkType": "is_blocked_by",
            "workItem": {"id": f"gid://gitlab/WorkItem/{id}", "iid": str(id),
                         "title": title, "webUrl": url,
                         "workItemType": {"name": "Issue"}}}


def _blocked_by_epic_wi(id, title):
    return {"linkType": "is_blocked_by",
            "workItem": {"id": f"gid://gitlab/WorkItem/{id}", "iid": str(id),
                         "title": title, "webUrl": "https://gitlab.example/e",
                         "workItemType": {"name": "Epic"}}}


ROOT_NS = "test-portfolio"        # the harness root group (id 1)
TEAM_NS = "test-portfolio/team"   # descendant group 10 — make_epic's default group_id


def _make_harness(epics, by_url, gql_pages):
    h = ReportsHarness()
    h._all_epics_cache = {h.parent_group: epics}
    h._make_session = lambda: _FakeSession(by_url)
    team = MagicMock()
    team.id = 10
    team.full_path = TEAM_NS
    h._rd_root_obj.descendant_groups.list = MagicMock(return_value=[team])
    pages = list(gql_pages)
    h.graphql_query = lambda *a, **k: pages.pop(0) if pages else None
    return h


def test_epic_blocked_only_by_issue_is_recorded():
    # Mirrors live #47: epic::feature under a portfolio epic, blocked by two
    # Issues — invisible to /related_epics.
    e37 = make_epic(id=94, iid=37, title="Portfolio Epic 1", etype="Epic")
    e45 = make_epic(id=96, iid=45, title="Child 3 Epic", etype="Feature")
    e45["parent_id"] = 94
    e47 = make_epic(id=98, iid=47, title="Child 3-1 Epic", etype="Feature")
    e47["parent_id"] = 96
    by_url = {_related_url(10, i) : [] for i in (37, 45, 47)}
    gql = [_wi_page([_wi_node(47, TEAM_NS, [
        _blocked_by_issue(135, "ET17: CCOP vs MM Documentation Consolidation"),
        _blocked_by_issue(147, "Audit IO Portfolio Backlog"),
    ])])]

    h = _make_harness([e37, e45, e47], by_url, gql)
    result = h._fetch_blocking_graph(h._rd_root_obj)

    (rel,) = result["relationships"]
    assert rel["blocked_epic"]["id_int"] == 98
    assert [(b["item_type"], b["title"]) for b in rel["blocked_by"]] == [
        ("Issue", "ET17: CCOP vs MM Documentation Consolidation"),
        ("Issue", "Audit IO Portfolio Backlog"),
    ]
    # Portfolio ancestry works exactly as for epic blockers.
    assert [a["id_int"] for a in rel["at_risk_portfolio_epics"]] == [94]
    # Reconciled blocked_by_count includes issue blockers.
    assert e47["blocked_by_count"] == 2


def test_mixed_epic_and_issue_blockers_merge():
    e1 = make_epic(id=1, iid=1, title="P", etype="Epic")
    e2 = make_epic(id=2, iid=2, title="F", etype="Feature")
    e2["parent_id"] = 1
    e3 = make_epic(id=3, iid=3, title="Blocker Epic", etype="Feature")
    by_url = {
        _related_url(10, 1): [],
        _related_url(10, 3): [],
        _related_url(10, 2): [{"id": 3, "link_type": "is_blocked_by",
                               "title": "Blocker Epic",
                               "web_url": e3["web_url"]}],
    }
    gql = [_wi_page([_wi_node(2, TEAM_NS, [
        _blocked_by_issue(500, "Blocking Issue"),
        # epic-type linked item must NOT duplicate the REST blocker
        _blocked_by_epic_wi(3, "Blocker Epic"),
    ])])]

    h = _make_harness([e1, e2, e3], by_url, gql)
    (rel,) = h._fetch_blocking_graph(h._rd_root_obj)["relationships"]
    assert [(b["item_type"], b["title"]) for b in rel["blocked_by"]] == [
        ("Epic", "Blocker Epic"), ("Issue", "Blocking Issue")]
    assert e2["blocked_by_count"] == 2


def test_graphql_pagination():
    e1 = make_epic(id=1, iid=1, title="P", etype="Epic")
    e2 = make_epic(id=2, iid=2, title="A", etype="Feature")
    e2["parent_id"] = 1
    e3 = make_epic(id=3, iid=3, title="B", etype="Feature")
    e3["parent_id"] = 1
    by_url = {_related_url(10, i): [] for i in (1, 2, 3)}
    gql = [
        _wi_page([_wi_node(2, TEAM_NS, [_blocked_by_issue(11, "I1")])],
                 has_next=True, cursor="c1"),
        _wi_page([_wi_node(3, TEAM_NS, [_blocked_by_issue(12, "I2")])]),
    ]
    h = _make_harness([e1, e2, e3], by_url, gql)
    result = h._fetch_blocking_graph(h._rd_root_obj)
    blocked = sorted(r["blocked_epic"]["id_int"] for r in result["relationships"])
    assert blocked == [2, 3]


def test_graphql_failure_degrades_to_epic_only_graph(capsys):
    e1 = make_epic(id=1, iid=1, title="P", etype="Epic")
    e2 = make_epic(id=2, iid=2, title="F", etype="Feature")
    e2["parent_id"] = 1
    e3 = make_epic(id=3, iid=3, title="Blocker", etype="Feature")
    by_url = {
        _related_url(10, 1): [],
        _related_url(10, 3): [],
        _related_url(10, 2): [{"id": 3, "link_type": "is_blocked_by",
                               "title": "Blocker", "web_url": e3["web_url"]}],
    }
    h = _make_harness([e1, e2, e3], by_url, gql_pages=[None])
    result = h._fetch_blocking_graph(h._rd_root_obj)
    # Epic->epic graph survives; the warning names the degradation.
    (rel,) = result["relationships"]
    assert rel["blocked_epic"]["id_int"] == 2
    assert "issue-blocker pass incomplete" in capsys.readouterr().out


def test_unknown_namespace_is_skipped():
    # An epic in a group outside the portfolio map can't be keyed — skip it.
    e1 = make_epic(id=1, iid=1, title="P", etype="Epic")
    by_url = {_related_url(10, 1): []}
    gql = [_wi_page([_wi_node(1, "some/other/group",
                              [_blocked_by_issue(11, "I1")])])]
    h = _make_harness([e1], by_url, gql)
    assert h._fetch_blocking_graph(h._rd_root_obj)["relationships"] == []
