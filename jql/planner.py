"""Query planner: conjunctive-envelope push-down for the JQL engine (issue #300).

Turns a parsed ``ast.Query`` plus the field registry (#299) into a ``Plan``:

- ``variables`` — the widest *conjunctive envelope* of the expression tree,
  translated into ``Group.workItems`` GraphQL filter arguments (state,
  labelName, assignee/author, milestone, weight, types, the eight date
  bounds, ``search`` + ``in``, wildcard IDs for IS [NOT] EMPTY, the ``not:``
  subset, ``or:`` same-field lists).
- ``expr`` — the **exact** expression tree, kept whole for client-side
  re-evaluation over every fetched item.

The engine's core contract: push-down is purely a data-volume optimization.
Every pushed filter must be satisfied by *any* item the full expression could
match (a superset), because correctness comes from re-evaluating ``expr``
client-side — never from server filter support. Consequently the planner is
deliberately conservative: anything it cannot prove safe (general OR across
fields, negated dates, numeric comparisons, id-resolution fields, EMPTY
values inside IN lists) simply stays client-side.

One exception to "always fetch": when an any-list intersection comes up
empty (e.g. ``type = task`` against the epic+issue entity scope) the
conjunction is provably unsatisfiable and ``Plan.empty`` is set — the
executor returns no results without fetching, because the server *skips*
blank list filters (applying no filter) rather than matching nothing.

Pure Python, no I/O. ``currentUser()`` is resolved by the caller (the query
mixin) against the token identity and passed in as ``current_user``; date
functions and relative durations resolve here against a single fixed ``now``
so pushed-down bounds and client-side evaluation always agree.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from . import ast
from .dates import JqlEvaluationError, evaluate_function, is_date_function, resolve_datetime
from .fields import UnknownFieldValueError

#: Entity scope v1 — work items of these types across the portfolio group
#: (``includeDescendants: true``). Applied to every plan as *scope*, not
#: push-down: the full-scan plan carries it too.
ENTITY_SCOPE_TYPES = ("EPIC", "ISSUE")

#: Fields whose top-level list argument is AND-semantics ("has all of");
#: their IN-lists must go through the ``or:`` input, never the plain arg.
_AND_LIST_ARGS = frozenset({"labelName", "assigneeUsernames"})

_DAY_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")

#: Negation flips a comparison operator instead of dropping the predicate
#: (NOT author != alice pushes as author = alice). Date bounds are exempt:
#: NOT (a >= x) == a < x only holds for items that *have* the date — a NULL
#: due/closed satisfies the negation client-side but no pushed Before/After
#: bound matches it server-side, so negated dates always stay client-side.
_NEGATED_OP = {"=": "!=", "!=": "=", ">": "<=", ">=": "<",
               "<": ">=", "<=": ">", "~": "!~", "!~": "~"}


class JqlPlanError(ValueError):
    """A semantically invalid query: bad operator/field combination,
    unresolvable value, or an unresolvable function."""


@dataclass
class Plan:
    """The executable form of a query.

    ``expr`` is always re-evaluated client-side over every fetched item;
    ``variables`` only narrows what gets fetched. ``sort`` is a pushed-down
    ``WorkItemSort`` enum value (single supported key); ``client_sort`` holds
    the ORDER BY keys when sorting must happen client-side instead. Exactly
    one of them is populated when the query has an ORDER BY.
    """
    expr:              Optional[object]
    variables:         Dict[str, object]
    sort:              Optional[str]
    client_sort:       Tuple[ast.SortKey, ...]
    now:               datetime
    current_user:      Optional[str] = None
    needs_bv:          bool = False
    needs_description: bool = False
    push_down:         bool = True
    #: The pushed conjunction is provably unsatisfiable (an any-list
    #: intersection came up empty — e.g. a type constraint entirely outside
    #: the entity scope). The executor must return an empty result *without
    #: fetching*: GitLab's Rails finders skip blank list params entirely
    #: (applying no filter at all), so an empty list can never be sent as a
    #: "match nothing" filter.
    empty:             bool = False
    #: The pushed variables select *exactly* the query's match set — every
    #: conjunct's server-side filter equals its client-side predicate, not a
    #: superset envelope, and no merge widened anything. When True, the
    #: GraphQL connection's ``count`` is the exact whole-set match total even
    #: on a truncated fetch. Deliberately conservative: only field/operator
    #: pushes whose server semantics provably equal the evaluator's qualify.
    exact:             bool = False


# ---------------------------------------------------------------------------
# Value resolution (shared with the executor)
# ---------------------------------------------------------------------------

def is_day_granular(node):
    """True when a value node names a whole day (``2026-01-31``) rather than
    an instant — equality on it means the day *range*."""
    if isinstance(node, (ast.DateLiteral, ast.String)):
        return _DAY_RE.match(node.value.strip()) is not None
    return False


def resolve_scalar(node, spec, now, current_user=None):
    """Resolve an AST value node to a concrete Python scalar.

    Date-typed fields get datetimes (durations relative to ``now``, functions
    evaluated); ``currentUser()`` becomes the resolved username; everything
    else keeps its literal value. Raises JqlPlanError for unknown functions
    or unresolvable values.
    """
    if isinstance(node, ast.Function):
        name = node.name.lower()
        if name == "currentuser":
            if node.args:
                raise JqlPlanError("currentUser() takes no arguments")
            if not current_user:
                raise JqlPlanError(
                    "currentUser() could not be resolved — no authenticated user identity")
            return current_user
        if is_date_function(node.name):
            try:
                return evaluate_function(node.name, node.args, now=now)
            except JqlEvaluationError as e:
                raise JqlPlanError(str(e))
        raise JqlPlanError("Unknown function '%s()'" % node.name)
    if spec is not None and spec.value_type == "date":
        try:
            return resolve_datetime(node, now=now)
        except JqlEvaluationError as e:
            raise JqlPlanError(str(e))
    if isinstance(node, (ast.String, ast.DateLiteral, ast.Duration)):
        return node.value
    if isinstance(node, ast.Number):
        return node.value
    raise JqlPlanError("Cannot resolve value %r" % (node,))


def query_mentions_current_user(query):
    """True when any value in the query is a currentUser() call — lets the
    caller skip identity resolution for queries that never need it."""
    def _in_value(v):
        if isinstance(v, ast.Function):
            return v.name.lower() == "currentuser" or any(_in_value(a) for a in v.args)
        return False

    def _walk(expr):
        if expr is None:
            return False
        if isinstance(expr, (ast.And, ast.Or)):
            return any(_walk(o) for o in expr.operands)
        if isinstance(expr, ast.Not):
            return _walk(expr.operand)
        if isinstance(expr, ast.Comparison):
            return _in_value(expr.value)
        if isinstance(expr, ast.InList):
            return any(_in_value(v) for v in expr.values)
        return False

    return _walk(query.where)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_ORDER_OPS = ("<", "<=", ">", ">=")
_TEXT_OPS = ("~", "!~")


def _validate_value(spec, node, now, current_user, ordering=False, substring=False):
    """Validate one RHS value against its field; raises the field errors."""
    if isinstance(node, ast.Empty):
        return
    val = resolve_scalar(node, spec, now, current_user)
    if spec.value_type == "enum":
        if str(val).strip().lower() not in spec.values:
            raise UnknownFieldValueError(spec.name, val, spec.values)
    elif spec.kind == "label":
        if substring:
            # '~' / '!~' match substrings of the taxonomy *values*
            # (piid ~ "2026") — any text RHS is meaningful, including ones
            # outside the vocabulary; the executor evaluates it client-side.
            return
        try:
            spec.label_for(val)
        except UnknownFieldValueError:
            # Ordering comparisons additionally accept bare numbers outside
            # the vocabulary (wsjf_urgency > 2.5).
            if not ordering:
                raise
            try:
                float(val)
            except (TypeError, ValueError):
                raise UnknownFieldValueError(spec.name, val, spec.values)
    elif spec.value_type == "number" or spec.kind == "custom":
        try:
            float(val)
        except (TypeError, ValueError):
            raise JqlPlanError(
                "Field '%s' takes a number, got %r" % (spec.name, val))
    # date fields already resolved (and therefore validated) in resolve_scalar


def _validate_predicate(pred, registry, now, current_user):
    spec = registry.resolve(pred.field)
    if isinstance(pred, ast.IsEmpty):
        if spec.value_type == "enum":
            raise JqlPlanError("Field '%s' is never empty" % spec.name)
        return spec
    if isinstance(pred, ast.InList):
        for v in pred.values:
            if isinstance(v, ast.Empty) and spec.value_type == "enum":
                raise JqlPlanError("Field '%s' is never empty" % spec.name)
            _validate_value(spec, v, now, current_user)
        return spec
    # Comparison
    if isinstance(pred.value, ast.Empty):
        if pred.op not in ("=", "!="):
            raise JqlPlanError("EMPTY is only valid with = or != (or IS [NOT] EMPTY)")
        if spec.value_type == "enum":
            raise JqlPlanError("Field '%s' is never empty" % spec.name)
        return spec
    if pred.op in _ORDER_OPS:
        if not (spec.value_type in ("number", "date") or spec.kind == "label"):
            raise JqlPlanError(
                "Operator '%s' is not supported for field '%s'" % (pred.op, spec.name))
    if pred.op in _TEXT_OPS:
        if spec.value_type not in ("text", "string", "label", "user"):
            raise JqlPlanError(
                "Operator '%s' is not supported for field '%s'" % (pred.op, spec.name))
    _validate_value(spec, pred.value, now, current_user,
                    ordering=pred.op in _ORDER_OPS,
                    substring=pred.op in _TEXT_OPS)
    return spec


def _validate(query, registry, now, current_user):
    """Walk the whole query, resolving every field and value. Returns the
    (needs_bv, needs_description) flags collected along the way."""
    needs_bv = [False]
    needs_desc = [False]

    def _note(spec):
        if spec.kind == "custom":
            needs_bv[0] = True
        if spec.name == "text":
            needs_desc[0] = True

    def _walk(expr):
        if isinstance(expr, (ast.And, ast.Or)):
            for op in expr.operands:
                _walk(op)
        elif isinstance(expr, ast.Not):
            _walk(expr.operand)
        else:
            _note(_validate_predicate(expr, registry, now, current_user))

    if query.where is not None:
        _walk(query.where)
    for key in query.order_by:
        spec = registry.resolve(key.field)
        _note(spec)
        if key.direction.upper() not in ("ASC", "DESC"):
            raise JqlPlanError("Invalid sort direction %r" % key.direction)
    return needs_bv[0], needs_desc[0]


# ---------------------------------------------------------------------------
# Conjunctive-envelope extraction
# ---------------------------------------------------------------------------

def _conjuncts(expr, negated=False):
    """Flatten the tree into top-level conjuncts as (negated, node) pairs.

    ``NOT`` distributes: ``NOT (a OR b)`` contributes NOT a and NOT b as
    conjuncts (De Morgan); ``NOT (a AND b)`` is a disjunction and contributes
    nothing beyond itself (handled — and skipped — downstream).
    """
    if isinstance(expr, ast.Not):
        return _conjuncts(expr.operand, not negated)
    if isinstance(expr, ast.And) and not negated:
        out = []
        for op in expr.operands:
            out.extend(_conjuncts(op, False))
        return out
    if isinstance(expr, ast.Or) and negated:
        out = []
        for op in expr.operands:
            out.extend(_conjuncts(op, True))
        return out
    return [(negated, expr)]


class _Vars:
    """Accumulator for GraphQL filter variables with superset-safe merging."""

    def __init__(self):
        self.top: Dict[str, object] = {}
        self.not_: Dict[str, object] = {}
        self.or_: Dict[str, List[str]] = {}
        #: An any-list intersection came up empty — every pushed value list
        #: is a superset envelope of its conjunct's matches, so an empty
        #: intersection proves no item can satisfy the conjunction.
        self.contradiction = False
        #: A merge kept only one of two conflicting constraints (scalar /
        #: or-list first-wins): the surviving filter is wider than the
        #: conjunction, so the pushed set can no longer be exact.
        self.lossy = False

    def scalar(self, arg, value):
        """Single-value arg. On conflict keep the first — the conjunction is
        a contradiction, and any one conjunct's filter is a superset of the
        (empty) result set."""
        if arg in self.top and self.top[arg] != value:
            self.lossy = True
        self.top.setdefault(arg, value)

    def and_list(self, arg, values):
        """AND-semantics list (labelName, assigneeUsernames): every conjunct
        appends — the server filter is the conjunction, exactly."""
        cur = self.top.setdefault(arg, [])
        for v in values:
            if v not in cur:
                cur.append(v)

    def any_list(self, arg, values):
        """OR-semantics list over a single-valued attribute (types,
        milestoneTitle, iids): repeat constraints intersect (tighter but
        still exact for the conjunction)."""
        values = list(dict.fromkeys(values))
        if arg in self.top:
            self.top[arg] = [v for v in self.top[arg] if v in values]
        else:
            self.top[arg] = values
        if not self.top[arg]:
            # Never emit an empty list filter: the server would *skip* the
            # blank param (no filter at all), not match nothing. Flag the
            # provable contradiction so the executor short-circuits instead.
            self.contradiction = True

    def not_list(self, arg, values):
        """List inside ``not:`` — excluded values accumulate."""
        cur = self.not_.setdefault(arg, [])
        for v in values:
            if v not in cur:
                cur.append(v)

    def not_scalar(self, arg, value):
        self.not_.setdefault(arg, value)

    def or_list(self, arg, values):
        """Same-field value list inside ``or:``. Only one list per arg —
        merging two IN conjuncts by union would *widen* one of them, which
        is superset-safe, so first-wins keeps it simply correct."""
        values = list(dict.fromkeys(values))
        if arg in self.or_ and self.or_[arg] != values:
            self.lossy = True
        self.or_.setdefault(arg, values)

    def date_after(self, arg, dt):
        cur = self.top.get(arg)
        self.top[arg] = dt if cur is None else max(cur, dt)

    def date_before(self, arg, dt):
        cur = self.top.get(arg)
        self.top[arg] = dt if cur is None else min(cur, dt)

    def finalize(self):
        out = dict(self.top)
        if self.not_:
            out["not"] = dict(self.not_)
        if self.or_:
            out["or"] = dict(self.or_)
        return out


def _weight_str(value):
    """GraphQL's weight filter arg is a String — format 5 / 5.0 as \"5\"."""
    f = float(value)
    return str(int(f)) if f.is_integer() else str(f)


