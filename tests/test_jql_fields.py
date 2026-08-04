"""Unit tests for the JQL field registry (jql/fields.py, issue #299).

Covers alias resolution, taxonomy-driven virtual field generation from a
fixture config, and the per-field push-down capability declarations asserted
against a checked-in introspection fixture of the GraphQL filter args
(tests/fixtures/gitlab_filter_args.json, captured from gitlab.com).
"""
import json
from pathlib import Path

import pytest

from jql.fields import (
    CORE_FIELDS,
    JIRA_ALIASES,
    FieldRegistry,
    FieldSpec,
    UnknownFieldError,
    UnknownFieldValueError,
)

pytestmark = pytest.mark.unit

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "gitlab_filter_args.json"

# Mirrors the config.example.json taxonomy shapes (scoped labels + the
# wsjf dict) plus the README variant of an *unscoped* epic_type taxonomy.
FIXTURE_CONFIG = {
    "business_value_field": {
        "name": "Business Value",
        "field_type": "SINGLE_SELECT",
        "select_options": ["1", "2", "3", "5", "8", "13", "21"],
    },
    "project_labels": ["project::DO", "project::RTSO", "project::DCGS"],
    "piid_labels": ["PIID::2026Q2", "PIID::2026Q3", "PIID::2026Q4"],
    "epic_type_labels": ["epic::epic", "epic::capability", "epic::feature"],
    "risk_labels": ["risk::high", "risk::medium", "risk::low"],
    "roam_labels": ["roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"],
    "work_type_labels": ["type::feature", "type::enabler", "type::infrastructure", "type::defect"],
    "lifecycle_labels": ["lifecycle::funnel", "lifecycle::analyzing", "lifecycle::backlog",
                         "lifecycle::implementing", "lifecycle::done"],
    "wsjf_labels": {
        "urgency": ["wsjf-urgency::1", "wsjf-urgency::2", "wsjf-urgency::3"],
        "risk":    ["wsjf-risk::1", "wsjf-risk::2", "wsjf-risk::3"],
    },
}


@pytest.fixture(scope="module")
def registry():
    return FieldRegistry.from_config(FIXTURE_CONFIG)


@pytest.fixture(scope="module")
def gl_args():
    with open(FIXTURE_PATH) as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Core vocabulary and alias resolution
# ---------------------------------------------------------------------------

class TestResolution:

    def test_core_fields_present(self, registry):
        for name in ("state", "type", "title", "text", "assignee", "author",
                     "labels", "milestone", "iteration", "weight", "created",
                     "updated", "due", "closed", "parent", "iid", "project"):
            assert registry.resolve(name).name == name
            assert name in registry

    @pytest.mark.parametrize("alias,canonical", [
        ("status", "state"),
        ("issuetype", "type"),
        ("sprint", "iteration"),
        ("reporter", "author"),
        ("summary", "title"),
    ])
    def test_jira_alias_resolution(self, registry, alias, canonical):
        assert registry.resolve(alias).name == canonical
        assert JIRA_ALIASES[alias] == canonical

    def test_resolution_is_case_insensitive(self, registry):
        assert registry.resolve("Status").name == "state"
        assert registry.resolve("ISSUETYPE").name == "type"
        assert registry.resolve("  Weight ").name == "weight"

    def test_aliases_do_not_appear_in_vocabulary(self, registry):
        assert "status" not in registry.vocabulary
        assert registry.aliases["status"] == "state"

    def test_unknown_field_error_lists_vocabulary(self, registry):
        with pytest.raises(UnknownFieldError) as exc:
            registry.resolve("frobnitz")
        assert exc.value.name == "frobnitz"
        assert exc.value.vocabulary == registry.vocabulary
        msg = str(exc.value)
        for expected in ("frobnitz", "state", "piid", "business_value", "status -> state"):
            assert expected in msg

    def test_registry_iteration_sorted_and_sized(self, registry):
        names = [spec.name for spec in registry]
        assert names == sorted(names)
        assert len(registry) == len(names)
        assert "nope" not in registry


# ---------------------------------------------------------------------------
# Taxonomy-driven virtual fields
# ---------------------------------------------------------------------------

