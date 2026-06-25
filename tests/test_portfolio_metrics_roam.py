"""Tests that calculate_portfolio_metrics wires work_item_id and roam_risks (Refs #10)."""
import sys
import pytest
from collections import defaultdict
from unittest.mock import MagicMock, patch



from mixins.utils import UtilitiesMixin


def _make_epic_obj(id, iid, labels, work_item_id, state="opened", parent_id=None):
    e = MagicMock()
    e.id           = id
    e.iid          = iid
    e.title        = f"Epic {iid}"
    e.description  = None
    e.state        = state
    e.labels       = labels
    e.web_url      = f"https://gitlab.com/groups/test/-/epics/{iid}"
    e.work_item_id = work_item_id
    e.parent_id    = parent_id
    e.group_id     = 10
    e.start_date   = None
    e.due_date     = None
    e.created_at   = None
    e.updated_at   = None
    return e


class ConcreteUtils(UtilitiesMixin):
    EPIC_TYPE_LABELS        = ["Epic", "Capability", "Feature"]
    EPIC_TYPE_DISPLAY_NAMES = ["Epic", "Capability", "Feature"]

    def __init__(self, epics, roam_by_epic=None):
        self.gl               = MagicMock()
        self.url              = "https://gitlab.com"
        self.private_token    = "test-token"
        self.gitlab_namespace = None
        self.BUSINESS_VALUE_FIELD = {"name": "Business Value"}
        self.ROAM_LABELS      = ["roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"]
        self._epics        = epics
        self._roam_by_epic = roam_by_epic or {}

        group = MagicMock()
        group.full_path = "test/portfolio"
        group.projects.list.return_value = []
        group.epics.list.return_value = epics
        self._group = group

        self.gl.groups.get.return_value = group

    def get_group_by_name(self, name):
        return self._group

    def graphql_query(self, query, variables=None):
        return {"group": {"epics": {"nodes": []}}}

    def _fetch_epic_weights(self, epics):
        return {}

    def _fetch_wi_supplement(self, group, epics):
        return {}, [], {}

    def _fetch_roam_risks(self, group, all_epics_raw):
        return self._roam_by_epic

    def _pct_through_pi(self, piid):
        return None


class TestPortfolioMetricsRoamWiring:
    def test_work_item_id_stored_on_epic_dict(self):
        epics = [_make_epic_obj(id=1, iid=1, labels=["Feature", "PIID::2026Q1"], work_item_id=12345)]
        utils = ConcreteUtils(epics=epics)

        result = utils.calculate_portfolio_metrics("test/portfolio")

        features = result.get("Feature", [])
        assert len(features) == 1
        assert features[0]["work_item_id"] == 12345

    def test_work_item_id_is_none_when_not_on_epic(self):
        epics = [_make_epic_obj(id=1, iid=1, labels=["Feature", "PIID::2026Q1"], work_item_id=None)]
        utils = ConcreteUtils(epics=epics)

        result = utils.calculate_portfolio_metrics("test/portfolio")

        assert result["Feature"][0]["work_item_id"] is None

    def test_roam_risks_attached_to_matching_epic(self):
        risk = {"iid": 9, "title": "Risk: DB overload", "roam_status": "roam::owned",
                "assignee": "Alice", "web_url": "https://gitlab.com/test/issues/9", "state": "opened"}
        epics = [_make_epic_obj(id=1, iid=1, labels=["Feature", "PIID::2026Q1"], work_item_id=55)]
        utils = ConcreteUtils(epics=epics, roam_by_epic={1: [risk]})

        result = utils.calculate_portfolio_metrics("test/portfolio")

        assert result["Feature"][0]["roam_risks"] == [risk]

    def test_roam_risks_empty_list_when_no_risks(self):
        epics = [_make_epic_obj(id=1, iid=1, labels=["Feature", "PIID::2026Q1"], work_item_id=55)]
        utils = ConcreteUtils(epics=epics, roam_by_epic={})

        result = utils.calculate_portfolio_metrics("test/portfolio")

        assert result["Feature"][0]["roam_risks"] == []

    def test_roam_risks_attached_across_multiple_epics(self):
        risk_a = {"iid": 1, "title": "Risk A", "roam_status": "roam::owned",
                  "assignee": "Alice", "web_url": "u1", "state": "opened"}
        risk_b = {"iid": 2, "title": "Risk B", "roam_status": "roam::mitigated",
                  "assignee": "Bob",   "web_url": "u2", "state": "opened"}
        epics = [
            _make_epic_obj(id=1, iid=1, labels=["Feature", "PIID::2026Q1"], work_item_id=10),
            _make_epic_obj(id=2, iid=2, labels=["Feature", "PIID::2026Q1"], work_item_id=20),
        ]
        utils = ConcreteUtils(epics=epics, roam_by_epic={1: [risk_a], 2: [risk_b]})

        result = utils.calculate_portfolio_metrics("test/portfolio")

        by_id = {e["id"]: e for e in result["Feature"]}
        assert by_id[1]["roam_risks"] == [risk_a]
        assert by_id[2]["roam_risks"] == [risk_b]


