"""Tests for the 6 phase-2 _data_* extraction methods and write_report_json (Refs #40)."""
import json
import tempfile
from pathlib import Path

import pytest

from tests.conftest import ReportsHarness, make_epic, make_risk

_PIID = "PIID::Q1-FY25"


def _h(**kwargs):
    epics = kwargs.pop("epics", [])
    return ReportsHarness(
        epics_all=epics,
        metrics={
            "Epic":       [e for e in epics if e.get("type") == "Epic"],
            "Capability": [e for e in epics if e.get("type") == "Capability"],
            "Feature":    [e for e in epics if e.get("type") == "Feature"],
        },
        **kwargs,
    )


# ---------------------------------------------------------------------------
# _data_orphan_epics
# ---------------------------------------------------------------------------

class TestDataOrphanEpics:
    def test_returns_dict_with_required_keys(self):
        d = _h()._data_orphan_epics()
        assert {"report_date", "group", "orphans"} <= d.keys()

    def test_empty_epics_returns_empty_orphans(self):
        d = _h()._data_orphan_epics()
        assert d["orphans"] == []

    def test_epic_with_no_parent_and_no_children_is_orphan(self):
        epic = make_epic(id=1, etype="Epic", parent_id=None)
        d = _h(epics=[epic])._data_orphan_epics()
        assert len(d["orphans"]) == 1
        assert d["orphans"][0]["title"] == epic["title"]

    def test_epic_with_parent_is_not_orphan(self):
        parent = make_epic(id=1, etype="Epic", parent_id=None)
        child  = make_epic(id=2, etype="Capability", parent_id=1)
        d = _h(epics=[parent, child])._data_orphan_epics()
        assert len(d["orphans"]) == 0

    def test_epic_that_is_a_parent_is_not_orphan(self):
        parent = make_epic(id=1, etype="Epic", parent_id=None)
        child  = make_epic(id=2, etype="Capability", parent_id=1)
        d = _h(epics=[parent, child])._data_orphan_epics()
        # parent has children → not orphan; child has parent → not orphan
        assert d["orphans"] == []

    def test_orphan_row_has_type_and_icon(self):
        epic = make_epic(id=1, etype="Epic", parent_id=None)
        row = _h(epics=[epic])._data_orphan_epics()["orphans"][0]
        assert row["type"] == "Epic"
        assert row["icon"] == "🏆"

    def test_json_serializable(self):
        epic = make_epic(id=1, etype="Epic")
        json.dumps(_h(epics=[epic])._data_orphan_epics())


# ---------------------------------------------------------------------------
# _data_orphan_issues
# ---------------------------------------------------------------------------

class TestDataOrphanIssues:
    def _harness_with_issues(self, issues, project_path="grp/proj"):
        from collections import defaultdict
        h = _h()
        h._rd_issues_by_project = defaultdict(list)
        h._rd_issues_by_project[project_path] = issues
        h._rd_projects_by_nsid = {
            1: [{"path_with_namespace": project_path, "name": "proj",
                 "name_with_namespace": "grp / proj", "issues_enabled": True,
                 "namespace_id": 1}]
        }
        return h

    def _issue(self, iid=1, title="Iss", epic_id=None, labels=None):
        return {
            "iid": iid, "title": title, "state": "opened",
            "web_url": f"https://gl.com/issues/{iid}",
            "epic_id": epic_id, "assignees": [],
            "labels": labels or [],
        }

    def test_returns_required_keys(self):
        d = _h()._data_orphan_issues()
        assert {"report_date", "group", "total", "projects"} <= d.keys()

    def test_issue_with_epic_id_not_orphan(self):
        issue = self._issue(epic_id=99)
        h = self._harness_with_issues([issue])
        d = h._data_orphan_issues()
        assert d["total"] == 0

    def test_issue_with_roam_label_not_orphan(self):
        issue = self._issue(labels=["roam::owned"])
        h = self._harness_with_issues([issue])
        d = h._data_orphan_issues()
        assert d["total"] == 0

    def test_bare_issue_is_orphan(self):
        issue = self._issue()
        h = self._harness_with_issues([issue])
        d = h._data_orphan_issues()
        assert d["total"] == 1
        assert len(d["projects"]) == 1

    def test_project_name_included(self):
        issue = self._issue()
        h = self._harness_with_issues([issue])
        d = h._data_orphan_issues()
        assert d["projects"][0]["name"]  # non-empty

    def test_json_serializable(self):
        json.dumps(_h()._data_orphan_issues())


# ---------------------------------------------------------------------------
# _data_premature_closures
# ---------------------------------------------------------------------------

