"""Integration tests for generate_risk_register() (Refs #8, #10)."""
import sys
import pytest
from datetime import date

sys.path.insert(0, "/root/.venv/beelzabub-project")

from conftest import ReportsHarness, make_epic, make_risk

TODAY     = date(2026, 6, 1)
YESTERDAY = "2026-05-31"


def _render(epics_all=None):
    """Build a ReportsHarness, call generate_risk_register, return captured markdown."""
    rpt = ReportsHarness(epics_all=epics_all or [])
    rpt.generate_risk_register()
    return rpt._uploaded.get("Portfolio/01 Program Management/Risk Register", "")


# ---------------------------------------------------------------------------
# ROAM section
# ---------------------------------------------------------------------------

class TestRoamSection:
    def test_roam_section_heading_present_when_risks_exist(self):
        epics = [make_epic(id=1, roam_risks=[make_risk()])]
        md = _render(epics)
        assert "## ⚠️ ROAM Risk Issues" in md

    def test_roam_owned_subsection(self):
        epics = [make_epic(id=1, roam_risks=[make_risk(roam_status="roam::owned")])]
        md = _render(epics)
        assert "### ⚠️ Owned" in md

    def test_roam_accepted_subsection(self):
        epics = [make_epic(id=1, roam_risks=[make_risk(roam_status="roam::accepted")])]
        md = _render(epics)
        assert "### ✋ Accepted" in md

    def test_roam_mitigated_subsection(self):
        epics = [make_epic(id=1, roam_risks=[make_risk(roam_status="roam::mitigated")])]
        md = _render(epics)
        assert "### 🛡️ Mitigated" in md

    def test_roam_resolved_subsection(self):
        epics = [make_epic(id=1, roam_risks=[make_risk(roam_status="roam::resolved")])]
        md = _render(epics)
        assert "### ✅ Resolved" in md

    def test_empty_roam_shows_guidance_message(self):
        md = _render(epics_all=[])
        assert "roam::owned" in md
        assert "No ROAM risk issues found" in md

    def test_risk_title_linked_in_table(self):
        risk  = make_risk(title="DB capacity risk", web_url="https://gitlab.com/test/issues/42")
        epics = [make_epic(id=1, roam_risks=[risk])]
        md    = _render(epics)
        assert "[DB capacity risk](https://gitlab.com/test/issues/42)" in md

    def test_epic_link_appears_in_row(self):
        epic = make_epic(id=1, title="Feature Alpha",
                         web_url="https://gitlab.com/groups/test/-/epics/1",
                         roam_risks=[make_risk()])
        md = _render([epic])
        assert "[Feature Alpha]" in md

    def test_assignee_appears_in_row(self):
        risk  = make_risk(assignee="Carol")
        epics = [make_epic(id=1, roam_risks=[risk])]
        md    = _render(epics)
        assert "Carol" in md

    def test_summary_counts_by_disposition(self):
        epics = [make_epic(id=1, roam_risks=[
            make_risk(iid=1, roam_status="roam::owned"),
            make_risk(iid=2, roam_status="roam::owned"),
            make_risk(iid=3, roam_status="roam::accepted"),
        ])]
        md = _render(epics)
        assert "<td>⚠️ Owned</td><td>2</td>" in md
        assert "<td>✋ Accepted</td><td>1</td>" in md

    def test_total_risk_count_in_summary(self):
        epics = [make_epic(id=1, roam_risks=[make_risk(iid=1), make_risk(iid=2)])]
        md = _render(epics)
        assert "<strong>Total</strong></td><td><strong>2</strong>" in md


# ---------------------------------------------------------------------------
# Child Overdue section (Refs #8)
# ---------------------------------------------------------------------------

class TestChildOverdueSection:
    def test_child_overdue_section_shown(self):
        parent  = make_epic(id=1, etype="Epic", labels=["Epic", "PIID::2026Q4"])
        child   = make_epic(id=2, etype="Feature", labels=["Feature"], due_date=YESTERDAY,
                             parent_id=1, state="opened")
        md = _render([parent, child])
        assert "## 📅 Child Overdue" in md

    def test_child_overdue_not_shown_if_child_closed(self):
        parent = make_epic(id=1, etype="Epic", labels=["Epic"])
        child  = make_epic(id=2, etype="Feature", labels=["Feature"], due_date=YESTERDAY,
                            parent_id=1, state="closed")
        md = _render([parent, child])
        assert "## 📅 Child Overdue" not in md

    def test_child_overdue_not_shown_if_no_due_date(self):
        parent = make_epic(id=1, etype="Epic", labels=["Epic"])
        child  = make_epic(id=2, etype="Feature", labels=["Feature"], due_date=None,
                            parent_id=1)
        md = _render([parent, child])
        assert "## 📅 Child Overdue" not in md

    def test_child_overdue_count_in_summary(self):
        parent = make_epic(id=1, etype="Epic",    labels=["Epic"])
        child  = make_epic(id=2, etype="Feature", labels=["Feature"],
                            due_date=YESTERDAY, parent_id=1)
        md = _render([parent, child])
        assert "Child Overdue" in md
        assert "1" in md


# ---------------------------------------------------------------------------
# Legend
# ---------------------------------------------------------------------------