# ---------------------------------------------------------------------------
# Risk propagates upward through the hierarchy (Refs #95)
# ---------------------------------------------------------------------------

def _risk(iid, status="roam::owned"):
    return {"iid": iid, "title": f"Risk {iid}", "roam_status": status,
            "assignee": "Alice", "web_url": f"u{iid}", "state": "opened"}


class TestInheritedRoamRiskPropagation:
    def _cap_feature(self, roam_by_epic):
        """Capability(id=1) ← Feature(id=2); risks per roam_by_epic."""
        epics = [
            _make_epic_obj(id=1, iid=1, labels=["Capability", "PIID::2026Q1"], work_item_id=10),
            _make_epic_obj(id=2, iid=2, labels=["Feature", "PIID::2026Q1"], work_item_id=20, parent_id=1),
        ]
        utils = ConcreteUtils(epics=epics, roam_by_epic=roam_by_epic)
        result = utils.calculate_portfolio_metrics("test/portfolio")
        cap = result["Capability"][0]
        feat = result["Feature"][0]
        return cap, feat

    def test_parent_inherits_child_risk(self):
        risk = _risk(9)
        cap, feat = self._cap_feature({2: [risk]})
        # Feature carries the risk directly; Capability inherits it.
        assert feat["roam_risks"] == [risk]
        assert feat["inherited_roam_risks"] == []
        assert cap["roam_risks"] == []
        assert cap["inherited_roam_risks"] == [risk]

    def test_leaf_has_no_inherited_risks(self):
        cap, feat = self._cap_feature({2: [_risk(9)]})
        assert feat["inherited_roam_risks"] == []

    def test_parent_with_no_child_risk_has_empty_inherited(self):
        cap, feat = self._cap_feature({})
        assert cap["inherited_roam_risks"] == []

    def test_direct_risk_not_duplicated_into_inherited(self):
        # Same risk iid on both parent and child → parent keeps it only as direct.
        risk = _risk(9)
        epics = [
            _make_epic_obj(id=1, iid=1, labels=["Capability", "PIID::2026Q1"], work_item_id=10),
            _make_epic_obj(id=2, iid=2, labels=["Feature", "PIID::2026Q1"], work_item_id=20, parent_id=1),
        ]
        utils = ConcreteUtils(epics=epics, roam_by_epic={1: [risk], 2: [risk]})
        result = utils.calculate_portfolio_metrics("test/portfolio")
        cap = result["Capability"][0]
        assert cap["roam_risks"] == [risk]
        assert cap["inherited_roam_risks"] == []

    def test_risk_propagates_two_levels(self):
        # Epic(1) ← Capability(2) ← Feature(3); the top Epic inherits the leaf risk.
        risk = _risk(9)
        epics = [
            _make_epic_obj(id=1, iid=1, labels=["Epic", "PIID::2026Q1"], work_item_id=10),
            _make_epic_obj(id=2, iid=2, labels=["Capability", "PIID::2026Q1"], work_item_id=20, parent_id=1),
            _make_epic_obj(id=3, iid=3, labels=["Feature", "PIID::2026Q1"], work_item_id=30, parent_id=2),
        ]
        utils = ConcreteUtils(epics=epics, roam_by_epic={3: [risk]})
        result = utils.calculate_portfolio_metrics("test/portfolio")
        assert result["Capability"][0]["inherited_roam_risks"] == [risk]
        assert result["Epic"][0]["inherited_roam_risks"] == [risk]
