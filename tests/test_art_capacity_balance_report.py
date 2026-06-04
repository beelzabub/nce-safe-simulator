"""Tests for generate_art_capacity_balance_report (Refs #24)."""
import sys

sys.path.insert(0, "/root/.venv/beelzabub-project")

from tests.conftest import ReportsHarness, make_epic


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


def _harness(features=None, team=None):
    vs   = _vs()
    art  = _art()
    t    = team or _team()
    return ReportsHarness(
        metrics={"Epic": [], "Capability": [], "Feature": features or []},
        vs_groups=[vs],
        groups_by_parent={vs["id"]: [art], art["id"]: [t]},
    )


def _art_page_key(h):
    return f"{h._wiki_t2}/ART Capacity Balance/VS 01/ART 01"


def _run(h):
    h.generate_art_capacity_balance_report()
    return h._uploaded.get(f"{h._wiki_t2}/ART Capacity Balance", "")


class TestCapacityBalanceStructure:
    def test_index_page_uploaded(self):
        h = _harness()
        h.generate_art_capacity_balance_report()
        assert f"{h._wiki_t2}/ART Capacity Balance" in h._uploaded

    def test_empty_state_no_crash(self):
        assert _run(_harness()) != ""

    def test_art_page_uploaded_when_data_present(self):
        team = _team(id=40)
        feat = make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         group_id=40, labels=["Feature", "PIID::2026Q1"],
                         planned_weight=10, actual_weight=9)
        h = _harness(features=[feat], team=team)
        h.generate_art_capacity_balance_report()
        assert _art_page_key(h) in h._uploaded

    def test_vs_landing_page_uploaded_when_data_present(self):
        team = _team(id=40)
        feat = make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         group_id=40, labels=["Feature", "PIID::2026Q1"],
                         planned_weight=10, actual_weight=9)
        h = _harness(features=[feat], team=team)
        h.generate_art_capacity_balance_report()
        assert f"{h._wiki_t2}/ART Capacity Balance/VS 01" in h._uploaded


class TestCapacityBalanceStatus:
    def _feat(self, planned, actual):
        return make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         group_id=40, labels=["Feature", "PIID::2026Q1"],
                         planned_weight=planned, actual_weight=actual)

    def test_over_capacity_flagged(self):
        # 150% load (actual 15 / planned 10) → 🔴 Over
        h = _harness(features=[self._feat(10, 15)])
        h.generate_art_capacity_balance_report()
        assert "🔴 Over" in h._uploaded.get(_art_page_key(h), "")

    def test_under_capacity_flagged(self):
        # 50% load (actual 5 / planned 10) → 🔵 Under
        h = _harness(features=[self._feat(10, 5)])
        h.generate_art_capacity_balance_report()
        assert "🔵 Under" in h._uploaded.get(_art_page_key(h), "")

    def test_balanced_team_shows_balanced(self):
        # 90% load (actual 9 / planned 10) → ✅ Balanced
        h = _harness(features=[self._feat(10, 9)])
        h.generate_art_capacity_balance_report()
        assert "✅ Balanced" in h._uploaded.get(_art_page_key(h), "")