class TestLegend:
    def test_legend_section_present(self):
        md = _render()
        assert "<summary>Legend</summary>" in md

    def test_roam_dispositions_in_legend(self):
        md = _render()
        for term in ("Owned", "Accepted", "Mitigated", "Resolved"):
            assert term in md

    def test_at_risk_indicators_in_legend(self):
        md = _render()
        assert "Behind Schedule" in md
        assert "Past Due"        in md
        assert "Child Overdue"   in md
        assert "Blocked"         in md


# ---------------------------------------------------------------------------
# Past Due section
# ---------------------------------------------------------------------------

class TestPastDueSection:
    def test_past_due_section_shown_for_overdue_epic(self):
        epic = make_epic(id=1, etype="Epic", labels=["Epic"], due_date=YESTERDAY)
        md = _render([epic])
        assert "## 📅 Past Due" in md

    def test_past_due_section_hidden_when_no_overdue_epics(self):
        epic = make_epic(id=1, etype="Epic", labels=["Epic"], due_date="2099-12-31")
        md = _render([epic])
        assert "## 📅 Past Due" not in md

    def test_past_due_count_in_summary(self):
        epic = make_epic(id=1, etype="Epic", labels=["Epic"], due_date=YESTERDAY)
        md = _render([epic])
        assert "<td>📅 Past Due</td><td>1</td>" in md

    def test_past_due_epic_also_shown_when_has_roam_risk(self):
        # Conditions are independent — epic appears in both ROAM and Past Due
        epic = make_epic(id=1, etype="Epic", labels=["Epic"],
                         due_date=YESTERDAY, roam_risks=[make_risk()])
        md = _render([epic])
        assert "## 📅 Past Due" in md
        assert "## ⚠️ ROAM Risk Issues" in md

    def test_past_due_shown_alongside_child_overdue(self):
        # Parent qualifies for both child_overdue and past_due — appears in both
        parent = make_epic(id=1, etype="Epic", labels=["Epic"], due_date=YESTERDAY)
        child  = make_epic(id=2, etype="Feature", labels=["Feature"],
                           due_date=YESTERDAY, parent_id=1)
        md = _render([parent, child])
        assert "## 📅 Child Overdue" in md
        assert "## 📅 Past Due" in md

    def test_prepend_reason_in_row(self):
        epic = make_epic(id=1, etype="Epic", labels=["Epic"], due_date=YESTERDAY)
        md = _render([epic])
        assert "📅 Past Due" in md

    def test_feature_type_excluded_from_past_due(self):
        epic = make_epic(id=1, etype="Feature", labels=["Feature"], due_date=YESTERDAY)
        md = _render([epic])
        assert "## 📅 Past Due" not in md


# ---------------------------------------------------------------------------
# Behind Schedule section
# ---------------------------------------------------------------------------

class TestBehindScheduleSection:
    def test_behind_schedule_section_shown(self):
        epic = make_epic(id=1, etype="Epic", labels=["Epic"],
                         pct_complete=30, pct_through_pi=70)
        md = _render([epic])
        assert "## ⏱️ Behind Schedule" in md

    def test_behind_schedule_hidden_when_on_track(self):
        epic = make_epic(id=1, etype="Epic", labels=["Epic"],
                         pct_complete=80, pct_through_pi=70)
        md = _render([epic])
        assert "## ⏱️ Behind Schedule" not in md

    def test_behind_schedule_hidden_when_no_pi(self):
        epic = make_epic(id=1, etype="Epic", labels=["Epic"],
                         pct_complete=0, pct_through_pi=None)
        md = _render([epic])
        assert "## ⏱️ Behind Schedule" not in md

    def test_behind_schedule_count_in_summary(self):
        epic = make_epic(id=1, etype="Epic", labels=["Epic"],
                         pct_complete=10, pct_through_pi=60)
        md = _render([epic])
        assert "<td>⏱️ Behind Schedule</td><td>1</td>" in md

    def test_behind_schedule_also_shown_when_has_roam_risk(self):
        # Conditions are independent — epic appears in both ROAM and Behind Schedule
        epic = make_epic(id=1, etype="Epic", labels=["Epic"],
                         pct_complete=10, pct_through_pi=60,
                         roam_risks=[make_risk()])
        md = _render([epic])
        assert "## ⏱️ Behind Schedule" in md
        assert "## ⚠️ ROAM Risk Issues" in md

    def test_behind_schedule_shown_alongside_past_due(self):
        # Epic is both past due and behind schedule — appears in both sections
        epic = make_epic(id=1, etype="Epic", labels=["Epic"],
                         due_date=YESTERDAY, pct_complete=10, pct_through_pi=60)
        md = _render([epic])
        assert "## 📅 Past Due" in md
        assert "## ⏱️ Behind Schedule" in md

    def test_prepend_reason_in_row(self):
        epic = make_epic(id=1, etype="Epic", labels=["Epic"],
                         pct_complete=10, pct_through_pi=60)
        md = _render([epic])
        assert "⏱️ Behind Schedule" in md

    def test_pi_at_zero_not_flagged(self):
        epic = make_epic(id=1, etype="Epic", labels=["Epic"],
                         pct_complete=0, pct_through_pi=0)
        md = _render([epic])
        assert "## ⏱️ Behind Schedule" not in md

    def test_pi_at_100_not_flagged(self):
        epic = make_epic(id=1, etype="Epic", labels=["Epic"],
                         pct_complete=0, pct_through_pi=100)
        md = _render([epic])
        assert "## ⏱️ Behind Schedule" not in md
