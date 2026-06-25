"""Unit tests for _item_risk_reasons() — the at-risk reason helper (Refs #8, #10)."""
import pytest
from datetime import date, timedelta
from conftest import make_epic, make_risk
from mixins.reports import _item_risk_reasons

TODAY      = date(2026, 6, 1)
YESTERDAY  = (TODAY - timedelta(days=1)).isoformat()
TOMORROW   = (TODAY + timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# 🔒 Blocked
# ---------------------------------------------------------------------------

class TestBlocked:
    def test_blocked_epic_shows_blocked(self):
        epic = make_epic(blocked_by_count=1)
        assert "🔒 Blocked" in _item_risk_reasons(epic, TODAY)

    def test_zero_blockers_not_flagged(self):
        epic = make_epic(blocked_by_count=0)
        assert "🔒 Blocked" not in _item_risk_reasons(epic, TODAY)

    def test_blocked_appears_first(self):
        epic = make_epic(blocked_by_count=2, pct_complete=0, pct_through_pi=50)
        reasons = _item_risk_reasons(epic, TODAY)
        assert reasons.startswith("🔒 Blocked")


# ---------------------------------------------------------------------------
# ⏱️ Behind Schedule
# ---------------------------------------------------------------------------

class TestBehindSchedule:
    def test_behind_schedule_when_done_lt_pi_elapsed(self):
        epic = make_epic(pct_complete=20, pct_through_pi=50)
        assert "⏱️ Behind Schedule" in _item_risk_reasons(epic, TODAY)

    def test_on_track_when_done_gte_pi_elapsed(self):
        epic = make_epic(pct_complete=60, pct_through_pi=50)
        assert "⏱️ Behind Schedule" not in _item_risk_reasons(epic, TODAY)

    def test_no_pi_elapsed_not_flagged(self):
        epic = make_epic(pct_complete=0, pct_through_pi=None)
        assert "⏱️ Behind Schedule" not in _item_risk_reasons(epic, TODAY)

    def test_pi_elapsed_zero_not_flagged(self):
        epic = make_epic(pct_complete=0, pct_through_pi=0)
        assert "⏱️ Behind Schedule" not in _item_risk_reasons(epic, TODAY)

    def test_pi_elapsed_100_not_flagged(self):
        # Past PI — behind-schedule logic only applies to active PIs
        epic = make_epic(pct_complete=40, pct_through_pi=100)
        assert "⏱️ Behind Schedule" not in _item_risk_reasons(epic, TODAY)

    def test_closed_epic_not_flagged(self):
        epic = make_epic(state="closed", pct_complete=0, pct_through_pi=50)
        assert "⏱️ Behind Schedule" not in _item_risk_reasons(epic, TODAY)


# ---------------------------------------------------------------------------
# 📅 Past Due
# ---------------------------------------------------------------------------

class TestPastDue:
    def test_past_due_when_due_date_yesterday(self):
        epic = make_epic(due_date=YESTERDAY)
        assert "📅 Past Due" in _item_risk_reasons(epic, TODAY)

    def test_not_past_due_when_due_tomorrow(self):
        epic = make_epic(due_date=TOMORROW)
        assert "📅 Past Due" not in _item_risk_reasons(epic, TODAY)

    def test_no_due_date_not_flagged(self):
        epic = make_epic(due_date=None)
        assert "📅 Past Due" not in _item_risk_reasons(epic, TODAY)

    def test_closed_epic_past_due_not_flagged(self):
        epic = make_epic(state="closed", due_date=YESTERDAY)
        assert "📅 Past Due" not in _item_risk_reasons(epic, TODAY)

    def test_invalid_due_date_not_flagged(self):
        epic = make_epic(due_date="not-a-date")
        assert "📅 Past Due" not in _item_risk_reasons(epic, TODAY)


# ---------------------------------------------------------------------------
# ⚠️ ROAM risks (Refs #10)
# ---------------------------------------------------------------------------

class TestRoamRisks:
    def test_single_risk_shows_count(self):
        epic = make_epic(roam_risks=[make_risk()])
        reason = _item_risk_reasons(epic, TODAY)
        assert "⚠️ 1 risk(s)" in reason

    def test_multiple_risks_shows_correct_count(self):
        epic = make_epic(roam_risks=[make_risk(iid=1), make_risk(iid=2), make_risk(iid=3)])
        reason = _item_risk_reasons(epic, TODAY)
        assert "⚠️ 3 risk(s)" in reason

    def test_roam_risks_shown_regardless_of_labels(self):
        epic = make_epic(roam_risks=[make_risk()], labels=["Feature", "risk::high"])
        assert "⚠️ 1 risk(s)" in _item_risk_reasons(epic, TODAY)

    def test_no_roam_risks_no_risk_indicator(self):
        epic = make_epic(roam_risks=[], labels=["Feature", "risk::high"])
        assert "risk(s)" not in _item_risk_reasons(epic, TODAY)

    def test_active_roam_statuses_trigger_flag(self):
        for status in ("roam::owned", "roam::accepted", "roam::mitigated"):
            epic = make_epic(roam_risks=[make_risk(roam_status=status)])
            assert "⚠️ 1 risk(s)" in _item_risk_reasons(epic, TODAY), f"Failed for {status}"

    def test_resolved_roam_does_not_trigger_flag(self):
        epic = make_epic(roam_risks=[make_risk(roam_status="roam::resolved")])
        assert "risk(s)" not in _item_risk_reasons(epic, TODAY)


# ---------------------------------------------------------------------------
# ⚠️ Child at risk — inherited from a descendant epic (Refs #95)
# ---------------------------------------------------------------------------

class TestInheritedRoamRisks:
    def test_single_inherited_risk_shows_child_at_risk(self):
        epic = make_epic(inherited_roam_risks=[make_risk()])
        assert "⚠️ Child at risk (1)" in _item_risk_reasons(epic, TODAY)

    def test_multiple_inherited_risks_shows_correct_count(self):
        epic = make_epic(inherited_roam_risks=[make_risk(iid=1), make_risk(iid=2)])
        assert "⚠️ Child at risk (2)" in _item_risk_reasons(epic, TODAY)

    def test_no_inherited_risks_no_indicator(self):
        epic = make_epic(inherited_roam_risks=[])
        assert "Child at risk" not in _item_risk_reasons(epic, TODAY)

    def test_active_inherited_statuses_trigger_flag(self):
        for status in ("roam::owned", "roam::accepted", "roam::mitigated"):
            epic = make_epic(inherited_roam_risks=[make_risk(roam_status=status)])
            assert "⚠️ Child at risk (1)" in _item_risk_reasons(epic, TODAY), f"Failed for {status}"

    def test_resolved_inherited_risk_does_not_trigger_flag(self):
        epic = make_epic(inherited_roam_risks=[make_risk(roam_status="roam::resolved")])
        assert "Child at risk" not in _item_risk_reasons(epic, TODAY)

    def test_direct_and_inherited_both_shown(self):
        epic = make_epic(roam_risks=[make_risk(iid=1)],
                         inherited_roam_risks=[make_risk(iid=2)])
        reason = _item_risk_reasons(epic, TODAY)
        assert "⚠️ 1 risk(s)" in reason
        assert "⚠️ Child at risk (1)" in reason


# ---------------------------------------------------------------------------
# No risk → returns "—"
# ---------------------------------------------------------------------------

class TestNoRisk:
    def test_no_conditions_returns_dash(self):
        epic = make_epic()
        assert _item_risk_reasons(epic, TODAY) == "—"

    def test_on_track_no_risk_returns_dash(self):
        epic = make_epic(pct_complete=60, pct_through_pi=50)
        assert _item_risk_reasons(epic, TODAY) == "—"

    def test_100pct_done_and_pi_elapsed_suppresses_all(self):
        # Work complete + PI over — no reason is relevant
        epic = make_epic(
            pct_complete=100, pct_through_pi=100,
            blocked_by_count=1,
            due_date="2024-03-31",
            roam_risks=[make_risk(roam_status="roam::owned")],
        )
        assert _item_risk_reasons(epic, TODAY) == "—"

    def test_100pct_done_active_pi_not_suppressed(self):
        # Work complete but PI still running — blocked flag should still show
        epic = make_epic(pct_complete=100, pct_through_pi=50, blocked_by_count=1)
        assert "🔒 Blocked" in _item_risk_reasons(epic, TODAY)


# ---------------------------------------------------------------------------
# Combination
# ---------------------------------------------------------------------------

class TestCombinations:
    def test_blocked_and_behind_schedule(self):
        epic = make_epic(blocked_by_count=1, pct_complete=10, pct_through_pi=50)
        reason = _item_risk_reasons(epic, TODAY)
        assert "🔒 Blocked" in reason
        assert "⏱️ Behind Schedule" in reason

    def test_all_conditions_combined(self):
        epic = make_epic(
            blocked_by_count=1,
            pct_complete=10,
            pct_through_pi=50,
            due_date=YESTERDAY,
            roam_risks=[make_risk(), make_risk(iid=2)],
        )
        reason = _item_risk_reasons(epic, TODAY)
        assert "🔒 Blocked" in reason
        assert "⏱️ Behind Schedule" in reason
        assert "📅 Past Due" in reason
        assert "⚠️ 2 risk(s)" in reason

    def test_separator_is_dot(self):
        epic = make_epic(blocked_by_count=1, pct_complete=0, pct_through_pi=50)
        reason = _item_risk_reasons(epic, TODAY)
        assert " · " in reason
