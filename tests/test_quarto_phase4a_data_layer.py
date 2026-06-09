"""Tests for the 5 phase-4a _data_* extraction methods (Refs #43)."""
import json
import tempfile
from datetime import date
from pathlib import Path

import pytest

from tests.conftest import ReportsHarness, make_epic

_PIID  = "PIID::2025Q1"
_PIID2 = "PIID::2025Q2"
_PROJ  = "project::Alpha"
_PROJ2 = "project::Beta"

_VS   = {"id": 10, "name": "VS Alpha",  "web_url": "https://gl.com/vs-alpha",  "parent_id": 1}
_ART  = {"id": 20, "name": "ART One",   "web_url": "https://gl.com/art-one",   "parent_id": 10, "full_path": "vs-alpha/art-one"}
_TEAM = {"id": 30, "name": "Team Red",  "web_url": "https://gl.com/team-red",  "parent_id": 20, "full_path": "vs-alpha/art-one/team-red"}


def _h(epics=None, piid_labels=None, project_labels=None,
        groups_by_id=None, groups_by_parent=None, vs_groups=None,
        work_type_labels=None):
    epics = epics or []
    h = ReportsHarness(
        epics_all=epics,
        metrics={
            "Epic":       [e for e in epics if e.get("type") == "Epic"],
            "Capability": [e for e in epics if e.get("type") == "Capability"],
            "Feature":    [e for e in epics if e.get("type") == "Feature"],
        },
        piid_labels=piid_labels or [],
        project_labels=project_labels or [],
        groups_by_id=groups_by_id or {},
        groups_by_parent=groups_by_parent or {},
        vs_groups=vs_groups or [],
    )
    if work_type_labels is not None:
        h._rd_work_type_labels = work_type_labels
    return h


def _epic_proj(id=1, proj=_PROJ, piid=_PIID, etype="Epic",
               state="opened", pct=0, planned=10, actual=5, blocked=0):
    e = make_epic(id=id, etype=etype, state=state, piid=piid,
                  planned_weight=planned, actual_weight=actual,
                  blocked_by_count=blocked)
    e["labels"] = [etype, piid, proj]
    return e


# ---------------------------------------------------------------------------
# _data_piid_project
# ---------------------------------------------------------------------------

class TestDataPiidProject:
    def test_returns_required_keys(self):
        d = _h()._data_piid_project()
        assert {"report_date", "group", "project_labels", "piid_labels", "piid_meta", "cells"} <= d.keys()

    def test_empty_returns_empty_cells(self):
        d = _h(piid_labels=[_PIID], project_labels=[_PROJ])._data_piid_project()
        assert d["cells"][f"{_PROJ}|{_PIID}"] is None

    def test_cell_populated(self):
        e = _epic_proj(pct=60, planned=10, actual=8)
        d = _h(epics=[e], piid_labels=[_PIID], project_labels=[_PROJ])._data_piid_project()
        cell = d["cells"][f"{_PROJ}|{_PIID}"]
        assert cell is not None
        assert cell["total"] == 1
        assert cell["open"] == 1
        assert cell["planned"] == 10
        assert cell["actual"] == 8
        assert cell["delta"] == -2

    def test_blocked_counted(self):
        e = _epic_proj(blocked=1)
        d = _h(epics=[e], piid_labels=[_PIID], project_labels=[_PROJ])._data_piid_project()
        assert d["cells"][f"{_PROJ}|{_PIID}"]["blocked"] == 1

    def test_status_planned_when_no_pct_pi(self):
        e = _epic_proj()
        d = _h(epics=[e], piid_labels=[_PIID], project_labels=[_PROJ])._data_piid_project()
        assert "Planned" in d["cells"][f"{_PROJ}|{_PIID}"]["status"]

    def test_piid_meta_phase_keys(self):
        d = _h(piid_labels=[_PIID])._data_piid_project()
        assert "phase" in d["piid_meta"][_PIID]
        assert "pct" in d["piid_meta"][_PIID]

    def test_multiple_projects_and_piids(self):
        e1 = _epic_proj(id=1, proj=_PROJ,  piid=_PIID)
        e2 = _epic_proj(id=2, proj=_PROJ2, piid=_PIID2)
        d  = _h(epics=[e1, e2],
                piid_labels=[_PIID, _PIID2],
                project_labels=[_PROJ, _PROJ2])._data_piid_project()
        assert d["cells"][f"{_PROJ}|{_PIID}"] is not None
        assert d["cells"][f"{_PROJ2}|{_PIID2}"] is not None
        assert d["cells"][f"{_PROJ}|{_PIID2}"] is None

    def test_json_serializable(self):
        e = _epic_proj()
        json.dumps(_h(epics=[e], piid_labels=[_PIID], project_labels=[_PROJ])._data_piid_project())


