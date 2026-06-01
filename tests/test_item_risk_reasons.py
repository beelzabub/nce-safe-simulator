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

    def test_roam_risks_supersede_legacy_label(self):
        epic = make_epic(
            roam_risks=[make_risk()],
            labels=["Feature", "risk::high"],
        )
        reason = _item_risk_reasons(epic, TODAY)
        assert "⚠️ 1 risk(s)" in reason
        assert "🔴 High Risk" not in reason

    def test_empty_roam_risks_falls_back_to_label(self):
        epic = make_epic(roam_risks=[], labels=["Feature", "risk::high"])
        reason = _item_risk_reasons(epic, TODAY)
        assert "🔴 High Risk" in reason

    def test_all_roam_statuses_trigger_flag(self):
        for status in ("roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"):
            epic = make_epic(roam_risks=[make_risk(roam_status=status)])
            assert "⚠️ 1 risk(s)" in _item_risk_reasons(epic, TODAY), f"Failed for {status}"


# ---------------------------------------------------------------------------
# 🏷️ Legacy risk:: label fallback (transition — Refs #10)
# ---------------------------------------------------------------------------

class TestLegacyRiskLabel:
    def test_high_risk_label(self):
        epic = make_epic(labels=["Feature", "risk::high"])
        assert "🔴 High Risk" in _item_risk_reasons(epic, TODAY)

    def test_medium_risk_label(self):
        epic = make_epic(labels=["Feature", "risk::medium"])
        assert "🟡 Med Risk" in _item_risk_reasons(epic, TODAY)

    def test_low_risk_label(self):
        epic = make_epic(labels=["Feature", "risk::low"])
        assert "🟢 Low Risk" in _item_risk_reasons(epic, TODAY)

    def test_unknown_label_not_flagged(self):
        epic = make_epic(labels=["Feature", "status::active"])
        reason = _item_risk_reasons(epic, TODAY)
        assert "High Risk" not in reason
        assert "Med Risk" not in reason
        assert "Low Risk" not in reason


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