def _canonical_labels(spec, values):
    return [spec.label_for(v) for v in values]


def _push_equality(spec, value, vars_, now, current_user):
    """Push one positive equality conjunct. Skips anything unsafe."""
    if spec.requires_id_resolution:
        return  # iterationId / parentIds take GitLab ids, not user values
    if spec.kind == "label":
        vars_.and_list("labelName", _canonical_labels(spec, [value]))
        return
    if spec.kind == "custom" or spec.graphql_arg is None:
        return
    name = spec.name
    if name == "state":
        vars_.scalar("state", str(value).strip().lower())
    elif name == "type":
        vars_.any_list("types", [str(value).strip().upper()])
    elif spec.search_in:  # title / text — substring search is a superset of equality
        if "search" not in vars_.top:
            vars_.scalar("search", str(value))
            vars_.scalar("in", list(spec.search_in))
    elif name == "assignee":
        vars_.and_list("assigneeUsernames", [str(value)])
    elif name == "author":
        vars_.scalar("authorUsername", str(value))
    elif name == "labels":
        vars_.and_list("labelName", [str(value)])
    elif name == "milestone":
        vars_.any_list("milestoneTitle", [str(value)])
    elif name == "weight":
        vars_.scalar("weight", _weight_str(value))
    elif name == "iid":
        vars_.any_list("iids", [_id_str(value)])


