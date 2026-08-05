"""Golden-query parity tests for the live JQL executor (issue #300).

The epic's core contract: the planner's push-down may only change *cost*,
never *results*. For every query in the golden fixture set, the planned run
(push-down + post-filter) must return the identical result set to a
full-scan run (post-filter only) over the same populated hierarchy.

The hierarchy is served by a fake GitLab GraphQL backend that implements
``Group.workItems`` filter semantics as declared by the field registry and
validates every request against the checked-in introspection fixture
(tests/fixtures/gitlab_filter_args.json) — an invalid argument name, enum
value, or ``not:``/``or:`` key raises instead of being silently ignored.

Plus targeted tests for pagination boundaries, result caps, early
termination, and ORDER BY stability through the full run_jql path.
"""
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from jql.executor import JqlExecutionError, parse_ts
from mixins.query import QueryMixin

pytestmark = pytest.mark.integration

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "gitlab_filter_args.json"
with open(FIXTURE_PATH) as fh:
    GL_ARGS = json.load(fh)

NOW = datetime(2026, 8, 1, 12, 0, 0)
BV_GID = "gid://gitlab/Issuables::CustomField/7"
GROUP_PATH = "portfolio"

#: run_jql request variable name -> GraphQL argument name.
_VAR_TO_ARG = {"searchIn": "in", "negated": "not", "unioned": "or"}

#: Non-filter arguments the fake accepts alongside the fixture's list.
_TRANSPORT_ARGS = {"fullPath"}


# ---------------------------------------------------------------------------
# Work-item fixture builder (GraphQL node shape + plain meta for the fake)
# ---------------------------------------------------------------------------

def wi(iid, type="Issue", title="", state="OPEN", labels=(), assignees=(),
       author="alice", milestone=None, milestone_due=None, iteration=None,
       weight=None, created="2026-01-10T00:00:00Z",
       updated="2026-07-01T00:00:00Z", closed=None, due=None, start=None,
       parent_iid=None, path="portfolio/team-a", bv=None, description=""):
    node = {
        "id": "gid://gitlab/WorkItem/%d" % (1000 + iid),
        "iid": str(iid),
        "title": title or "Work item %d" % iid,
        "state": state,
        "webUrl": "https://gitlab.example/%s/-/work_items/%d" % (path, iid),
        "createdAt": created,
        "updatedAt": updated,
        "closedAt": closed,
        "workItemType": {"name": type},
        "author": {"username": author},
        "namespace": {"fullPath": path},
        "widgets": [
            {"labels": {"nodes": [{"title": l} for l in labels]}},
            {"assignees": {"nodes": [{"username": u} for u in assignees]}},
            {"milestone": {"title": milestone, "dueDate": milestone_due}
             if milestone else None},
            {"iteration": {"id": "gid://gitlab/Iteration/%d" % iid,
                           "title": iteration} if iteration else None},
            {"weight": weight},
            {"startDate": start, "dueDate": due},
            {"parent": {"iid": str(parent_iid)} if parent_iid else None},
            {"description": description},
            {"customFieldValues": [
                {"customField": {"id": BV_GID, "name": "Business Value"},
                 "selectedOptions": [{"id": "o", "value": str(bv)}]},
            ] if bv is not None else []},
        ],
    }
    meta = {
        "iid": iid, "type": type, "title": node["title"], "state": state,
        "labels": list(labels), "assignees": list(assignees), "author": author,
        "milestone": milestone, "milestone_due": milestone_due,
        "iteration": iteration, "weight": weight, "created": created,
        "updated": updated, "closed": closed, "due": due, "start": start,
        "parent_iid": parent_iid, "path": path, "bv": bv,
        "description": description,
    }
    # Normalize widget list: GitLab returns {} for widgets a type lacks.
    node["widgets"] = [w if w and list(w.values()) != [None] else {}
                       for w in node["widgets"]]
    return {"meta": meta, "node": node}


