"""Unit tests for the JQL query planner (jql/planner.py, issue #300).

Covers conjunctive-envelope extraction and GraphQL variable construction:
push-down of every declared capability (state, labels, users, milestone,
weight, types, the eight date bounds, search+in, wildcards, not:, or:),
the superset-safety rules (id-resolution fields, EMPTY inside IN, general
OR), ORDER BY planning, and the plan-time validation errors.
"""
from datetime import datetime, timedelta

import pytest

from jql import ast, parse
from jql.fields import FieldRegistry, UnknownFieldError, UnknownFieldValueError
from jql.planner import (
    ENTITY_SCOPE_TYPES,
    JqlPlanError,
    is_day_granular,
    plan_query,
    query_mentions_current_user,
    resolve_scalar,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 1, 12, 0, 0)

CONFIG = {
    "business_value_field": {"name": "Business Value"},
    "piid_labels": ["PIID::2026Q2", "PIID::2026Q3", "PIID::2026Q4"],
    "epic_type_labels": ["epic::epic", "epic::capability", "epic::feature"],
    "risk_labels": ["risk::high", "risk::medium", "risk::low"],
    "wsjf_labels": {
        "urgency": ["wsjf-urgency::1", "wsjf-urgency::2", "wsjf-urgency::3"],
        "risk":    ["wsjf-risk::1", "wsjf-risk::2", "wsjf-risk::3"],
    },
}


@pytest.fixture(scope="module")
def registry():
    return FieldRegistry.from_config(CONFIG)


def make_plan(query, registry, **kw):
    kw.setdefault("now", NOW)
    return plan_query(parse(query), registry, **kw)


# ---------------------------------------------------------------------------
# Entity scope
# ---------------------------------------------------------------------------

class TestEntityScope:

    def test_empty_query_carries_scope_types_only(self, registry):
        plan = make_plan("", registry)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}
        assert plan.expr is None

    def test_full_scan_plan_keeps_scope_types(self, registry):
        plan = make_plan("state = opened AND labels = x", registry, push_down=False)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}

    def test_type_constraint_intersects_scope(self, registry):
        plan = make_plan("type = epic", registry)
        assert plan.variables["types"] == ["EPIC"]

    def test_type_outside_scope_marks_plan_empty(self, registry):
        # types: [] must never be sent — the server skips blank list filters
        # (no filter at all) instead of matching nothing. The plan flags the
        # provable contradiction so the executor short-circuits.
        plan = make_plan("type = task", registry)
        assert plan.variables["types"] == []
        assert plan.empty is True

    def test_type_in_list_intersects_scope(self, registry):
        plan = make_plan("type IN (epic, issue, task)", registry)
        assert sorted(plan.variables["types"]) == ["EPIC", "ISSUE"]
        assert plan.empty is False

    def test_in_scope_type_plan_not_empty(self, registry):
        plan = make_plan("type = epic", registry)
        assert plan.empty is False

    def test_full_scan_plan_never_empty(self, registry):
        plan = make_plan("type = task", registry, push_down=False)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}
        assert plan.empty is False

    def test_contradictory_any_lists_mark_plan_empty(self, registry):
        plan = make_plan('milestone IN ("M1") AND milestone IN ("M2")', registry)
        assert plan.variables["milestoneTitle"] == []
        assert plan.empty is True


# ---------------------------------------------------------------------------
# Equality push-down
# ---------------------------------------------------------------------------

