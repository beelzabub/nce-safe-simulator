"""Unit tests for the JQL client-side executor pieces (jql/executor.py, #300).

Covers result shaping from raw GraphQL nodes, exact expression-tree
evaluation over shaped items (every operator class, multi-valued fields,
EMPTY, dates, taxonomy fields, business_value, currentUser()), stable
multi-key client-side sorting, and GraphQL document assembly.
"""
from datetime import datetime

import pytest

from jql import parse
from jql.executor import (
    EvalContext,
    JqlExecutionError,
    build_work_items_query,
    evaluate,
    parse_ts,
    shape_node,
    sort_items,
)
from jql.fields import FieldRegistry

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 1, 12, 0, 0)

CONFIG = {
    "business_value_field": {"name": "Business Value"},
    "piid_labels": ["PIID::2026Q2", "PIID::2026Q3"],
    "epic_type_labels": ["epic::epic", "epic::capability", "epic::feature"],
    "risk_labels": ["risk::high", "risk::medium", "risk::low"],
    "wsjf_labels": {
        "urgency": ["wsjf-urgency::1", "wsjf-urgency::2", "wsjf-urgency::3"],
    },
}

REGISTRY = FieldRegistry.from_config(CONFIG)
CTX = EvalContext(registry=REGISTRY, now=NOW, current_user="jamie")

BV_GID = "gid://gitlab/Issuables::CustomField/7"


def item(**overrides):
    base = {
        "id": 100, "iid": 1, "type": "issue", "title": "Payment gateway rollout",
        "state": "opened", "labels": [], "assignees": [], "author": "alice",
        "assignee_names": [], "author_name": None,
        "milestone": None, "milestone_due": None, "iteration": None,
        "weight": None, "business_value": None, "start_date": None,
        "due_date": None, "created_at": "2026-03-01T10:00:00Z",
        "updated_at": "2026-07-15T08:30:00Z", "closed_at": None,
        "parent_iid": None, "namespace_path": "portfolio/team-a",
        "web_url": "https://gitlab.example/x/1", "description": None,
    }
    base.update(overrides)
    return base


def ev(query, it, ctx=CTX):
    return evaluate(parse(query).where, it, ctx)


# ---------------------------------------------------------------------------
# shape_node
# ---------------------------------------------------------------------------

FULL_NODE = {
    "id": "gid://gitlab/WorkItem/1234",
    "iid": "42",
    "title": "Build the thing",
    "state": "OPEN",
    "webUrl": "https://gitlab.example/g/p/-/work_items/42",
    "createdAt": "2026-01-05T09:00:00Z",
    "updatedAt": "2026-07-01T10:00:00Z",
    "closedAt": None,
    "workItemType": {"name": "Key Result"},
    "author": {"username": "alice", "name": "Alice Anderson"},
    "namespace": {"fullPath": "portfolio/team-a"},
    "widgets": [
        {"labels": {"nodes": [{"title": "risk::high"}, {"title": "PIID::2026Q2"}]}},
        {"assignees": {"nodes": [{"username": "bob", "name": "Bob Barker"},
                                 {"username": "carol"}]}},
        {"milestone": {"title": "M1", "dueDate": "2026-09-30"}},
        {"iteration": {"id": "gid://gitlab/Iteration/9", "title": "Sprint 3"}},
        {"weight": 5},
        {"startDate": "2026-02-01", "dueDate": "2026-10-01"},
        {"parent": {"iid": "7"}},
        {"description": "Long form text"},
        {"customFieldValues": [
            {"customField": {"id": "gid://gitlab/other", "name": "Other"},
             "selectedOptions": [{"id": "o0", "value": "99"}]},
            {"customField": {"id": BV_GID, "name": "Business Value"},
             "selectedOptions": [{"id": "o1", "value": "8"}]},
        ]},
    ],
}