# The golden hierarchy: epics + issues with deliberate edge cases — empty
# assignees, missing weights/dues/milestones, closed items, scoped labels,
# out-of-vocabulary PIID labels, BV set/unset, multi-assignee, currentUser.
ITEMS = [
    wi(1, type="Epic", title="Payments capability", state="OPEN",
       labels=["epic::capability", "PIID::2026Q2", "wsjf-urgency::3"],
       weight=8, created="2026-01-05T09:00:00Z", updated="2026-07-20T00:00:00Z",
       due="2026-12-01", start="2026-02-01", bv=13, path="portfolio"),
    wi(2, type="Epic", title="Gateway feature epic", state="OPEN",
       labels=["epic::feature", "PIID::2026Q2", "wsjf-urgency::1", "risk::high"],
       weight=3, created="2026-02-10T12:00:00Z", updated="2026-07-28T00:00:00Z",
       due="2026-10-15", bv=8, parent_iid=1, path="portfolio"),
    wi(3, type="Epic", title="Reporting epic", state="CLOSED",
       labels=["epic::epic", "PIID::2026Q3"],
       weight=5, created="2025-11-01T08:00:00Z", updated="2026-03-01T00:00:00Z",
       closed="2026-02-15T10:00:00Z", bv=3, path="portfolio"),
    wi(4, type="Epic", title="Unlabeled epic", state="OPEN",
       labels=["PIID::2031Q9"],       # PIID outside the configured vocabulary
       created="2026-06-01T00:00:00Z", updated="2026-07-30T00:00:00Z",
       path="portfolio"),
    wi(11, title="Implement payment gateway API", state="OPEN",
       labels=["type::feature", "risk::high"], assignees=["alice"],
       author="bob", milestone="M1", milestone_due="2026-09-30",
       weight=5, created="2026-03-01T10:00:00Z", updated="2026-07-25T00:00:00Z",
       due="2026-09-01", parent_iid=2, bv=8,
       description="Phased rollout behind a feature flag"),
    wi(12, title="Fix gateway timeout defect", state="OPEN",
       labels=["type::defect", "risk::medium"], assignees=["bob", "carol"],
       author="alice", milestone="M1", milestone_due="2026-09-30",
       weight=2, created="2026-04-15T09:30:00Z", updated="2026-07-10T00:00:00Z",
       due="2026-08-20", iteration="Sprint 3", parent_iid=2),
    wi(13, title="Reporting dashboard widgets", state="CLOSED",
       labels=["type::feature"], assignees=["carol"],
       author="carol", milestone="M2", milestone_due="2026-06-30",
       weight=8, created="2025-12-01T00:00:00Z", updated="2026-02-20T00:00:00Z",
       closed="2026-02-20T11:00:00Z", due="2026-02-01", parent_iid=3, bv=5),
    wi(14, title="Unassigned backlog item", state="OPEN",
       labels=[], assignees=[], author="dave",
       created="2026-05-20T14:00:00Z", updated="2026-05-21T00:00:00Z",
       path="portfolio/team-b"),
    wi(15, title="Jamie's spike on search", state="OPEN",
       labels=["type::enabler"], assignees=["jamie"], author="jamie",
       weight=1, created="2026-07-01T00:00:00Z", updated="2026-07-31T00:00:00Z",
       iteration="Sprint 3", path="portfolio/team-b",
       description="Investigate JQL semantics"),
    wi(16, title="Zero-weight chore", state="OPEN",
       labels=["type::defect"], assignees=["alice", "jamie"], author="bob",
       weight=0, created="2026-06-15T00:00:00Z", updated="2026-06-16T00:00:00Z",
       due="2026-08-05", bv=1, path="portfolio/team-b"),
    # Task exists in the data but sits outside the v1 entity scope.
    wi(17, type="Task", title="Out-of-scope task", state="OPEN",
       labels=["risk::high"], assignees=["alice"], weight=9,
       created="2026-06-01T00:00:00Z", updated="2026-06-02T00:00:00Z"),
]


# ---------------------------------------------------------------------------
# Fake GitLab GraphQL backend
# ---------------------------------------------------------------------------

