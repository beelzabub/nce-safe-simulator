"""Tests for generate_issue_blocking_report and _data_issue_blocking (Refs #106)."""
import pytest

from tests.conftest import ReportsHarness


def _blocked_issue(iid=1, title="Blocked Issue", project="grp/proj-a",
                   state="opened", epic_iid=None, epic_title=None):
    return {
        "id":           1000 + iid,
        "iid":          iid,
        "title":        title,
        "web_url":      f"https://gitlab.com/{project}/-/issues/{iid}",
        "project_path": project,
        "state":        state,
        "epic_iid":     epic_iid,
        "epic_title":   epic_title,
    }


def _blocker(iid=99, title="Blocker Issue", project="grp/proj-b"):
    return {
        "id":           2000 + iid,
        "iid":          iid,
        "title":        title,
        "web_url":      f"https://gitlab.com/{project}/-/issues/{iid}",
        "project_path": project,
    }


def _rel(blocked, blockers=None):
    return {"blocked_issue": blocked, "blocked_by": blockers or []}


def _harness(rels=None, total_relationships=None):
    h = ReportsHarness()
    h._rd_issue_blocking = {
        "relationships": rels or [],
        "summary": {
            "total_blocked":       len(rels or []),
            "total_relationships": total_relationships if total_relationships is not None
                                   else sum(len(r["blocked_by"]) for r in (rels or [])),
        },
    }
    return h


def _run(h):
    h.generate_issue_blocking_report()
    return h._uploaded.get(f"{h._wiki_t2}/Issue Blocking", "")


class TestIssueBlockingReportStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = _harness()
        h.generate_issue_blocking_report()
        assert f"{h._wiki_t2}/Issue Blocking" in h._uploaded

    def test_page_title_present(self):
        assert "# Issue Blocking" in _run(_harness())

    def test_summary_section_present(self):
        assert "## Summary" in _run(_harness())

    def test_blocked_issues_section_present(self):
        assert "## Blocked Issues" in _run(_harness())


class TestIssueBlockingReportEmptyState:
    def test_empty_message_shown(self):
        content = _run(_harness(rels=[]))
        assert "_No blocked issues found._" in content

    def test_summary_counts_zero_when_empty(self):
        content = _run(_harness(rels=[]))
        assert "| Blocked issues | **0** |" in content


class TestIssueBlockingReportWithData:
    def test_blocked_issue_count_in_summary(self):
        rel = _rel(_blocked_issue(iid=1), blockers=[_blocker(iid=99)])
        content = _run(_harness(rels=[rel], total_relationships=1))
        assert "| Blocked issues | **1** |" in content

    def test_total_relationships_from_summary(self):
        rel = _rel(_blocked_issue(iid=1),
                   blockers=[_blocker(iid=98), _blocker(iid=99)])
        content = _run(_harness(rels=[rel], total_relationships=2))
        assert "| Total blocking relationships | **2** |" in content

    def test_table_columns_present(self):
        rel = _rel(_blocked_issue(iid=1), blockers=[_blocker(iid=99)])
        content = _run(_harness(rels=[rel]))
        assert "| Blocked Issue | Project | Epic | Blocked By |" in content

    def test_blocked_and_blocker_shown(self):
        rel = _rel(
            _blocked_issue(iid=1, title="My Blocked Issue", project="grp/web"),
            blockers=[_blocker(iid=99, title="My Blocker Issue")],
        )
        content = _run(_harness(rels=[rel]))
        assert "My Blocked Issue" in content
        assert "My Blocker Issue" in content
        assert "grp/web" in content
        assert "⛔" in content
        assert "🔒" in content

    def test_epic_title_shown_when_present(self):
        rel = _rel(
            _blocked_issue(iid=1, epic_iid=42, epic_title="Parent Epic Foo"),
            blockers=[_blocker(iid=99)],
        )
        content = _run(_harness(rels=[rel]))
        assert "Parent Epic Foo" in content

    def test_epic_dash_when_absent(self):
        rel = _rel(_blocked_issue(iid=1, epic_iid=None, epic_title=None),
                   blockers=[_blocker(iid=99)])
        content = _run(_harness(rels=[rel]))
        # The Epic cell falls back to an em dash
        assert "—" in content


class TestDataIssueBlocking:
    def test_shape_empty(self):
        h = _harness(rels=[])
        data = h._data_issue_blocking()
        assert set(data) == {"report_date", "group", "summary", "blocked_items"}
        assert data["summary"]["total_blocked"] == 0
        assert data["blocked_items"] == []

    def test_blocked_item_fields(self):
        rel = _rel(
            _blocked_issue(iid=7, title="Issue Seven", project="grp/svc",
                           epic_iid=5, epic_title="Epic Five", state="opened"),
            blockers=[_blocker(iid=99, title="Blocker Nine", project="grp/dep")],
        )
        data = _harness(rels=[rel], total_relationships=1)._data_issue_blocking()
        assert data["summary"]["total_blocked"] == 1
        assert data["summary"]["total_relationships"] == 1
        item = data["blocked_items"][0]
        assert item["title"] == "Issue Seven"
        assert item["project_path"] == "grp/svc"
        assert item["epic_title"] == "Epic Five"
        assert item["state"] == "Opened"
        assert item["blockers"][0]["title"] == "Blocker Nine"
        assert item["blockers"][0]["project_path"] == "grp/dep"