class TestShapeNode:

    def test_full_node(self):
        shaped = shape_node(FULL_NODE, bv_field_id=BV_GID)
        assert shaped == {
            "id": 1234, "iid": 42, "type": "key_result",
            "title": "Build the thing", "state": "opened",
            "labels": ["risk::high", "PIID::2026Q2"],
            "assignees": ["bob", "carol"], "author": "alice",
            "assignee_names": ["Bob Barker"], "author_name": "Alice Anderson",
            "milestone": "M1", "milestone_due": "2026-09-30",
            "iteration": "Sprint 3", "weight": 5, "business_value": 8,
            "start_date": "2026-02-01", "due_date": "2026-10-01",
            "created_at": "2026-01-05T09:00:00Z",
            "updated_at": "2026-07-01T10:00:00Z", "closed_at": None,
            "parent_iid": 7, "namespace_path": "portfolio/team-a",
            "web_url": "https://gitlab.example/g/p/-/work_items/42",
            "description": "Long form text",
        }

    def test_bv_ignored_without_field_id(self):
        assert shape_node(FULL_NODE, bv_field_id=None)["business_value"] is None

    def test_minimal_node(self):
        shaped = shape_node({
            "id": "gid://gitlab/WorkItem/9", "iid": "3", "title": "t",
            "state": "CLOSED", "workItemType": {"name": "Epic"}, "widgets": [],
        })
        assert shaped["type"] == "epic"
        assert shaped["state"] == "closed"
        assert shaped["labels"] == []
        assert shaped["assignees"] == []
        assert shaped["weight"] is None
        assert shaped["parent_iid"] is None

    def test_parse_ts(self):
        assert parse_ts("2026-01-05T09:00:00Z") == datetime(2026, 1, 5, 9)
        assert parse_ts("2026-01-05T09:00:00+02:00") == datetime(2026, 1, 5, 7)
        assert parse_ts("2026-01-05") == datetime(2026, 1, 5)
        assert parse_ts(None) is None
        assert parse_ts("garbage") is None


# ---------------------------------------------------------------------------
# evaluate — scalar and multi-valued fields
# ---------------------------------------------------------------------------

class TestEvaluateBasics:

    def test_state_equality(self):
        assert ev("state = opened", item())
        assert not ev("state = closed", item())
        assert ev("state != closed", item())

    def test_state_all_matches_everything(self):
        assert ev("state = all", item())
        assert ev("state = all", item(state="closed"))

    def test_type(self):
        assert ev("type = issue", item())
        assert ev("issuetype = issue", item())
        assert not ev("type = epic", item())

    def test_title_contains_case_insensitive(self):
        assert ev('title ~ "GATEWAY"', item())
        assert not ev('title ~ "nonexistent"', item())
        assert ev('title !~ "nonexistent"', item())

    def test_title_equality_exact(self):
        assert ev('title = "payment gateway rollout"', item())
        assert not ev('title = "payment"', item())

    def test_text_searches_description_too(self):
        it = item(description="phased rollout plan for the beta cohort")
        assert ev('text ~ "beta cohort"', it)
        assert not ev('text ~ "beta cohort"', item())

    def test_assignee_membership(self):
        it = item(assignees=["alice", "bob"])
        assert ev("assignee = alice", it)
        assert ev("assignee = ALICE", it)
        assert not ev("assignee = carol", it)
        assert ev("assignee != carol", it)

    def test_assignee_currentuser(self):
        assert ev("assignee = currentUser()", item(assignees=["jamie"]))
        assert not ev("assignee = currentUser()", item(assignees=["bob"]))

    def test_labels_membership_and_contains(self):
        it = item(labels=["risk::high", "type::feature"])
        assert ev('labels = "risk::high"', it)
        assert ev('labels ~ "risk"', it)
        assert not ev('labels = "risk"', it)

    def test_author(self):
        assert ev("author = alice", item())
        assert ev("reporter = alice", item())
        assert not ev("author = bob", item())

    def test_milestone(self):
        assert ev('milestone = "M1"', item(milestone="M1"))
        assert not ev('milestone = "M1"', item())

    def test_iteration_alias_sprint(self):
        assert ev('sprint = "Sprint 3"', item(iteration="Sprint 3"))
        assert not ev('sprint = "Sprint 3"', item())

    def test_iid_and_parent_numeric(self):
        assert ev("iid = 1", item())
        assert ev("iid IN (1, 2)", item())
        assert ev("parent = 7", item(parent_iid=7))
        assert not ev("parent = 7", item())

    def test_project_matches_full_path_or_leaf(self):
        assert ev("project = team-a", item())
        assert ev('project = "portfolio/team-a"', item())
        assert not ev("project = team-b", item())


