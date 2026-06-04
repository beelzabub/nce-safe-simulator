"""Tests for generate_pi_predictability_scorecard (Refs #24)."""
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


def _harness(epics=None, vs=None, art=None, piid_labels=None):
    all_epics = epics or []
    vs_  = vs  or _vs()
    art_ = art or _art()
    h = ReportsHarness(
        metrics={
            "Epic":       [e for e in all_epics if e.get("type") == "Epic"],
            "Capability": [e for e in all_epics if e.get("type") == "Capability"],
            "Feature":    [e for e in all_epics if e.get("type") == "Feature"],
        },
        vs_groups=[vs_],
        groups_by_parent={vs_["id"]: [art_], art_["id"]: []},
        piid_labels=piid_labels or [],
    )
    return h


def _run(h):
    h.generate_pi_predictability_scorecard()
    return h._uploaded.get(f"{h._wiki_t2}/PI Predictability Scorecard", "")


class TestPiPredictabilityStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = _harness()
        h.generate_pi_predictability_scorecard()
        assert f"{h._wiki_t2}/PI Predictability Scorecard" in h._uploaded

    def test_page_title_present(self):
        assert "# PI Predictability Scorecard" in _run(_harness())

    def test_empty_state_shows_guidance(self):
        assert "_No PI-committed Features or Capabilities found" in _run(_harness())

    def test_empty_state_no_crash(self):
        assert _run(_harness()) != ""


class TestPiPredictabilityScoring:
    def test_100_pct_when_all_closed(self):
        art = _art(id=30)
        epics = [
            make_epic(id=i, etype="Feature", piid="PIID::2026Q1",
                      state="closed", group_id=30,
                      labels=["Feature", "PIID::2026Q1"])
            for i in range(1, 4)
        ]
        h = _harness(epics=epics, art=art, piid_labels=["PIID::2026Q1"])
        h._mock_pct_pi = 100
        assert "100%" in _run(h)

    def test_0_pct_when_none_closed(self):
        art = _art(id=30)
        epics = [
            make_epic(id=i, etype="Feature", piid="PIID::2026Q1",
                      state="opened", group_id=30,
                      labels=["Feature", "PIID::2026Q1"])
            for i in range(1, 3)
        ]
        h = _harness(epics=epics, art=art, piid_labels=["PIID::2026Q1"])
        h._mock_pct_pi = 100
        assert "0%" in _run(h)

    def test_pi_columns_in_header(self):
        art = _art(id=30)
        epic = make_epic(id=1, etype="Feature", piid="PIID::2026Q1",
                         state="closed", group_id=30,
                         labels=["Feature", "PIID::2026Q1"])
        h = _harness(epics=[epic], art=art, piid_labels=["PIID::2026Q1"])
        h._mock_pct_pi = 100
        assert "PIID::2026Q1" in _run(h)

    def test_art_row_present_in_table(self):
        art = _art(id=30, name="ART Alpha")
        epic = make_epic(id=1, etype="Feature", piid="PIID::2026Q1",
                         state="opened", group_id=30,
                         labels=["Feature", "PIID::2026Q1"])
        h = _harness(epics=[epic], art=art, piid_labels=["PIID::2026Q1"])
        h._mock_pct_pi = 100
        assert "ART Alpha" in _run(h)

    def test_portfolio_total_row_present(self):
        art = _art(id=30)
        epic = make_epic(id=1, etype="Feature", piid="PIID::2026Q1",
                         state="closed", group_id=30,
                         labels=["Feature", "PIID::2026Q1"])
        h = _harness(epics=[epic], art=art, piid_labels=["PIID::2026Q1"])
        h._mock_pct_pi = 100
        assert "Portfolio Total" in _run(h)

    def test_future_pi_shown_as_planned(self):
        """When pct_pi is None, in-progress cell shows planned count."""
        art = _art(id=30)
        epic = make_epic(id=1, etype="Feature", piid="PIID::2099Q1",
                         state="opened", group_id=30,
                         labels=["Feature", "PIID::2099Q1"])
        h = _harness(epics=[epic], art=art, piid_labels=["PIID::2099Q1"])
        # _mock_pct_pi not set → None → future PI cell
        assert "planned" in _run(h)