class TestEqualityPushdown:

    def test_state(self, registry):
        plan = make_plan("state = opened", registry)
        assert plan.variables["state"] == "opened"

    def test_state_alias_status(self, registry):
        plan = make_plan("status = closed", registry)
        assert plan.variables["state"] == "closed"

    def test_label_equalities_accumulate_as_and_list(self, registry):
        plan = make_plan('labels = "a::x" AND labels = "b::y"', registry)
        assert plan.variables["labelName"] == ["a::x", "b::y"]

    def test_taxonomy_field_resolves_to_canonical_label(self, registry):
        plan = make_plan("piid = 2026Q2", registry)
        assert plan.variables["labelName"] == ["PIID::2026Q2"]

    def test_taxonomy_value_case_insensitive(self, registry):
        plan = make_plan("epic_type = FEATURE", registry)
        assert plan.variables["labelName"] == ["epic::feature"]

    def test_assignee_equality_stays_client_side(self, registry):
        # assignee matches username OR display name; assigneeUsernames
        # push-down would drop display-name matches, so none is emitted.
        plan = make_plan("assignee = alice AND assignee = bob", registry)
        assert "assigneeUsernames" not in plan.variables

    def test_author_stays_client_side(self, registry):
        plan = make_plan("author = alice", registry)
        assert "authorUsername" not in plan.variables

    def test_reporter_alias_stays_client_side(self, registry):
        plan = make_plan("reporter = alice", registry)
        assert "authorUsername" not in plan.variables

    def test_milestone_title(self, registry):
        plan = make_plan('milestone = "PI-3"', registry)
        assert plan.variables["milestoneTitle"] == ["PI-3"]

    def test_weight_pushed_as_string(self, registry):
        plan = make_plan("weight = 5", registry)
        assert plan.variables["weight"] == "5"

    def test_iid_any_list(self, registry):
        plan = make_plan("iid = 42", registry)
        assert plan.variables["iids"] == ["42"]

    def test_title_equality_pushes_substring_search(self, registry):
        plan = make_plan('title = "API Gateway"', registry)
        assert plan.variables["search"] == "API Gateway"
        assert plan.variables["in"] == ["TITLE"]

    def test_text_contains_pushes_search_in_title_and_description(self, registry):
        plan = make_plan('text ~ "rollout"', registry)
        assert plan.variables["search"] == "rollout"
        assert plan.variables["in"] == ["TITLE", "DESCRIPTION"]

    def test_second_search_stays_client_side(self, registry):
        plan = make_plan('title ~ "a" AND text ~ "b"', registry)
        assert plan.variables["search"] == "a"
        assert plan.variables["in"] == ["TITLE"]

    def test_conflicting_scalars_keep_first(self, registry):
        # Contradiction — any one conjunct's filter is a superset of {}.
        plan = make_plan("state = opened AND state = closed", registry)
        assert plan.variables["state"] == "opened"

    def test_project_has_no_server_filter(self, registry):
        plan = make_plan("project = team-a", registry)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}

    def test_currentuser_stays_client_side_like_any_person(self, registry):
        plan = make_plan("assignee = currentUser()", registry, current_user="jamie")
        assert "assigneeUsernames" not in plan.variables

    def test_business_value_never_pushes(self, registry):
        plan = make_plan("business_value = 8", registry)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}
        assert plan.needs_bv is True


class TestIdResolutionFields:
    """iterationId / parentIds take GitLab ids, not the titles/iids users
    write — equality must stay client-side (pushing raw values would change
    the result set, not just the cost)."""

    def test_iteration_equality_not_pushed(self, registry):
        plan = make_plan('sprint = "Sprint 3"', registry)
        assert "iterationId" not in plan.variables

    def test_parent_equality_not_pushed(self, registry):
        plan = make_plan("parent = 42", registry)
        assert "parentIds" not in plan.variables

    def test_iteration_wildcard_still_pushes(self, registry):
        plan = make_plan("iteration IS EMPTY", registry)
        assert plan.variables["iterationWildcardId"] == "NONE"

    def test_parent_wildcard_still_pushes(self, registry):
        plan = make_plan("parent IS NOT EMPTY", registry)
        assert plan.variables["parentWildcardId"] == "ANY"


# ---------------------------------------------------------------------------
# Date bounds
# ---------------------------------------------------------------------------

