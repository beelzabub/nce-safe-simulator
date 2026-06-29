"""Tests that epic blocked_by_count is reconciled with the /related_epics graph.

Regression coverage for #107: calculate_portfolio_metrics derives a provisional
blocked_by_count from the legacy GraphQL blockedByCount, while _fetch_blocking_graph
builds the blocking detail from the REST /related_epics endpoint.  These two APIs
can disagree, so _fetch_blocking_graph must recompute blocked_by_count from its own
graph to keep the summary counts and the blocking report detail consistent.
"""
from tests.conftest import ReportsHarness, make_epic


class _FakeResp:
    def __init__(self, payload, ok=True):
        self._payload = payload
        self.ok = ok

    def json(self):
        return self._payload


class _FakeSession:
    """Maps related_epics URLs to canned REST responses."""

    def __init__(self, by_url):
        self._by_url = by_url

    def get(self, url, *args, **kwargs):
        if url not in self._by_url:
            return _FakeResp([], ok=False)
        return _FakeResp(self._by_url[url])


def _related_url(group_id, iid):
    return f"https://gitlab.com/api/v4/groups/{group_id}/epics/{iid}/related_epics"


def _blocked_by(epic_id, title, web_url):
    return {"id": epic_id, "link_type": "is_blocked_by", "title": title, "web_url": web_url}


def _make_harness(epics, by_url):
    h = ReportsHarness()
    h._all_epics_cache = {h.parent_group: epics}
    h._make_session = lambda: _FakeSession(by_url)
    return h


def test_blocked_by_count_reconciled_to_related_epics_graph():
    # A: GraphQL said 0, but /related_epics shows it is blocked by B  -> should become 1
    # B: a blocker, itself unblocked                                  -> should stay 0
    # C: GraphQL false-positive (1), but /related_epics is empty      -> should become 0
    epic_a = make_epic(id=1, iid=1, title="A", blocked_by_count=0)
    epic_b = make_epic(id=2, iid=2, title="B", blocked_by_count=0)
    epic_c = make_epic(id=3, iid=3, title="C", blocked_by_count=1)
    epics  = [epic_a, epic_b, epic_c]

    by_url = {
        _related_url(10, 1): [_blocked_by(2, "B", epic_b["web_url"])],
        _related_url(10, 2): [],
        _related_url(10, 3): [],
    }
    h = _make_harness(epics, by_url)

    result = h._fetch_blocking_graph(h._rd_root_obj)

    # Detail: exactly one blocked epic (A), blocked by exactly one epic (B).
    rels = result["relationships"]
    assert len(rels) == 1
    assert rels[0]["blocked_epic"]["id"] == 1
    assert [b["id"] for b in rels[0]["blocked_by"]] == [2]
    assert result["summary"]["total_blocked"] == 1

    # Summary counts now agree with the detail (the bug fix).
    assert epic_a["blocked_by_count"] == 1   # vice-versa case: GraphQL undercounted
    assert epic_b["blocked_by_count"] == 0
    assert epic_c["blocked_by_count"] == 0   # the divergence the bug produced


def test_summary_and_detail_invariant_holds_for_every_epic():
    """blocked_by_count > 0  iff  the epic appears as a blocked_epic in the graph."""
    epic_a = make_epic(id=1, iid=1, title="A", blocked_by_count=5)   # wildly wrong
    epic_b = make_epic(id=2, iid=2, title="B", blocked_by_count=0)
    epic_c = make_epic(id=3, iid=3, title="C", blocked_by_count=9)   # wildly wrong
    epics  = [epic_a, epic_b, epic_c]

    by_url = {
        _related_url(10, 1): [
            _blocked_by(2, "B", epic_b["web_url"]),
            _blocked_by(3, "C", epic_c["web_url"]),
        ],
        _related_url(10, 2): [],
        _related_url(10, 3): [],
    }
    h = _make_harness(epics, by_url)

    result = h._fetch_blocking_graph(h._rd_root_obj)

    blocked_ids = {r["blocked_epic"]["id"] for r in result["relationships"]}
    detail_count = {r["blocked_epic"]["id"]: len(r["blocked_by"]) for r in result["relationships"]}
    for e in epics:
        appears = e["id"] in blocked_ids
        assert (e["blocked_by_count"] > 0) == appears
        assert e["blocked_by_count"] == detail_count.get(e["id"], 0)

    # A is blocked by two epics; the count must match the detail length.
    assert epic_a["blocked_by_count"] == 2


def test_non_blocking_links_are_ignored():
    """Only is_blocked_by links count; 'blocks'/'relates_to' must not inflate the count."""
    epic_a = make_epic(id=1, iid=1, title="A", blocked_by_count=0)
    epic_b = make_epic(id=2, iid=2, title="B", blocked_by_count=0)
    epics  = [epic_a, epic_b]

    by_url = {
        _related_url(10, 1): [
            {"id": 2, "link_type": "blocks",      "title": "B", "web_url": epic_b["web_url"]},
            {"id": 2, "link_type": "relates_to",  "title": "B", "web_url": epic_b["web_url"]},
        ],
        _related_url(10, 2): [],
    }
    h = _make_harness(epics, by_url)

    result = h._fetch_blocking_graph(h._rd_root_obj)

    assert result["relationships"] == []
    assert epic_a["blocked_by_count"] == 0
    assert epic_b["blocked_by_count"] == 0


def test_failed_fetch_preserves_provisional_count_and_warns(capsys):
    """A failed /related_epics call must NOT zero the count (Refs #107).

    Otherwise a transient API error silently marks a genuinely-blocked epic as
    unblocked. Failed epics keep their provisional GraphQL count; only epics whose
    fetch succeeded are reconciled from the graph.
    """
    epic_a = make_epic(id=1, iid=1, title="A", blocked_by_count=2)  # fetch -> HTTP error
    epic_b = make_epic(id=2, iid=2, title="B", blocked_by_count=3)  # fetch -> exception
    epic_c = make_epic(id=3, iid=3, title="C", blocked_by_count=0)  # fetch ok, blocked by D
    epic_d = make_epic(id=4, iid=4, title="D", blocked_by_count=0)  # fetch ok, unblocked
    epics  = [epic_a, epic_b, epic_c, epic_d]

    class _PartialSession:
        def get(self, url, *args, **kwargs):
            if url == _related_url(10, 1):
                return _FakeResp([], ok=False)           # HTTP failure
            if url == _related_url(10, 2):
                raise ConnectionError("boom")            # network exception
            if url == _related_url(10, 3):
                return _FakeResp([_blocked_by(4, "D", epic_d["web_url"])])
            return _FakeResp([])

    h = _make_harness(epics, {})
    h._make_session = lambda: _PartialSession()

    h._fetch_blocking_graph(h._rd_root_obj)

    # Successful fetches reconcile from the graph …
    assert epic_c["blocked_by_count"] == 1
    assert epic_d["blocked_by_count"] == 0
    # … but failed fetches keep their provisional count rather than being zeroed.
    assert epic_a["blocked_by_count"] == 2
    assert epic_b["blocked_by_count"] == 3
    # And the degraded run is surfaced, not silent.
    assert "2 epic(s)" in capsys.readouterr().out