class TestTaxonomyFields:

    @pytest.mark.parametrize("name,prefix", [
        ("piid", "PIID"),
        ("epic_type", "epic"),
        ("risk", "risk"),
        ("roam", "roam"),
        ("work_type", "type"),
        ("lifecycle", "lifecycle"),
        ("wsjf_urgency", "wsjf-urgency"),
        ("wsjf_risk", "wsjf-risk"),
    ])
    def test_virtual_fields_generated(self, registry, name, prefix):
        spec = registry.resolve(name)
        assert spec.kind == "label"
        assert spec.label_prefix == prefix
        # Same push-down surface as raw labels: labelName AND-list + not: + or:
        assert spec.graphql_arg == "labelName"
        assert spec.arg_is_list
        assert spec.supports_not
        assert spec.or_arg == "labelNames"
        assert spec.comparisons == "equality"
        assert not spec.supports_empty_wildcard

    def test_value_resolves_to_scoped_label(self, registry):
        assert registry.resolve("piid").label_for("2026Q2") == "PIID::2026Q2"
        assert registry.resolve("epic_type").label_for("feature") == "epic::feature"
        assert registry.resolve("wsjf_urgency").label_for("3") == "wsjf-urgency::3"

    def test_value_resolution_is_case_insensitive(self, registry):
        assert registry.resolve("piid").label_for("2026q2") == "PIID::2026Q2"
        assert registry.resolve("roam").label_for("OWNED") == "roam::owned"

    def test_full_label_accepted_as_value(self, registry):
        assert registry.resolve("piid").label_for("PIID::2026Q2") == "PIID::2026Q2"
        assert registry.resolve("piid").label_for("piid::2026q2") == "PIID::2026Q2"

    def test_unknown_value_error_lists_valid_values(self, registry):
        with pytest.raises(UnknownFieldValueError) as exc:
            registry.resolve("piid").label_for("PI-99")
        assert exc.value.field_name == "piid"
        assert exc.value.valid_values == ("2026Q2", "2026Q3", "2026Q4")
        assert "2026Q3" in str(exc.value)

    def test_unscoped_taxonomy_uses_label_as_value(self):
        # README documents epic_type_labels as plain names too.
        registry = FieldRegistry.from_config(
            {"epic_type_labels": ["Epic", "Capability", "Feature"]})
        spec = registry.resolve("epic_type")
        assert spec.label_prefix is None
        assert spec.values == ("Epic", "Capability", "Feature")
        assert spec.label_for("capability") == "Capability"

    def test_project_taxonomy_renamed_not_shadowing_core_field(self, registry):
        # config 'project_labels' would derive 'project', colliding with the
        # core project field — it gets the '_label' suffix instead.
        spec = registry.resolve("project_label")
        assert spec.kind == "label"
        assert spec.label_for("do") == "project::DO"
        assert registry.resolve("project").kind == "core"
        assert registry.resolve("project").post_filter_only

    def test_label_for_rejected_on_non_label_fields(self, registry):
        with pytest.raises(TypeError):
            registry.resolve("state").label_for("opened")

    def test_empty_config_still_has_core_vocabulary(self):
        registry = FieldRegistry.from_config({})
        assert registry.resolve("state").name == "state"
        assert "piid" not in registry
        # business_value is always present, with the default field name.
        assert registry.resolve("business_value").custom_field_name == "Business Value"


# ---------------------------------------------------------------------------
# business_value — declared post-filter-only
# ---------------------------------------------------------------------------

class TestBusinessValue:

    def test_post_filter_only(self, registry):
        spec = registry.resolve("business_value")
        assert spec.kind == "custom"
        assert spec.value_type == "number"
        assert spec.post_filter_only
        assert not spec.push_down
        assert spec.sort_prefix is None

    def test_custom_field_name_comes_from_config(self):
        registry = FieldRegistry.from_config(
            {"business_value_field": {"name": "BV Points"}})
        assert registry.resolve("business_value").custom_field_name == "BV Points"

    def test_customfield_filter_is_select_option_only(self, gl_args):
        # The reason BV cannot push down: the customField filter input offers
        # only select-option matching — no numeric comparison fields.
        cf = gl_args["Group.workItems.customField"]
        assert set(cf) == {"customFieldId", "customFieldName",
                           "selectedOptionIds", "selectedOptionValues"}


# ---------------------------------------------------------------------------
# Capability declarations vs. the introspection fixture
# ---------------------------------------------------------------------------

