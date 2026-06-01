"""Integration tests for generate_risk_register() (Refs #8, #10)."""
import sys
import pytest
from datetime import date

sys.path.insert(0, "/root/.venv/beelzabub-project")

from conftest import ReportsHarness, make_epic, make_risk

TODAY     = date(2026, 6, 1)
YESTERDAY = "2026-05-31"


def _render(epics_all=None, risk_labels=None):
    """Build a ReportsHarness, call generate_risk_register, return captured markdown."""
    rpt = ReportsHarness(
        epics_all=epics_all or [],
        risk_labels=risk_labels if risk_labels is not None else ["risk::high", "risk::medium", "risk::low"],
    )
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
        assert "| ⚠️ Owned | 2 |" in md
        assert "| ✋ Accepted | 1 |" in md

    def test_total_risk_count_in_summary(self):
        epics = [make_epic(id=1, roam_risks=[make_risk(iid=1), make_risk(iid=2)])]
        md = _render(epics)
        assert "| **Total** | **2** |" in md


# ---------------------------------------------------------------------------
# Legacy risk:: label section (transition)
# ---------------------------------------------------------------------------

class TestLegacySection:
    def test_legacy_section_shown_when_risk_labels_present(self):
        epics = [make_epic(id=1, labels=["Feature", "risk::high"])]
        md = _render(epics)
        assert "Legacy Risk Labels" in md

    def test_legacy_section_hidden_when_all_migrated(self):
        # Epic has ROAM risks and no risk:: label
        epics = [make_epic(id=1, roam_risks=[make_risk()], labels=["Feature"])]
        md = _render(epics)
        assert "Legacy Risk Labels" not in md

    def test_legacy_high_subsection(self):
        epics = [make_epic(id=1, labels=["Feature", "risk::high"])]
        md = _render(epics)
        assert "### 🔴 High" in md

    def test_legacy_migration_note_shown(self):
        epics = [make_epic(id=1, labels=["Feature", "risk::medium"])]
        md = _render(epics)
        assert "migrate" in md.lower()

    def test_epic_not_double_counted(self):
        # Epic has both ROAM risk AND legacy risk:: label — should appear in ROAM section
        # and ALSO in legacy section (legacy checks labels independently)
        epic = make_epic(id=1, labels=["Feature", "risk::high"], roam_risks=[make_risk()])
        md   = _render([epic])
        # Should appear in ROAM section
        assert "## ⚠️ ROAM Risk Issues" in md


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
        assert "## Legend" in md

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