class TestDateBounds:

    def test_created_gte(self, registry):
        plan = make_plan("created >= 2026-01-01", registry)
        assert plan.variables["createdAfter"] == datetime(2026, 1, 1)

    def test_all_four_date_fields(self, registry):
        plan = make_plan(
            "created >= 2026-01-01 AND updated >= 2026-01-02 AND "
            "due <= 2026-12-01 AND closed <= 2026-12-02", registry)
        assert plan.variables["createdAfter"] == datetime(2026, 1, 1)
        assert plan.variables["updatedAfter"] == datetime(2026, 1, 2)
        assert plan.variables["dueBefore"] == datetime(2026, 12, 1)
        assert plan.variables["closedBefore"] == datetime(2026, 12, 2)

    def test_strict_lt_pushes_inclusive_superset(self, registry):
        plan = make_plan("created < 2026-03-01", registry)
        assert plan.variables["createdBefore"] == datetime(2026, 3, 1)

    def test_day_equality_becomes_day_range(self, registry):
        plan = make_plan("created = 2026-05-04", registry)
        assert plan.variables["createdAfter"] == datetime(2026, 5, 4)
        assert plan.variables["createdBefore"] == (
            datetime(2026, 5, 5) - timedelta(microseconds=1))

    def test_relative_duration_resolves_against_now(self, registry):
        plan = make_plan("updated >= -4w", registry)
        assert plan.variables["updatedAfter"] == NOW - timedelta(weeks=4)

    def test_date_function_resolves(self, registry):
        plan = make_plan("created >= startOfMonth()", registry)
        assert plan.variables["createdAfter"] == datetime(2026, 8, 1)

    def test_two_lower_bounds_keep_tightest(self, registry):
        plan = make_plan("created >= 2026-01-01 AND created >= 2026-03-01", registry)
        assert plan.variables["createdAfter"] == datetime(2026, 3, 1)

    def test_two_upper_bounds_keep_tightest(self, registry):
        plan = make_plan("created <= 2026-06-01 AND created < 2026-03-01", registry)
        assert plan.variables["createdBefore"] == datetime(2026, 3, 1)

    def test_negated_date_not_pushed_as_bound_flip(self, registry):
        # NOT (a >= x) == a < x only for non-NULL a: a NULL date satisfies
        # the negation client-side but no pushed bound matches it server-side.
        # Negated dates therefore never push, on any date field.
        plan = make_plan("NOT created >= 2026-03-01", registry)
        assert "createdBefore" not in plan.variables
        assert "createdAfter" not in plan.variables

    @pytest.mark.parametrize("query,args", [
        ("NOT due >= 2026-09-01",    ("dueAfter", "dueBefore")),
        ("NOT due < 2026-09-01",     ("dueAfter", "dueBefore")),
        ("NOT closed >= 2026-03-01", ("closedAfter", "closedBefore")),
        ("NOT closed <= 2026-03-01", ("closedAfter", "closedBefore")),
        ("NOT updated > 2026-03-01", ("updatedAfter", "updatedBefore")),
        ("NOT created != 2026-03-01", ("createdAfter", "createdBefore")),
    ])
    def test_negated_nullable_date_never_pushes(self, registry, query, args):
        plan = make_plan(query, registry)
        for arg in args:
            assert arg not in plan.variables

    def test_demorgan_negated_date_stays_client_side(self, registry):
        # NOT (due >= X OR weight = 5) distributes to NOT due >= X AND
        # NOT weight = 5 — the date half must not push a flipped bound.
        plan = make_plan("NOT (due >= 2026-09-01 OR weight = 5)", registry)
        assert "dueBefore" not in plan.variables
        assert "dueAfter" not in plan.variables
        assert plan.variables["not"] == {"weight": "5"}

    def test_date_inequality_stays_client_side(self, registry):
        plan = make_plan("created != 2026-03-01", registry)
        assert "createdAfter" not in plan.variables
        assert "createdBefore" not in plan.variables


# ---------------------------------------------------------------------------
# IS [NOT] EMPTY wildcards
# ---------------------------------------------------------------------------

class TestWildcards:

    @pytest.mark.parametrize("query,arg,value", [
        ("assignee IS EMPTY",      "assigneeWildcardId",  "NONE"),
        ("assignee IS NOT EMPTY",  "assigneeWildcardId",  "ANY"),
        ("milestone IS EMPTY",     "milestoneWildcardId", "NONE"),
        ("weight IS EMPTY",        "weightWildcardId",    "NONE"),
        ("assignee = EMPTY",       "assigneeWildcardId",  "NONE"),
        ("assignee != EMPTY",      "assigneeWildcardId",  "ANY"),
        ("NOT assignee IS EMPTY",  "assigneeWildcardId",  "ANY"),
    ])
    def test_wildcard_pushdown(self, registry, query, arg, value):
        plan = make_plan(query, registry)
        assert plan.variables[arg] == value

    def test_labels_empty_has_no_wildcard(self, registry):
        plan = make_plan("labels IS EMPTY", registry)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}

    def test_due_empty_has_no_wildcard(self, registry):
        plan = make_plan("due IS EMPTY", registry)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}

    def test_taxonomy_empty_has_no_wildcard(self, registry):
        plan = make_plan("piid IS EMPTY", registry)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}


