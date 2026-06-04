"""Tests for generate_unassigned_pi_report (Refs #24)."""
import sys

sys.path.insert(0, "/root/.venv/beelzabub-project")

from tests.conftest import ReportsHarness, make_epic


def _run(h):
    h.generate_unassigned_pi_report()
    return h._uploaded.get(f"{h._wiki_t4}/Unassigned PI", "")


class TestUnassignedPiStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = ReportsHarness()
        h.generate_unassigned_pi_report()
        assert f"{h._wiki_t4}/Unassigned PI" in h._uploaded

    def test_page_title_present(self):
        assert "# Unassigned PI Report" in _run(ReportsHarness())

    def test_total_count_line_present(self):
        assert "Total unassigned:" in _run(ReportsHarness())

    def test_empty_state_no_crash(self):
        assert _run(ReportsHarness()) != ""


class TestUnassignedPiEmptyState:
    def test_zero_unassigned_when_all_have_piid(self):
        epic = make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         labels=["Feature", "PIID::2026Q1"])
        content = _run(ReportsHarness(epics_all=[epic]))
        assert "**Total unassigned: 0**" in content


class TestUnassignedPiWithData:
    def test_epic_without_piid_label_listed(self):
        epic = make_epic(id=10, title="No-PI Feature", etype="Feature",
                         labels=["Feature"])
        content = _run(ReportsHarness(epics_all=[epic]))
        assert "No-PI Feature" in content

    def test_grouped_by_type_shows_epic_section(self):
        epic = make_epic(id=10, title="No-PI Epic", etype="Epic", labels=["Epic"])
        content = _run(ReportsHarness(epics_all=[epic]))
        assert "## 🏆 Epic" in content

    def test_grouped_by_type_shows_feature_section(self):
        feat = make_epic(id=11, title="No-PI Feat", etype="Feature", labels=["Feature"])
        content = _run(ReportsHarness(epics_all=[feat]))
        assert "## 🛠️ Feature" in content

    def test_unassigned_count_reflects_epics_without_piid(self):
        e1 = make_epic(id=10, etype="Feature", labels=["Feature"])
        e2 = make_epic(id=11, etype="Feature", labels=["Feature"])
        e3 = make_epic(id=12, etype="Feature", piid="PIID::2026Q1",
                       labels=["Feature", "PIID::2026Q1"])
        h = ReportsHarness(epics_all=[e1, e2, e3])
        assert "**Total unassigned: 2**" in _run(h)

    def test_piid_labelled_epic_excluded_from_list(self):
        assigned = make_epic(id=10, title="Assigned Feature", etype="Feature",
                             piid="PIID::2026Q1", labels=["Feature", "PIID::2026Q1"])
        content = _run(ReportsHarness(epics_all=[assigned]))
        assert "Assigned Feature" not in content
