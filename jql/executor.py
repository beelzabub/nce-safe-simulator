"""Client-side execution pieces for the JQL engine (issue #300).

Pure functions — no I/O and no GitLab client import (transport stays in
``mixins/query.py`` per the package contract):

- ``build_work_items_query`` — assemble the ``Group.workItems`` GraphQL
  document for exactly the filter variables a plan pushed down, plus the
  widget selections the query needs (Business Value / description are
  fetched only when referenced).
- ``shape_node`` — flatten one GraphQL work-item node into the simulator's
  documented flat field schema (export-style keys: ``labels``, ``assignees``,
  ``author``, ``milestone``, ``weight``, ``business_value``, ``*_at`` dates…).
- ``evaluate`` — re-evaluate the **exact** parsed expression tree over a
  shaped item. This is where correctness lives: whatever the server filtered,
  every returned item is checked against the full expression again, so
  push-down can only ever change cost, never results.
- ``sort_items`` — stable multi-key ORDER BY fallback for keys the
  ``WorkItemSort`` enum cannot express (None values always sort last).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import ast
from .fields import FieldRegistry
from .planner import is_day_granular, resolve_scalar

__all__ = [
    "JqlExecutionError",
    "EvalContext",
    "build_work_items_query",
    "collect_label_colors",
    "shape_node",
    "evaluate",
    "sort_items",
    "parse_ts",
]


class JqlExecutionError(RuntimeError):
    """Transport/shape failure while running a planned query."""


# ---------------------------------------------------------------------------
# GraphQL document assembly
# ---------------------------------------------------------------------------

#: GraphQL type per filter argument (verified against the introspection
#: fixture tests/fixtures/gitlab_filter_args.json). List inner types are
#: declared non-null — a stricter variable type is always accepted where the
#: server declares the nullable form.
_ARG_TYPES = {
    "state":              "IssuableState",
    "types":              "[IssueType!]",
    "labelName":          "[String!]",
    "authorUsername":     "String",
    "assigneeUsernames":  "[String!]",
    "milestoneTitle":     "[String!]",
    "weight":             "String",
    "iids":               "[String!]",
    "search":             "String",
    "in":                 "[IssuableSearchableField!]",
    "createdAfter":       "Time",
    "createdBefore":      "Time",
    "updatedAfter":       "Time",
    "updatedBefore":      "Time",
    "dueAfter":           "Time",
    "dueBefore":          "Time",
    "closedAfter":        "Time",
    "closedBefore":       "Time",
    "assigneeWildcardId": "AssigneeWildcardId",
    "milestoneWildcardId": "MilestoneWildcardId",
    "weightWildcardId":   "WeightWildcardId",
    "iterationWildcardId": "IterationWildcardId",
    "parentWildcardId":   "WorkItemParentWildcardId",
    "sort":               "WorkItemSort",
    "not":                "NegatedWorkItemFilterInput",
    "or":                 "UnionedWorkItemFilterInput",
}

#: Filter args whose names would be awkward/reserved as GraphQL variable
#: names get an alias for the variable itself (arg name stays as-is).
_VAR_NAMES = {"in": "searchIn", "not": "negated", "or": "unioned"}

_CORE_NODE_FIELDS = """
            id
            iid
            title
            state
            webUrl
            createdAt
            updatedAt
            closedAt
            workItemType { name }
            author { username name }
            namespace { fullPath }"""

_CORE_WIDGETS = """
              ... on WorkItemWidgetLabels { labels { nodes { title color textColor } } }
              ... on WorkItemWidgetAssignees { assignees { nodes { username name } } }
              ... on WorkItemWidgetMilestone { milestone { title dueDate } }
              ... on WorkItemWidgetIteration { iteration { id title } }
              ... on WorkItemWidgetWeight { weight }
              ... on WorkItemWidgetStartAndDueDate { startDate dueDate }
              ... on WorkItemWidgetHierarchy { parent { iid } }"""

_DESCRIPTION_WIDGET = """
              ... on WorkItemWidgetDescription { description }"""

_CUSTOM_FIELDS_WIDGET = """
              ... on WorkItemWidgetCustomFields {
                customFieldValues {
                  customField { id name }
                  ... on WorkItemSelectFieldValue { selectedOptions { id value } }
                }
              }"""


def _gql_value(value):
    """Serialize a variable value for transport (datetimes → ISO-8601 UTC)."""
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    if isinstance(value, dict):
        return {k: _gql_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_gql_value(v) for v in value]
    return value


def build_work_items_query(variables, needs_bv=False, needs_description=False):
    """Build the paginated Group.workItems document for a plan's variables.

    Returns ``(query_text, request_variables)`` — the caller adds
    ``fullPath`` / ``first`` / ``after`` per page. Unknown argument names
    raise instead of producing a document the server would reject.
    """
    args = sorted(variables)
    unknown = [a for a in args if a not in _ARG_TYPES]
    if unknown:
        raise JqlExecutionError(
            "No GraphQL declaration for filter argument(s): %s" % ", ".join(unknown))

    decls = ["$fullPath: ID!", "$first: Int!", "$after: String"]
    uses = ["includeDescendants: true", "first: $first", "after: $after"]
    request = {}
    for arg in args:
        var = _VAR_NAMES.get(arg, arg)
        decls.append("$%s: %s" % (var, _ARG_TYPES[arg]))
        uses.append("%s: $%s" % (arg, var))
        request[var] = _gql_value(variables[arg])

    widgets = _CORE_WIDGETS
    if needs_description:
        widgets += _DESCRIPTION_WIDGET
    if needs_bv:
        widgets += _CUSTOM_FIELDS_WIDGET

    query = """    query JqlWorkItems(%s) {
      group(fullPath: $fullPath) {
        workItems(%s) {
          count
          pageInfo { hasNextPage endCursor }
          nodes {%s
            widgets {%s
            }
          }
        }
      }
    }""" % (", ".join(decls), ", ".join(uses), _CORE_NODE_FIELDS, widgets)
    return query, request


# ---------------------------------------------------------------------------
# Result shaping
# ---------------------------------------------------------------------------

def _gid_tail(gid):
    tail = str(gid or "").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


def parse_ts(value):
    """Parse an ISO-8601 timestamp or date to a *naive UTC* datetime.

    All engine datetimes are naive UTC — plan ``now``, resolved literals, and
    item timestamps — so comparisons never mix aware and naive values.
    """
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _widget_map(node):
    merged = {}
    for w in node.get("widgets") or []:
        if isinstance(w, dict):
            merged.update(w)
    return merged


def collect_label_colors(node, into):
    """Harvest ``label title -> {color, text_color}`` from a raw GraphQL node
    into ``into`` — the colors set in GitLab, which the web UI's label chips
    honor. First sighting wins; labels without a color are skipped so the
    UI's default chip style applies."""
    for n in (_widget_map(node).get("labels") or {}).get("nodes") or []:
        title = n.get("title")
        if title and title not in into and n.get("color"):
            into[title] = {"color": n["color"],
                           "text_color": n.get("textColor")}