class FakeGitLabBackend:
    """Implements Group.workItems filtering exactly as the field registry
    declares GitLab's semantics, with cursor pagination and strict
    validation of every request against the introspection fixture."""

    def __init__(self, items=ITEMS, page_size=100):
        self.items = items
        self.page_size = page_size
        self.calls = []

    # -- entry point (mirrors UtilitiesMixin.graphql_query) ---------------

    def __call__(self, query, variables=None, retries=0):
        if "currentUser" in query and "workItems" not in query:
            return {"currentUser": {"username": "jamie"}}
        variables = dict(variables or {})
        args = {_VAR_TO_ARG.get(k, k): v for k, v in variables.items()}
        self.calls.append(args)
        self._validate(args)
        if args.get("fullPath") != GROUP_PATH:
            return {"group": None}

        matched = [e for e in self.items if self._match(e["meta"], args)]
        matched = self._sort(matched, args.get("sort"))

        start = int(args.get("after") or 0)
        size = min(self.page_size, args.get("first") or 100)
        page = matched[start:start + size]
        return {"group": {"workItems": {
            "pageInfo": {
                "hasNextPage": start + size < len(matched),
                "endCursor": str(start + size),
            },
            "nodes": [copy.deepcopy(e["node"]) for e in page],
        }}}

    # -- request validation ------------------------------------------------

    def _validate(self, args):
        valid = set(GL_ARGS["Group.workItems"]) | _TRANSPORT_ARGS
        # Rails finders skip blank params: an empty list filter would apply
        # NO filter at all (not "match nothing"), so the client must never
        # send one — a provably-empty plan must short-circuit instead.
        for key, value in args.items():
            if isinstance(value, list):
                assert value, "blank list filter would be skipped by Rails: %s" % key
            elif isinstance(value, dict):
                for sub, v in value.items():
                    if isinstance(v, list):
                        assert v, ("blank list filter would be skipped by "
                                   "Rails: %s.%s" % (key, sub))
        for key, value in args.items():
            assert key in valid, "invalid Group.workItems argument: %s" % key
            if key == "state":
                assert value in GL_ARGS["enum.IssuableState"], value
            elif key == "types":
                assert set(value) <= set(GL_ARGS["enum.IssueType"]), value
            elif key == "in":
                assert set(value) <= set(GL_ARGS["enum.IssuableSearchableField"]), value
            elif key == "sort":
                assert value in GL_ARGS["Group.workItems.sort"], value
            elif key.endswith("WildcardId"):
                enum = "enum.%s" % GL_ARGS["Group.workItems"][key]
                assert value in GL_ARGS[enum], value
            elif key == "not":
                assert set(value) <= set(GL_ARGS["Group.workItems.not"]), value
            elif key == "or":
                assert set(value) <= set(GL_ARGS["Group.workItems.or"]), value

    # -- filter semantics --------------------------------------------------

    @staticmethod
    def _fold(v):
        return str(v).casefold()

    def _match(self, m, args):
        for key, value in args.items():
            if key in _TRANSPORT_ARGS | {"first", "after", "sort", "in"}:
                continue
            if key == "search":
                if not self._match_search(m, value, args.get("in")):
                    return False
            elif key == "not":
                if any(self._match_arg(m, k, v) for k, v in value.items()):
                    return False
            elif key == "or":
                if not all(self._match_or(m, k, v) for k, v in value.items()):
                    return False
            elif not self._match_arg(m, key, value):
                return False
        return True

    def _match_arg(self, m, key, value):
        fold = self._fold
        if key == "state":
            if value == "all":
                return True
            return {"opened": "OPEN", "closed": "CLOSED"}.get(value) == m["state"]
        if key == "types":
            return m["type"].upper().replace(" ", "_") in value
        if key == "labelName":
            labels = [fold(l) for l in m["labels"]]
            return all(fold(v) in labels for v in value)
        if key == "authorUsername":
            vals = value if isinstance(value, list) else [value]
            return fold(m["author"]) in [fold(v) for v in vals]
        if key == "assigneeUsernames":
            have = [fold(a) for a in m["assignees"]]
            return all(fold(v) in have for v in value)
        if key == "milestoneTitle":
            return m["milestone"] is not None and \
                fold(m["milestone"]) in [fold(v) for v in value]
        if key == "weight":
            return m["weight"] is not None and str(m["weight"]) == str(value)
        if key == "iids":
            return str(m["iid"]) in [str(v) for v in value]
        if key.endswith(("After", "Before")):
            return self._match_date(m, key, value)
        if key == "assigneeWildcardId":
            return bool(m["assignees"]) == (value == "ANY")
        if key == "milestoneWildcardId":
            return (m["milestone"] is not None) == (value == "ANY")
        if key == "weightWildcardId":
            return (m["weight"] is not None) == (value == "ANY")
        if key == "iterationWildcardId":
            return (m["iteration"] is not None) == (value == "ANY")
        if key == "parentWildcardId":
            return (m["parent_iid"] is not None) == (value == "ANY")
        raise AssertionError("fake backend has no semantics for %r" % key)

    def _match_search(self, m, needle, scopes):
        needle = self._fold(needle)
        scopes = scopes or ["TITLE", "DESCRIPTION"]
        hay = ""
        if "TITLE" in scopes:
            hay += self._fold(m["title"]) + "\n"
        if "DESCRIPTION" in scopes:
            hay += self._fold(m["description"] or "")
        return needle in hay

    def _match_or(self, m, key, value):
        fold = self._fold
        if key == "assigneeUsernames":
            have = [fold(a) for a in m["assignees"]]
            return any(fold(v) in have for v in value)
        if key == "authorUsernames":
            return fold(m["author"]) in [fold(v) for v in value]
        if key == "labelNames":
            labels = [fold(l) for l in m["labels"]]
            return any(fold(v) in labels for v in value)
        raise AssertionError("fake backend has no or: semantics for %r" % key)

    def _match_date(self, m, key, value):
        field = key.replace("After", "").replace("Before", "")
        ts = parse_ts(m[field])
        if ts is None:
            return False
        bound = parse_ts(value)
        return ts >= bound if key.endswith("After") else ts <= bound

    # -- server-side sort --------------------------------------------------

    _SORT_KEYS = {
        "CREATED": lambda m: parse_ts(m["created"]),
        "UPDATED": lambda m: parse_ts(m["updated"]),
        "CLOSED_AT": lambda m: parse_ts(m["closed"]),
        "DUE_DATE": lambda m: parse_ts(m["due"]),
        "START_DATE": lambda m: parse_ts(m["start"]),
        "TITLE": lambda m: str(m["title"]).casefold(),
        "WEIGHT": lambda m: m["weight"],
        "MILESTONE_DUE": lambda m: parse_ts(m["milestone_due"]),
    }

    def _sort(self, matched, sort):
        if not sort:
            return matched
        assert sort in GL_ARGS["Group.workItems.sort"], sort
        prefix, direction = sort.rsplit("_", 1)
        keyfunc = self._SORT_KEYS.get(prefix)
        assert keyfunc is not None, "fake backend cannot sort by %s" % prefix
        desc = direction == "DESC"
        present = [e for e in matched if keyfunc(e["meta"]) is not None]
        missing = [e for e in matched if keyfunc(e["meta"]) is None]
        present.sort(key=lambda e: keyfunc(e["meta"]), reverse=desc)
        return present + missing