class TestCapabilitiesAgainstIntrospection:

    def test_equality_args_exist_on_group_work_items(self, registry, gl_args):
        args = gl_args["Group.workItems"]
        for spec in registry:
            if spec.graphql_arg:
                assert spec.graphql_arg in args, (
                    f"{spec.name}: '{spec.graphql_arg}' is not a Group.workItems argument")

    def test_list_declarations_match_arg_types(self, registry, gl_args):
        args = gl_args["Group.workItems"]
        for spec in registry:
            if spec.graphql_arg and spec.graphql_arg != "search":
                is_list = args[spec.graphql_arg].startswith("[")
                assert spec.arg_is_list == is_list, (
                    f"{spec.name}: arg_is_list={spec.arg_is_list} but "
                    f"{spec.graphql_arg} is {args[spec.graphql_arg]}")

    def test_date_bound_args_exist(self, registry, gl_args):
        args = gl_args["Group.workItems"]
        for spec in registry:
            if spec.date_bound_args:
                after, before = spec.date_bound_args
                assert args.get(after) == "Time", f"{spec.name}: {after}"
                assert args.get(before) == "Time", f"{spec.name}: {before}"

    def test_only_date_fields_declare_comparison_support(self, registry):
        for spec in registry:
            if spec.comparisons == "date_bounds":
                assert spec.value_type == "date"
            else:
                assert spec.comparisons == "equality"

    def test_wildcard_args_offer_none_and_any(self, registry, gl_args):
        args = gl_args["Group.workItems"]
        for spec in registry:
            if spec.wildcard_arg:
                enum_name = args.get(spec.wildcard_arg)
                assert enum_name, f"{spec.name}: '{spec.wildcard_arg}' not an argument"
                enum_values = gl_args.get(f"enum.{enum_name}")
                assert enum_values, f"{spec.name}: enum {enum_name} missing from fixture"
                assert {"NONE", "ANY"} <= set(enum_values), (
                    f"{spec.name}: {enum_name} lacks NONE/ANY")

    def test_not_support_matches_negated_input(self, registry, gl_args):
        negatable = set(gl_args["Group.workItems.not"])
        for spec in registry:
            if spec.graphql_arg is None:
                assert not spec.supports_not
            elif spec.supports_not:
                assert spec.graphql_arg in negatable, (
                    f"{spec.name}: not: has no '{spec.graphql_arg}'")
            else:
                assert spec.graphql_arg not in negatable, (
                    f"{spec.name}: not: DOES accept '{spec.graphql_arg}' — declare it")

    def test_or_support_matches_unioned_input(self, registry, gl_args):
        unioned = set(gl_args["Group.workItems.or"])
        for spec in registry:
            if spec.or_arg:
                assert spec.or_arg in unioned, (
                    f"{spec.name}: or: has no '{spec.or_arg}'")

    def test_search_scopes_are_valid(self, registry, gl_args):
        searchable = set(gl_args["enum.IssuableSearchableField"])
        for spec in registry:
            assert set(spec.search_in) <= searchable
            if spec.graphql_arg == "search":
                assert spec.search_in, f"{spec.name}: search push-down needs in: scopes"

    def test_sort_prefixes_exist_in_sort_enum(self, registry, gl_args):
        sort_values = set(gl_args["Group.workItems.sort"])
        for spec in registry:
            if spec.sort_prefix:
                assert f"{spec.sort_prefix}_ASC" in sort_values, spec.name
                assert f"{spec.sort_prefix}_DESC" in sort_values, spec.name

    def test_state_values_match_issuable_state_enum(self, registry, gl_args):
        spec = registry.resolve("state")
        assert set(spec.values) == set(gl_args["enum.IssuableState"])

    def test_type_values_match_issue_type_enum(self, registry, gl_args):
        spec = registry.resolve("type")
        assert {v.upper() for v in spec.values} == set(gl_args["enum.IssueType"])

    def test_capability_args_also_exist_on_project_issues(self, registry, gl_args):
        # Project.issues shares every declared argument name except the
        # parent-hierarchy filters (epicId/epicWildcardId there).
        args = set(gl_args["Project.issues"])
        for spec in registry:
            if spec.name == "parent":
                continue
            if spec.graphql_arg:
                assert spec.graphql_arg in args, f"{spec.name}: {spec.graphql_arg}"
            if spec.date_bound_args:
                assert set(spec.date_bound_args) <= args, spec.name

    def test_weight_is_equality_only(self, registry):
        spec = registry.resolve("weight")
        assert spec.comparisons == "equality"
        assert spec.supports_empty_wildcard
        assert spec.supports_not

    def test_iid_and_state_have_no_negation(self, registry):
        assert not registry.resolve("iid").supports_not
        assert not registry.resolve("state").supports_not


# ---------------------------------------------------------------------------
# Registry construction guards
# ---------------------------------------------------------------------------

class TestConstructionGuards:

    def test_duplicate_field_name_rejected(self):
        spec = FieldSpec(name="state", kind="core", value_type="enum")
        with pytest.raises(ValueError, match="Duplicate field name"):
            FieldRegistry(list(CORE_FIELDS) + [spec])

    def test_duplicate_alias_rejected(self):
        spec = FieldSpec(name="my_status", kind="core", value_type="enum",
                         aliases=("status",))
        with pytest.raises(ValueError, match="Duplicate field alias"):
            FieldRegistry(list(CORE_FIELDS) + [spec])
