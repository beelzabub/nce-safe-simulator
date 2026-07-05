"""Tests for /api/analysis/portfolio (epic #165, issues #168/#169).

Builds fixture snapshots under a tmp reports/ tree (the endpoint resolves the
newest complete snapshot exactly like report reuse does) and asserts the
portfolio view: every epic::epic listed, attention flags, chain
reconstruction, and the weight/BV rollup semantics.
"""

import json

from fastapi.testclient import TestClient

from server.app import app
from server.analysis import build_portfolio_view


# ---------------------------------------------------------------------------
# Fixture snapshot
# ---------------------------------------------------------------------------

def _epic(id, type, title=None, parent_id=None, planned=None, actual=None,
          bv=None, state="opened", pct_complete=0.0, pct_through_pi=None):
    return {
        "id": id, "iid": id, "type": type,
        "title": title or f"{type} {id}",
        "state": state, "parent_id": parent_id, "labels": [type],
        "piid": "PIID::2026Q3", "web_url": f"https://gitlab.example/epics/{id}",
        "planned_weight": planned, "actual_weight": actual,
        "business_value": bv,
        "pct_complete": pct_complete, "pct_through_pi": pct_through_pi,
    }


def _ref(epic):
    return {"id": epic["id"], "id_int": epic["id"], "title": epic["title"],
            "type": epic["type"], "web_url": epic["web_url"]}


# Portfolio of three epics:
#   Epic 1 — blocked work below it (via Capability 2 and directly)
#   Epic 5 — healthy and ahead of schedule
#   Epic 7 — nothing blocked, but behind schedule
E1 = _epic(1, "Epic", planned=233, bv=21, pct_complete=40, pct_through_pi=30)
C2 = _epic(2, "Capability", parent_id=1, planned=34, bv=8)
F3 = _epic(3, "Feature", parent_id=2, planned=13, bv=5)
F4 = _epic(4, "Feature", parent_id=1, planned=None, actual=8, bv=None)
E5 = _epic(5, "Epic", planned=89, bv=13, pct_complete=80, pct_through_pi=50)
F6 = _epic(6, "Feature", parent_id=5, planned=5, bv=3)
E7 = _epic(7, "Epic", planned=144, bv=2, pct_complete=10, pct_through_pi=60)

EPICS = [E1, C2, F3, F4, E5, F6, E7]

BLOCKING = {
    "summary": {"total_blocked": 2, "total_relationships": 2,
                "portfolio_epics_at_risk": 1},
    "relationships": [
        {
            "blocked_epic": _ref(F3),
            "blocked_by": [_ref(F6)],
            "at_risk_portfolio_epics": [_ref(E1)],
        },
        {
            "blocked_epic": _ref(F4),
            "blocked_by": [_ref(F6)],
            "at_risk_portfolio_epics": [_ref(E1)],
        },
    ],
}


def _write_snapshot(reports_dir, date="20260701", time="120000",
                    epics=EPICS, blocking=BLOCKING, complete=True,
                    graph_name="blocking_graph.json", raw=None):
    data = reports_dir / date / time / "data"
    data.mkdir(parents=True)
    (data / "epics.json").write_text(json.dumps(
        {"generated_at": "2026-07-01T12:00:00Z", "epics": epics,
         "all_epics_raw": raw if raw is not None else epics}))
    if blocking is not None:
        (data / graph_name).write_text(json.dumps(blocking))
    if complete:
        (data / "snapshot.complete").touch()
    return data


# ---------------------------------------------------------------------------
# Endpoint behavior
# ---------------------------------------------------------------------------

def test_404_when_no_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = TestClient(app).get("/api/analysis/portfolio")
    assert r.status_code == 404
    assert "run reports" in r.json()["detail"]


def test_incomplete_snapshot_is_ignored(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports", complete=False)
    assert TestClient(app).get("/api/analysis/portfolio").status_code == 404


def test_newest_complete_snapshot_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports", date="20260601", time="090000",
                    blocking={"relationships": []})
    _write_snapshot(tmp_path / "reports", date="20260701", time="120000")
    body = TestClient(app).get("/api/analysis/portfolio").json()
    assert body["snapshot"] == {"date": "20260701", "time": "120000",
                                "generated_at": "2026-07-01T12:00:00Z"}
    assert body["totals"]["blocked_items"] == 2