def shape_node(node, bv_field_id=None):
    """Flatten one GraphQL work-item node to the simulator's flat schema.

    Keys mirror the documented export field schema (see
    ``mixins/importexport.py``): ``labels`` / ``assignees`` are lists,
    ``author`` / ``milestone`` are the username / title, dates stay ISO
    strings. ``business_value`` resolves from the custom-fields widget when
    ``bv_field_id`` is given (None otherwise); ``description`` is None unless
    the plan fetched it.
    """
    w = _widget_map(node)

    milestone = w.get("milestone") or {}
    iteration = w.get("iteration") or {}
    parent = w.get("parent") or {}

    business_value = None
    if bv_field_id is not None:
        for cfv in w.get("customFieldValues") or []:
            if not isinstance(cfv, dict):
                continue
            if (cfv.get("customField") or {}).get("id") != bv_field_id:
                continue
            opts = cfv.get("selectedOptions") or []
            if opts:
                try:
                    business_value = int(opts[0].get("value", ""))
                except (TypeError, ValueError):
                    business_value = None
            break

    state = str(node.get("state") or "").lower()
    state = {"open": "opened"}.get(state, state)

    wi_type = ((node.get("workItemType") or {}).get("name") or "")
    parent_iid = parent.get("iid")

    return {
        "id":             _gid_tail(node.get("id")),
        "iid":            int(node["iid"]) if str(node.get("iid", "")).isdigit() else node.get("iid"),
        "type":           wi_type.strip().lower().replace(" ", "_"),
        "title":          node.get("title") or "",
        "state":          state,
        "labels":         [n["title"] for n in ((w.get("labels") or {}).get("nodes") or [])],
        "assignees":      [n["username"] for n in ((w.get("assignees") or {}).get("nodes") or [])],
        "assignee_names": [n["name"] for n in ((w.get("assignees") or {}).get("nodes") or [])
                           if n.get("name")],
        "author":         (node.get("author") or {}).get("username"),
        "author_name":    (node.get("author") or {}).get("name"),
        "milestone":      milestone.get("title"),
        "milestone_due":  milestone.get("dueDate"),
        "iteration":      iteration.get("title") or iteration.get("id"),
        "weight":         w.get("weight"),
        "business_value": business_value,
        "start_date":     w.get("startDate"),
        "due_date":       w.get("dueDate"),
        "created_at":     node.get("createdAt"),
        "updated_at":     node.get("updatedAt"),
        "closed_at":      node.get("closedAt"),
        "parent_iid":     int(parent_iid) if str(parent_iid or "").isdigit() else parent_iid,
        "namespace_path": (node.get("namespace") or {}).get("fullPath") or "",
        "web_url":        node.get("webUrl") or "",
        "description":    w.get("description"),
    }


