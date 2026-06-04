"""
Stub test suite — remaining report methods not yet covered by real tests.

Covered and removed:
  Group A: generate_portfolio_health_dashboard, generate_epic_lifecycle_report
  Group B: generate_wsjf_priority_board, generate_blocking_report
  Group C: generate_orphan_epics_report, generate_orphan_issues_report,
           generate_premature_closures_report, generate_unassigned_pi_report,
           generate_piid_project_report, generate_piid_project_detail_report,
           generate_workload_report, generate_pi_predictability_scorecard,
           generate_team_backlog_report, generate_art_capacity_balance_report,
           generate_vs_cross_art_risk_report, generate_flow_metrics_report,
           generate_wiki_index

Still pending (implement and remove the skip marker):
  generate_portfolio_report      — SAFe hierarchy tree (Epic → Capability → Feature)
  generate_art_feature_status_report  — Group B
  generate_vs_capability_dashboard_report — Group B
"""
import sys
import pytest

sys.path.insert(0, "/root/.venv/beelzabub-project")

pytestmark = pytest.mark.stub


# ---------------------------------------------------------------------------
# generate_portfolio_report (SAFe hierarchy)
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="stub")
def test_portfolio_report_renders_epic_capability_feature_tree():
    """Epic → Capability → Feature indentation in the markdown output."""


@pytest.mark.skip(reason="stub")
def test_portfolio_report_cross_group_children_included():
    pass


@pytest.mark.skip(reason="stub")
def test_portfolio_report_pct_complete_shown_per_item():
    pass


@pytest.mark.skip(reason="stub")
def test_portfolio_report_uploads_to_tier3():
    pass


# ---------------------------------------------------------------------------
# generate_art_feature_status_report + _generate_art_feature_status_page
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="stub")
def test_art_feature_status_page_renders_table_per_team():
    """One ## heading per team, table rows for each Feature."""


@pytest.mark.skip(reason="stub")
def test_art_feature_status_at_risk_reason_column_present():
    """Column header 'At Risk Reason' must appear (Refs #8)."""


@pytest.mark.skip(reason="stub")
def test_art_feature_status_blocked_shows_locked_icon():
    pass


@pytest.mark.skip(reason="stub")
def test_art_feature_status_planned_future_pi():
    pass


@pytest.mark.skip(reason="stub")
def test_art_feature_status_complete_past_pi():
    pass


@pytest.mark.skip(reason="stub")
def test_art_feature_status_incomplete_past_pi():
    pass


@pytest.mark.skip(reason="stub")
def test_art_feature_status_at_risk_reason_shows_roam_count():
    """⚠️ N risk(s) in reason column when feature has ROAM issues (Refs #10)."""


@pytest.mark.skip(reason="stub")
def test_art_feature_status_index_page_lists_all_arts():
    pass


# ---------------------------------------------------------------------------
# generate_vs_capability_dashboard_report + _generate_vs_capability_dashboard_page
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="stub")
def test_vs_capability_dashboard_capability_section_rendered():
    pass


@pytest.mark.skip(reason="stub")
def test_vs_capability_dashboard_direct_feature_section_rendered():
    pass


@pytest.mark.skip(reason="stub")
def test_vs_capability_dashboard_detail_rows_have_at_risk_reason_column():
    """At Risk Reason column present in details (Refs #8)."""


@pytest.mark.skip(reason="stub")
def test_vs_capability_dashboard_at_risk_reason_shows_roam_count():
    pass
