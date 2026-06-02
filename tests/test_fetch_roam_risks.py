"""Unit tests for _fetch_roam_risks() in mixins/utils.py (Refs #10)."""
import sys
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, "/root/.venv/beelzabub-project")

from mixins.utils import UtilitiesMixin
from conftest import make_epic, make_mock_group

_FAKE_PROJECT_PATH = "test/team-backlog"


def _make_utils(graphql_issues, roam_labels=None):
    """Build a ConcreteUtils whose group has one project returning the given issues."""
    class ConcreteUtils(UtilitiesMixin):
        def __init__(self):
            self.ROAM_LABELS   = roam_labels or [
                "roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"
            ]
            self.url           = "https://gitlab.com"
            self.private_token = "test-token"
            self._issues       = graphql_issues

            fake_project = MagicMock()
            fake_project.path_with_namespace = _FAKE_PROJECT_PATH

            group = MagicMock()
            group.full_path = "test/portfolio"
            group.projects.list.return_value = [fake_project]
            group.subgroups.list.return_value = []

            self.gl = MagicMock()
            self._group = group

        def graphql_query(self, query, variables=None):
            return {"project": {"issues": {"nodes": self._issues}}}

    u = ConcreteUtils()
    return u, u._group


def _make_gql_issue(iid, title, roam_status, assignee_name, linked_wi_ids):
    return {
        "iid":   iid,
        "title": title,
        "webUrl": f"https://gitlab.com/test/issues/{iid}",
        "state": "opened",
        "labels": {"nodes": [{"title": roam_status}]},
        "assignees": {"nodes": [{"name": assignee_name}]},
        "linkedWorkItems": {
            "nodes": [
                {"workItem": {"id": f"gid://gitlab/WorkItem/{wi_id}"}}
                for wi_id in linked_wi_ids
            ]
        },
    }


class TestFetchRoamRisks:
    def test_returns_empty_when_no_roam_labels(self):
        u, group = _make_utils([], roam_labels=[])
        assert u._fetch_roam_risks(group, []) == {}

    def test_returns_empty_when_no_epics_provided(self):
        u, group = _make_utils([_make_gql_issue(1, "Risk A", "roam::owned", "Alice", [100])])
        assert u._fetch_roam_risks(group, []) == {}

    def test_returns_empty_when_graphql_returns_none(self):
        class NullGql(UtilitiesMixin):
            def __init__(self):
                self.ROAM_LABELS   = ["roam::owned"]
                self.url           = "https://gitlab.com"
                self.private_token = "test-token"
                fake_project       = MagicMock()
                fake_project.path_with_namespace = _FAKE_PROJECT_PATH
                group = MagicMock()
                group.projects.list.return_value = [fake_project]
                group.subgroups.list.return_value = []
                self.gl    = MagicMock()
                self._group = group
            def graphql_query(self, *a, **kw):
                return None

        u = NullGql()
        assert u._fetch_roam_risks(u._group, [make_epic(id=1, work_item_id=555)]) == {}

    def test_single_risk_linked_to_single_epic(self):
        wi_id, epic_id = 555, 100
        u, group = _make_utils([
            _make_gql_issue(1, "Risk: DB may overflow", "roam::owned", "Alice", [wi_id])
        ])
        result = u._fetch_roam_risks(group, [make_epic(id=epic_id, work_item_id=wi_id)])

        assert epic_id in result
        risk = result[epic_id][0]
        assert risk["title"]       == "Risk: DB may overflow"
        assert risk["roam_status"] == "roam::owned"
        assert risk["assignee"]    == "Alice"

    def test_multiple_risks_linked_to_same_epic(self):
        wi_id, epic_id = 555, 100
        u, group = _make_utils([
            _make_gql_issue(1, "Risk A", "roam::owned",    "Alice", [wi_id]),
            _make_gql_issue(2, "Risk B", "roam::accepted", "Bob",   [wi_id]),
        ])
        result = u._fetch_roam_risks(group, [make_epic(id=epic_id, work_item_id=wi_id)])
        assert len(result[epic_id]) == 2

    def test_risk_linked_to_multiple_epics(self):
        wi_a, wi_b, id_a, id_b = 111, 222, 10, 20
        u, group = _make_utils([
            _make_gql_issue(1, "Cross-cutting risk", "roam::mitigated", "Carol", [wi_a, wi_b])
        ])
        result = u._fetch_roam_risks(group, [
            make_epic(id=id_a, work_item_id=wi_a),
            make_epic(id=id_b, work_item_id=wi_b),
        ])
        assert id_a in result
        assert id_b in result

    def test_risk_linked_to_unknown_work_item_is_ignored(self):
        u, group = _make_utils([
            _make_gql_issue(1, "Risk A", "roam::owned", "Alice", [999])
        ])
        result = u._fetch_roam_risks(group, [make_epic(id=100, work_item_id=555)])
        assert result == {}

    def test_issue_without_roam_label_is_skipped(self):
        u, group = _make_utils([
            _make_gql_issue(1, "Not a risk", "bug", "Alice", [555])
        ])
        result = u._fetch_roam_risks(group, [make_epic(id=100, work_item_id=555)])
        assert result == {}

    def test_all_four_roam_statuses_are_captured(self):
        epics = [make_epic(id=i, work_item_id=i) for i in range(1, 5)]
        issues = [
            _make_gql_issue(i, f"Risk {s}", s, "Dev", [i])
            for i, s in enumerate(
                ["roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"], 1
            )
        ]
        u, group = _make_utils(issues)
        result = u._fetch_roam_risks(group, epics)
        for i, status in enumerate(
            ["roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"], 1
        ):
            assert result[i][0]["roam_status"] == status

    def test_issue_with_no_assignee_shows_dash(self):
        issue = {
            "iid": 1, "title": "Unassigned risk",
            "webUrl": "https://gitlab.com/test/issues/1",
            "state": "opened",
            "labels": {"nodes": [{"title": "roam::owned"}]},
            "assignees": {"nodes": []},
            "linkedWorkItems": {"nodes": [{"workItem": {"id": "gid://gitlab/WorkItem/555"}}]},
        }
        u, group = _make_utils([issue])
        result = u._fetch_roam_risks(group, [make_epic(id=100, work_item_id=555)])
        assert result[100][0]["assignee"] == "—"