# ---------------------------------------------------------------------------
# Expression evaluation
# ---------------------------------------------------------------------------

@dataclass
class EvalContext:
    registry: FieldRegistry
    now: datetime
    current_user: Optional[str] = None


def _fold(value):
    return str(value).casefold()


def _item_value(spec, item):
    """The item's raw comparable value for a core/custom field."""
    if spec.kind == "custom":
        return item.get("business_value")
    name = spec.name
    if name == "text":
        desc = item.get("description") or ""
        return "%s\n%s" % (item.get("title") or "", desc)
    return {
        "state":     item.get("state"),
        "type":      item.get("type"),
        "title":     item.get("title"),
        "assignee":  item.get("assignees") or [],
        "author":    item.get("author"),
        "labels":    item.get("labels") or [],
        "milestone": item.get("milestone"),
        "iteration": item.get("iteration"),
        "weight":    item.get("weight"),
        "created":   item.get("created_at"),
        "updated":   item.get("updated_at"),
        "due":       item.get("due_date"),
        "closed":    item.get("closed_at"),
        "parent":    item.get("parent_iid"),
        "iid":       item.get("iid"),
        "project":   item.get("namespace_path"),
    }[name]


def _taxonomy_labels(spec, item):
    """The item's labels that belong to this taxonomy (canonical form)."""
    out = []
    for label in item.get("labels") or []:
        if spec.label_prefix is not None:
            if _fold(label).startswith(_fold(spec.label_prefix) + "::"):
                out.append(label)
        elif spec.label_map and _fold(label) in spec.label_map:
            out.append(spec.label_map[_fold(label)])
    return out


def _taxonomy_values(spec, item):
    """The value parts of the item's taxonomy labels (\"PIID::2026Q2\" → \"2026Q2\")."""
    vals = []
    for label in _taxonomy_labels(spec, item):
        if spec.label_prefix is not None and "::" in label:
            vals.append(label.split("::", 1)[1])
        else:
            vals.append(label)
    return vals


