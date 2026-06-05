"""Tests for the 4 phase-3 _data_* extraction methods (Refs #41)."""
import json
import tempfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.conftest import ReportsHarness, make_epic

_PIID = "PIID::Q1-FY25"
_VS   = {"id": 10, "name": "VS Alpha", "web_url": "https://gl.com/vs-alpha"}
_ART  = {"id": 20, "name": "ART One",  "web_url": "https://gl.com/art-one",
          "parent_id": 10}
_TEAM = {"id": 30, "name": "Team Red", "web_url": "https://gl.com/team-red",
          "parent_id": 20}


def _h(epics=None, vs_groups=None, groups_by_parent=None, groups_by_id=None,
        piid_labels=None, lifecycle_labels=None, blocking=None, issues_by_project=None):
    epics = epics or []
    h = ReportsHarness(
        epics_all=epics,
        metrics={
            "Epic":       [e for e in epics if e.get("type") == "Epic"],
            "Capability": [e for e in epics if e.get("type") == "Capability"],
            "Feature":    [e for e in epics if e.get("type") == "Feature"],
        },
        vs_groups=vs_groups or [],
        groups_by_id=groups_by_id or {},
        groups_by_parent=groups_by_parent or {},
        piid_labels=piid_labels or [],
        lifecycle_labels=lifecycle_labels or [],
    )
    if blocking is not None:
        h._rd_blocking = blocking
    if issues_by_project is not None:
        h._rd_issues_by_project = defaultdict(list, issues_by_project)
    return h


# ---------------------------------------------------------------------------
# _data_blocking
# ---------------------------------------------------------------------------

class TestDataBlocking:
    def test_returns_required_keys(self):
        d = _h()._data_blocking()
        assert {"report_date", "group", "summary", "portfolio_risk",
                "vs_cross_art", "blocked_items"} <= d.keys()

    def test_empty_relationships(self):
        d = _h()._data_blocking()
        assert d["summary"]["total_blocked"] == 0
        assert d["blocked_items"] == []
        assert d["portfolio_risk"] == []

    def test_blocked_item_captured(self):
        blocking = {
            "relationships": [{
                "blocked_epic": {"id": 1, "id_int": 1, "title": "Blocked E",
                                 "web_url": "https://gl.com/e/1", "type": "Feature",
                                 "state": "opened"},
                "blocked_by": [{"id": 2, "id_int": 2, "title": "Blocker E",
                                 "web_url": "https://gl.com/e/2", "type": "Epic"}],
                "at_risk_portfolio_epics": [],
            }],
            "summary": {"total_relationships": 1},
        }
        d = _h(blocking=blocking)._data_blocking()
        assert d["summary"]["total_blocked"] == 1
        assert len(d["blocked_items"]) == 1
        item = d["blocked_items"][0]
        assert item["title"] == "Blocked E"
        assert len(item["blockers"]) == 1

    def test_ancestor_risk_propagated(self):
        blocking = {
            "relationships": [{
                "blocked_epic": {"id": 2, "id_int": 2, "title": "Child",
                                 "web_url": "", "type": "Feature", "state": "opened"},
                "blocked_by": [],
                "at_risk_portfolio_epics": [
                    {"id": 1, "title": "Parent Epic", "web_url": "", "type": "Epic"}
                ],
            }],
            "summary": {"total_relationships": 0},
        }
        d = _h(blocking=blocking)._data_blocking()
        assert len(d["portfolio_risk"]) == 1
        assert d["portfolio_risk"][0]["title"] == "Parent Epic"

    def test_json_serializable(self):
        json.dumps(_h()._data_blocking())


# ---------------------------------------------------------------------------
# _data_epic_lifecycle
# ---------------------------------------------------------------------------

