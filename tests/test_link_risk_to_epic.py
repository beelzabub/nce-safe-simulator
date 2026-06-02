"""Unit tests for BootstrapMixin._link_risk_to_epic (Refs #10)."""
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/root/.venv/beelzabub-project")

from mixins.bootstrap import BootstrapMixin


class ConcreteBootstrap(BootstrapMixin):
    def __init__(self, graphql_result=None):
        self.gl            = MagicMock()
        self.url           = "https://gitlab.com"
        self.private_token = "test-token"
        self._gql_result   = graphql_result
        self._gql_calls    = []

    def graphql_query(self, query, variables=None):
        self._gql_calls.append(variables)
        return self._gql_result


def _epic(work_item_id=100, iid=1):
    obj = MagicMock()
    obj.work_item_id = work_item_id
    obj.iid          = iid
    return obj


def _risk(id=191000200, iid=7):
    obj = MagicMock()
    obj.id  = id
    obj.iid = iid
    return obj


def _project(id=42):
    obj = MagicMock()
    obj.id = id
    return obj


def _ok_gql():
    return {"workItemAddLinkedItems": {"workItem": {"id": "gid://..."}, "errors": []}}


class TestLinkRiskToEpic:
    def test_calls_mutation_with_correct_gids(self):
        bs = ConcreteBootstrap(graphql_result=_ok_gql())
        bs._link_risk_to_epic(_risk(id=191000200), _epic(work_item_id=100), _project())
        assert len(bs._gql_calls) == 1
        assert bs._gql_calls[0] == {
            "epicGid": "gid://gitlab/WorkItem/100",
            "riskGid": "gid://gitlab/WorkItem/191000200",
        }

    def test_skips_when_epic_has_no_work_item_id(self):
        bs = ConcreteBootstrap(graphql_result=_ok_gql())
        bs._link_risk_to_epic(_risk(), _epic(work_item_id=None), _project())
        assert bs._gql_calls == []

    def test_risk_global_id_used_directly_as_work_item_gid(self):
        bs = ConcreteBootstrap(graphql_result=_ok_gql())
        bs._link_risk_to_epic(_risk(id=999888777), _epic(work_item_id=100), _project())
        assert bs._gql_calls[0]["riskGid"] == "gid://gitlab/WorkItem/999888777"

    def test_no_rest_call_needed_for_risk_gid(self):
        bs = ConcreteBootstrap(graphql_result=_ok_gql())
        with patch("requests.get") as mock_get:
            bs._link_risk_to_epic(_risk(id=12345), _epic(work_item_id=100), _project())
        mock_get.assert_not_called()

    def test_prints_warning_on_graphql_errors(self, capsys):
        result = {"workItemAddLinkedItems": {"workItem": {"id": "..."}, "errors": ["link failed"]}}
        bs = ConcreteBootstrap(graphql_result=result)
        bs._link_risk_to_epic(_risk(), _epic(), _project())
        assert "link failed" in capsys.readouterr().out