class TestEvaluateNumbers:

    def test_weight_comparisons(self):
        it = item(weight=5)
        assert ev("weight = 5", it)
        assert ev("weight >= 5", it)
        assert ev("weight > 3", it)
        assert not ev("weight > 5", it)
        assert ev("weight < 8", it)
        assert ev("weight != 3", it)

    def test_weight_zero_is_not_empty(self):
        it = item(weight=0)
        assert ev("weight = 0", it)
        assert not ev("weight IS EMPTY", it)

    def test_missing_weight(self):
        it = item()
        assert not ev("weight = 5", it)
        assert not ev("weight >= 0", it)
        assert ev("weight != 5", it)          # pure negation semantics
        assert ev("weight IS EMPTY", it)

    def test_business_value(self):
        it = item(business_value=8)
        assert ev("business_value >= 8", it)
        assert not ev("business_value > 8", it)
        assert ev("business_value IS NOT EMPTY", it)
        assert ev("business_value IS EMPTY", item())


class TestEvaluateDates:

    def test_date_bounds(self):
        it = item(created_at="2026-03-01T10:00:00Z")
        assert ev("created >= 2026-03-01", it)
        assert ev("created >= 2026-01-01", it)
        assert not ev("created >= 2026-04-01", it)
        assert ev("created < 2026-04-01", it)

    def test_day_equality_matches_whole_day(self):
        it = item(created_at="2026-03-01T10:00:00Z")
        assert ev("created = 2026-03-01", it)
        assert not ev("created = 2026-03-02", it)
        assert ev("created != 2026-03-02", it)

    def test_relative_duration(self):
        assert ev("updated >= -4w", item(updated_at="2026-07-15T00:00:00Z"))
        assert not ev("updated >= -4w", item(updated_at="2026-06-01T00:00:00Z"))

    def test_date_functions(self):
        assert ev("created >= startOfYear()", item(created_at="2026-03-01T00:00:00Z"))
        assert not ev("created >= startOfMonth()", item(created_at="2026-03-01T00:00:00Z"))

    def test_missing_date(self):
        assert not ev("due <= 2026-12-31", item())
        assert ev("due IS EMPTY", item())
        assert not ev("due IS EMPTY", item(due_date="2026-12-01"))

    def test_date_only_due(self):
        it = item(due_date="2026-10-01")
        assert ev("due = 2026-10-01", it)
        assert ev("due <= 2026-10-01", it)