def _id_str(value):
    """iids are strings server-side; normalize 12 / 12.0 / \"12\" to \"12\"."""
    try:
        f = float(value)
        if f.is_integer():
            return str(int(f))
    except (TypeError, ValueError):
        pass
    return str(value)


def _push_not_equality(spec, value, vars_):
    """Push one negated equality via the ``not:`` input (declared subset only)."""
    if not spec.supports_not or spec.requires_id_resolution:
        return
    if spec.kind == "label":
        vars_.not_list("labelName", _canonical_labels(spec, [value]))
        return
    name = spec.name
    if name == "type":
        vars_.not_list("types", [str(value).strip().upper()])
    elif name == "assignee":
        vars_.not_list("assigneeUsernames", [str(value)])
    elif name == "author":
        vars_.not_list("authorUsername", [str(value)])  # list inside not:
    elif name == "labels":
        vars_.not_list("labelName", [str(value)])
    elif name == "milestone":
        vars_.not_list("milestoneTitle", [str(value)])
    elif name == "weight":
        vars_.not_scalar("weight", _weight_str(value))


def _push_in_list(spec, values, vars_):
    """Push a positive IN over already-resolved scalar values."""
    if spec.requires_id_resolution:
        return
    if spec.kind == "label":
        vars_.or_list("labelNames", _canonical_labels(spec, values))
        return
    name = spec.name
    if name == "type":
        vars_.any_list("types", [str(v).strip().upper() for v in values])
    elif name == "milestone":
        vars_.any_list("milestoneTitle", [str(v) for v in values])
    elif name == "iid":
        vars_.any_list("iids", [_id_str(v) for v in values])
    elif name == "state" and len(values) == 1:
        vars_.scalar("state", str(values[0]).strip().lower())
    elif name == "assignee":
        vars_.or_list("assigneeUsernames", [str(v) for v in values])
    elif name == "author":
        vars_.or_list("authorUsernames", [str(v) for v in values])
    elif name == "labels":
        vars_.or_list("labelNames", [str(v) for v in values])


