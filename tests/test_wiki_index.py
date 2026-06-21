"""Tests for generate_wiki_index (Refs #24)."""
import sys



from tests.conftest import ReportsHarness


def _run(h):
    h.generate_wiki_index()
    return h._uploaded


class TestWikiIndexUploads:
    def test_home_page_uploaded(self):
        h = ReportsHarness()
        h.generate_wiki_index()
        assert "home" in h._uploaded

    def test_tier1_landing_page_uploaded(self):
        h = ReportsHarness()
        h.generate_wiki_index()
        assert h._wiki_t1 in h._uploaded

    def test_tier2_landing_page_uploaded(self):
        h = ReportsHarness()
        h.generate_wiki_index()
        assert h._wiki_t2 in h._uploaded

    def test_tier3_landing_page_uploaded(self):
        h = ReportsHarness()
        h.generate_wiki_index()
        assert h._wiki_t3 in h._uploaded

    def test_tier4_landing_page_uploaded(self):
        h = ReportsHarness()
        h.generate_wiki_index()
        assert h._wiki_t4 in h._uploaded

    def test_root_folder_page_uploaded(self):
        h = ReportsHarness()
        h.generate_wiki_index()
        root_page = f"{h._rd_root_obj.name} — Portfolio Home"
        assert root_page in h._uploaded

    def test_empty_state_no_crash(self):
        uploaded = _run(ReportsHarness())
        assert uploaded != {}


class TestWikiIndexTier1Content:
    def test_home_page_contains_portfolio_health_dashboard_link(self):
        uploaded = _run(ReportsHarness())
        assert "Portfolio Health Dashboard" in uploaded.get("home", "")

    def test_home_page_has_executive_pulse_section(self):
        uploaded = _run(ReportsHarness())
        assert "Executive Pulse" in uploaded.get("home", "")

    def test_t1_landing_has_vs_traffic_light_description(self):
        h = ReportsHarness()
        h.generate_wiki_index()
        t1 = h._uploaded.get(h._wiki_t1, "")
        assert "Portfolio Health Dashboard" in t1


class TestWikiIndexTier2Content:
    def test_home_contains_program_x_pi_matrix_link(self):
        uploaded = _run(ReportsHarness())
        assert "Program × PI Matrix" in uploaded.get("home", "")

    def test_home_contains_pi_predictability_link(self):
        uploaded = _run(ReportsHarness())
        assert "PI Predictability Scorecard" in uploaded.get("home", "")

    def test_home_contains_risk_register_link(self):
        uploaded = _run(ReportsHarness())
        assert "Risk Register" in uploaded.get("home", "")

    def test_home_contains_wsjf_priority_board_link(self):
        uploaded = _run(ReportsHarness())
        assert "WSJF Priority Board" in uploaded.get("home", "")

    def test_t2_landing_page_has_program_management_description(self):
        h = ReportsHarness()
        h.generate_wiki_index()
        t2 = h._uploaded.get(h._wiki_t2, "")
        assert "Program Management" in t2


class TestWikiIndexTier3Content:
    def test_home_contains_art_feature_status_link(self):
        uploaded = _run(ReportsHarness())
        assert "ART Feature Status" in uploaded.get("home", "")

    def test_home_contains_workload_link(self):
        uploaded = _run(ReportsHarness())
        assert "Program Workload by Group" in uploaded.get("home", "")

    def test_home_contains_flow_metrics_link(self):
        uploaded = _run(ReportsHarness())
        assert "Flow Metrics" in uploaded.get("home", "")

    def test_t3_landing_page_has_operational_detail_description(self):
        h = ReportsHarness()
        h.generate_wiki_index()
        t3 = h._uploaded.get(h._wiki_t3, "")
        assert "Operational" in t3


class TestWikiIndexTier4Content:
    def test_home_contains_unassigned_pi_link(self):
        uploaded = _run(ReportsHarness())
        assert "Unassigned PI" in uploaded.get("home", "")

    def test_home_contains_orphaned_epics_link(self):
        uploaded = _run(ReportsHarness())
        assert "Orphaned Epics" in uploaded.get("home", "")

    def test_home_contains_orphaned_issues_link(self):
        uploaded = _run(ReportsHarness())
        assert "Orphaned Issues" in uploaded.get("home", "")

    def test_home_contains_premature_closures_link(self):
        uploaded = _run(ReportsHarness())
        assert "Premature Closures" in uploaded.get("home", "")

    def test_t4_landing_page_has_data_quality_description(self):
        h = ReportsHarness()
        h.generate_wiki_index()
        t4 = h._uploaded.get(h._wiki_t4, "")
        assert "Data Quality" in t4