# ---------------------------------------------------------------------------
# _data_piid_project_detail
# ---------------------------------------------------------------------------

class TestDataPiidProjectDetail:
    def test_returns_required_keys(self):
        d = _h()._data_piid_project_detail()
        assert {"report_date", "group", "project_labels", "pis"} <= d.keys()

    def test_pi_section_per_piid(self):
        e = _epic_proj()
        d = _h(epics=[e], piid_labels=[_PIID, _PIID2], project_labels=[_PROJ])._data_piid_project_detail()
        assert len(d["pis"]) == 2
        assert d["pis"][0]["piid"] == _PIID
        assert d["pis"][1]["piid"] == _PIID2

    def test_project_row_has_data(self):
        e = _epic_proj(pct=50, planned=20, actual=10)
        d = _h(epics=[e], piid_labels=[_PIID], project_labels=[_PROJ])._data_piid_project_detail()
        proj_row = d["pis"][0]["projects"][0]
        assert proj_row["has_data"] is True
        assert proj_row["total"] == 1
        assert proj_row["planned"] == 20

    def test_project_row_no_data(self):
        d = _h(piid_labels=[_PIID], project_labels=[_PROJ])._data_piid_project_detail()
        proj_row = d["pis"][0]["projects"][0]
        assert proj_row["has_data"] is False
        assert proj_row["total"] == 0

    def test_phase_future_when_no_pct_pi(self):
        d = _h(piid_labels=[_PIID], project_labels=[_PROJ])._data_piid_project_detail()
        assert d["pis"][0]["phase"] == "Future"

    def test_json_serializable(self):
        e = _epic_proj()
        json.dumps(_h(epics=[e], piid_labels=[_PIID], project_labels=[_PROJ])._data_piid_project_detail())


# ---------------------------------------------------------------------------
# _data_portfolio
# ---------------------------------------------------------------------------

class TestDataPortfolio:
    def test_returns_required_keys(self):
        d = _h()._data_portfolio()
        assert {"report_date", "group", "summary", "hierarchy"} <= d.keys()

    def test_empty_summary_and_hierarchy(self):
        d = _h()._data_portfolio()
        assert d["summary"] == []
        assert d["hierarchy"] == []

    def test_summary_row_per_type(self):
        e = make_epic(id=1, etype="Feature", planned_weight=10, actual_weight=5)
        d = _h(epics=[e])._data_portfolio()
        assert len(d["summary"]) == 1
        assert d["summary"][0]["type"] == "Feature"
        assert d["summary"][0]["total"] == 1

    def test_summary_counts(self):
        epics = [
            make_epic(id=1, etype="Epic",       state="opened"),
            make_epic(id=2, etype="Feature",    state="closed"),
            make_epic(id=3, etype="Capability", state="opened"),
        ]
        d = _h(epics=epics)._data_portfolio()
        types = {r["type"]: r for r in d["summary"]}
        assert types["Epic"]["open"] == 1
        assert types["Feature"]["closed"] == 1

    def test_hierarchy_top_level_epics(self):
        e = make_epic(id=1, etype="Epic")
        d = _h(epics=[e])._data_portfolio()
        assert len(d["hierarchy"]) == 1
        assert d["hierarchy"][0]["id"] == 1

    def test_hierarchy_children_nested(self):
        parent = make_epic(id=1, etype="Epic", parent_id=None)
        child  = make_epic(id=2, etype="Feature", parent_id=1)
        d      = _h(epics=[parent, child])._data_portfolio()
        assert len(d["hierarchy"]) == 1
        assert len(d["hierarchy"][0]["children"]) == 1
        assert d["hierarchy"][0]["children"][0]["id"] == 2

    def test_blocked_flag(self):
        e = make_epic(id=1, etype="Epic", blocked_by_count=2)
        d = _h(epics=[e])._data_portfolio()
        assert d["hierarchy"][0]["blocked"] is True

    def test_status_icon_planned_when_no_pct_pi(self):
        e = make_epic(id=1, etype="Epic")
        e["pct_through_pi"] = None
        d = _h(epics=[e])._data_portfolio()
        assert d["hierarchy"][0]["status_icon"] == "🔵"

    def test_json_serializable(self):
        parent = make_epic(id=1, etype="Epic")
        child  = make_epic(id=2, etype="Feature", parent_id=1)
        json.dumps(_h(epics=[parent, child])._data_portfolio())


