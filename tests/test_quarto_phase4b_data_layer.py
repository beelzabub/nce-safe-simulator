"""Tests for the 3 phase-4b _data_* extraction methods (Refs #44)."""
import json
import tempfile
from pathlib import Path

import pytest

from tests.conftest import ReportsHarness, make_epic, make_risk

_VS   = {"id": 10, "name": "VS Alpha",  "web_url": "https://gl.com/vs-alpha",  "parent_id": 1}
_ART  = {"id": 20, "name": "ART One",   "web_url": "https://gl.com/art-one",   "parent_id": 10, "full_path": "vs-alpha/art-one"}
_TEAM = {"id": 30, "name": "Team Red",  "web_url": "https://gl.com/team-red",  "parent_id": 20, "full_path": "vs-alpha/art-one/team-red"}

_PROJ_NS = "vs-alpha/art-one/team-red/team-backlog"
_PROJ = {
    "path":                "team-backlog",
    "path_with_namespace": _PROJ_NS,
    "name_with_namespace": "VS Alpha / ART One / Team Red / team-backlog",
    "web_url":             f"https://gl.com/{_PROJ_NS}",
    "issues_enabled":      True,
}


def _h(features=None, capabilities=None, epics_all=None, issues=None,
        epics_by_id=None, groups_by_parent=None, vs_groups=None):
    feats = features or []
    caps  = capabilities or []
    h = ReportsHarness(
        epics_all=epics_all,
        metrics={
            "Epic":       [],
            "Capability": caps,
            "Feature":    feats,
        },
        groups_by_parent=groups_by_parent or {1: [_VS], 10: [_ART], 20: [_TEAM]},
        vs_groups=vs_groups or [_VS],
    )
    if issues is not None:
        h._rd_projects_by_nsid = {_TEAM["id"]: [_PROJ]}
        h._rd_issues_by_project[_PROJ_NS] = issues
    if epics_by_id is not None:
        h._rd_epics_by_id = epics_by_id
    return h


def _feature(team_id=30, **kw):
    return make_epic(etype="Feature", group_id=team_id, **kw)


def _capability(art_id=20, **kw):
    return make_epic(etype="Capability", group_id=art_id, piid="PIID::2026Q1", **kw)


def _direct_feature(art_id=20, **kw):
    return make_epic(etype="Feature", group_id=art_id, piid="PIID::2026Q1",
                     parent_id=None, **kw)


def _issue(iid=1, title="Story", state="opened", weight=3, epic_id=None):
    return {
        "iid":     iid,
        "title":   title,
        "web_url": f"https://gl.com/issues/{iid}",
        "state":   state,
        "weight":  weight,
        "epic_id": epic_id,
    }


# ---------------------------------------------------------------------------
# _data_art_feature_status
# ---------------------------------------------------------------------------

class TestDataArtFeatureStatus:
    def test_returns_required_keys(self):
        d = _h()._data_art_feature_status()
        assert {"report_date", "group", "value_streams"} <= d.keys()

    def test_empty_returns_no_value_streams(self):
        d = _h()._data_art_feature_status()
        assert d["value_streams"] == []

    def test_vs_appears_when_feature_present(self):
        d = _h(features=[_feature()])._data_art_feature_status()
        assert len(d["value_streams"]) == 1
        assert d["value_streams"][0]["vs_name"] == "VS Alpha"

    def test_art_nested_in_vs(self):
        d = _h(features=[_feature()])._data_art_feature_status()
        arts = d["value_streams"][0]["arts"]
        assert len(arts) == 1
        assert arts[0]["art_name"] == "ART One"

    def test_team_nested_in_art(self):
        d = _h(features=[_feature()])._data_art_feature_status()
        teams = d["value_streams"][0]["arts"][0]["teams"]
        assert len(teams) == 1
        assert teams[0]["team_name"] == "Team Red"

    def test_feature_in_team(self):
        f = _feature(title="My Feature")
        d = _h(features=[f])._data_art_feature_status()
        features = d["value_streams"][0]["arts"][0]["teams"][0]["features"]
        assert len(features) == 1
        assert features[0]["title"] == "My Feature"

    def test_feature_has_required_fields(self):
        d = _h(features=[_feature()])._data_art_feature_status()
        feat = d["value_streams"][0]["arts"][0]["teams"][0]["features"][0]
        for key in ("title", "url", "piid", "state", "pct_complete", "pct_pi",
                    "planned", "actual", "status", "risk_reason"):
            assert key in feat

    def test_status_planned_when_no_pct_pi(self):
        f = _feature(pct_through_pi=None)
        d = _h(features=[f])._data_art_feature_status()
        feat = d["value_streams"][0]["arts"][0]["teams"][0]["features"][0]
        assert feat["status"] == "🔵 Planned"

    def test_status_blocked(self):
        f = _feature(blocked_by_count=1)
        d = _h(features=[f])._data_art_feature_status()
        feat = d["value_streams"][0]["arts"][0]["teams"][0]["features"][0]
        assert feat["status"] == "🔒 Blocked"

    def test_status_at_risk(self):
        f = _feature(pct_through_pi=60, pct_complete=30)
        d = _h(features=[f])._data_art_feature_status()
        feat = d["value_streams"][0]["arts"][0]["teams"][0]["features"][0]
        assert feat["status"] == "⚠️ At Risk"

    def test_status_on_track(self):
        f = _feature(pct_through_pi=50, pct_complete=80)
        d = _h(features=[f])._data_art_feature_status()
        feat = d["value_streams"][0]["arts"][0]["teams"][0]["features"][0]
        assert feat["status"] == "✅ On Track"

    def test_art_summary_counts_at_risk_and_blocked(self):
        f1 = _feature(id=1, pct_through_pi=60, pct_complete=20)
        f2 = _feature(id=2, blocked_by_count=1)
        d  = _h(features=[f1, f2])._data_art_feature_status()
        art = d["value_streams"][0]["arts"][0]
        assert art["at_risk"]        == 1
        assert art["blocked"]        == 1
        assert art["total_features"] == 2

    def test_risk_reason_roam(self):
        risk = make_risk(roam_status="roam::owned")
        f    = _feature(roam_risks=[risk])
        d    = _h(features=[f])._data_art_feature_status()
        feat = d["value_streams"][0]["arts"][0]["teams"][0]["features"][0]
        assert "risk" in feat["risk_reason"].lower()

    def test_json_serializable(self):
        json.dumps(_h(features=[_feature()])._data_art_feature_status())