def _tax_rank(spec, value):
    """Orderable rank of a taxonomy value: numeric when it parses as a
    number, else its position in the declared vocabulary; None otherwise.
    Ranks of different kinds never compare (returns tagged tuples)."""
    text = str(value).strip()
    try:
        return ("num", float(text))
    except ValueError:
        pass
    low_values = [v.lower() for v in spec.values]
    t = text.lower()
    if t in low_values:
        return ("vocab", float(low_values.index(t)))
    # accept the full label form too ("wsjf-urgency::2")
    if spec.label_map and t in spec.label_map:
        label = spec.label_map[t]
        part = label.split("::", 1)[1] if "::" in label else label
        return _tax_rank(spec, part)
    return None


_ORDER_CMP = {
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}


def _is_empty(spec, item):
    if spec.kind == "label":
        return not _taxonomy_labels(spec, item)
    value = _item_value(spec, item)
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    return value is None or value == ""


def _id_eq(item_value, rhs):
    if item_value is None:
        return False
    try:
        return int(item_value) == int(float(rhs))
    except (TypeError, ValueError):
        return _fold(item_value) == _fold(rhs)


def _eval_date(spec, op, node, item, ctx):
    ivalue = parse_ts(_item_value(spec, item))
    rhs = resolve_scalar(node, spec, ctx.now, ctx.current_user)
    if ivalue is None:
        return op == "!="
    if op in ("=", "!="):
        if is_day_granular(node):
            hit = rhs <= ivalue < rhs + timedelta(days=1)
        else:
            hit = ivalue == rhs
        return hit if op == "=" else not hit
    return _ORDER_CMP[op](ivalue, rhs)


def _eval_number(spec, op, node, item, ctx):
    ivalue = _item_value(spec, item)
    rhs = float(resolve_scalar(node, spec, ctx.now, ctx.current_user))
    if ivalue is None:
        return op == "!="
    f = float(ivalue)
    if op == "=":
        return f == rhs
    if op == "!=":
        return f != rhs
    return _ORDER_CMP[op](f, rhs)


def _eval_taxonomy(spec, op, node, item, ctx):
    rhs = resolve_scalar(node, spec, ctx.now, ctx.current_user)
    if op in ("=", "!="):
        label = spec.label_for(rhs)
        hit = any(_fold(l) == _fold(label) for l in _taxonomy_labels(spec, item))
        return hit if op == "=" else not hit
    values = _taxonomy_values(spec, item)
    if op in ("~", "!~"):
        hit = any(_fold(rhs) in _fold(v) for v in values)
        return hit if op == "~" else not hit
    rhs_rank = _tax_rank(spec, rhs)
    if rhs_rank is None:
        return False
    hit = False
    for v in values:
        rank = _tax_rank(spec, v)
        if rank is not None and rank[0] == rhs_rank[0] and _ORDER_CMP[op](rank[1], rhs_rank[1]):
            hit = True
            break
    return hit