def _push_not_in_list(spec, values, vars_):
    if not spec.supports_not or spec.requires_id_resolution:
        return
    if spec.kind == "label":
        vars_.not_list("labelName", _canonical_labels(spec, values))
        return
    name = spec.name
    if name == "type":
        vars_.not_list("types", [str(v).strip().upper() for v in values])
    elif name == "assignee":
        vars_.not_list("assigneeUsernames", [str(v) for v in values])
    elif name == "author":
        vars_.not_list("authorUsername", [str(v) for v in values])
    elif name == "labels":
        vars_.not_list("labelName", [str(v) for v in values])
    elif name == "milestone":
        vars_.not_list("milestoneTitle", [str(v) for v in values])
    elif name == "weight" and len(values) == 1:
        vars_.not_scalar("weight", _weight_str(values[0]))


def _push_empty(spec, not_empty, vars_):
    """IS [NOT] EMPTY via the wildcard enums (NONE / ANY)."""
    if spec.wildcard_arg is None:
        return
    vars_.scalar(spec.wildcard_arg, "ANY" if not_empty else "NONE")


def _push_date_bound(spec, op, dt, day, vars_, now):
    after, before = spec.date_bound_args
    if op == "=":
        if day:
            vars_.date_after(after, dt)
            vars_.date_before(before, dt + timedelta(days=1) - timedelta(microseconds=1))
        else:
            vars_.date_after(after, dt)
            vars_.date_before(before, dt)
    elif op in (">", ">="):
        vars_.date_after(after, dt)
    elif op in ("<", "<="):
        vars_.date_before(before, dt)
    # != has no server-side form (dates are absent from not:)