# ---------------------------------------------------------------------------
# QueryMixin harness
# ---------------------------------------------------------------------------

class QueryHarness(QueryMixin):
    parent_group = "Portfolio"
    config_file = None
    BUSINESS_VALUE_FIELD = {"name": "Business Value"}
    PIID_LABELS = ["PIID::2026Q2", "PIID::2026Q3", "PIID::2026Q4"]
    EPIC_TYPE_LABELS = ["epic::epic", "epic::capability", "epic::feature"]
    RISK_LABELS = ["risk::high", "risk::medium", "risk::low"]
    WORK_TYPE_LABELS = ["type::feature", "type::enabler",
                        "type::infrastructure", "type::defect"]
    WSJF_URGENCY_LABELS = ["wsjf-urgency::1", "wsjf-urgency::2", "wsjf-urgency::3"]
    WSJF_RISK_LABELS = ["wsjf-risk::1", "wsjf-risk::2", "wsjf-risk::3"]

    def __init__(self, backend=None):
        self.backend = backend or FakeGitLabBackend()
        self.gl = SimpleNamespace(user=SimpleNamespace(username="jamie"))

    def graphql_query(self, query, variables=None, retries=0):
        return self.backend(query, variables=variables, retries=retries)

    def get_group_by_name(self, name):
        assert name == self.parent_group
        return SimpleNamespace(full_path=GROUP_PATH)

    def _find_bv_field(self, group=None):
        assert group == GROUP_PATH
        return {"id": BV_GID, "name": "Business Value"}


@pytest.fixture()
def harness():
    return QueryHarness()