def _eval_comparison(field, op, node, item, ctx):
    spec = ctx.registry.resolve(field)
    if isinstance(node, ast.Empty):
        empty = _is_empty(spec, item)
        return (not empty) if op == "!=" else empty
    if spec.value_type == "date":
        return _eval_date(spec, op, node, item, ctx)
    if spec.kind == "label":
        return _eval_taxonomy(spec, op, node, item, ctx)
    if spec.value_type == "number" or spec.kind == "custom":
        return _eval_number(spec, op, node, item, ctx)

    rhs = resolve_scalar(node, spec, ctx.now, ctx.current_user)

    # `state = all` is GitLab-speak for "no state filter".
    if spec.name == "state" and _fold(rhs) == "all":
        return op == "="

    ivalue = _item_value(spec, item)
    # People match by username OR display name ('beelzabub' or "Jamie
    # Powers"). The extra candidates join only string comparison — IS EMPTY
    # (handled above) and sorting still see the plain username value(s).
    if spec.name == "assignee":
        ivalue = list(ivalue) + list(item.get("assignee_names") or [])
    elif spec.name == "author":
        ivalue = [v for v in (ivalue, item.get("author_name")) if v]
    if isinstance(ivalue, (list, tuple)):
        folded = [_fold(v) for v in ivalue]
        if op == "=":
            return _fold(rhs) in folded
        if op == "!=":
            return _fold(rhs) not in folded
        if op == "~":
            return any(_fold(rhs) in v for v in folded)
        if op == "!~":
            return not any(_fold(rhs) in v for v in folded)
        raise JqlExecutionError("Operator '%s' not valid for field '%s'" % (op, spec.name))

    if op in ("=", "!="):
        if spec.name in ("iid", "parent"):
            hit = _id_eq(ivalue, rhs)
        elif spec.name == "project":
            path = _fold(ivalue or "")
            hit = path == _fold(rhs) or path.rsplit("/", 1)[-1] == _fold(rhs)
        else:
            hit = ivalue is not None and _fold(ivalue) == _fold(rhs)
        return hit if op == "=" else not hit
    if op in ("~", "!~"):
        hit = ivalue is not None and _fold(rhs) in _fold(ivalue)
        return hit if op == "~" else not hit
    raise JqlExecutionError("Operator '%s' not valid for field '%s'" % (op, spec.name))


def evaluate(expr, item, ctx):
    """Evaluate the exact expression tree against one shaped item."""
    if isinstance(expr, ast.And):
        return all(evaluate(o, item, ctx) for o in expr.operands)
    if isinstance(expr, ast.Or):
        return any(evaluate(o, item, ctx) for o in expr.operands)
    if isinstance(expr, ast.Not):
        return not evaluate(expr.operand, item, ctx)
    if isinstance(expr, ast.Comparison):
        return _eval_comparison(expr.field, expr.op, expr.value, item, ctx)
    if isinstance(expr, ast.InList):
        hit = any(_eval_comparison(expr.field, "=", v, item, ctx) for v in expr.values)
        return (not hit) if expr.negated else hit
    if isinstance(expr, ast.IsEmpty):
        spec = ctx.registry.resolve(expr.field)
        return _is_empty(spec, item) != expr.negated
    raise JqlExecutionError("Cannot evaluate %r" % (expr,))


# ---------------------------------------------------------------------------
# Client-side ORDER BY
# ---------------------------------------------------------------------------

def _sort_value(spec, item):
    """Comparable sort key for one item under one field, or None (sorts last).

    Field semantics match the push-down sort enum where one exists (milestone
    sorts by its due date — MILESTONE_DUE — not its title), so the ordering
    never depends on which plan ran.
    """
    if spec.kind == "custom":
        v = item.get("business_value")
        return float(v) if v is not None else None
    if spec.kind == "label":
        ranks = [r for r in (_tax_rank(spec, v) for v in _taxonomy_values(spec, item))
                 if r is not None]
        return min(ranks) if ranks else None
    name = spec.name
    if spec.value_type == "date":
        return parse_ts(_item_value(spec, item))
    if name == "milestone":
        return parse_ts(item.get("milestone_due"))
    if name == "weight":
        v = item.get("weight")
        return float(v) if v is not None else None
    if name in ("iid", "parent"):
        v = _item_value(spec, item)
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    value = _item_value(spec, item)
    if isinstance(value, (list, tuple)):
        return ", ".join(sorted(_fold(v) for v in value)) or None
    return _fold(value) if value not in (None, "") else None


def sort_items(items, sort_keys, registry):
    """Stable in-place multi-key sort. Keys apply left-to-right (major key
    first); None values always sort last regardless of direction, and ties
    keep their fetch order (Python's sort is stable)."""
    for key in reversed(sort_keys):
        spec = registry.resolve(key.field)
        desc = key.direction.upper() == "DESC"
        keyed = [(_sort_value(spec, it), it) for it in items]
        present = [p for p in keyed if p[0] is not None]
        missing = [it for v, it in keyed if v is None]
        present.sort(key=lambda p: p[0], reverse=desc)
        items[:] = [it for _, it in present] + missing
    return items