def _try_or_collapse(expr, registry, vars_, now, current_user):
    """A top-level OR whose operands are all =/IN on the *same* field pushes
    as a same-field value list. EMPTY anywhere disqualifies the whole
    disjunct — no server-side list can express \"or is empty\"."""
    field_name = None
    values = []
    for op in expr.operands:
        if isinstance(op, ast.Comparison) and op.op == "=":
            vals = [op.value]
        elif isinstance(op, ast.InList) and not op.negated:
            vals = list(op.values)
        else:
            return
        if any(isinstance(v, ast.Empty) for v in vals):
            return
        spec = registry.resolve(op.field)
        if field_name is None:
            field_name = spec.name
        elif spec.name != field_name:
            return
        values.extend(resolve_scalar(v, spec, now, current_user) for v in vals)
    if field_name is None:
        return
    _push_in_list(registry.resolve(field_name), values, vars_)


#: Core fields whose pushed =/IN filters select exactly what the evaluator
#: keeps (semantics validated by the golden parity suite's GitLab-modelled
#: backend) — the basis for Plan.exact. Off-list pushes are superset
#: envelopes only: search (word-match vs substring), date bounds (server
#: inclusivity unverified against every op), weight ranges, custom fields,
#: and user fields (post_filter_only: equality also matches display names,
#: which no username push can express).
_EXACT_EQUALITY_FIELDS = {"state", "type", "labels", "milestone", "iid",
                          "weight"}