class TestDataEpicLifecycle:
    def _epic_lc(self, id=1, lc_label="lifecycle::backlog", age_days=10, etype="Epic"):
        created = (date.today() - timedelta(days=age_days)).isoformat()
        e = make_epic(id=id, etype=etype)
        e["labels"] = [etype, lc_label]
        e["created_at"] = created
        return e

    def test_returns_required_keys(self):
        d = _h()._data_epic_lifecycle()
        assert {"report_date", "group", "states", "stuck", "unlabelled"} <= d.keys()

    def test_five_states_always_present(self):
        d = _h()._data_epic_lifecycle()
        assert len(d["states"]) == 5

    def test_epic_bucketed_by_lifecycle_label(self):
        e = self._epic_lc(lc_label="lifecycle::funnel")
        d = _h(epics=[e])._data_epic_lifecycle()
        funnel = next(s for s in d["states"] if s["key"] == "lifecycle::funnel")
        assert funnel["count"] == 1

    def test_unlabelled_epic_in_unlabelled(self):
        e = make_epic(id=1, etype="Epic")
        e["labels"] = ["Epic"]
        d = _h(epics=[e])._data_epic_lifecycle()
        assert len(d["unlabelled"]) == 1

    def test_stuck_detected_over_threshold(self):
        e = self._epic_lc(lc_label="lifecycle::analyzing", age_days=45)
        d = _h(epics=[e])._data_epic_lifecycle()
        assert len(d["stuck"]) == 1
        assert d["stuck"][0]["key"] == "lifecycle::analyzing"

    def test_not_stuck_under_threshold(self):
        e = self._epic_lc(lc_label="lifecycle::analyzing", age_days=10)
        d = _h(epics=[e])._data_epic_lifecycle()
        assert len(d["stuck"]) == 0

    def test_over_threshold_flag(self):
        e = self._epic_lc(lc_label="lifecycle::backlog", age_days=100)
        d = _h(epics=[e])._data_epic_lifecycle()
        backlog = next(s for s in d["states"] if s["key"] == "lifecycle::backlog")
        assert backlog["over_threshold"] is True

    def test_json_serializable(self):
        json.dumps(_h()._data_epic_lifecycle())


# ---------------------------------------------------------------------------
# _data_pi_predictability
# ---------------------------------------------------------------------------

class TestDataPiPredictability:
    def _art_harness(self, features=None):
        features = features or []
        h = _h(
            epics=features,
            vs_groups=[_VS],
            groups_by_id={10: _VS, 20: _ART, 30: _TEAM},
            groups_by_parent={10: [_ART], 20: [_TEAM]},
            piid_labels=[_PIID],
        )
        h._mock_pct_pi = 100  # past PI → show final predictability
        return h

    def _feature(self, id=1, state="closed", piid=_PIID):
        e = make_epic(id=id, etype="Feature", state=state, piid=piid, group_id=30)
        e["labels"] = ["Feature", piid]
        return e

    def test_returns_required_keys(self):
        d = _h()._data_pi_predictability()
        assert {"report_date", "group", "pis", "rows", "portfolio_row"} <= d.keys()

    def test_no_data_returns_empty(self):
        d = _h()._data_pi_predictability()
        assert d["pis"] == []
        assert d["rows"] == []

    def test_closed_feature_counted(self):
        f = self._feature(state="closed")
        d = self._art_harness([f])._data_pi_predictability()
        assert len(d["pis"]) == 1
        assert len(d["rows"]) == 1
        cell = d["rows"][0]["cells"][0]
        assert cell["closed"] == 1
        assert cell["total"] == 1
        assert cell["pct"] == 100

    def test_open_feature_reduces_pct(self):
        f1 = self._feature(id=1, state="closed")
        f2 = self._feature(id=2, state="opened")
        d = self._art_harness([f1, f2])._data_pi_predictability()
        cell = d["rows"][0]["cells"][0]
        assert cell["pct"] == 50

    def test_past_pi_icon_green_at_80(self):
        features = [self._feature(id=i, state="closed") for i in range(1, 5)]
        features.append(self._feature(id=5, state="opened"))
        d = self._art_harness(features)._data_pi_predictability()
        cell = d["rows"][0]["cells"][0]
        assert cell["pct"] == 80
        assert cell["icon"] == "✅"

    def test_portfolio_row_present(self):
        f = self._feature(state="closed")
        d = self._art_harness([f])._data_pi_predictability()
        assert len(d["portfolio_row"]) == 1

    def test_json_serializable(self):
        json.dumps(_h()._data_pi_predictability())


