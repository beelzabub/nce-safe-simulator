"""Tests for generate_team_backlog_report (Refs #24)."""
import sys
from unittest.mock import MagicMock

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


def _backlog_project(team_id=40):
    path = f"test/team-{team_id}/team-backlog"
    return {
        "path":                path.split("/")[-1],
        "path_with_namespace": path,
        "name_with_namespace": f"Test / Team / team-backlog",
        "web_url":             f"https://gitlab.com/{path}",
        "issues_enabled":      True,
    }


def _issue(iid=1, title="Story", state="opened", weight=3, epic_id=None):
    return {
        "iid":       iid,
        "title":     title,
        "web_url":   f"https://gitlab.com/test/issues/{iid}",
        "state":     state,
        "weight":    weight,
        "epic_id":   epic_id,
    }


def _harness(issues=None, epics_by_id=None):
    vs   = _vs()
    art  = _art()
    team = _team()
    proj = _backlog_project()

    h = ReportsHarness(vs_groups=[vs])
    h._rd_groups_by_parent = {vs["id"]: [art], art["id"]: [team]}
    h._rd_projects_by_nsid = {team["id"]: [proj]}
    if issues:
        h._rd_issues_by_project[proj["path_with_namespace"]] = issues
    h._rd_epics_by_id = epics_by_id or {}
    h.gl = MagicMock()
    h.gl.groups.get.return_value = MagicMock()
    return h


def _run(h):
    h.generate_team_backlog_report()
    return {
        "index":   h._uploaded.get(f"{h._wiki_t3}/Team Backlogs", ""),
        "backlog": h._uploaded.get("Team Backlog", ""),
    }


class TestTeamBacklogStructure:
    def test_index_page_uploaded(self):
        h = _harness()
        h.generate_team_backlog_report()
        assert f"{h._wiki_t3}/Team Backlogs" in h._uploaded

    def test_team_page_uploaded(self):
        h = _harness()
        h.generate_team_backlog_report()
        assert "Team Backlog" in h._uploaded

    def test_index_title_present(self):
        pages = _run(_harness())
        assert "# Team Backlog Index" in pages["index"]

    def test_team_page_title_present(self):
        pages = _run(_harness())
        assert "# Team Backlog" in pages["backlog"]

    def test_summary_section_present(self):
        assert "## Summary" in _run(_harness())["backlog"]


class TestTeamBacklogWithData:
    def test_issue_title_shown_in_team_page(self):
        issues = [_issue(iid=1, title="My Story")]
        pages = _run(_harness(issues=issues))
        assert "My Story" in pages["backlog"]

    def test_issue_grouped_by_feature_when_linked(self):
        epic   = make_epic(id=100, title="Parent Feature", etype="Feature")
        issues = [_issue(iid=1, title="Linked Issue", epic_id=100)]
        h = _harness(issues=issues, epics_by_id={100: epic})
        pages = _run(h)
        assert "Parent Feature" in pages["backlog"]
        assert "Issues by Feature" in pages["backlog"]

    def test_unlinked_issues_section_present(self):
        issues = [_issue(iid=1, title="Free Issue", epic_id=None)]
        pages = _run(_harness(issues=issues))
        assert "Unlinked Issues" in pages["backlog"]

    def test_pct_done_calculated_from_weights(self):
        issues = [
            _issue(iid=1, state="closed", weight=5),
            _issue(iid=2, state="opened", weight=5),
        ]
        pages = _run(_harness(issues=issues))
        assert "50%" in pages["backlog"]

    def test_team_appears_in_index(self):
        pages = _run(_harness())
        assert "Team Alpha" in pages["index"]
