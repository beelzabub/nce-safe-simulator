"""Tests for generate_issue_blocking_report and _data_issue_blocking (Refs #106)."""
from unittest.mock import MagicMock

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


class TestIssueBlockingGraphPagination:
    """_fetch_issue_blocking_graph must page past GitLab's 100-node GraphQL cap (Refs #120)."""

    def test_blocked_issue_beyond_first_page_is_counted(self):
        h = ReportsHarness()
        h.parent_group = "TestGroup"
        h.url = "https://gitlab.test"

        blocked_url = "https://gitlab.test/grp/proj/-/issues/201"
        h._issues_cache = {"TestGroup": [{
            "id": 9201, "iid": 201, "title": "Blocked beyond first page",
            "web_url": blocked_url, "project_path": "grp/proj",
            "state": "opened", "epic_iid": None,
        }]}
        h._all_epics_cache = {"TestGroup": []}

        # Page 1: 100 unblocked issues + hasNextPage. Page 2: the blocked one.
        page1 = {"group": {"issues": {
            "pageInfo": {"hasNextPage": True, "endCursor": "CURSOR1"},
            "nodes": [{"iid": i, "webUrl": f"https://gitlab.test/grp/proj/-/issues/{i}",
                       "blocked": False, "blockedByCount": 0} for i in range(1, 101)],
        }}}
        page2 = {"group": {"issues": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [{"iid": 201, "webUrl": blocked_url,
                       "blocked": True, "blockedByCount": 1}],
        }}}

        def fake_gql(query, variables=None, retries=0):
            return page1 if (variables or {}).get("after") is None else page2
        h.graphql_query = fake_gql

        # REST links for the flagged issue → one is_blocked_by relationship.
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = [{
            "link_type": "is_blocked_by", "id": 1, "iid": 99, "title": "Blocker",
            "web_url": "https://gitlab.test/grp/other/-/issues/99",
            "references": {"full": "grp/other#99"},
        }]
        session = MagicMock()
        session.get.return_value = resp
        h._make_session = lambda: session

        group = MagicMock()
        group.full_path = "TestGroup"
        result = h._fetch_issue_blocking_graph(group)

        # Without pagination the page-2 issue is missed → total_blocked would be 0.
        assert result["summary"]["total_blocked"] == 1
        assert result["relationships"][0]["blocked_issue"]["iid"] == 201