# ---------------------------------------------------------------------------
# _data_team_backlog
# ---------------------------------------------------------------------------

class TestDataTeamBacklog:
    def test_returns_required_keys(self):
        d = _h()._data_team_backlog()
        assert {"report_date", "group", "teams"} <= d.keys()

    def test_team_appears_without_backlog_project(self):
        d = _h()._data_team_backlog()
        assert len(d["teams"]) == 1
        assert d["teams"][0]["has_backlog_project"] is False

    def test_team_appears_with_backlog_project(self):
        d = _h(issues=[])._data_team_backlog()
        assert d["teams"][0]["has_backlog_project"] is True

    def test_team_has_required_fields(self):
        d = _h(issues=[])._data_team_backlog()
        t = d["teams"][0]
        for key in ("vs_name", "art_name", "team_name", "team_url",
                    "has_backlog_project", "total", "open", "closed",
                    "total_weight", "closed_weight", "pct_done",
                    "by_feature", "unlinked"):
            assert key in t

    def test_pct_done_from_weights(self):
        issues = [
            _issue(iid=1, state="closed", weight=5),
            _issue(iid=2, state="opened", weight=5),
        ]
        d = _h(issues=issues)._data_team_backlog()
        assert d["teams"][0]["pct_done"] == 50

    def test_unlinked_issue_in_unlinked(self):
        issues = [_issue(iid=1, epic_id=None)]
        d = _h(issues=issues)._data_team_backlog()
        assert len(d["teams"][0]["unlinked"]) == 1

    def test_linked_issue_in_by_feature(self):
        issues = [_issue(iid=1, epic_id=100)]
        d = _h(issues=issues)._data_team_backlog()
        assert len(d["teams"][0]["by_feature"]) == 1
        assert d["teams"][0]["by_feature"][0]["epic_id"] == 100

    def test_feature_group_pct_done(self):
        issues = [
            _issue(iid=1, epic_id=100, state="closed", weight=4),
            _issue(iid=2, epic_id=100, state="opened", weight=4),
        ]
        d = _h(issues=issues)._data_team_backlog()
        group = d["teams"][0]["by_feature"][0]
        assert group["pct_done"] == 50

    def test_epic_title_from_epics_by_id(self):
        epic   = make_epic(id=100, title="Parent Feature", etype="Feature")
        issues = [_issue(iid=1, epic_id=100)]
        d = _h(issues=issues, epics_by_id={100: epic})._data_team_backlog()
        assert d["teams"][0]["by_feature"][0]["epic_title"] == "Parent Feature"

    def test_team_vs_art_names_correct(self):
        d = _h(issues=[])._data_team_backlog()
        t = d["teams"][0]
        assert t["vs_name"]   == "VS Alpha"
        assert t["art_name"]  == "ART One"
        assert t["team_name"] == "Team Red"

    def test_json_serializable(self):
        issues = [_issue(iid=1, epic_id=100)]
        json.dumps(_h(issues=issues)._data_team_backlog())