# ---------------------------------------------------------------------------
# _data_workload
# ---------------------------------------------------------------------------

class TestDataWorkload:
    def _wl_harness(self, epics=None):
        epics = epics or []
        return _h(
            epics=epics,
            groups_by_id={10: _VS, 20: _ART, 30: _TEAM},
            groups_by_parent={1: [_VS], 10: [_ART], 20: [_TEAM]},
            vs_groups=[_VS],
        )

    def _feature(self, id=1, piid=_PIID, gid=30, planned=10, actual=8, pct=50):
        e = make_epic(id=id, etype="Feature", piid=piid, group_id=gid,
                      planned_weight=planned, actual_weight=actual, pct_complete=pct)
        e["labels"] = ["Feature", piid]
        return e

    def test_returns_required_keys(self):
        d = _h()._data_workload()
        assert {"report_date", "group", "pis"} <= d.keys()

    def test_empty_returns_empty_pis(self):
        d = _h()._data_workload()
        assert d["pis"] == []

    def test_pi_section_created(self):
        f = self._feature()
        d = self._wl_harness([f])._data_workload()
        assert len(d["pis"]) == 1
        assert d["pis"][0]["piid"] == _PIID

    def test_group_row_in_pi(self):
        f = self._feature(planned=20, actual=15)
        d = self._wl_harness([f])._data_workload()
        grp = d["pis"][0]["groups"][0]
        assert grp["planned"] == 20
        assert grp["actual"] == 15
        assert grp["delta"] == -5
        assert grp["epic_count"] == 1

    def test_phase_unknown_when_no_dates(self):
        # Use a non-standard PIID format that the YYYYQn regex cannot parse
        f = self._feature(piid="PIID::CUSTOM-FORMAT")
        d = self._wl_harness([f])._data_workload()
        assert d["pis"][0]["phase"] == "unknown"

    def test_multiple_pis_sorted(self):
        f1 = self._feature(id=1, piid=_PIID2)
        f2 = self._feature(id=2, piid=_PIID)
        d  = self._wl_harness([f1, f2])._data_workload()
        piids = [p["piid"] for p in d["pis"]]
        assert set(piids) == {_PIID, _PIID2}

    def test_status_planned_for_unknown_phase(self):
        # Non-parseable label → phase "unknown" → status "🔵 Planned"
        f = self._feature(piid="PIID::CUSTOM-FORMAT")
        d = self._wl_harness([f])._data_workload()
        assert d["pis"][0]["groups"][0]["status"] == "🔵 Planned"

    def test_json_serializable(self):
        f = self._feature()
        json.dumps(self._wl_harness([f])._data_workload())


# ---------------------------------------------------------------------------
# _data_flow_metrics
# ---------------------------------------------------------------------------

