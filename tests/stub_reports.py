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


