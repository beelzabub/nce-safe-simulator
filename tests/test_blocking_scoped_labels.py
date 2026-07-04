"""Regression tests for #172: scoped epic-type labels in the blocking graph.

_fetch_blocking_graph used a local type resolver that compared *display*
names ("Epic") against the epics' *raw* labels ("epic::epic"), so on
scoped-label configs every blocked epic typed as "Unknown" and — because the
portfolio-ancestor walk relies on that type — at_risk_portfolio_epics was
always empty. That blanked the WSJF "Epic at Risk" column, the Blocking
report's portfolio-risk table, and the Portfolio Explorer's flags.
"""
from tests.conftest import ReportsHarness, make_epic


class ScopedHarness(ReportsHarness):
    """The live config style: scoped labels, derived display names."""
    EPIC_TYPE_LABELS        = ["epic::epic", "epic::capability", "epic::feature"]
    EPIC_TYPE_DISPLAY_NAMES = ["Epic", "Capability", "Feature"]


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


def _scoped_epic(id, iid, title, tier, parent_id=None):
    e = make_epic(id=id, iid=iid, title=title)
    e["labels"] = [f"epic::{tier}", "PIID::2026Q3"]
    e["parent_id"] = parent_id
    return e


def _graph(harness_cls=ScopedHarness):
    # Mirrors the live #37 chain: Epic -> Feature -> Feature -> Feature,
    # the leaf blocked by an unrelated feature.
    e37 = _scoped_epic(94, 37, "Portfolio Epic 1", "epic")
    e38 = _scoped_epic(95, 38, "Child 1", "feature", parent_id=94)
    e39 = _scoped_epic(96, 39, "Child 1-1", "feature", parent_id=95)
    e40 = _scoped_epic(97, 40, "Child 1-1-1", "feature", parent_id=96)
    e41 = _scoped_epic(98, 41, "Child Epic 2-1", "feature")
    epics = [e37, e38, e39, e40, e41]

    by_url = {_related_url(10, e["iid"]): [] for e in epics}
    by_url[_related_url(10, 40)] = [{
        "id": 98, "link_type": "is_blocked_by",
        "title": "Child Epic 2-1", "web_url": e41["web_url"],
    }]

    h = harness_cls()
    h._all_epics_cache = {h.parent_group: epics}
    h._make_session = lambda: _FakeSession(by_url)
    return h._fetch_blocking_graph(h._rd_root_obj)


def test_scoped_labels_resolve_portfolio_ancestors():
    result = _graph()
    (rel,) = result["relationships"]
    assert rel["blocked_epic"]["id_int"] == 97
    # The deep chain still reaches the scoped-labeled portfolio epic.
    assert [(a["id_int"], a["title"]) for a in rel["at_risk_portfolio_epics"]] \
        == [(94, "Portfolio Epic 1")]
    assert result["summary"]["portfolio_epics_at_risk"] == 1


def test_scoped_labels_resolve_types_not_unknown():
    # The WSJF blocking-detail table types come from these fields (#172).
    (rel,) = _graph()["relationships"]
    assert rel["blocked_epic"]["type"] == "Feature"
    assert rel["blocked_by"][0]["type"] == "Feature"
    assert rel["at_risk_portfolio_epics"][0]["type"] == "Epic"


def test_plain_labels_still_resolve():
    class PlainHarness(ReportsHarness):
        pass  # conftest default: plain Epic/Capability/Feature labels

    e1 = make_epic(id=1, iid=1, title="P", etype="Epic")
    e2 = make_epic(id=2, iid=2, title="F", etype="Feature")
    e2["parent_id"] = 1
    e3 = make_epic(id=3, iid=3, title="B", etype="Feature")
    by_url = {
        _related_url(10, 1): [],
        _related_url(10, 3): [],
        _related_url(10, 2): [{
            "id": 3, "link_type": "is_blocked_by",
            "title": "B", "web_url": e3["web_url"],
        }],
    }
    h = PlainHarness()
    h._all_epics_cache = {h.parent_group: [e1, e2, e3]}
    h._make_session = lambda: _FakeSession(by_url)
    result = h._fetch_blocking_graph(h._rd_root_obj)
    (rel,) = result["relationships"]
    assert rel["at_risk_portfolio_epics"][0]["id_int"] == 1
    assert rel["blocked_epic"]["type"] == "Feature"
