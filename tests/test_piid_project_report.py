"""Tests for generate_piid_project_report and generate_piid_project_detail_report (Refs #24)."""
import sys

sys.path.insert(0, "/root/.venv/beelzabub-project")

from tests.conftest import ReportsHarness, make_epic


def _harness(epics=None, piid_labels=None, project_labels=None):
    all_epics = epics or []
    return ReportsHarness(
        metrics={
            "Epic":       [e for e in all_epics if e.get("type") == "Epic"],
            "Capability": [e for e in all_epics if e.get("type") == "Capability"],
            "Feature":    [e for e in all_epics if e.get("type") == "Feature"],
        },
        piid_labels=piid_labels or [],
        project_labels=project_labels or [],
    )


def _run_matrix(h):
    h.generate_piid_project_report()
    return h._uploaded.get(f"{h._wiki_t2}/Program × PI Matrix", "")


def _run_detail(h):
    h.generate_piid_project_detail_report()
    return h._uploaded.get(f"{h._wiki_t2}/Program PI Detail", "")


# ---------------------------------------------------------------------------
# Program × PI Matrix
# ---------------------------------------------------------------------------

class TestPiidProjectMatrixStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = _harness()
        h.generate_piid_project_report()
        assert f"{h._wiki_t2}/Program × PI Matrix" in h._uploaded

    def test_page_title_present(self):
        assert "# Program × PI Report" in _run_matrix(_harness())

    def test_empty_state_no_crash(self):
        assert _run_matrix(_harness()) != ""

    def test_header_row_contains_piid_labels(self):
        h = _harness(piid_labels=["PIID::2026Q1", "PIID::2026Q2"],
                     project_labels=["Program A"])
        content = _run_matrix(h)
        assert "PIID::2026Q1" in content
        assert "PIID::2026Q2" in content

    def test_program_row_in_table(self):
        h = _harness(piid_labels=["PIID::2026Q1"], project_labels=["Program Alpha"])
        assert "Program Alpha" in _run_matrix(h)


class TestPiidProjectMatrixStatus:
    def _cell_epic(self, piid, proj, pct_done=50):
        return make_epic(
            id=10, etype="Feature",
            labels=["Feature", piid, proj],
            piid=piid,
            pct_complete=pct_done,
            planned_weight=10,
            actual_weight=5,
        )

    def test_on_track_when_pct_done_gte_pct_pi(self):
        epic = self._cell_epic("PIID::2026Q1", "Program A", pct_done=60)
        h = _harness(epics=[epic], piid_labels=["PIID::2026Q1"],
                     project_labels=["Program A"])
        h._mock_pct_pi = 50
        assert "✅ On Track" in _run_matrix(h)

    def test_at_risk_when_pct_done_lt_pct_pi(self):
        epic = self._cell_epic("PIID::2026Q1", "Program A", pct_done=20)
        h = _harness(epics=[epic], piid_labels=["PIID::2026Q1"],
                     project_labels=["Program A"])
        h._mock_pct_pi = 60
        assert "⚠️ At Risk" in _run_matrix(h)

    def test_blocked_count_shown_in_cell(self):
        epic = make_epic(
            id=10, etype="Feature",
            labels=["Feature", "PIID::2026Q1", "Program A"],
            piid="PIID::2026Q1",
            blocked_by_count=1,
            planned_weight=10, actual_weight=5,
        )
        h = _harness(epics=[epic], piid_labels=["PIID::2026Q1"],
                     project_labels=["Program A"])
        h._mock_pct_pi = 50
        # blocked_str shows count of blocked epics in the cell, not total relationships
        assert "🔒1" in _run_matrix(h)

    def test_empty_cell_shown_as_dash_when_no_epics(self):
        h = _harness(piid_labels=["PIID::2026Q1"], project_labels=["Program A"])
        content = _run_matrix(h)
        assert " — " in content


# ---------------------------------------------------------------------------
# Program PI Detail
# ---------------------------------------------------------------------------

class TestPiidProjectDetailStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = _harness()
        h.generate_piid_project_detail_report()
        assert f"{h._wiki_t2}/Program PI Detail" in h._uploaded

    def test_page_title_present(self):
        assert "# Program PI Detail Report" in _run_detail(_harness())

    def test_pi_section_created_per_piid(self):
        h = _harness(piid_labels=["PIID::2026Q1", "PIID::2026Q2"],
                     project_labels=["Program A"])
        content = _run_detail(h)
        assert "PIID::2026Q1" in content
        assert "PIID::2026Q2" in content

    def test_future_pi_shows_planned_phase(self):
        """With _mock_pct_pi=None (default) the phase is Future."""
        h = _harness(piid_labels=["PIID::2099Q1"], project_labels=["Program A"])
        assert "Future" in _run_detail(h)

    def test_project_row_appears_in_pi_section(self):
        epic = make_epic(
            id=10, etype="Feature",
            labels=["Feature", "PIID::2026Q1", "Program Alpha"],
            piid="PIID::2026Q1",
            planned_weight=10, actual_weight=5,
        )
        h = _harness(epics=[epic], piid_labels=["PIID::2026Q1"],
                     project_labels=["Program Alpha"])
        assert "Program Alpha" in _run_detail(h)

    def test_project_link_present_when_epics_exist(self):
        epic = make_epic(
            id=10, etype="Feature",
            labels=["Feature", "PIID::2026Q1", "Program A"],
            piid="PIID::2026Q1",
            planned_weight=10, actual_weight=5,
        )
        h = _harness(epics=[epic], piid_labels=["PIID::2026Q1"],
                     project_labels=["Program A"])
        content = _run_detail(h)
        # Row with data renders the project name as a link
        assert "[Program A]" in content