def ids(result):
    return sorted(i["iid"] for i in result["items"])


# ---------------------------------------------------------------------------
# Golden-query parity: planned run == full-scan run, always
# ---------------------------------------------------------------------------

GOLDEN_QUERIES = [
    "",
    "state = opened",
    "state = closed",
    "state = all",
    "type = epic",
    'type = epic AND labels = "epic::feature"',
    "type IN (epic, issue)",
    "type = task",
    "type IN (task, ticket)",
    "type IN (task, epic)",
    "type = task AND weight = 9",
    'milestone IN ("M1") AND milestone IN ("M2")',
    "weight >= 5",
    "weight = 5",
    "weight != 2",
    "weight IS EMPTY",
    "weight IS NOT EMPTY",
    "state = opened AND (assignee = alice OR assignee IS EMPTY)",
    "assignee = currentUser()",
    "assignee IN (alice, bob)",
    "assignee IN (alice, EMPTY)",
    "assignee IS EMPTY",
    "author != alice",
    "author IN (alice, carol)",
    'labels = "risk::high"',
    'labels IN ("risk::high", "risk::medium")',
    'NOT labels = "type::defect"',
    "labels IS EMPTY",
    'labels ~ "risk"',
    "piid = 2026Q2",
    "piid IS EMPTY",
    'piid ~ "2026"',
    'piid ~ "Q9"',
    'piid !~ "2026"',
    "epic_type = feature",
    'epic_type ~ "cap"',
    "epic_type IS NOT EMPTY",
    "wsjf_urgency > 1",
    "wsjf_urgency IN (1, 3)",
    "risk NOT IN (medium, low)",
    "business_value >= 8",
    "business_value IS EMPTY",
    "created >= 2026-01-01 AND created < 2026-06-01",
    "created = 2026-03-01",
    "updated >= -4w",
    "due IS EMPTY",
    "due <= 2026-09-01",
    "NOT created >= 2026-03-01",
    "NOT due >= 2026-09-01",
    "NOT due < 2026-09-01",
    "NOT closed >= 2026-03-01",
    "NOT closed <= 2026-03-01",
    "NOT (due >= 2026-09-01 OR weight = 5)",
    "closed >= 2026-02-01 AND state = closed",
    'milestone = "M1"',
    'milestone = "M1" OR milestone = "M2"',
    "milestone IS NOT EMPTY AND weight IS EMPTY",
    'title ~ "gateway"',
    'NOT title ~ "gateway"',
    'text ~ "phased rollout"',
    'title = "Reporting epic"',
    'sprint = "Sprint 3"',
    "iteration IS EMPTY",
    "parent = 2",
    "parent IS EMPTY",
    "iid IN (11, 12, 99)",
    "project = team-b",
    "(type = epic AND weight >= 3) OR (type = issue AND labels = \"risk::high\")",
    "NOT (assignee = alice OR assignee = bob)",
    "state = opened AND state = closed",
    "status = opened AND issuetype = issue",
    "state = opened ORDER BY due ASC",
    "ORDER BY business_value DESC",
    "ORDER BY due ASC, weight DESC",
    "ORDER BY piid ASC, iid DESC",
]