class TestEvaluateTaxonomy:

    def test_equality_bare_and_full(self):
        it = item(labels=["PIID::2026Q2"])
        assert ev("piid = 2026Q2", it)
        assert ev('piid = "PIID::2026Q2"', it)
        assert not ev("piid = 2026Q3", it)
        assert ev("piid != 2026Q3", it)

    def test_is_empty(self):
        assert ev("piid IS EMPTY", item(labels=["risk::high"]))
        assert not ev("piid IS EMPTY", item(labels=["PIID::2026Q2"]))
        assert ev("piid IS NOT EMPTY", item(labels=["PIID::2026Q2"]))

    def test_numeric_ordering(self):
        it = item(labels=["wsjf-urgency::3"])
        assert ev("wsjf_urgency > 2", it)
        assert ev("wsjf_urgency >= 3", it)
        assert not ev("wsjf_urgency > 3", it)
        assert not ev("wsjf_urgency > 2", item())     # no label -> False

    def test_vocab_ordering_for_non_numeric_values(self):
        it = item(labels=["epic::capability"])
        assert ev("epic_type > epic", it)              # capability after epic
        assert ev("epic_type < feature", it)
        assert not ev("epic_type > capability", it)

    def test_in_list(self):
        it = item(labels=["wsjf-urgency::2"])
        assert ev("wsjf_urgency IN (2, 3)", it)
        assert not ev("wsjf_urgency IN (1, 3)", it)
        assert ev("wsjf_urgency NOT IN (1, 3)", it)

    def test_unscoped_labels_out_of_vocab_prefix_still_counts(self):
        # A PIID:: label outside the configured vocabulary still belongs to
        # the piid taxonomy for IS EMPTY purposes.
        assert not ev("piid IS EMPTY", item(labels=["PIID::2031Q9"]))

    def test_substring_over_taxonomy_values(self):
        # '~' needles are free text, not vocabulary members — reachable
        # through run_jql now that plan-time validation allows them.
        it = item(labels=["PIID::2026Q2"])
        assert ev('piid ~ "2026"', it)
        assert ev('piid ~ "q2"', it)                   # case-insensitive
        assert not ev('piid ~ "2027"', it)
        assert ev('piid !~ "2027"', it)
        assert not ev('piid ~ "2026"', item())         # no label -> no match
        assert ev('piid !~ "2026"', item())

    def test_substring_matches_out_of_vocab_taxonomy_value(self):
        assert ev('piid ~ "Q9"', item(labels=["PIID::2031Q9"]))


class TestEvaluateBoolean:

    def test_and_or_not(self):
        it = item(labels=["risk::high"], weight=5)
        assert ev('labels = "risk::high" AND weight >= 5', it)
        assert not ev('labels = "risk::high" AND weight > 5', it)
        assert ev('weight > 5 OR labels = "risk::high"', it)
        assert ev('NOT weight > 5', it)

    def test_grouping(self):
        it = item(state="opened", assignees=[])
        assert ev("state = opened AND (assignee = alice OR assignee IS EMPTY)", it)
        assert not ev(
            "state = opened AND (assignee = alice OR assignee IS EMPTY)",
            item(assignees=["bob"]))

    def test_empty_literal_forms(self):
        assert ev("assignee = EMPTY", item())
        assert not ev("assignee = EMPTY", item(assignees=["a"]))
        assert ev("assignee != EMPTY", item(assignees=["a"]))
        assert ev("milestone IS NULL", item())


# ---------------------------------------------------------------------------
# sort_items
# ---------------------------------------------------------------------------

def sort_by(query, items):
    keys = parse(query).order_by
    return sort_items(list(items), keys, REGISTRY)