_EXACT_IN_FIELDS = {"type", "milestone", "iid", "labels"}


def _conjunct_exact(negated, expr, registry):
    """True when this conjunct's pushed filter matches *exactly* the items
    its client-side evaluation keeps — the conservative whitelist behind
    Plan.exact. Anything not provably exact answers False, which downgrades
    the reported total to "unknown", never to a wrong number."""
    if isinstance(expr, ast.IsEmpty):
        # _push_empty handles both polarities exactly via the wildcard enum.
        return registry.resolve(expr.field).wildcard_arg is not None
    if negated:
        return False
    if isinstance(expr, (ast.Or, ast.And)):
        return False
    if isinstance(expr, ast.InList):
        if expr.negated or any(isinstance(v, ast.Empty) for v in expr.values):
            return False
        spec = registry.resolve(expr.field)
        if spec.requires_id_resolution or spec.post_filter_only:
            return False
        if spec.kind == "label":
            return True
        if spec.name == "state":
            return len(expr.values) == 1   # multi-value state is not pushed
        return spec.name in _EXACT_IN_FIELDS
    if isinstance(expr, ast.Comparison):
        spec = registry.resolve(expr.field)
        if isinstance(expr.value, ast.Empty):
            return spec.wildcard_arg is not None
        if expr.op != "=" or spec.requires_id_resolution or spec.post_filter_only:
            return False
        if spec.kind == "label":
            return True
        if (spec.value_type == "date" or spec.kind == "custom"
                or spec.graphql_arg is None or spec.search_in):
            return False
        return spec.name in _EXACT_EQUALITY_FIELDS
    return False


