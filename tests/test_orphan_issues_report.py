"""Tests for generate_orphan_issues_report (Refs #24)."""
import sys

sys.path.insert(0, "/root/.venv/beelzabub-project")

from tests.conftest import ReportsHarness


def _project(path="test-group/my-project", name_with_ns="Test Group / My Project"):
    return {
        "path":               path.split("/")[-1],
        "path_with_namespace": path,
        "name_with_namespace": name_with_ns,
        "web_url":             f"https://gitlab.com/{path}",
        "issues_enabled":      True,
    }


def _issue(iid=1, title="An issue", epic_id=None, labels=None, state="opened"):
    return {
        "iid":       iid,
        "title":     title,
        "web_url":   f"https://gitlab.com/test/issues/{iid}",
        "state":     state,
        "epic_id":   epic_id,
        "labels":    labels or [],
        "assignees": [],
    }


def _harness(project=None, issues=None):
    proj = project or _project()
    h = ReportsHarness()
    h._rd_projects_by_nsid = {1: [proj]}
    h._rd_issues_by_project[proj["path_with_namespace"]] = issues or []
    return h


def _run(h):
    h.generate_orphan_issues_report()
    return h._uploaded.get(f"{h._wiki_t4}/Orphaned Issues", "")


class TestOrphanIssuesStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = ReportsHarness()
        h.generate_orphan_issues_report()
        assert f"{h._wiki_t4}/Orphaned Issues" in h._uploaded

    def test_page_title_present(self):
        assert "# Orphaned Issues Report" in _run(ReportsHarness())

    def test_empty_state_no_crash(self):
        assert _run(ReportsHarness()) != ""


class TestOrphanIssuesEmptyState:
    def test_no_orphans_message_when_no_projects(self):
        assert "_No orphaned issues found._" in _run(ReportsHarness())

    def test_issue_with_epic_excluded(self):
        proj   = _project()
        linked = _issue(iid=1, epic_id=100)
        content = _run(_harness(proj, [linked]))
        assert "_No orphaned issues found._" in content

    def test_roam_labelled_issues_excluded(self):
        proj = _project()
        roam = _issue(iid=1, labels=["roam::owned"])
        content = _run(_harness(proj, [roam]))
        assert "_No orphaned issues found._" in content


class TestOrphanIssuesWithData:
    def test_orphan_issue_title_shown(self):
        proj  = _project()
        issue = _issue(iid=5, title="Unlinked Task")
        content = _run(_harness(proj, [issue]))
        assert "Unlinked Task" in content

    def test_total_count_in_summary(self):
        proj   = _project()
        issues = [_issue(iid=i, title=f"Issue {i}") for i in range(1, 4)]
        content = _run(_harness(proj, issues))
        assert "3 orphaned issue(s)" in content

    def test_grouped_by_project_section_header(self):
        proj  = _project(name_with_ns="Test Group / My Project")
        issue = _issue(iid=1, title="Task")
        content = _run(_harness(proj, [issue]))
        assert "My Project" in content
