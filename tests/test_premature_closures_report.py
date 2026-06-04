"""Tests for generate_premature_closures_report (Refs #24)."""
import sys
from collections import defaultdict

sys.path.insert(0, "/root/.venv/beelzabub-project")

from tests.conftest import ReportsHarness, make_epic


def _open_issue(iid=1, title="Open issue"):
    return {
        "iid":       iid,
        "title":     title,
        "web_url":   f"https://gitlab.com/test/issues/{iid}",
        "state":     "opened",
        "assignees": [],
    }


def _harness(epics=None, issues_by_epic=None):
    h = ReportsHarness(epics_all=epics or [])
    if issues_by_epic:
        h._rd_issues_by_epic = defaultdict(list, issues_by_epic)
    return h


def _run(h):
    h.generate_premature_closures_report()
    return h._uploaded.get(f"{h._wiki_t4}/Premature Closures", "")


class TestPrematureClosuresStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = _harness()
        h.generate_premature_closures_report()
        assert f"{h._wiki_t4}/Premature Closures" in h._uploaded

    def test_empty_state_no_crash(self):
        assert _run(_harness()) != ""


class TestPrematureClosuresEmptyState:
    def test_no_findings_message_when_empty(self):
        assert "✅ _No premature closures found" in _run(_harness())

    def test_open_epic_not_flagged(self):
        epic = make_epic(id=10, etype="Epic", state="opened")
        assert "✅ _No premature closures found" in _run(_harness(epics=[epic]))

    def test_closed_epic_with_all_closed_children_ok(self):
        epic  = make_epic(id=10, etype="Epic",        state="closed")
        child = make_epic(id=11, etype="Capability",  state="closed", parent_id=10)
        assert "✅ _No premature closures found" in _run(_harness(epics=[epic, child]))

    def test_feature_type_excluded_from_check(self):
        """Only Epics and Capabilities are checked, not Features."""
        feat = make_epic(id=10, title="Closed Feature", etype="Feature", state="closed")
        assert "✅ _No premature closures found" in _run(_harness(epics=[feat]))


class TestPrematureClosuresWithData:
    def test_closed_epic_with_open_child_flagged(self):
        closed = make_epic(id=10, title="Closed Epic", etype="Epic",        state="closed")
        child  = make_epic(id=11, title="Open Cap",    etype="Capability",  state="opened", parent_id=10)
        content = _run(_harness(epics=[closed, child]))
        assert "Closed Epic" in content

    def test_closed_epic_with_open_issue_flagged(self):
        closed = make_epic(id=10, title="Closed Epic", etype="Epic", state="closed")
        issue  = _open_issue(iid=1, title="Still open")
        content = _run(_harness(epics=[closed], issues_by_epic={10: [issue]}))
        assert "Closed Epic" in content
        assert "Still open" in content

    def test_closed_capability_with_open_child_flagged(self):
        cap   = make_epic(id=20, title="Closed Cap", etype="Capability", state="closed")
        child = make_epic(id=21, title="Open Feature", etype="Feature",  state="opened", parent_id=20)
        content = _run(_harness(epics=[cap, child]))
        assert "Closed Cap" in content

    def test_total_count_in_heading(self):
        epic  = make_epic(id=10, title="Closed Epic", etype="Epic", state="closed")
        child = make_epic(id=11, etype="Capability",  state="opened", parent_id=10)
        content = _run(_harness(epics=[epic, child]))
        assert "1 closed epic(s) with open work" in content
