"""Tests for generate_orphan_epics_report (Refs #24)."""
import sys



from tests.conftest import ReportsHarness, make_epic


def _run(h):
    h.generate_orphan_epics_report()
    return h._uploaded.get(f"{h._wiki_t4}/Orphaned Epics", "")


class TestOrphanEpicsStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = ReportsHarness()
        h.generate_orphan_epics_report()
        assert f"{h._wiki_t4}/Orphaned Epics" in h._uploaded

    def test_page_title_present(self):
        assert "# Orphaned Epics Report" in _run(ReportsHarness())

    def test_empty_state_no_crash(self):
        assert _run(ReportsHarness()) != ""


class TestOrphanEpicsEmptyState:
    def test_no_orphans_message_when_empty(self):
        assert "_No orphaned epics found._" in _run(ReportsHarness())


class TestOrphanEpicsWithData:
    def test_disconnected_epic_listed_as_orphan(self):
        epic = make_epic(id=10, title="Lonely Feature", etype="Feature")
        content = _run(ReportsHarness(epics_all=[epic]))
        assert "Lonely Feature" in content

    def test_orphan_count_shown_in_summary(self):
        epic = make_epic(id=10, title="Lonely Feature", etype="Feature")
        content = _run(ReportsHarness(epics_all=[epic]))
        assert "1 orphaned epic(s) found" in content

    def test_epic_with_parent_not_listed(self):
        parent = make_epic(id=10, title="Root Epic", etype="Epic")
        child  = make_epic(id=11, title="Child Feature", etype="Feature", parent_id=10)
        content = _run(ReportsHarness(epics_all=[parent, child]))
        assert "_No orphaned epics found._" in content

    def test_root_epic_with_children_excluded(self):
        """Epics that have children are not orphans even if they have no parent."""
        root  = make_epic(id=10, title="Portfolio Epic", etype="Epic", parent_id=None)
        child = make_epic(id=11, title="Child Cap", etype="Capability", parent_id=10)
        content = _run(ReportsHarness(epics_all=[root, child]))
        assert "Portfolio Epic" not in content

    def test_feature_icon_present_for_feature_orphan(self):
        epic = make_epic(id=10, title="Orphan Feature", etype="Feature")
        assert "🛠️" in _run(ReportsHarness(epics_all=[epic]))

    def test_multiple_orphans_all_listed(self):
        epics = [make_epic(id=i, title=f"Orphan {i}", etype="Feature") for i in range(1, 4)]
        content = _run(ReportsHarness(epics_all=epics))
        assert "3 orphaned epic(s) found" in content