class TestGoldenParity:

    @pytest.mark.parametrize("query", GOLDEN_QUERIES)
    def test_pushdown_and_full_scan_agree(self, harness, query):
        planned = harness.run_jql(query, limit=1000, now=NOW)
        scanned = harness.run_jql(query, limit=1000, push_down=False, now=NOW)
        assert ids(planned) == ids(scanned)

    @pytest.mark.parametrize("query", GOLDEN_QUERIES)
    def test_parity_survives_small_pages(self, query):
        planned = QueryHarness(FakeGitLabBackend(page_size=3)).run_jql(
            query, limit=1000, now=NOW)
        scanned = QueryHarness(FakeGitLabBackend(page_size=3)).run_jql(
            query, limit=1000, push_down=False, now=NOW)
        assert ids(planned) == ids(scanned)

    def test_pushdown_actually_narrows_the_fetch(self, harness):
        result = harness.run_jql('type = epic AND labels = "epic::feature"',
                                 limit=1000, now=NOW)
        assert result["plan"]["variables"]["types"] == ["EPIC"]
        assert result["plan"]["variables"]["labelName"] == ["epic::feature"]
        assert result["plan"]["scanned"] == 1        # server did the narrowing
        scan = harness.run_jql('type = epic AND labels = "epic::feature"',
                               limit=1000, push_down=False, now=NOW)
        assert scan["plan"]["scanned"] == len(ITEMS) - 1  # task out of scope

    def test_task_type_stays_out_of_scope(self, harness):
        # Even a query that matches the task's attributes never sees it.
        result = harness.run_jql("weight = 9", limit=1000, now=NOW)
        assert ids(result) == []

    def test_out_of_scope_type_short_circuits_without_fetch(self, harness):
        # types: [] must never reach the server (Rails skips blank list
        # filters — it would return *all* types, and entity scope lives only
        # in the pushed variables). The provably-empty plan never fetches.
        result = harness.run_jql("type = task", limit=1000, now=NOW)
        assert ids(result) == []
        assert result["truncated"] is False
        assert result["plan"]["pages_fetched"] == 0
        assert result["plan"]["scanned"] == 0
        assert harness.backend.calls == []

    def test_contradictory_any_lists_short_circuit_without_fetch(self, harness):
        result = harness.run_jql('milestone IN ("M1") AND milestone IN ("M2")',
                                 limit=1000, now=NOW)
        assert ids(result) == []
        assert harness.backend.calls == []


# ---------------------------------------------------------------------------
# Golden result-set spot checks (fixture ground truth)
# ---------------------------------------------------------------------------

class TestGoldenResults:

    @pytest.mark.parametrize("query,expected", [
        ("state = closed", [3, 13]),
        ("type = epic", [1, 2, 3, 4]),
        ('type = epic AND labels = "epic::feature"', [2]),
        ("weight >= 5", [1, 3, 11, 13]),
        ("assignee = currentUser()", [15, 16]),
        ("state = opened AND (assignee = alice OR assignee IS EMPTY)",
         [1, 2, 4, 11, 14, 16]),
        ("piid = 2026Q2", [1, 2]),
        ("piid IS EMPTY", [11, 12, 13, 14, 15, 16]),
        ('piid ~ "2026"', [1, 2, 3]),
        ('piid ~ "Q9"', [4]),          # out-of-vocabulary label, substring hit
        ('piid !~ "2026"', [4, 11, 12, 13, 14, 15, 16]),
        ('epic_type ~ "cap"', [1]),
        ("wsjf_urgency > 1", [1]),
        ("business_value >= 8", [1, 2, 11]),
        ("created = 2026-03-01", [11]),
        ("updated >= -4w", [1, 2, 4, 11, 12, 15]),
        ("due IS EMPTY", [3, 4, 14, 15]),
        ('milestone = "M1" OR milestone = "M2"', [11, 12, 13]),
        ('title ~ "gateway"', [2, 11, 12]),
        ('text ~ "phased rollout"', [11]),
        ('sprint = "Sprint 3"', [12, 15]),
        ("parent = 2", [11, 12]),
        ("project = team-b", [14, 15, 16]),
        ("NOT (assignee = alice OR assignee = bob)", [1, 2, 3, 4, 13, 14, 15]),
        ("state = opened AND state = closed", []),
        ("weight = 0", [16]),
        ("weight IS EMPTY", [4, 14]),
        # Negated ordering on nullable date fields: items with no date
        # satisfy the negation and must appear in the result.
        ("NOT due >= 2026-09-01", [3, 4, 12, 13, 14, 15, 16]),
        ("NOT closed >= 2026-03-01", [1, 2, 3, 4, 11, 12, 13, 14, 15, 16]),
        ("NOT (due >= 2026-09-01 OR weight = 5)", [4, 12, 13, 14, 15, 16]),
        ("type = task", []),
        ('milestone IN ("M1") AND milestone IN ("M2")', []),
    ])
    def test_expected_result_set(self, harness, query, expected):
        assert ids(harness.run_jql(query, limit=1000, now=NOW)) == expected

    def test_result_shape_matches_documented_schema(self, harness):
        result = harness.run_jql("iid = 11", limit=10, now=NOW)
        (item,) = result["items"]
        assert set(item) == {
            "id", "iid", "type", "title", "state", "labels", "assignees",
            "author", "milestone", "milestone_due", "iteration", "weight",
            "business_value", "start_date", "due_date", "created_at",
            "updated_at", "closed_at", "parent_iid", "namespace_path",
            "web_url", "description",
        }
        assert item["iid"] == 11
        assert item["type"] == "issue"
        assert item["assignees"] == ["alice"]
        assert item["milestone"] == "M1"
        assert item["weight"] == 5

    def test_business_value_resolved_only_when_needed(self, harness):
        with_bv = harness.run_jql("business_value >= 8", limit=10, now=NOW)
        assert all(i["business_value"] >= 8 for i in with_bv["items"])
        without = harness.run_jql("iid = 11", limit=10, now=NOW)
        assert without["items"][0]["business_value"] is None  # not fetched