# ---------------------------------------------------------------------------
# _data_vs_capability_dashboard
# ---------------------------------------------------------------------------

class TestDataVsCapabilityDashboard:
    def test_returns_required_keys(self):
        d = _h()._data_vs_capability_dashboard()
        assert {"report_date", "group", "value_streams"} <= d.keys()

    def test_empty_no_value_streams(self):
        d = _h()._data_vs_capability_dashboard()
        assert d["value_streams"] == []

    def test_vs_appears_with_capability(self):
        d = _h(capabilities=[_capability()])._data_vs_capability_dashboard()
        assert len(d["value_streams"]) == 1
        assert d["value_streams"][0]["vs_name"] == "VS Alpha"

    def test_vs_appears_with_direct_feature(self):
        d = _h(features=[_direct_feature()])._data_vs_capability_dashboard()
        assert len(d["value_streams"]) == 1

    def test_pi_section_created(self):
        d = _h(capabilities=[_capability()])._data_vs_capability_dashboard()
        vs = d["value_streams"][0]
        assert len(vs["pis"]) == 1
        assert vs["pis"][0]["piid"] == "PIID::2026Q1"

    def test_capability_in_pi_caps_section(self):
        d = _h(capabilities=[_capability()])._data_vs_capability_dashboard()
        pi = d["value_streams"][0]["pis"][0]
        assert len(pi["capabilities"]) == 1
        assert pi["capabilities"][0]["art_name"] == "ART One"

    def test_direct_feature_in_pi_direct_section(self):
        d = _h(features=[_direct_feature()])._data_vs_capability_dashboard()
        pi = d["value_streams"][0]["pis"][0]
        assert len(pi["direct_features"]) == 1

    def test_capability_section_absent_when_no_caps(self):
        d = _h(features=[_direct_feature()])._data_vs_capability_dashboard()
        pi = d["value_streams"][0]["pis"][0]
        assert pi["capabilities"] == []

    def test_direct_section_absent_when_no_direct(self):
        d = _h(capabilities=[_capability()])._data_vs_capability_dashboard()
        pi = d["value_streams"][0]["pis"][0]
        assert pi["direct_features"] == []

    def test_feature_with_cap_parent_excluded_from_direct(self):
        cap  = _capability(id=200)
        feat = make_epic(etype="Feature", group_id=20, piid="PIID::2026Q1",
                         parent_id=200)
        d = _h(capabilities=[cap], features=[feat])._data_vs_capability_dashboard()
        pi = d["value_streams"][0]["pis"][0]
        assert pi["direct_features"] == []

    def test_art_section_has_required_fields(self):
        d = _h(capabilities=[_capability()])._data_vs_capability_dashboard()
        art = d["value_streams"][0]["pis"][0]["capabilities"][0]
        for key in ("art_name", "art_url", "count", "planned", "actual",
                    "delta", "avg_pct", "status", "items"):
            assert key in art

    def test_item_has_required_fields(self):
        d = _h(capabilities=[_capability()])._data_vs_capability_dashboard()
        item = d["value_streams"][0]["pis"][0]["capabilities"][0]["items"][0]
        for key in ("title", "url", "state", "pct_complete", "planned",
                    "actual", "status", "risk_reason"):
            assert key in item

    def test_at_risk_reason_for_roam(self):
        risk = make_risk(roam_status="roam::mitigated")
        d    = _h(capabilities=[_capability(roam_risks=[risk])])._data_vs_capability_dashboard()
        item = d["value_streams"][0]["pis"][0]["capabilities"][0]["items"][0]
        assert "risk" in item["risk_reason"].lower()

    def test_vs_summary_counts_populated(self):
        d = _h(capabilities=[_capability()],
                features=[_direct_feature()])._data_vs_capability_dashboard()
        vs = d["value_streams"][0]
        assert vs["total_caps"]   == 1
        assert vs["total_direct"] == 1

    def test_json_serializable(self):
        json.dumps(
            _h(capabilities=[_capability()],
               features=[_direct_feature()])._data_vs_capability_dashboard()
        )


# ---------------------------------------------------------------------------
# write_report_json — all 19 files written
# ---------------------------------------------------------------------------

class TestWriteReportJsonPhase4b:
    ALL_KEYS = [
        "health-dashboard", "orphan-epics", "orphan-issues", "premature-closures",
        "unassigned-pi", "risk-register", "wsjf",
        "blocking", "epic-lifecycle", "pi-predictability", "art-capacity-balance",
        "piid-project", "piid-project-detail", "portfolio", "workload", "flow-metrics",
        "art-feature-status", "team-backlog", "vs-capability-dashboard",
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