# ---------------------------------------------------------------------------
# The not: subset
# ---------------------------------------------------------------------------

class TestNotPushdown:

    def test_not_equals_label(self, registry):
        plan = make_plan('labels != "type::defect"', registry)
        assert plan.variables["not"] == {"labelName": ["type::defect"]}

    def test_not_keyword_label(self, registry):
        plan = make_plan('NOT labels = "type::defect"', registry)
        assert plan.variables["not"] == {"labelName": ["type::defect"]}

    def test_not_author_stays_client_side(self, registry):
        plan = make_plan("author != alice", registry)
        assert "not" not in plan.variables

    def test_not_assignee_stays_client_side(self, registry):
        plan = make_plan("assignee != alice", registry)
        assert "not" not in plan.variables

    def test_not_type(self, registry):
        plan = make_plan("type != epic", registry)
        assert plan.variables["not"] == {"types": ["EPIC"]}

    def test_not_weight(self, registry):
        plan = make_plan("weight != 3", registry)
        assert plan.variables["not"] == {"weight": "3"}

    def test_not_taxonomy_resolves_canonical(self, registry):
        plan = make_plan("risk != high", registry)
        assert plan.variables["not"] == {"labelName": ["risk::high"]}

    def test_not_in_pushes_not_list(self, registry):
        # People NOT IN stays client-side (see above); labels keep the not: form.
        plan = make_plan('labels NOT IN ("risk::high", "risk::low")', registry)
        assert plan.variables["not"] == {"labelName": ["risk::high", "risk::low"]}

    def test_double_negation_pushes_positive(self, registry):
        plan = make_plan("NOT weight != 3", registry)
        assert plan.variables["weight"] == "3"
        assert "not" not in plan.variables

    def test_state_never_negated_server_side(self, registry):
        plan = make_plan("state != closed", registry)
        assert "not" not in plan.variables
        assert "state" not in plan.variables

    def test_not_title_contains_stays_client_side(self, registry):
        plan = make_plan('NOT title ~ "beta"', registry)
        assert "search" not in plan.variables
        assert "not" not in plan.variables

    def test_demorgan_not_or_distributes(self, registry):
        plan = make_plan('NOT (risk = high OR milestone = "PI-3")', registry)
        assert plan.variables["not"] == {
            "labelName": ["risk::high"], "milestoneTitle": ["PI-3"]}

    def test_negated_and_contributes_nothing(self, registry):
        plan = make_plan("NOT (assignee = alice AND author = bob)", registry)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}


# ---------------------------------------------------------------------------
# IN lists and the or: input
# ---------------------------------------------------------------------------

class TestOrPushdown:

    def test_assignee_in_uses_or_input(self, registry):
        plan = make_plan("assignee IN (alice, bob)", registry)
        assert plan.variables["or"] == {"assigneeUsernames": ["alice", "bob"]}

    def test_author_in_uses_plural_or_arg(self, registry):
        plan = make_plan("author IN (alice, bob)", registry)
        assert plan.variables["or"] == {"authorUsernames": ["alice", "bob"]}

    def test_labels_in_uses_labelnames(self, registry):
        plan = make_plan('labels IN ("risk::high", "risk::low")', registry)
        assert plan.variables["or"] == {"labelNames": ["risk::high", "risk::low"]}

    def test_taxonomy_in_resolves_canonical(self, registry):
        plan = make_plan("wsjf_urgency IN (2, 3)", registry)
        assert plan.variables["or"] == {
            "labelNames": ["wsjf-urgency::2", "wsjf-urgency::3"]}

    def test_milestone_in_uses_top_level_any_list(self, registry):
        plan = make_plan('milestone IN ("M1", "M2")', registry)
        assert plan.variables["milestoneTitle"] == ["M1", "M2"]

    def test_same_field_or_collapses_to_list(self, registry):
        plan = make_plan("assignee = alice OR assignee = bob", registry)
        assert plan.variables["or"] == {"assigneeUsernames": ["alice", "bob"]}

    def test_same_field_or_on_milestone_collapses(self, registry):
        plan = make_plan('milestone = "M1" OR milestone = "M2"', registry)
        assert plan.variables["milestoneTitle"] == ["M1", "M2"]

    def test_or_collapse_honors_aliases(self, registry):
        plan = make_plan("author = a OR reporter = b", registry)
        assert plan.variables["or"] == {"authorUsernames": ["a", "b"]}

    def test_cross_field_or_pushes_nothing(self, registry):
        plan = make_plan("assignee = alice OR author = bob", registry)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}

    def test_or_with_is_empty_operand_pushes_nothing(self, registry):
        # or: lists cannot express "or is empty" — pushing the list would
        # drop the EMPTY-matching items from the envelope.
        plan = make_plan("assignee = alice OR assignee IS EMPTY", registry)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}

    def test_in_list_with_empty_value_pushes_nothing(self, registry):
        plan = make_plan("assignee IN (alice, EMPTY)", registry)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}

    def test_or_conjunct_inside_and_still_pushes_other_conjunct(self, registry):
        plan = make_plan(
            "state = opened AND (assignee = alice OR author = bob)", registry)
        assert plan.variables["state"] == "opened"

    def test_two_in_conjuncts_same_field_keep_first(self, registry):
        plan = make_plan(
            "assignee IN (alice, bob) AND assignee IN (bob, carol)", registry)
        assert plan.variables["or"] == {"assigneeUsernames": ["alice", "bob"]}

    def test_weight_in_stays_client_side(self, registry):
        plan = make_plan("weight IN (3, 5)", registry)
        assert plan.variables == {"types": list(ENTITY_SCOPE_TYPES)}