class TestSortItems:

    def test_single_key_asc(self):
        a, b, c = item(id=1, weight=5), item(id=2, weight=1), item(id=3, weight=3)
        assert [i["id"] for i in sort_by("ORDER BY weight ASC", [a, b, c])] == [2, 3, 1]

    def test_single_key_desc(self):
        a, b, c = item(id=1, weight=5), item(id=2, weight=1), item(id=3, weight=3)
        assert [i["id"] for i in sort_by("ORDER BY weight DESC", [a, b, c])] == [1, 3, 2]

    def test_none_sorts_last_both_directions(self):
        a, b = item(id=1), item(id=2, weight=3)
        assert [i["id"] for i in sort_by("ORDER BY weight ASC", [a, b])] == [2, 1]
        assert [i["id"] for i in sort_by("ORDER BY weight DESC", [a, b])] == [2, 1]

    def test_stability_preserves_fetch_order_on_ties(self):
        items = [item(id=n, weight=5) for n in (4, 1, 3)]
        assert [i["id"] for i in sort_by("ORDER BY weight ASC", items)] == [4, 1, 3]

    def test_multi_key(self):
        items = [
            item(id=1, due_date="2026-01-01", weight=1),
            item(id=2, due_date="2026-01-01", weight=9),
            item(id=3, due_date="2025-12-01", weight=5),
        ]
        result = sort_by("ORDER BY due ASC, weight DESC", items)
        assert [i["id"] for i in result] == [3, 2, 1]

    def test_date_key(self):
        items = [item(id=1, created_at="2026-05-01T00:00:00Z"),
                 item(id=2, created_at="2026-01-01T00:00:00Z")]
        assert [i["id"] for i in sort_by("ORDER BY created ASC", items)] == [2, 1]

    def test_title_key_case_insensitive(self):
        items = [item(id=1, title="beta"), item(id=2, title="Alpha")]
        assert [i["id"] for i in sort_by("ORDER BY title ASC", items)] == [2, 1]

    def test_milestone_sorts_by_due_date_not_title(self):
        items = [
            item(id=1, milestone="A-first-alphabetically", milestone_due="2026-12-01"),
            item(id=2, milestone="Z-last-alphabetically", milestone_due="2026-01-01"),
        ]
        assert [i["id"] for i in sort_by("ORDER BY milestone ASC", items)] == [2, 1]

    def test_business_value_key(self):
        items = [item(id=1, business_value=3), item(id=2, business_value=13),
                 item(id=3)]
        assert [i["id"] for i in sort_by("ORDER BY business_value DESC", items)] == [2, 1, 3]

    def test_taxonomy_key_numeric(self):
        items = [item(id=1, labels=["wsjf-urgency::3"]),
                 item(id=2, labels=["wsjf-urgency::1"])]
        assert [i["id"] for i in sort_by("ORDER BY wsjf_urgency ASC", items)] == [2, 1]

    def test_iid_numeric_key(self):
        items = [item(id=1, iid=10), item(id=2, iid=2)]
        assert [i["id"] for i in sort_by("ORDER BY iid ASC", items)] == [2, 1]


# ---------------------------------------------------------------------------
# build_work_items_query
# ---------------------------------------------------------------------------

class TestBuildQuery:

    def test_declares_only_used_variables(self):
        query, request = build_work_items_query(
            {"state": "opened", "labelName": ["risk::high"]})
        assert "$state: IssuableState" in query
        assert "$labelName: [String!]" in query
        assert "state: $state" in query
        assert "labelName: $labelName" in query
        assert "assigneeUsernames" not in query
        assert request == {"state": "opened", "labelName": ["risk::high"]}

    def test_always_paginates_with_descendants(self):
        query, _ = build_work_items_query({})
        assert "includeDescendants: true" in query
        assert "first: $first" in query
        assert "after: $after" in query
        assert "pageInfo { hasNextPage endCursor }" in query

    def test_requests_connection_count(self):
        # The connection's count is the exact server-side match total — the
        # executor's `total` for fully-pushed-down queries rides on it.
        query, _ = build_work_items_query({})
        assert "count" in query.split("pageInfo")[0]

    def test_reserved_arg_names_get_variable_aliases(self):
        query, request = build_work_items_query({
            "search": "x", "in": ["TITLE"],
            "not": {"labelName": ["a"]}, "or": {"labelNames": ["b"]},
        })
        assert "in: $searchIn" in query
        assert "not: $negated" in query
        assert "or: $unioned" in query
        assert request["searchIn"] == ["TITLE"]
        assert request["negated"] == {"labelName": ["a"]}
        assert request["unioned"] == {"labelNames": ["b"]}

    def test_datetimes_serialized_iso_utc(self):
        _, request = build_work_items_query(
            {"createdAfter": datetime(2026, 1, 2, 3, 4, 5)})
        assert request["createdAfter"] == "2026-01-02T03:04:05Z"

    def test_optional_widgets(self):
        base, _ = build_work_items_query({})
        assert "WorkItemWidgetDescription" not in base
        assert "WorkItemWidgetCustomFields" not in base
        with_extras, _ = build_work_items_query(
            {}, needs_bv=True, needs_description=True)
        assert "WorkItemWidgetDescription" in with_extras
        assert "WorkItemWidgetCustomFields" in with_extras

    def test_unknown_arg_raises(self):
        with pytest.raises(JqlExecutionError):
            build_work_items_query({"bogusArg": 1})