class TestDataPrematureClosures:
    def test_returns_required_keys(self):
        d = _h()._data_premature_closures()
        assert {"report_date", "group", "total", "findings"} <= d.keys()

    def test_open_epic_not_flagged(self):
        epic = make_epic(id=1, etype="Epic", state="opened")
        d = _h(epics=[epic])._data_premature_closures()
        assert d["total"] == 0

    def test_closed_epic_with_no_open_children_not_flagged(self):
        parent = make_epic(id=1, etype="Epic", state="closed")
        child  = make_epic(id=2, etype="Capability", state="closed", parent_id=1)
        d = _h(epics=[parent, child])._data_premature_closures()
        assert d["total"] == 0

    def test_closed_epic_with_open_child_is_flagged(self):
        parent = make_epic(id=1, etype="Epic", state="closed")
        child  = make_epic(id=2, etype="Capability", state="opened", parent_id=1)
        d = _h(epics=[parent, child])._data_premature_closures()
        assert d["total"] == 1
        assert d["findings"][0]["title"] == parent["title"]

    def test_finding_has_open_children_list(self):
        parent = make_epic(id=1, etype="Epic", state="closed")
        child  = make_epic(id=2, etype="Capability", state="opened", parent_id=1)
        d = _h(epics=[parent, child])._data_premature_closures()
        assert len(d["findings"][0]["open_children"]) == 1

    def test_closed_epic_with_open_issues_is_flagged(self):
        from collections import defaultdict
        parent = make_epic(id=1, etype="Epic", state="closed")
        h = _h(epics=[parent])
        h._rd_issues_by_epic[1] = [
            {"iid": 5, "title": "Open issue", "state": "opened",
             "web_url": "", "assignees": []}
        ]
        d = h._data_premature_closures()
        assert d["total"] == 1
        assert len(d["findings"][0]["open_issues"]) == 1

    def test_json_serializable(self):
        json.dumps(_h()._data_premature_closures())


# ---------------------------------------------------------------------------
# _data_unassigned_pi
# ---------------------------------------------------------------------------

class TestDataUnassignedPi:
    def test_returns_required_keys(self):
        d = _h()._data_unassigned_pi()
        assert {"report_date", "group", "total", "by_type"} <= d.keys()

    def test_by_type_has_all_buckets(self):
        d = _h()._data_unassigned_pi()
        assert {"Epic", "Capability", "Feature", "Unknown"} <= d["by_type"].keys()

    def test_epic_with_piid_excluded(self):
        epic = make_epic(id=1, etype="Epic", piid=_PIID)
        d = _h(epics=[epic])._data_unassigned_pi()
        assert d["total"] == 0

    def test_epic_without_piid_included(self):
        epic = make_epic(id=1, etype="Epic", piid=None)
        epic["labels"] = ["Epic"]
        d = _h(epics=[epic])._data_unassigned_pi()
        assert d["total"] == 1
        assert len(d["by_type"]["Epic"]) == 1

    def test_parent_title_resolved(self):
        parent = make_epic(id=1, etype="Epic", title="Parent Epic", piid=None)
        parent["labels"] = ["Epic"]
        child  = make_epic(id=2, etype="Capability", piid=None, parent_id=1)
        child["labels"] = ["Capability"]
        d = _h(epics=[parent, child])._data_unassigned_pi()
        cap_rows = d["by_type"]["Capability"]
        assert cap_rows[0]["parent"] == "Parent Epic"

    def test_rows_sorted_by_title(self):
        e1 = make_epic(id=1, etype="Epic", title="Zebra", piid=None)
        e1["labels"] = ["Epic"]
        e2 = make_epic(id=2, etype="Epic", title="Alpha", piid=None)
        e2["labels"] = ["Epic"]
        d = _h(epics=[e1, e2])._data_unassigned_pi()
        titles = [r["title"] for r in d["by_type"]["Epic"]]
        assert titles == sorted(titles)

    def test_json_serializable(self):
        json.dumps(_h()._data_unassigned_pi())


# ---------------------------------------------------------------------------
# _data_risk_register
# ---------------------------------------------------------------------------

