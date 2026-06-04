"""Tests for generate_portfolio_health_dashboard (Refs #24)."""
import sys
import pytest

sys.path.insert(0, "/root/.venv/beelzabub-project")

from tests.conftest import ReportsHarness, make_epic

_PIID = "PIID::Q1-FY25"
_VS   = {"id": 10, "name": "Value Stream 01", "web_url": "https://gitlab.com/test/vs-01"}


def _harness(epics=None, vs_groups=None, piid_labels=None, pct_pi=None):
    epics = epics or []
    h = ReportsHarness(
        epics_all=epics,
        metrics={
            "Epic":       [e for e in epics if e.get("type") == "Epic"],
            "Capability": [e for e in epics if e.get("type") == "Capability"],
            "Feature":    [e for e in epics if e.get("type") == "Feature"],
        },
        vs_groups=vs_groups or [],
        piid_labels=piid_labels or [],
    )
    if pct_pi is not None:
        h._mock_pct_pi = pct_pi
    return h


def _run(h):
    h.generate_portfolio_health_dashboard()
    return h._uploaded.get(f"{h._wiki_t1}/Portfolio Health Dashboard", "")


class TestPortfolioHealthDashboardStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = _harness()
        h.generate_portfolio_health_dashboard()
        assert f"{h._wiki_t1}/Portfolio Health Dashboard" in h._uploaded

    def test_portfolio_summary_section_present(self):
        assert "## Portfolio Summary" in _run(_harness())

    def test_value_stream_status_section_present(self):
        assert "## Value Stream Status" in _run(_harness())

    def test_needs_attention_section_present(self):
        assert "## Needs Attention" in _run(_harness())

    def test_empty_state_no_crash(self):
        content = _run(_harness())
        assert content != ""


class TestPortfolioHealthDashboardCounts:
    def test_total_epics_count_reflects_epics_all(self):
        epics = [make_epic(id=i, etype="Epic") for i in range(1, 4)]
        content = _run(_harness(epics=epics))
        assert ">3<" in content

    def test_cross_group_epics_excluded_from_total(self):
        normal = make_epic(id=1, etype="Epic")
        cross  = make_epic(id=2, etype="Epic")
        cross["is_cross_group"] = True
        content = _run(_harness(epics=[normal, cross]))
        assert ">1<" in content

    def test_roam_risk_count_for_active_statuses(self):
        active_statuses = ["roam::owned", "roam::accepted", "roam::mitigated"]
        epics = [
            make_epic(id=i, etype="Epic",
                      roam_risks=[{"roam_status": s}])
            for i, s in enumerate(active_statuses, 1)
        ]
        content = _run(_harness(epics=epics))
        assert ">3<" in content

    def test_resolved_roam_risk_not_counted_as_active(self):
        epic = make_epic(id=1, etype="Epic",
                         roam_risks=[{"roam_status": "roam::resolved"}])
        content = _run(_harness(epics=[epic]))
        assert ">0<" in content


class TestPortfolioHealthDashboardLinks:
    def test_roam_risk_link_points_to_risk_register_wiki(self):
        epic = make_epic(id=1, etype="Epic",
                         roam_risks=[{"roam_status": "roam::owned"}])
        h = _harness(epics=[epic])
        content = _run(h)
        assert "Risk-Register" in content

    def test_all_summary_links_open_in_new_tab(self):
        content = _run(_harness())
        assert content.count('target="_blank"') >= 5

    def test_total_epics_link_is_html_anchor(self):
        content = _run(_harness(epics=[make_epic(id=1, etype="Epic")]))
        assert "<a href=" in content
        assert ">1<" in content


class TestPortfolioHealthDashboardTrafficLights:
    def test_schedule_green_when_pct_done_close_to_elapsed(self):
        # 55% done, 50% elapsed → gap = -5pp ≤ 10 → 🟢
        epic = make_epic(id=1, etype="Feature", group_id=10,
                         piid=_PIID, pct_complete=55, planned_weight=10)
        epic["type"] = "Feature"
        content = _run(_harness(
            epics=[epic], vs_groups=[_VS],
            piid_labels=[_PIID], pct_pi=50,
        ))
        assert "🟢" in content

    def test_schedule_yellow_when_moderately_behind(self):
        # 40% done, 55% elapsed → gap = 15pp → 🟡
        epic = make_epic(id=1, etype="Feature", group_id=10,
                         piid=_PIID, pct_complete=40, planned_weight=10)
        epic["type"] = "Feature"
        content = _run(_harness(
            epics=[epic], vs_groups=[_VS],
            piid_labels=[_PIID], pct_pi=55,
        ))
        assert "🟡" in content

    def test_schedule_red_when_far_behind(self):
        # 10% done, 60% elapsed → gap = 50pp > 20 → 🔴
        epic = make_epic(id=1, etype="Feature", group_id=10,
                         piid=_PIID, pct_complete=10, planned_weight=10)
        epic["type"] = "Feature"
        content = _run(_harness(
            epics=[epic], vs_groups=[_VS],
            piid_labels=[_PIID], pct_pi=60,
        ))
        assert "🔴" in content

    def test_risk_yellow_when_one_active_roam(self):
        epic = make_epic(id=1, etype="Feature", group_id=10,
                         piid=_PIID,
                         roam_risks=[{"roam_status": "roam::owned"}])
        epic["type"] = "Feature"
        content = _run(_harness(
            epics=[epic], vs_groups=[_VS],
            piid_labels=[_PIID], pct_pi=50,
        ))
        assert "🟡" in content

    def test_risk_red_when_three_or_more_active_roam(self):
        risks = [{"roam_status": "roam::owned"}] * 3
        epic  = make_epic(id=1, etype="Feature", group_id=10,
                          piid=_PIID, roam_risks=risks)
        epic["type"] = "Feature"
        content = _run(_harness(
            epics=[epic], vs_groups=[_VS],
            piid_labels=[_PIID], pct_pi=50,
        ))
        assert "🔴" in content

    def test_no_current_pi_shows_blank_schedule(self):
        # No piid_labels → no current PI → ⬜ for schedule
        vs   = dict(_VS)
        epic = make_epic(id=1, etype="Feature", group_id=10)
        epic["type"] = "Feature"
        content = _run(_harness(epics=[epic], vs_groups=[vs]))
        assert "⬜" in content


class TestPortfolioHealthDashboardVSRows:
    def test_vs_name_appears_in_output(self):
        vs = {"id": 99, "name": "Alpha Stream", "web_url": "https://gitlab.com/alpha"}
        content = _run(_harness(vs_groups=[vs]))
        assert "Alpha Stream" in content

    def test_multiple_vs_rows_rendered(self):
        vs1 = {"id": 10, "name": "VS One",   "web_url": "https://gitlab.com/vs1"}
        vs2 = {"id": 20, "name": "VS Two",   "web_url": "https://gitlab.com/vs2"}
        content = _run(_harness(vs_groups=[vs1, vs2]))
        assert "VS One" in content
        assert "VS Two" in content
