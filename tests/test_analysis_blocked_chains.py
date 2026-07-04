"""Tests for /api/analysis/blocked-chains (epic #165, issue #168).

Builds fixture snapshots under a tmp reports/ tree (the endpoint resolves the
newest complete snapshot exactly like report reuse does) and asserts chain
reconstruction and the weight/BV rollup semantics.
"""

import json

from fastapi.testclient import TestClient

from server.app import app
from server.analysis import build_blocked_chains


# ---------------------------------------------------------------------------
# Fixture snapshot
# ---------------------------------------------------------------------------

def _epic(id, type, title=None, parent_id=None, planned=None, actual=None,
          bv=None, state="opened"):
    return {
        "id": id, "iid": id, "type": type,
        "title": title or f"{type} {id}",
        "state": state, "parent_id": parent_id, "labels": [type],
        "piid": "PIID::2026Q3", "web_url": f"https://gitlab.example/epics/{id}",
        "planned_weight": planned, "actual_weight": actual,
        "business_value": bv, "pct_complete": 0.0,
    }


def _ref(epic):
    return {"id": epic["id"], "id_int": epic["id"], "title": epic["title"],
            "type": epic["type"], "web_url": epic["web_url"]}


# Hierarchy: Epic 1 -> Capability 2 -> Feature 3 (blocked by Feature 6)
#            Epic 1 -> Feature 4 (direct, blocked by Feature 6)
#            Epic 5 -> (nothing blocked)
E1 = _epic(1, "Epic", planned=233, bv=21)
C2 = _epic(2, "Capability", parent_id=1, planned=34, bv=8)
F3 = _epic(3, "Feature", parent_id=2, planned=13, bv=5)
F4 = _epic(4, "Feature", parent_id=1, planned=None, actual=8, bv=None)
E5 = _epic(5, "Epic", planned=89, bv=13)
F6 = _epic(6, "Feature", parent_id=5, planned=5, bv=3)

EPICS = [E1, C2, F3, F4, E5, F6]

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
                    epics=EPICS, blocking=BLOCKING, complete=True):
    data = reports_dir / date / time / "data"
    data.mkdir(parents=True)
    (data / "epics.json").write_text(json.dumps(
        {"generated_at": "2026-07-01T12:00:00Z", "epics": epics}))
    if blocking is not None:
        (data / "blocking.json").write_text(json.dumps(blocking))
    if complete:
        (data / "snapshot.complete").touch()
    return data


# ---------------------------------------------------------------------------
# Endpoint behavior
# ---------------------------------------------------------------------------

def test_404_when_no_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = TestClient(app).get("/api/analysis/blocked-chains")
    assert r.status_code == 404
    assert "run reports" in r.json()["detail"]


def test_incomplete_snapshot_is_ignored(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports", complete=False)
    assert TestClient(app).get("/api/analysis/blocked-chains").status_code == 404


def test_newest_complete_snapshot_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports", date="20260601", time="090000",
                    blocking={"relationships": []})
    _write_snapshot(tmp_path / "reports", date="20260701", time="120000")
    body = TestClient(app).get("/api/analysis/blocked-chains").json()
    assert body["snapshot"] == {"date": "20260701", "time": "120000",
                                "generated_at": "2026-07-01T12:00:00Z"}
    assert body["totals"]["blocked_items"] == 2


def test_full_payload_shape_and_rollups(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports")
    body = TestClient(app).get("/api/analysis/blocked-chains").json()

    # E5 has no blocked descendants and must be absent.
    assert body["totals"]["portfolio_epics_at_risk"] == 1
    (pe,) = body["portfolio_epics"]
    assert pe["epic"]["id"] == 1
    assert pe["epic"]["business_value"] == 21

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
                                 "type": "Feature", "web_url": F6["web_url"]}]
    # Slim epic dicts must not leak bulky fields.
    assert "description" not in deep["nodes"][0]


def test_empty_blocking_yields_zero_totals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports", blocking={"relationships": []})
    body = TestClient(app).get("/api/analysis/blocked-chains").json()
    assert body["totals"] == {"portfolio_epics_at_risk": 0, "blocked_items": 0,
                              "blocked_weight": 0,
                              "blocked_business_value": 0}
    assert body["portfolio_epics"] == []


def test_missing_blocking_file_is_empty_not_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "reports", blocking=None)
    body = TestClient(app).get("/api/analysis/blocked-chains").json()
    assert body["totals"]["blocked_items"] == 0


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
    body = build_blocked_chains(_by_id([e10, e11, f12]), blocking)

    # Each threatened portfolio epic carries its own exposure...
    assert body["totals"]["portfolio_epics_at_risk"] == 2
    assert all(pe["rollup"]["blocked_weight"] == 13
               for pe in body["portfolio_epics"])
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
    body = build_blocked_chains(_by_id([e1, f2]), blocking)
    assert body["portfolio_epics"] == []
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
    body = build_blocked_chains(_by_id([e1, a, b]), blocking)
    assert body["portfolio_epics"] == []


def test_sorted_by_bv_at_risk_desc():
    e1 = _epic(1, "Epic")
    f2 = _epic(2, "Feature", parent_id=1, planned=5, bv=2)
    e3 = _epic(3, "Epic")
    f4 = _epic(4, "Feature", parent_id=3, planned=3, bv=13)
    blocking = {"relationships": [
        {"blocked_epic": _ref(f2), "blocked_by": [],
         "at_risk_portfolio_epics": [_ref(e1)]},
        {"blocked_epic": _ref(f4), "blocked_by": [],
         "at_risk_portfolio_epics": [_ref(e3)]},
    ]}
    body = build_blocked_chains(_by_id([e1, f2, e3, f4]), blocking)
    assert [pe["epic"]["id"] for pe in body["portfolio_epics"]] == [3, 1]