# ---------------------------------------------------------------------------
# Numeric comparisons never push
# ---------------------------------------------------------------------------

class TestNumericComparisons:

    def test_weight_gte_stays_client_side(self, registry):
        plan = make_plan("weight >= 5", registry)
        assert "weight" not in plan.variables

    def test_taxonomy_comparison_stays_client_side(self, registry):
        plan = make_plan("wsjf_urgency > 2", registry)
        assert "labelName" not in plan.variables
        assert "or" not in plan.variables


# ---------------------------------------------------------------------------
# ORDER BY
# ---------------------------------------------------------------------------

class TestOrderBy:

    def test_single_supported_key_pushes_sort(self, registry):
        plan = make_plan("state = opened ORDER BY due ASC", registry)
        assert plan.sort == "DUE_DATE_ASC"
        assert plan.variables["sort"] == "DUE_DATE_ASC"
        assert plan.client_sort == ()

    def test_desc_direction(self, registry):
        plan = make_plan("ORDER BY updated DESC", registry)
        assert plan.sort == "UPDATED_DESC"

    def test_milestone_sorts_by_due_date_enum(self, registry):
        plan = make_plan("ORDER BY milestone ASC", registry)
        assert plan.sort == "MILESTONE_DUE_ASC"

    def test_multi_key_falls_back_to_client_sort(self, registry):
        plan = make_plan("ORDER BY due ASC, weight DESC", registry)
        assert plan.sort is None
        assert "sort" not in plan.variables
        assert [k.field for k in plan.client_sort] == ["due", "weight"]

    def test_unsupported_key_falls_back_to_client_sort(self, registry):
        plan = make_plan("ORDER BY business_value DESC", registry)
        assert plan.sort is None
        assert [k.field for k in plan.client_sort] == ["business_value"]
        assert plan.needs_bv is True

    def test_taxonomy_key_falls_back_to_client_sort(self, registry):
        plan = make_plan("ORDER BY piid ASC", registry)
        assert plan.sort is None
        assert [k.field for k in plan.client_sort] == ["piid"]

    def test_full_scan_never_pushes_sort(self, registry):
        plan = make_plan("ORDER BY due ASC", registry, push_down=False)
        assert plan.sort is None
        assert [k.field for k in plan.client_sort] == ["due"]

    def test_unknown_sort_field_raises(self, registry):
        with pytest.raises(UnknownFieldError):
            make_plan("ORDER BY nonsense ASC", registry)


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

