"""Tests for generate_workload_report (Refs #24)."""
import sys



from tests.conftest import ReportsHarness, make_epic


def _group(id=30, name="Team Alpha", full_path="test/team-alpha"):
    return {
        "id":        id,
        "name":      name,
        "full_path": full_path,
        "web_url":   f"https://gitlab.com/{full_path}",
    }


def _harness(epics=None, groups_by_id=None):
    all_epics = epics or []
    return ReportsHarness(
        metrics={
            "Epic":       [e for e in all_epics if e.get("type") == "Epic"],
            "Capability": [e for e in all_epics if e.get("type") == "Capability"],
            "Feature":    [e for e in all_epics if e.get("type") == "Feature"],
        },
        groups_by_id=groups_by_id or {},
    )


def _run(h):
    h.generate_workload_report()
    return h._uploaded.get(f"{h._wiki_t3}/ART-Team Workload", "")


class TestWorkloadReportStructure:
    def test_no_upload_when_empty(self):
        h = _harness()
        h.generate_workload_report()
        assert f"{h._wiki_t3}/ART-Team Workload" not in h._uploaded

    def test_uploads_to_correct_wiki_page_when_data_present(self):
        epic = make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         group_id=30, labels=["Feature", "PIID::2026Q1"])
        h = _harness(epics=[epic])
        h.generate_workload_report()
        assert f"{h._wiki_t3}/ART-Team Workload" in h._uploaded

    def test_page_title_present(self):
        epic = make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         group_id=30, labels=["Feature", "PIID::2026Q1"])
        content = _run(_harness(epics=[epic]))
        assert "# ART/Team Workload Report" in content

    def test_pi_section_heading_present(self):
        epic = make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         group_id=30, labels=["Feature", "PIID::2026Q1"])
        content = _run(_harness(epics=[epic]))
        assert "PIID::2026Q1" in content

    def test_group_name_shown_when_in_groups_by_id(self):
        grp  = _group(id=30, name="ART Alpha")
        epic = make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         group_id=30, labels=["Feature", "PIID::2026Q1"],
                         planned_weight=10, actual_weight=8)
        content = _run(_harness(epics=[epic], groups_by_id={30: grp}))
        assert "ART Alpha" in content

    def test_fallback_group_name_when_not_in_groups_by_id(self):
        epic = make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         group_id=99, labels=["Feature", "PIID::2026Q1"])
        content = _run(_harness(epics=[epic]))
        assert "Group 99" in content


class TestWorkloadReportStatus:
    def test_at_risk_when_pct_done_lt_pct_pi(self):
        grp  = _group(id=30, name="Team A")
        epic = make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         group_id=30, labels=["Feature", "PIID::2026Q1"],
                         pct_complete=20, planned_weight=10, actual_weight=5)
        h = _harness(epics=[epic], groups_by_id={30: grp})
        h._mock_pct_pi = 60
        content = _run(h)
        assert "⚠️ At Risk" in content

    def test_on_track_when_pct_done_gte_pct_pi(self):
        grp  = _group(id=30, name="Team B")
        epic = make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         group_id=30, labels=["Feature", "PIID::2026Q1"],
                         pct_complete=70, planned_weight=10, actual_weight=8)
        h = _harness(epics=[epic], groups_by_id={30: grp})
        h._mock_pct_pi = 50
        content = _run(h)
        assert "✅ On Track" in content

    def test_planned_status_when_no_pct_pi(self):
        grp  = _group(id=30, name="Team C")
        epic = make_epic(id=10, etype="Feature", piid="PIID::2099Q4",
                         group_id=30, labels=["Feature", "PIID::2099Q4"],
                         pct_complete=0, planned_weight=10, actual_weight=0)
        h = _harness(epics=[epic], groups_by_id={30: grp})
        # _mock_pct_pi not set → returns None → "future" phase
        content = _run(h)
        assert "🔵 Planned" in content