def test_all_portfolio_epics_listed_with_flags(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports")
    body = TestClient(app).get("/api/analysis/portfolio").json()

    # Every epic::epic appears — healthy ones included.
    assert body["totals"]["portfolio_epics"] == 3
    assert body["totals"]["needs_attention"] == 2
    by_id = {pe["epic"]["id"]: pe for pe in body["portfolio_epics"]}
    assert set(by_id) == {1, 5, 7}

    # Epic 1: blocked (and ahead of schedule).
    assert by_id[1]["flags"] == {"blocked": True, "behind_schedule": False}
    assert by_id[1]["needs_attention"] is True

    # Epic 7: nothing blocked but trailing its PI.
    assert by_id[7]["flags"] == {"blocked": False, "behind_schedule": True}
    assert by_id[7]["rollup"]["blocked_count"] == 0
    assert by_id[7]["chains"] == []

    # Epic 5: healthy.
    assert by_id[5]["needs_attention"] is False

    # Attention sorts first; healthy last.
    assert [pe["epic"]["id"] for pe in body["portfolio_epics"]] == [1, 7, 5]


def test_rollups_and_chains(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports")
    body = TestClient(app).get("/api/analysis/portfolio").json()
    pe = next(p for p in body["portfolio_epics"] if p["epic"]["id"] == 1)

    # F3 planned 13 + F4 (planned null -> actual 8); BV 5 + null->0.
    assert pe["rollup"] == {"blocked_count": 2, "blocked_weight": 21,
                            "blocked_business_value": 5}
    assert body["totals"]["blocked_weight"] == 21
    assert body["totals"]["blocked_business_value"] == 5

    # Chains are reconstructed top-down with the blocked node flagged.
    chains = {tuple(n["id"] for n in c["nodes"]): c for c in pe["chains"]}
    assert set(chains) == {(1, 2, 3), (1, 4)}
    deep = chains[(1, 2, 3)]
    assert [n["blocked"] for n in deep["nodes"]] == [False, False, True]
    assert deep["blockers"] == [{"id": 6, "title": F6["title"],
                                 "type": "Feature", "item_type": "Epic",
                                 "web_url": F6["web_url"]}]
    # Slim epic dicts must not leak bulky fields.
    assert "description" not in deep["nodes"][0]
    # Schedule context ships with each epic for the UI's PI marker.
    assert pe["epic"]["pct_through_pi"] == 30


def test_empty_blocking_still_lists_portfolio(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports", blocking={"relationships": []})
    body = TestClient(app).get("/api/analysis/portfolio").json()
    assert body["totals"]["portfolio_epics"] == 3
    assert body["totals"]["blocked_items"] == 0
    # Epic 7 still needs attention on schedule alone.
    assert body["totals"]["needs_attention"] == 1


def test_missing_blocking_file_is_empty_not_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports", blocking=None)
    body = TestClient(app).get("/api/analysis/portfolio").json()
    assert body["totals"]["blocked_items"] == 0
    assert body["totals"]["portfolio_epics"] == 3


def test_legacy_blocking_json_fallback(tmp_path, monkeypatch):
    # Pre-#172 runs only have blocking.json; a well-formed one still works.
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports", graph_name="blocking.json")
    body = TestClient(app).get("/api/analysis/portfolio").json()
    assert body["totals"]["blocked_items"] == 2


def test_clobbered_legacy_blocking_json_degrades_gracefully(tmp_path, monkeypatch):
    # Pre-#172 runs where the Quarto data layer overwrote blocking.json:
    # different schema, no relationships — an empty graph, not an error.
    monkeypatch.chdir(tmp_path)
    quarto_shape = {"report_date": "2026-07-01",
                    "summary": {"total_blocked": 8, "total_relationships": 8,
                                "total_portfolio_risk": 0, "total_cross_art": 2},
                    "portfolio_risk": [], "vs_cross_art": [], "blocked_items": []}
    _write_snapshot(tmp_path / "reports", blocking=quarto_shape,
                    graph_name="blocking.json")
    body = TestClient(app).get("/api/analysis/portfolio").json()
    assert body["totals"]["blocked_items"] == 0
    assert body["totals"]["portfolio_epics"] == 3


# ---------------------------------------------------------------------------
# Untyped epics in chains (#174) — a labeling slip must degrade the display,
# not hide the blocked work.
# ---------------------------------------------------------------------------

def _untyped(id, title, parent_id=None, planned=None, bv=None):
    e = _epic(id, "Feature", title=title, parent_id=parent_id,
              planned=planned, bv=bv)
    del e["type"]
    e["labels"] = []          # no tier label at all
    return e


def test_untyped_intermediate_renders_instead_of_dropping_chain(tmp_path, monkeypatch):
    # Mirrors live #37 -> #45 (untyped) -> #47 (untyped, blocked twice).
    monkeypatch.chdir(tmp_path)
    e37 = _epic(94, "Epic", title="Portfolio Epic 1")
    u45 = _untyped(96, "Child 3 Epic", parent_id=94)
    u47 = _untyped(98, "Child 3-1 Epic", parent_id=96, planned=8, bv=13)
    b1 = _epic(70, "Feature", title="Blocker A")
    b2 = _epic(71, "Feature", title="Blocker B")
    blocking = {"relationships": [{
        "blocked_epic": _ref({**u47, "type": None}),
        "blocked_by": [_ref(b1), _ref(b2)],
        "at_risk_portfolio_epics": [_ref(e37)],
    }]}
    _write_snapshot(tmp_path / "reports", epics=[e37, b1, b2],
                    raw=[e37, u45, u47, b1, b2], blocking=blocking)
    body = TestClient(app).get("/api/analysis/portfolio").json()

    pe = next(p for p in body["portfolio_epics"] if p["epic"]["id"] == 94)
    assert pe["flags"]["blocked"] is True
    (chain,) = pe["chains"]
    assert [(n["id"], n.get("type"), n["blocked"]) for n in chain["nodes"]] == [
        (94, "Epic", False), (96, None, False), (98, None, True)]
    assert len(chain["blockers"]) == 2
    # Untyped blocked item still contributes weight/BV.
    assert pe["rollup"] == {"blocked_count": 1, "blocked_weight": 8,
                            "blocked_business_value": 13}
    assert body["totals"]["untyped_in_chains"] == 2


def test_fully_typed_snapshot_reports_zero_untyped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports")
    body = TestClient(app).get("/api/analysis/portfolio").json()
    assert body["totals"]["untyped_in_chains"] == 0


# ---------------------------------------------------------------------------
# Computation edge cases (pure function)
# ---------------------------------------------------------------------------

def _by_id(epics):
    return {e["id"]: e for e in epics}


def test_blocked_item_threatening_two_portfolio_epics_dedupes_totals():
    # Nested portfolio epics: Epic 10 -> Epic 11 -> Feature 12 (blocked).
    e10 = _epic(10, "Epic", planned=144, bv=13)
    e11 = _epic(11, "Epic", parent_id=10, planned=89, bv=8)
    f12 = _epic(12, "Feature", parent_id=11, planned=13, bv=5)
    blocking = {"relationships": [{
        "blocked_epic": _ref(f12),
        "blocked_by": [],
        "at_risk_portfolio_epics": [_ref(e10), _ref(e11)],
    }]}
    body = build_portfolio_view(_by_id([e10, e11, f12]), blocking)

    # Each threatened portfolio epic carries its own exposure...
    at_risk = [pe for pe in body["portfolio_epics"] if pe["flags"]["blocked"]]
    assert len(at_risk) == 2
    assert all(pe["rollup"]["blocked_weight"] == 13 for pe in at_risk)
    # ...but grand totals count the blocked item once.
    assert body["totals"]["blocked_items"] == 1
    assert body["totals"]["blocked_weight"] == 13
    assert body["totals"]["blocked_business_value"] == 5


def test_broken_parent_chain_is_skipped():
    # Blocked feature whose parent walk never reaches the claimed ancestor.
    e1 = _epic(1, "Epic")
    f2 = _epic(2, "Feature", parent_id=999)   # dangling parent
    blocking = {"relationships": [{
        "blocked_epic": _ref(f2),
        "blocked_by": [],
        "at_risk_portfolio_epics": [_ref(e1)],
    }]}
    body = build_portfolio_view(_by_id([e1, f2]), blocking)
    (pe,) = body["portfolio_epics"]
    assert pe["flags"]["blocked"] is False
    assert body["totals"]["blocked_items"] == 0


def test_parent_cycle_does_not_hang():
    e1 = _epic(1, "Epic")
    a = _epic(2, "Capability", parent_id=3)
    b = _epic(3, "Capability", parent_id=2)   # 2 <-> 3 cycle
    blocking = {"relationships": [{
        "blocked_epic": _ref(a),
        "blocked_by": [],
        "at_risk_portfolio_epics": [_ref(e1)],
    }]}
    body = build_portfolio_view(_by_id([e1, a, b]), blocking)
    (pe,) = body["portfolio_epics"]
    assert pe["flags"]["blocked"] is False


def test_closed_epic_is_not_behind_schedule():
    done = _epic(1, "Epic", state="closed", pct_complete=10, pct_through_pi=90)
    body = build_portfolio_view(_by_id([done]), {})
    (pe,) = body["portfolio_epics"]
    assert pe["flags"]["behind_schedule"] is False
    assert pe["needs_attention"] is False


def test_attention_sort_order():
    blocked_big_bv = _epic(1, "Epic")
    fb = _epic(2, "Feature", parent_id=1, planned=3, bv=13)
    blocked_small_bv = _epic(3, "Epic")
    fs = _epic(4, "Feature", parent_id=3, planned=5, bv=2)
    behind = _epic(5, "Epic", planned=200, pct_complete=5, pct_through_pi=50)
    healthy_heavy = _epic(6, "Epic", planned=999, pct_complete=90,
                          pct_through_pi=10)
    blocking = {"relationships": [
        {"blocked_epic": _ref(fb), "blocked_by": [],
         "at_risk_portfolio_epics": [_ref(blocked_big_bv)]},
        {"blocked_epic": _ref(fs), "blocked_by": [],
         "at_risk_portfolio_epics": [_ref(blocked_small_bv)]},
    ]}
    body = build_portfolio_view(
        _by_id([blocked_big_bv, fb, blocked_small_bv, fs, behind,
                healthy_heavy]),
        blocking)
    # Blocked by BV desc, then behind-schedule, healthy last.
    assert [pe["epic"]["id"] for pe in body["portfolio_epics"]] == [1, 3, 5, 6]