class TestValidation:

    def test_unknown_field(self, registry):
        with pytest.raises(UnknownFieldError):
            make_plan("frobnicate = 1", registry)

    def test_unknown_enum_value(self, registry):
        with pytest.raises(UnknownFieldValueError):
            make_plan("state = open", registry)

    def test_unknown_taxonomy_value(self, registry):
        with pytest.raises(UnknownFieldValueError):
            make_plan("piid = 2031Q9", registry)

    def test_unknown_taxonomy_value_inside_in(self, registry):
        with pytest.raises(UnknownFieldValueError):
            make_plan("risk IN (high, bogus)", registry)

    def test_ordering_op_on_text_field(self, registry):
        with pytest.raises(JqlPlanError):
            make_plan('title > "a"', registry)

    def test_contains_op_on_number_field(self, registry):
        with pytest.raises(JqlPlanError):
            make_plan("weight ~ 5", registry)

    def test_contains_op_on_date_field(self, registry):
        with pytest.raises(JqlPlanError):
            make_plan("created ~ 2026-01-01", registry)

    def test_is_empty_on_state(self, registry):
        with pytest.raises(JqlPlanError):
            make_plan("state IS EMPTY", registry)

    def test_empty_with_ordering_op(self, registry):
        with pytest.raises(JqlPlanError):
            make_plan("weight > EMPTY", registry)

    def test_non_numeric_weight_value(self, registry):
        with pytest.raises(JqlPlanError):
            make_plan("weight = heavy", registry)

    def test_bad_date_value(self, registry):
        with pytest.raises(JqlPlanError):
            make_plan("created >= notadate", registry)

    def test_unknown_function(self, registry):
        with pytest.raises(JqlPlanError):
            make_plan("assignee = membersOf(admins)", registry)

    def test_currentuser_unresolved_raises(self, registry):
        with pytest.raises(JqlPlanError):
            make_plan("assignee = currentUser()", registry, current_user=None)

    def test_taxonomy_ordering_accepts_numbers_outside_vocab(self, registry):
        plan = make_plan("wsjf_urgency > 2.5", registry)
        assert plan.expr is not None

    def test_taxonomy_substring_accepts_non_vocabulary_rhs(self, registry):
        # '~' matches substrings of taxonomy values (piid ~ "2026") — the RHS
        # is a search needle, not a vocabulary member, and stays client-side.
        plan = make_plan('piid ~ "2026"', registry)
        assert plan.expr is not None
        assert "labelName" not in plan.variables
        assert "search" not in plan.variables

    def test_taxonomy_negated_substring_accepts_non_vocabulary_rhs(self, registry):
        plan = make_plan('epic_type !~ "cap"', registry)
        assert plan.expr is not None
        assert "labelName" not in plan.variables

    def test_taxonomy_ordering_rejects_non_numeric_outside_vocab(self, registry):
        with pytest.raises(UnknownFieldValueError):
            make_plan("wsjf_urgency > banana", registry)

    def test_validation_runs_even_without_pushdown(self, registry):
        with pytest.raises(UnknownFieldValueError):
            make_plan("state = open", registry, push_down=False)

    def test_validation_reaches_or_branches(self, registry):
        with pytest.raises(UnknownFieldError):
            make_plan("state = opened OR frobnicate = 1", registry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:

    def test_query_mentions_current_user_true(self, registry):
        assert query_mentions_current_user(parse("assignee = currentUser()"))

    def test_query_mentions_current_user_in_list(self, registry):
        assert query_mentions_current_user(parse("assignee IN (currentUser(), bob)"))

    def test_query_mentions_current_user_false(self, registry):
        assert not query_mentions_current_user(parse("assignee = alice"))

    def test_query_mentions_current_user_empty_query(self, registry):
        assert not query_mentions_current_user(parse(""))

    def test_is_day_granular(self):
        assert is_day_granular(ast.DateLiteral(value="2026-01-31"))
        assert is_day_granular(ast.String(value="2026-01-31", quoted=True))
        assert not is_day_granular(ast.String(value="2026-01-31 10:00", quoted=True))
        assert not is_day_granular(ast.Duration(value="-4w"))

    def test_resolve_scalar_duration_on_date_field(self, registry):
        spec = registry.resolve("created")
        assert resolve_scalar(ast.Duration(value="-1d"), spec, NOW) == NOW - timedelta(days=1)

    def test_needs_description_flag(self, registry):
        assert make_plan('text ~ "x"', registry).needs_description is True
        assert make_plan('title ~ "x"', registry).needs_description is False

    def test_needs_bv_flag_from_predicate(self, registry):
        assert make_plan("business_value >= 8", registry).needs_bv is True
        assert make_plan("weight >= 8", registry).needs_bv is False