# ---------------------------------------------------------------------------
# Pagination, caps, early termination
# ---------------------------------------------------------------------------

class TestPaginationAndCaps:

    def test_paginates_to_exhaustion(self):
        backend = FakeGitLabBackend(page_size=2)
        harness = QueryHarness(backend)
        result = harness.run_jql("", limit=1000, now=NOW)
        assert result["count"] == len(ITEMS) - 1     # task out of scope
        assert result["plan"]["pages_fetched"] == 5  # 10 items / 2 per page

    def test_pagination_boundary_match_on_last_row_of_page(self):
        backend = FakeGitLabBackend(page_size=1)
        result = QueryHarness(backend).run_jql("iid = 16", limit=10, now=NOW)
        assert ids(result) == [16]

    def test_default_result_cap(self, harness):
        harness.JQL_DEFAULT_LIMIT = 4
        result = harness.run_jql("", now=NOW)
        assert result["count"] == 4
        assert result["limit"] == 4
        assert result["truncated"] is True

    def test_explicit_limit_overrides_default(self, harness):
        harness.JQL_DEFAULT_LIMIT = 4
        result = harness.run_jql("", limit=1000, now=NOW)
        assert result["count"] == len(ITEMS) - 1
        assert result["truncated"] is False

    def test_invalid_limit_rejected(self, harness):
        with pytest.raises(ValueError):
            harness.run_jql("", limit=0, now=NOW)

    def test_early_stop_without_order_by(self):
        backend = FakeGitLabBackend(page_size=2)
        harness = QueryHarness(backend)
        result = harness.run_jql("", limit=2, now=NOW)
        assert result["count"] == 2
        assert result["plan"]["pages_fetched"] == 1

    def test_truncated_true_when_limit_lands_on_page_boundary(self):
        # Early stop with the count exactly at the limit and more pages
        # unfetched: 8 more matching items exist — the flag must say so.
        backend = FakeGitLabBackend(page_size=2)
        result = QueryHarness(backend).run_jql("", limit=2, now=NOW)
        assert result["count"] == 2
        assert result["truncated"] is True

    def test_truncated_true_when_page_size_equals_limit(self):
        backend = FakeGitLabBackend(page_size=5)
        result = QueryHarness(backend).run_jql("", limit=5, now=NOW)
        assert result["count"] == 5
        assert result["truncated"] is True

    def test_truncated_false_when_early_stop_hits_final_page(self):
        # The limit lands exactly on the last page and nothing is left.
        backend = FakeGitLabBackend(page_size=2)
        result = QueryHarness(backend).run_jql("", limit=10, now=NOW)
        assert result["count"] == 10
        assert result["plan"]["pages_fetched"] == 5
        assert result["truncated"] is False

    def test_no_early_stop_with_client_sort(self):
        backend = FakeGitLabBackend(page_size=2)
        harness = QueryHarness(backend)
        result = harness.run_jql("ORDER BY business_value DESC", limit=2, now=NOW)
        assert result["plan"]["pages_fetched"] == 5   # full fetch, then sort
        assert [i["iid"] for i in result["items"]] == [1, 2]

    def test_early_stop_with_pushed_sort_keeps_server_order(self):
        backend = FakeGitLabBackend(page_size=3)
        harness = QueryHarness(backend)
        result = harness.run_jql("ORDER BY created ASC", limit=3, now=NOW)
        assert result["plan"]["pages_fetched"] == 1
        assert [i["iid"] for i in result["items"]] == [3, 13, 1]

    def test_cap_applies_after_client_sort(self, harness):
        result = harness.run_jql("ORDER BY business_value DESC", limit=3, now=NOW)
        assert [i["business_value"] for i in result["items"]] == [13, 8, 8]
        assert result["truncated"] is True