class TestDataFlowMetrics:
    def test_returns_required_keys(self):
        d = _h()._data_flow_metrics()
        assert {"report_date", "group", "velocity", "load", "load_no_pi",
                "distribution", "flow_time", "predictability"} <= d.keys()

    def test_empty_all_sections(self):
        d = _h()._data_flow_metrics()
        assert d["velocity"] == []
        assert d["load"] == []
        assert d["load_no_pi"] is None
        assert d["predictability"] == []

    def _typed_epic(self, id=1, etype="Feature", piid=_PIID, state="opened",
                    created_at=None, updated_at=None):
        e = make_epic(id=id, etype=etype, state=state, piid=piid)
        e["labels"] = [etype, piid]
        e["created_at"] = created_at or "2025-01-01"
        e["updated_at"] = updated_at or "2025-02-01"
        return e

    def test_velocity_counts_closed_features(self):
        e = self._typed_epic(state="closed")
        d = _h(epics=[e], piid_labels=[_PIID])._data_flow_metrics()
        assert d["velocity"][0]["features"] == 1
        assert d["velocity"][0]["total"] == 1

    def test_velocity_does_not_count_open(self):
        e = self._typed_epic(state="opened")
        d = _h(epics=[e], piid_labels=[_PIID])._data_flow_metrics()
        assert d["velocity"][0]["features"] == 0

    def test_load_counts_open_epics(self):
        e = self._typed_epic(state="opened")
        d = _h(epics=[e], piid_labels=[_PIID])._data_flow_metrics()
        assert d["load"][0]["features"] == 1

    def test_load_no_pi_populated(self):
        e = make_epic(id=1, etype="Feature", piid=None)
        e["labels"] = ["Feature"]
        d = _h(epics=[e])._data_flow_metrics()
        assert d["load_no_pi"] is not None
        assert d["load_no_pi"]["features"] == 1

    def test_distribution_by_type_has_three_rows(self):
        d = _h()._data_flow_metrics()
        assert len(d["distribution"]["by_type"]) == 3

    def test_distribution_no_work_type_labels(self):
        d = _h()._data_flow_metrics()
        assert d["distribution"]["has_work_type_labels"] is False
        assert d["distribution"]["by_work_type"] == []

    def test_distribution_with_work_type_labels(self):
        e = self._typed_epic()
        e["labels"].append("type::feature")
        d = _h(epics=[e], work_type_labels=["type::feature"])._data_flow_metrics()
        assert d["distribution"]["has_work_type_labels"] is True
        assert len(d["distribution"]["by_work_type"]) == 1
        assert d["distribution"]["by_work_type"][0]["label"] == "type::feature"

    def test_predictability_counts(self):
        closed = self._typed_epic(id=1, state="closed")
        opened = self._typed_epic(id=2, state="opened")
        d = _h(epics=[closed, opened], piid_labels=[_PIID])._data_flow_metrics()
        assert len(d["predictability"]) == 1
        p = d["predictability"][0]
        assert p["committed"] == 2
        assert p["delivered"] == 1
        assert p["pct"] == 50

    def test_predictability_icon_green_at_80(self):
        epics = [self._typed_epic(id=i, state="closed") for i in range(1, 5)]
        epics.append(self._typed_epic(id=5, state="opened"))
        d = _h(epics=epics, piid_labels=[_PIID])._data_flow_metrics()
        assert d["predictability"][0]["pct"] == 80
        assert d["predictability"][0]["icon"] == "🟢"

    def test_flow_time_open_ages_three_types(self):
        d = _h()._data_flow_metrics()
        assert len(d["flow_time"]["open_ages"]) == 3

    def test_flow_time_no_closed_data(self):
        d = _h()._data_flow_metrics()
        assert d["flow_time"]["has_closed_data"] is False

    def test_json_serializable(self):
        e = self._typed_epic()
        json.dumps(_h(epics=[e], piid_labels=[_PIID])._data_flow_metrics())


# ---------------------------------------------------------------------------
# write_report_json — all 16 files written
# ---------------------------------------------------------------------------

class TestWriteReportJsonPhase4a:
    ALL_KEYS = [
        "health-dashboard", "orphan-epics", "orphan-issues", "premature-closures",
        "unassigned-pi", "risk-register", "wsjf",
        "blocking", "epic-lifecycle", "pi-predictability", "art-capacity-balance",
        "piid-project", "piid-project-detail", "portfolio", "workload", "flow-metrics",
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