def _apply_conjunct(negated, expr, registry, vars_, now, current_user):
    if isinstance(expr, ast.Or):
        if not negated:
            _try_or_collapse(expr, registry, vars_, now, current_user)
        return
    if isinstance(expr, ast.And):
        return  # negated AND == disjunction; nothing safe to push

    if isinstance(expr, ast.IsEmpty):
        spec = registry.resolve(expr.field)
        _push_empty(spec, not_empty=(expr.negated != negated), vars_=vars_)
        return

    if isinstance(expr, ast.InList):
        spec = registry.resolve(expr.field)
        if any(isinstance(v, ast.Empty) for v in expr.values):
            return  # a pushed value list would drop the EMPTY-matching items
        values = [resolve_scalar(v, spec, now, current_user) for v in expr.values]
        if expr.negated != negated:
            _push_not_in_list(spec, values, vars_)
        else:
            _push_in_list(spec, values, vars_)
        return

    if isinstance(expr, ast.Comparison):
        spec = registry.resolve(expr.field)
        op = _NEGATED_OP[expr.op] if negated else expr.op
        if isinstance(expr.value, ast.Empty):
            not_empty = (op == "!=")
            _push_empty(spec, not_empty=not_empty, vars_=vars_)
            return
        if spec.value_type == "date":
            if negated:
                # NOT (a >= x) == a < x only for items that *have* the date:
                # a NULL due/closed satisfies the negation client-side, but
                # no pushed Before/After bound ever matches a NULL date
                # server-side. Negated dates always stay client-side.
                return
            dt = resolve_scalar(expr.value, spec, now, current_user)
            _push_date_bound(spec, op, dt, is_day_granular(expr.value), vars_, now)
            return
        value = resolve_scalar(expr.value, spec, now, current_user)
        if op == "=":
            _push_equality(spec, value, vars_, now, current_user)
        elif op == "!=":
            _push_not_equality(spec, value, vars_)
        elif op == "~" and spec.search_in:
            if "search" not in vars_.top:
                vars_.scalar("search", str(value))
                vars_.scalar("in", list(spec.search_in))
        # ordering ops on non-date fields and !~ have no server-side form


# ---------------------------------------------------------------------------
# ORDER BY
# ---------------------------------------------------------------------------

def _plan_sort(order_by, registry, push_down):
    """Single supported key pushes down via the WorkItemSort enum; multi-key
    or unsupported keys fall back to a stable client-side sort."""
    if not order_by:
        return None, ()
    if push_down and len(order_by) == 1:
        spec = registry.resolve(order_by[0].field)
        if spec.sort_prefix:
            return "%s_%s" % (spec.sort_prefix, order_by[0].direction.upper()), ()
    return None, tuple(order_by)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def plan_query(query, registry, now=None, current_user=None, push_down=True):
    """Plan a parsed query against the field registry.

    ``push_down=False`` yields the full-scan plan — entity scope only, every
    predicate evaluated client-side. The golden-query parity tests assert it
    returns the identical result set to the pushed-down plan.
    """
    now = now or datetime.utcnow()
    needs_bv, needs_desc = _validate(query, registry, now, current_user)

    vars_ = _Vars()
    conjuncts = _conjuncts(query.where) if query.where is not None else []
    if push_down and query.where is not None:
        for negated, expr in conjuncts:
            _apply_conjunct(negated, expr, registry, vars_, now, current_user)

    # Entity scope v1 (epics + issues) — applied to every plan; an envelope
    # type constraint intersects with it rather than widening it.
    vars_.any_list("types", list(ENTITY_SCOPE_TYPES))

    sort, client_sort = _plan_sort(query.order_by, registry, push_down)
    if sort:
        vars_.scalar("sort", sort)

    # A predicate-free query is exact by construction (the scope filter IS
    # the query); with predicates, exactness needs push-down on, no lossy
    # merges, and every conjunct on the provably-exact whitelist.
    exact = (not vars_.lossy
             and (query.where is None
                  or (push_down and all(_conjunct_exact(n, e, registry)
                                        for n, e in conjuncts))))

    return Plan(
        expr=query.where,
        variables=vars_.finalize(),
        sort=sort,
        client_sort=client_sort,
        now=now,
        current_user=current_user,
        needs_bv=needs_bv,
        needs_description=needs_desc,
        push_down=push_down,
        empty=vars_.contradiction,
        exact=exact,
    )