# ---------------------------------------------------------------------------
# Plan reporting
# ---------------------------------------------------------------------------

class TestPlanReporting:

    def test_result_json_serializable_with_date_bounds(self, harness):
        # The plan block reports variables in transport form — raw datetimes
        # would blow up json.dumps in the CLI/API surfaces (#301/#302).
        result = harness.run_jql(
            "created >= 2026-01-01 AND due <= 2026-09-01", limit=100, now=NOW)
        payload = json.loads(json.dumps(result))
        assert payload["plan"]["variables"]["createdAfter"] == "2026-01-01T00:00:00Z"
        assert payload["plan"]["variables"]["dueBefore"] == "2026-09-01T00:00:00Z"

    def test_result_json_serializable_with_day_equality_range(self, harness):
        result = harness.run_jql("created = 2026-03-01", limit=100, now=NOW)
        json.dumps(result)

    def test_result_json_serializable_for_empty_plan(self, harness):
        json.dumps(harness.run_jql("type = task", limit=100, now=NOW))


# ---------------------------------------------------------------------------
# ORDER BY through the full path
# ---------------------------------------------------------------------------

class TestOrderByEndToEnd:

    def test_pushed_sort_orders_results(self, harness):
        result = harness.run_jql("state = opened ORDER BY due ASC",
                                 limit=100, now=NOW)
        assert result["plan"]["sort"] == "DUE_DATE_ASC"
        dues = [i["due_date"] for i in result["items"]]
        with_due = [d for d in dues if d is not None]
        assert with_due == sorted(with_due)
        assert dues[len(with_due):] == [None] * (len(dues) - len(with_due))

    def test_pushed_and_client_sort_agree(self, harness):
        pushed = harness.run_jql("ORDER BY due ASC", limit=100, now=NOW)
        client = harness.run_jql("ORDER BY due ASC", limit=100,
                                 push_down=False, now=NOW)
        assert pushed["plan"]["sort"] == "DUE_DATE_ASC"
        assert client["plan"]["sort"] is None
        assert [i["due_date"] for i in pushed["items"]] == \
               [i["due_date"] for i in client["items"]]

    def test_multi_key_client_sort(self, harness):
        result = harness.run_jql(
            'milestone = "M1" OR milestone = "M2" ORDER BY milestone ASC, weight DESC',
            limit=100, now=NOW)
        assert result["plan"]["sort"] is None
        assert [i["iid"] for i in result["items"]] == [13, 11, 12]

    def test_order_by_stability_on_ties(self, harness):
        # iids 11 and 12 share milestone M1 due date; fetch order breaks the tie.
        result = harness.run_jql('milestone = "M1" ORDER BY milestone ASC',
                                 limit=100, push_down=False, now=NOW)
        assert [i["iid"] for i in result["items"]] == [11, 12]


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

class TestErrorPaths:

    def test_group_not_found(self):
        harness = QueryHarness()
        harness.get_group_by_name = lambda name: SimpleNamespace(full_path="wrong")
        with pytest.raises(JqlExecutionError):
            harness.run_jql("state = opened", now=NOW)

    def test_transport_failure(self):
        harness = QueryHarness()
        harness.graphql_query = lambda *a, **k: None
        with pytest.raises(JqlExecutionError):
            harness.run_jql("state = opened", now=NOW)

    def test_missing_bv_field_degrades_to_empty(self, harness, capsys):
        harness._find_bv_field = lambda group=None: None
        result = harness.run_jql("business_value IS EMPTY", limit=100, now=NOW)
        assert ids(result) == ids(harness.run_jql("", limit=100, now=NOW))
        # The warning goes to stderr — stdout is the CLI's data channel (#301).
        captured = capsys.readouterr()
        assert "Business Value" in captured.err
        assert captured.out == ""

    def test_currentuser_via_graphql_fallback(self):
        harness = QueryHarness()
        harness.gl = SimpleNamespace(user=None)
        result = harness.run_jql("assignee = currentUser()", limit=100, now=NOW)
        assert ids(result) == [15, 16]