class TestDataRiskRegister:
    def test_returns_required_keys(self):
        d = _h()._data_risk_register()
        assert {"report_date", "group", "summary", "roam_rows",
                "blocked", "child_overdue", "past_due", "behind_schedule"} <= d.keys()

    def test_summary_has_required_keys(self):
        s = _h()._data_risk_register()["summary"]
        assert {"roam", "total_all_roam", "total_linked", "alerts", "vs_counts"} <= s.keys()

    def test_roam_row_structure(self):
        risk = make_risk(iid=1, roam_status="roam::owned")
        epic = make_epic(id=1, etype="Epic", roam_risks=[risk])
        d = _h(epics=[epic])._data_risk_register()
        rows = d["roam_rows"]["roam::owned"]
        assert len(rows) == 1
        assert {"title", "url", "assignee", "epics"} <= rows[0].keys()

    def test_blocked_epic_appears_in_blocked_section(self):
        epic = make_epic(id=1, etype="Epic", blocked_by_count=2)
        epic["labels"] = ["Epic"]
        d = _h(epics=[epic])._data_risk_register()
        assert len(d["blocked"]) == 1

    def test_behind_schedule_detected(self):
        epic = make_epic(id=1, etype="Feature", pct_complete=10)
        epic["pct_through_pi"] = 60
        epic["labels"] = ["Feature"]
        d = _h(epics=[epic])._data_risk_register()
        assert len(d["behind_schedule"]) == 1

    def test_closed_epic_excluded_from_conditions(self):
        epic = make_epic(id=1, etype="Epic", state="closed", blocked_by_count=2)
        epic["labels"] = ["Epic"]
        d = _h(epics=[epic])._data_risk_register()
        assert len(d["blocked"]) == 0

    def test_json_serializable(self):
        json.dumps(_h()._data_risk_register())


# ---------------------------------------------------------------------------
# _data_wsjf
# ---------------------------------------------------------------------------

class TestDataWsjf:
    def _wsjf_epic(self, id=1, value=8, urgency=5, risk=3, size=10):
        epic = make_epic(id=id, etype="Epic", planned_weight=size)
        epic["labels"] = ["Epic", f"wsjf-urgency::{urgency}", f"wsjf-risk::{risk}"]
        epic["business_value"] = value
        epic["state"] = "Opened"
        return epic

    def test_returns_required_keys(self):
        d = _h()._data_wsjf()
        assert {"report_date", "group", "summary", "candidates", "blocked_bv"} <= d.keys()

    def test_no_scored_epics_returns_empty_candidates(self):
        d = _h()._data_wsjf()
        assert d["candidates"] == []

    def test_scored_epic_appears_in_candidates(self):
        epic = self._wsjf_epic()
        d = _h(epics=[epic])._data_wsjf()
        assert len(d["candidates"]) == 1

    def test_score_computed_correctly(self):
        epic = self._wsjf_epic(value=8, urgency=5, risk=3, size=8)
        d = _h(epics=[epic])._data_wsjf()
        c = d["candidates"][0]
        assert c["score"] == round((8 + 5 + 3) / 8, 2)

    def test_missing_size_gives_none_score(self):
        epic = self._wsjf_epic(size=0)
        d = _h(epics=[epic])._data_wsjf()
        assert d["candidates"][0]["score"] is None

    def test_ranks_assigned_in_order(self):
        e1 = self._wsjf_epic(id=1, value=13, urgency=13, risk=13, size=1)
        e2 = self._wsjf_epic(id=2, value=1,  urgency=1,  risk=1,  size=13)
        d  = _h(epics=[e1, e2])._data_wsjf()
        assert d["candidates"][0]["rank"] == 1
        assert d["candidates"][1]["rank"] == 2

    def test_summary_counts_correct(self):
        e1 = self._wsjf_epic(id=1, value=8, urgency=5, risk=3, size=10)
        e2 = self._wsjf_epic(id=2, value=8, urgency=5, risk=3, size=0)
        d  = _h(epics=[e1, e2])._data_wsjf()
        assert d["summary"]["scored"]  == 1
        assert d["summary"]["partial"] == 1

    def test_json_serializable(self):
        epic = self._wsjf_epic()
        json.dumps(_h(epics=[epic])._data_wsjf())

    def test_closed_epic_excluded(self):
        epic = self._wsjf_epic()
        epic["state"] = "Closed"
        d = _h(epics=[epic])._data_wsjf()
        assert d["candidates"] == []


# ---------------------------------------------------------------------------
# write_report_json — all 7 files written
# ---------------------------------------------------------------------------

class TestWriteReportJsonPhase2:
    KEYS = [
        "health-dashboard",
        "orphan-epics",
        "orphan-issues",
        "premature-closures",
        "unassigned-pi",
        "risk-register",
        "wsjf",
    ]

    def test_all_json_files_created(self):
        h = _h()
        with tempfile.TemporaryDirectory() as tmp:
            h.write_report_json(tmp)
            for key in self.KEYS:
                assert (Path(tmp) / f"{key}.json").exists(), f"Missing {key}.json"

    def test_all_json_files_valid(self):
        h = _h()
        with tempfile.TemporaryDirectory() as tmp:
            h.write_report_json(tmp)
            for key in self.KEYS:
                data = json.loads((Path(tmp) / f"{key}.json").read_text())
                assert isinstance(data, dict), f"{key}.json is not a dict"

    def test_creates_dir_if_missing(self):
        h = _h()
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "deep" / "data"
            h.write_report_json(nested)
            assert (nested / "health-dashboard.json").exists()
