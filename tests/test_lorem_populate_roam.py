"""Tests that _lorem_populate_group creates ROAM risk issues and links them (Refs #10)."""
import sys
import random
import pytest
from unittest.mock import MagicMock, patch, call



from mixins.bootstrap import BootstrapMixin


class ConcreteBootstrap(BootstrapMixin):
    EPIC_TYPE_LABELS        = ["Epic", "Capability", "Feature"]
    EPIC_TYPE_DISPLAY_NAMES = ["Epic", "Capability", "Feature"]

    def __init__(self, roam_labels=None):
        self.gl            = MagicMock()
        self.url           = "https://gitlab.com"
        self.private_token = "test-token"
        self.ROAM_LABELS   = roam_labels if roam_labels is not None else [
            "roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"
        ]
        self.fibonacci_weights = [1, 2, 3, 5, 8, 13]
        self._link_calls   = []

    def graphql_query(self, query, variables=None):
        return None

    def _lorem_epics_in_group(self, group, count, allowed_types=None):
        feature = MagicMock()
        feature.id    = 1
        feature.iid   = 1
        feature.title = "Feature Epic"
        feature.labels = ["Feature"]
        feature.work_item_id = 999
        return [(feature, "Feature")]

    def create_lorem_milestones(self, project):
        return []

    def _link_risk_to_epic(self, risk_issue, epic, project):
        self._link_calls.append((risk_issue, epic))


def _make_project():
    project = MagicMock()
    project.id   = 10
    project.path = "team-backlog"
    project.path_with_namespace = "test/team-backlog"

    issue = MagicMock()
    issue.iid = 1
    issue.work_item_id = None
    project.issues.create.return_value = issue

    ms = MagicMock()
    project.milestones.create.return_value = ms
    return project


class TestLoremPopulateRoamIssues:
    def test_risk_issues_created_when_roam_labels_configured(self):
        bs = ConcreteBootstrap()
        group = MagicMock()
        group.id   = 1
        group.name = "Team 01"
        group.path = "team-01"
        group.full_path = "test/team-01"

        project = _make_project()
        bs.gl.projects.create.return_value = project

        with patch("random.choices", return_value=[1]):
            with patch("random.randint", return_value=1):
                bs._lorem_populate_group(group, epic_count=1)

        assert bs.gl.projects.create.called
        assert project.issues.create.called
        risk_calls = [
            c for c in project.issues.create.call_args_list
            if any(l.startswith("roam::") for l in c[0][0].get("labels", []))
        ]
        assert len(risk_calls) >= 1

    def test_risk_issue_title_prefixed_with_risk(self):
        bs = ConcreteBootstrap()
        group = MagicMock()
        group.id = 1
        group.name = "Team 01"
        group.path = "team-01"
        group.full_path = "test/team-01"

        project = _make_project()
        bs.gl.projects.create.return_value = project

        with patch("random.choices", return_value=[1]):
            with patch("random.randint", return_value=1):
                bs._lorem_populate_group(group, epic_count=1)

        risk_calls = [
            c for c in project.issues.create.call_args_list
            if any(l.startswith("roam::") for l in c[0][0].get("labels", []))
        ]
        for c in risk_calls:
            assert c[0][0]["title"].startswith("Risk:")

    def test_link_risk_to_epic_called_for_each_risk_issue(self):
        bs = ConcreteBootstrap()
        group = MagicMock()
        group.id = 1
        group.name = "Team 01"
        group.path = "team-01"
        group.full_path = "test/team-01"

        project = _make_project()
        bs.gl.projects.create.return_value = project

        with patch("random.choices", return_value=[2]):
            with patch("random.randint", return_value=1):
                bs._lorem_populate_group(group, epic_count=1)

        assert len(bs._link_calls) == 2

    def test_no_risk_issues_when_roam_labels_empty(self):
        bs = ConcreteBootstrap(roam_labels=[])
        group = MagicMock()
        group.id = 1
        group.name = "Team 01"
        group.path = "team-01"
        group.full_path = "test/team-01"

        project = _make_project()
        bs.gl.projects.create.return_value = project

        with patch("random.randint", return_value=1):
            bs._lorem_populate_group(group, epic_count=1)

        assert bs._link_calls == []
