"""Unit tests for _fetch_roam_risks() in mixins/utils.py (Refs #10)."""
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/root/.venv/beelzabub-project")

from mixins.utils import UtilitiesMixin
from conftest import make_epic, make_mock_group


class ConcreteUtils(UtilitiesMixin):
    def __init__(self, roam_labels=None, graphql_result=None):
        self.gl            = MagicMock()
        self.url           = "https://gitlab.com"
        self.private_token = "test-token"
        self.ROAM_LABELS   = roam_labels or [
            "roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"
        ]
        self._gql_result   = graphql_result

    def graphql_query(self, query, variables=None):
        return self._gql_result


def _make_gql_result(issues):
    return {"group": {"issues": {"nodes": issues}}}


def _make_gql_issue(iid, title, roam_status, assignee_name, linked_wi_ids):
    return {
        "iid":   iid,
        "title": title,
        "webUrl": f"https://gitlab.com/test/issues/{iid}",
        "state": "opened",
        "labels": {"nodes": [{"title": roam_status}]},
        "assignees": {"nodes": [{"name": assignee_name, "username": assignee_name.lower()}]},
        "linkedWorkItems": {
            "nodes": [
                {
                    "linkType": "RELATED",
                    "workItem": {
                        "id": f"gid://gitlab/WorkItem/{wi_id}",
                        "title": f"Epic {wi_id}",
                        "webUrl": f"https://gitlab.com/groups/test/-/epics/{wi_id}",
                    }
                }
                for wi_id in linked_wi_ids
            ]
        }
    }


class TestFetchRoamRisks:
    def test_returns_empty_when_no_roam_labels(self):
        utils = ConcreteUtils(roam_labels=[])
        group = make_mock_group()
        result = utils._fetch_roam_risks(group, [])
        assert result == {}

    def test_returns_empty_when_no_epics_with_work_item_id(self):
        utils = ConcreteUtils(graphql_result=_make_gql_result([
            _make_gql_issue(1, "Risk A", "roam::owned", "Alice", [999])
        ]))
        epics_all = [make_epic(id=100, work_item_id=None)]
        result = utils._fetch_roam_risks(make_mock_group(), epics_all)
        assert result == {}

    def test_returns_empty_when_graphql_returns_none(self):
        utils = ConcreteUtils(graphql_result=None)
        epics_all = [make_epic(id=100, work_item_id=555)]
        result = utils._fetch_roam_risks(make_mock_group(), epics_all)
        assert result == {}

    def test_single_risk_linked_to_single_epic(self):
        wi_id = 555
        epic_id = 100
        utils = ConcreteUtils(graphql_result=_make_gql_result([
            _make_gql_issue(1, "Risk: DB may overflow", "roam::owned", "Alice", [wi_id])
        ]))
        epics_all = [make_epic(id=epic_id, work_item_id=wi_id)]
        result = utils._fetch_roam_risks(make_mock_group(), epics_all)

        assert epic_id in result
        assert len(result[epic_id]) == 1
        risk = result[epic_id][0]
        assert risk["title"]       == "Risk: DB may overflow"
        assert risk["roam_status"] == "roam::owned"
        assert risk["assignee"]    == "Alice"

    def test_multiple_risks_linked_to_same_epic(self):
        wi_id = 555
        epic_id = 100
        utils = ConcreteUtils(graphql_result=_make_gql_result([
            _make_gql_issue(1, "Risk A", "roam::owned",    "Alice", [wi_id]),
            _make_gql_issue(2, "Risk B", "roam::accepted", "Bob",   [wi_id]),
        ]))
        epics_all = [make_epic(id=epic_id, work_item_id=wi_id)]
        result = utils._fetch_roam_risks(make_mock_group(), epics_all)

        assert epic_id in result
        assert len(result[epic_id]) == 2

    def test_risk_linked_to_multiple_epics(self):
        wi_a, wi_b = 111, 222
        id_a, id_b = 10,  20
        utils = ConcreteUtils(graphql_result=_make_gql_result([
            _make_gql_issue(1, "Cross-cutting risk", "roam::mitigated", "Carol", [wi_a, wi_b])
        ]))
        epics_all = [
            make_epic(id=id_a, work_item_id=wi_a),
            make_epic(id=id_b, work_item_id=wi_b),
        ]
        result = utils._fetch_roam_risks(make_mock_group(), epics_all)

        assert id_a in result
        assert id_b in result

    def test_risk_linked_to_unknown_work_item_is_ignored(self):
        wi_known   = 555
        wi_unknown = 999
        epic_id    = 100
        utils = ConcreteUtils(graphql_result=_make_gql_result([
            _make_gql_issue(1, "Risk A", "roam::owned", "Alice", [wi_unknown])
        ]))
        epics_all = [make_epic(id=epic_id, work_item_id=wi_known)]
        result = utils._fetch_roam_risks(make_mock_group(), epics_all)
        assert result == {}

    def test_all_four_roam_statuses_are_captured(self):
        epics_all = [make_epic(id=i, work_item_id=i) for i in range(1, 5)]
        issues = [
            _make_gql_issue(i, f"Risk {s}", s, "Dev", [i])
            for i, s in enumerate(
                ["roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"], 1
            )
        ]
        utils = ConcreteUtils(graphql_result=_make_gql_result(issues))
        result = utils._fetch_roam_risks(make_mock_group(), epics_all)

        for i, status in enumerate(
            ["roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"], 1
        ):
            epic_risks = result.get(i, [])
            assert len(epic_risks) == 1
            assert epic_risks[0]["roam_status"] == status

    def test_issue_with_no_assignee_shows_dash(self):
        wi_id = 555
        utils = ConcreteUtils(graphql_result=_make_gql_result([{
            "iid": 1, "title": "Unassigned risk",
            "webUrl": "https://gitlab.com/test/issues/1",
            "state": "opened",
            "labels": {"nodes": [{"title": "roam::owned"}]},
            "assignees": {"nodes": []},
            "linkedWorkItems": {"nodes": [
                {"linkType": "RELATED", "workItem": {
                    "id": f"gid://gitlab/WorkItem/{wi_id}",
                    "title": "Epic", "webUrl": "https://gitlab.com/-/epics/1"
                }}
            ]}
        }]))
        epics_all = [make_epic(id=100, work_item_id=wi_id)]
        result = utils._fetch_roam_risks(make_mock_group(), epics_all)
        assert result[100][0]["assignee"] == "—"