# ---------------------------------------------------------------------------
# _data_art_capacity_balance
# ---------------------------------------------------------------------------

class TestDataArtCapacityBalance:
    def _cap_harness(self, features=None):
        features = features or []
        h = _h(
            epics=features,
            vs_groups=[_VS],
            groups_by_id={10: _VS, 20: _ART, 30: _TEAM},
            groups_by_parent={10: [_ART], 20: [_TEAM]},
        )
        return h

    def _feature(self, id=1, planned=10, actual=8, piid=_PIID):
        e = make_epic(id=id, etype="Feature", piid=piid, group_id=30,
                      planned_weight=planned, actual_weight=actual)
        e["labels"] = ["Feature", piid]
        return e

    def test_returns_required_keys(self):
        d = _h()._data_art_capacity_balance()
        assert {"report_date", "group", "arts"} <= d.keys()

    def test_no_features_returns_empty_arts(self):
        d = _h()._data_art_capacity_balance()
        assert d["arts"] == []

    def test_feature_bucketed_into_art(self):
        f = self._feature()
        d = self._cap_harness([f])._data_art_capacity_balance()
        assert len(d["arts"]) == 1
        assert d["arts"][0]["art_name"] == "ART One"

    def test_pi_and_team_nested(self):
        f = self._feature()
        d = self._cap_harness([f])._data_art_capacity_balance()
        art = d["arts"][0]
        assert len(art["pis"]) == 1
        assert art["pis"][0]["piid"] == _PIID
        assert len(art["pis"][0]["teams"]) == 1

    def test_load_pct_computed(self):
        f = self._feature(planned=10, actual=8)
        d = self._cap_harness([f])._data_art_capacity_balance()
        team = d["arts"][0]["pis"][0]["teams"][0]
        assert team["load_pct"] == 80

    def test_balanced_status(self):
        f = self._feature(planned=10, actual=9)
        d = self._cap_harness([f])._data_art_capacity_balance()
        assert "Balanced" in d["arts"][0]["pis"][0]["teams"][0]["status"]

    def test_over_status(self):
        f = self._feature(planned=10, actual=13)
        d = self._cap_harness([f])._data_art_capacity_balance()
        team = d["arts"][0]["pis"][0]["teams"][0]
        assert "Over" in team["status"]
        assert d["arts"][0]["over_count"] == 1

    def test_under_status(self):
        f = self._feature(planned=10, actual=5)
        d = self._cap_harness([f])._data_art_capacity_balance()
        team = d["arts"][0]["pis"][0]["teams"][0]
        assert "Under" in team["status"]
        assert d["arts"][0]["under_count"] == 1

    def test_delta_computed(self):
        f = self._feature(planned=10, actual=12)
        d = self._cap_harness([f])._data_art_capacity_balance()
        assert d["arts"][0]["pis"][0]["teams"][0]["delta"] == 2

    def test_json_serializable(self):
        json.dumps(_h()._data_art_capacity_balance())


# ---------------------------------------------------------------------------
# write_report_json — all 11 files written
# ---------------------------------------------------------------------------

class TestWriteReportJsonPhase3:
    ALL_KEYS = [
        "health-dashboard", "orphan-epics", "orphan-issues", "premature-closures",
        "unassigned-pi", "risk-register", "wsjf",
        "blocking", "epic-lifecycle", "pi-predictability", "art-capacity-balance",
    ]

    def test_all_json_files_created(self):
        h = _h()
        with tempfile.TemporaryDirectory() as tmp:
            h.write_report_json(tmp)
            for key in self.ALL_KEYS:
                assert (Path(tmp) / f"{key}.json").exists(), f"Missing {key}.json"

    def test_all_json_files_valid(self):
        h = _h()
        with tempfile.TemporaryDirectory() as tmp:
            h.write_report_json(tmp)
            for key in self.ALL_KEYS:
                data = json.loads((Path(tmp) / f"{key}.json").read_text())
                assert isinstance(data, dict), f"{key}.json is not a dict"
