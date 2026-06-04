"""Tests for generate_art_feature_status_report (Refs #24)."""
import sys

sys.path.insert(0, "/root/.venv/beelzabub-project")

from tests.conftest import ReportsHarness, make_epic, make_risk


# ---------------------------------------------------------------------------
# Hierarchy helpers
# ---------------------------------------------------------------------------

def _vs(id=20, name="VS 01"):
    return {"id": id, "name": name,
            "web_url": f"https://gitlab.com/test/vs-{id}",
            "full_path": f"test/vs-{id}"}


def _art(id=30, name="ART 01"):
    return {"id": id, "name": name,
            "web_url": f"https://gitlab.com/test/art-{id}",
            "full_path": f"test/art-{id}"}


def _team(id=40, name="Team Alpha"):
    return {"id": id, "name": name,
            "web_url": f"https://gitlab.com/test/team-{id}",
            "full_path": f"test/team-{id}"}


def _harness(features=None):
    vs   = _vs()
    art  = _art()
    team = _team()
    return ReportsHarness(
        metrics={"Epic": [], "Capability": [], "Feature": features or []},
        vs_groups=[vs],
        groups_by_parent={vs["id"]: [art], art["id"]: [team]},
    )


def _feature(team_id=40, **kw):
    """Feature whose group_id matches Team Alpha so it lands on the ART page."""
    return make_epic(etype="Feature", group_id=team_id, **kw)


def _run(h):
    h.generate_art_feature_status_report()


def _top_page(h):
    return h._uploaded.get(f"{h._wiki_t3}/ART Feature Status", "")


def _vs_page(h, vs="VS 01"):
    return h._uploaded.get(f"{h._wiki_t3}/ART Feature Status/{vs}", "")


def _art_page(h, vs="VS 01", art="ART 01"):
    return h._uploaded.get(f"{h._wiki_t3}/ART Feature Status/{vs}/{art}", "")


# ---------------------------------------------------------------------------
# Structure / upload tests
# ---------------------------------------------------------------------------

class TestArtFeatureStatusStructure:
    def test_top_level_page_uploaded(self):
        h = _harness()
        _run(h)
        assert f"{h._wiki_t3}/ART Feature Status" in h._uploaded

    def test_empty_state_no_crash(self):
        h = _harness()
        _run(h)  # must not raise

    def test_vs_page_uploaded_when_data_present(self):
        h = _harness(features=[_feature()])
        _run(h)
        assert f"{h._wiki_t3}/ART Feature Status/VS 01" in h._uploaded

    def test_art_page_uploaded_when_data_present(self):
        h = _harness(features=[_feature()])
        _run(h)
        assert f"{h._wiki_t3}/ART Feature Status/VS 01/ART 01" in h._uploaded

    def test_table_per_team_in_art_page(self):
        # One ## heading per team
        h = _harness(features=[_feature()])
        _run(h)
        assert "## Team Alpha" in _art_page(h)

    def test_at_risk_reason_column_present(self):
        # Column header required (Refs #8)
        h = _harness(features=[_feature()])
        _run(h)
        assert "At Risk Reason" in _art_page(h)

    def test_index_page_lists_all_arts(self):
        # Top-level page must contain ART name as a link
        h = _harness(features=[_feature()])
        _run(h)
        assert "ART 01" in _top_page(h)


# ---------------------------------------------------------------------------
# Status logic
# ---------------------------------------------------------------------------

class TestArtFeatureStatusStatus:
    def _h(self, **kw):
        return _harness(features=[_feature(**kw)])

    def test_blocked_shows_locked_icon(self):
        h = self._h(blocked_by_count=1)
        _run(h)
        assert "🔒 Blocked" in _art_page(h)

    def test_planned_when_no_pct_pi(self):
        h = self._h(pct_through_pi=None)
        _run(h)
        assert "🔵 Planned" in _art_page(h)

    def test_planned_when_pct_pi_zero(self):
        h = self._h(pct_through_pi=0)
        _run(h)
        assert "🔵 Planned" in _art_page(h)

    def test_complete_when_past_pi_fully_done(self):
        h = self._h(pct_through_pi=100, pct_complete=100)
        _run(h)
        assert "✅ Complete" in _art_page(h)

    def test_incomplete_when_past_pi_not_done(self):
        h = self._h(pct_through_pi=100, pct_complete=60)
        _run(h)
        assert "❌ Incomplete" in _art_page(h)

    def test_at_risk_when_behind_schedule(self):
        h = self._h(pct_through_pi=60, pct_complete=30)
        _run(h)
        assert "⚠️ At Risk" in _art_page(h)

    def test_on_track_when_ahead_of_schedule(self):
        h = self._h(pct_through_pi=50, pct_complete=80)
        _run(h)
        assert "✅ On Track" in _art_page(h)


# ---------------------------------------------------------------------------
# At Risk Reason column content
# ---------------------------------------------------------------------------

class TestArtFeatureStatusRiskReason:
    def test_roam_count_shown_in_reason_column(self):
        # ⚠️ N risk(s) must appear when feature has ROAM issues (Refs #10)
        risk = make_risk(roam_status="roam::owned")
        h = _harness(features=[_feature(roam_risks=[risk])])
        _run(h)
        assert "risk" in _art_page(h).lower()

    def test_no_risk_shows_dash(self):
        h = _harness(features=[_feature(pct_through_pi=50, pct_complete=80)])
        _run(h)
        # On-track feature with no blockers or ROAM risks → dash in reason column
        assert "—" in _art_page(h)

    def test_blocked_count_reflected_in_vs_summary(self):
        h = _harness(features=[_feature(blocked_by_count=2)])
        _run(h)
        assert "2" in _vs_page(h)
