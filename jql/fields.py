"""Field registry and GitLab field mapping for the JQL query engine (#299).

The single source of truth the planner/executor (#300) consumes: which field
names a query may use, what values they take, and — per field — how far each
predicate can be *pushed down* into GitLab's live query surface
(``Group.workItems`` / ``Project.issues`` GraphQL filter arguments) versus
evaluated client-side over the fetched pages.

Three field kinds:

- **core** — real work-item attributes with a static capability table below,
  asserted against a checked-in introspection fixture of the GraphQL filter
  args (``tests/fixtures/gitlab_filter_args.json``, captured from gitlab.com).
- **label** — scoped-label virtual fields generated from the ``config.json``
  taxonomies (``piid_labels``, ``epic_type_labels``, ``wsjf_labels``, …):
  ``piid = 2026Q2`` resolves to ``labelName: "PIID::2026Q2"``.
- **custom** — ``business_value``, the Business Value custom field
  (``mixins/utils.py`` plumbing). Declared post-filter-only: the GraphQL
  ``customField:`` filter supports select-option fields only (verified by
  introspection), so BV predicates are resolved client-side via the existing
  BV fetch.

Capability declarations are made against ``Group.workItems`` — the surface
the executor queries (portfolio group, ``includeDescendants: true``).
``Project.issues`` accepts the same argument names for every capability
declared here; its few divergences (``epicId`` instead of ``parentIds``,
``iids`` allowed under ``not:``) are noted inline and never *widen* what a
field claims.

Push-down is purely a data-volume optimization: anything not push-downable
(numeric comparisons, general OR, negated dates, …) is still queryable — the
planner keeps it in the residual expression for client-side evaluation.
"""

from dataclasses import dataclass
from typing import Dict, Iterator, Optional, Tuple


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class UnknownFieldError(ValueError):
    """Raised when a query names a field outside the registry vocabulary."""

    def __init__(self, name, vocabulary, aliases=None):
        self.name       = name
        self.vocabulary = tuple(vocabulary)
        self.aliases    = dict(aliases or {})
        msg = (f"Unknown field '{name}'. Valid fields: "
               + ", ".join(self.vocabulary))
        if self.aliases:
            msg += ("; aliases: "
                    + ", ".join(f"{a} -> {c}" for a, c in sorted(self.aliases.items())))
        super().__init__(msg)


class UnknownFieldValueError(ValueError):
    """Raised when a taxonomy/enum field is compared to a value outside its vocabulary."""

    def __init__(self, field_name, value, valid_values):
        self.field_name   = field_name
        self.value        = value
        self.valid_values = tuple(valid_values)
        super().__init__(
            f"Unknown value '{value}' for field '{field_name}'. "
            "Valid values: " + ", ".join(self.valid_values))


# ---------------------------------------------------------------------------
# Field specification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FieldSpec:
    """One queryable field and its push-down capability declaration.

    Capability semantics (all against ``Group.workItems``):

    - ``graphql_arg``      — equality filter argument (``None`` = post-filter only).
    - ``requires_id_resolution`` — the equality argument takes GitLab *ids*
                             (iteration ids, WorkItemID GIDs), not the titles /
                             iids users write in queries. The planner must
                             resolve values to ids before pushing the predicate
                             down, and MUST keep it in the client-side residual
                             when it cannot — pushing raw user values would
                             silently change the result set, not just the cost.
                             Wildcard (IS [NOT] EMPTY) push-down is unaffected:
                             the ``wildcard_arg`` enum takes no user value.
    - ``arg_is_list``      — the argument takes a list (so ``IN (a, b)`` pushes
                             down as a same-arg list where ``or_arg`` allows it,
                             and multiple ANDed equalities can share the arg for
                             AND-list args like ``labelName``).
    - ``date_bound_args``  — ``(afterArg, beforeArg)`` pair for date fields; the
                             only server-side comparison support that exists
                             (``>=``/``<=``; ``=`` becomes a day range). All
                             other fields are equality-only server-side.
    - ``wildcard_arg``     — enum argument whose ``NONE``/``ANY`` values express
                             ``IS EMPTY`` / ``IS NOT EMPTY``.
    - ``supports_not``     — the argument exists in the ``not:`` input.
    - ``or_arg``           — argument name inside the ``or:`` input (same-field
                             value lists only; GitLab has no cross-field OR).
    - ``search_in``        — for text fields: the ``in:`` scope paired with
                             ``search:`` (substring ``~`` push-down).
    - ``sort_prefix``      — ``ORDER BY`` push-down: ``<prefix>_ASC/_DESC`` in
                             the sort enum (``None`` = client-side sort only).
                             The prefix *defines* the field's sort semantics:
                             a client-side fallback comparator must order by
                             the same key the enum does (e.g. milestone sorts
                             by MILESTONE_DUE — due date, not title), so the
                             ordering never depends on which plan ran.
    """

    name:              str
    kind:              str                            # "core" | "label" | "custom"
    value_type:        str                            # "enum" | "string" | "user" | "text" | "date" | "number" | "label"
    graphql_arg:       Optional[str] = None
    requires_id_resolution: bool = False
    arg_is_list:       bool = False
    date_bound_args:   Optional[Tuple[str, str]] = None
    wildcard_arg:      Optional[str] = None
    supports_not:      bool = False
    or_arg:            Optional[str] = None
    search_in:         Tuple[str, ...] = ()
    sort_prefix:       Optional[str] = None
    values:            Tuple[str, ...] = ()           # allowed values for enum fields
    label_prefix:      Optional[str] = None           # scoped-label prefix ("PIID", "epic", …)
    label_map:         Optional[Dict[str, str]] = None  # lower value/label -> canonical label
    custom_field_name: Optional[str] = None           # kind == "custom" only
    aliases:           Tuple[str, ...] = ()
    description:       str = ""

    # -- derived capabilities ------------------------------------------------

    @property
    def push_down(self):
        """True when any server-side filter argument exists for this field."""
        return self.graphql_arg is not None or self.date_bound_args is not None

    @property
    def post_filter_only(self):
        return not self.push_down

    @property
    def comparisons(self):
        """Server-side comparison support: 'date_bounds' or 'equality'."""
        return "date_bounds" if self.date_bound_args else "equality"

    @property
    def supports_empty_wildcard(self):
        """IS [NOT] EMPTY pushes down via wildcard NONE/ANY."""
        return self.wildcard_arg is not None

    @property
    def supports_or(self):
        return self.or_arg is not None

    # -- scoped-label value resolution ---------------------------------------

    def label_for(self, value):
        """Resolve a taxonomy value to its full GitLab label name.

        Accepts the bare value (``"2026Q2"``) or the full label
        (``"PIID::2026Q2"``), case-insensitively. Raises
        UnknownFieldValueError listing the valid vocabulary otherwise.
        """
        if self.label_map is None:
            raise TypeError(f"Field '{self.name}' is not a scoped-label field")
        label = self.label_map.get(str(value).strip().lower())
        if label is None:
            raise UnknownFieldValueError(self.name, value, self.values)
        return label


# ---------------------------------------------------------------------------
# Core work-item fields — static capability table
# ---------------------------------------------------------------------------
# Every declaration below is asserted against the checked-in introspection
# fixture (tests/fixtures/gitlab_filter_args.json) by tests/test_jql_fields.py,
# so a GitLab schema drift shows up as a test failure, not a runtime surprise.

CORE_FIELDS = (
    FieldSpec(
        name="state", kind="core", value_type="enum",
        graphql_arg="state",
        values=("opened", "closed", "locked", "all"),
        aliases=("status",),
        description="Work item state (IssuableState). No not:/or:/wildcard support.",
    ),
    FieldSpec(
        name="type", kind="core", value_type="enum",
        graphql_arg="types", arg_is_list=True, supports_not=True,
        values=("issue", "incident", "test_case", "requirement", "task",
                "ticket", "objective", "key_result", "epic"),
        aliases=("issuetype",),
        description="Work item type (IssueType enum, lowercase in queries).",
    ),
    FieldSpec(
        name="title", kind="core", value_type="text",
        graphql_arg="search", search_in=("TITLE",),
        sort_prefix="TITLE",
        aliases=("summary",),
        description="Substring '~' search over the title (search: + in: [TITLE]). "
                    "'!~' has no server-side form (search is absent from not:) — post-filter.",
    ),
    FieldSpec(
        name="text", kind="core", value_type="text",
        graphql_arg="search", search_in=("TITLE", "DESCRIPTION"),
        description="Substring '~' search over title + description.",
    ),
    FieldSpec(
        name="assignee", kind="core", value_type="user",
        graphql_arg="assigneeUsernames", arg_is_list=True,
        wildcard_arg="assigneeWildcardId", supports_not=True,
        or_arg="assigneeUsernames",
        description="Assignee username(s); IS EMPTY via assigneeWildcardId: NONE.",
    ),
    FieldSpec(
        name="author", kind="core", value_type="user",
        graphql_arg="authorUsername", supports_not=True,
        or_arg="authorUsernames",
        aliases=("reporter",),
        description="Author username. or: takes the plural authorUsernames list.",
    ),
    FieldSpec(
        name="labels", kind="core", value_type="label",
        graphql_arg="labelName", arg_is_list=True, supports_not=True,
        or_arg="labelNames",
        description="Label names. labelName is an AND-list; or: labelNames is the OR form.",
    ),
    FieldSpec(
        name="milestone", kind="core", value_type="string",
        graphql_arg="milestoneTitle", arg_is_list=True,
        wildcard_arg="milestoneWildcardId", supports_not=True,
        sort_prefix="MILESTONE_DUE",
        description="Milestone title; IS EMPTY via milestoneWildcardId: NONE. "
                    "ORDER BY milestone means milestone *due date* order "
                    "(MILESTONE_DUE — GitLab has no title sort); a client-side "
                    "comparator must sort by due date too.",
    ),
    FieldSpec(
        name="iteration", kind="core", value_type="string",
        graphql_arg="iterationId", requires_id_resolution=True,
        arg_is_list=True,
        wildcard_arg="iterationWildcardId", supports_not=True,
        aliases=("sprint",),
        description="Iteration. iterationId takes iteration *ids*, but queries "
                    "say sprint = \"Sprint 3\" — equality pushes down only "
                    "after title->id resolution (requires_id_resolution); "
                    "IS EMPTY via iterationWildcardId: NONE needs no ids.",
    ),
    FieldSpec(
        name="weight", kind="core", value_type="number",
        graphql_arg="weight",
        wildcard_arg="weightWildcardId", supports_not=True,
        sort_prefix="WEIGHT",
        description="Weight. Server-side equality only — 'weight >= 5' is post-filter.",
    ),
    FieldSpec(
        name="created", kind="core", value_type="date",
        date_bound_args=("createdAfter", "createdBefore"),
        sort_prefix="CREATED",
        description="Creation time; Before/After bounds push down, negation does not.",
    ),
    FieldSpec(
        name="updated", kind="core", value_type="date",
        date_bound_args=("updatedAfter", "updatedBefore"),
        sort_prefix="UPDATED",
        description="Last-update time; Before/After bounds push down.",
    ),
    FieldSpec(
        name="due", kind="core", value_type="date",
        date_bound_args=("dueAfter", "dueBefore"),
        sort_prefix="DUE_DATE",
        description="Due date; Before/After bounds push down.",
    ),
    FieldSpec(
        name="closed", kind="core", value_type="date",
        date_bound_args=("closedAfter", "closedBefore"),
        sort_prefix="CLOSED_AT",
        description="Close time; Before/After bounds push down.",
    ),
    FieldSpec(
        name="parent", kind="core", value_type="string",
        graphql_arg="parentIds", requires_id_resolution=True,
        arg_is_list=True,
        wildcard_arg="parentWildcardId", supports_not=True,
        description="Parent work item. parentIds takes WorkItemID *GIDs*, but "
                    "queries say parent = 42 (iid) — equality pushes down only "
                    "after iid->GID resolution (requires_id_resolution); "
                    "IS EMPTY via parentWildcardId: NONE needs no ids. "
                    "Project.issues uses epicId/epicWildcardId instead.",
    ),
    FieldSpec(
        name="iid", kind="core", value_type="string",
        graphql_arg="iids", arg_is_list=True,
        description="Work item iid(s). not: iids exists only on Project.issues — "
                    "declared unsupported here.",
    ),
    FieldSpec(
        name="project", kind="core", value_type="string",
        description="Containing project (path or name). No group-wide filter arg — post-filter.",
    ),
)

# Jira name -> canonical simulator field, derived from the per-spec aliases.
JIRA_ALIASES = {alias: spec.name for spec in CORE_FIELDS for alias in spec.aliases}


# ---------------------------------------------------------------------------
# Scoped-label virtual fields from config.json taxonomies
# ---------------------------------------------------------------------------

# wsjf_labels is a {"urgency": [...], "risk": [...]} dict, not a flat list.
_WSJF_KEY = "wsjf_labels"


def _label_field_spec(name, labels, config_key):
    """Build a virtual FieldSpec from one taxonomy label list.

    Scoped labels ("PIID::2026Q2") expose the value part after '::' as the
    query value; unscoped taxonomies (e.g. epic_type_labels as plain
    ["Epic", "Capability", "Feature"]) expose the label itself. Both the bare
    value and the full label resolve, case-insensitively.
    """
    label_map = {}
    values    = []
    prefixes  = set()
    for label in labels:
        if "::" in label:
            prefix, value = label.split("::", 1)
            prefixes.add(prefix)
        else:
            value = label
        values.append(value)
        label_map[value.lower()] = label
        label_map[label.lower()] = label
    return FieldSpec(
        name=name, kind="label", value_type="label",
        # Same push-down surface as the raw `labels` field: equality via the
        # labelName AND-list, negation via not:, IN-lists via or: labelNames.
        # Comparisons (wsjf_urgency > 3) and IS EMPTY (no label with this
        # prefix) have no server-side form — post-filter.
        graphql_arg="labelName", arg_is_list=True, supports_not=True,
        or_arg="labelNames",
        values=tuple(values),
        label_prefix=(prefixes.pop() if len(prefixes) == 1 else None),
        label_map=label_map,
        description=f"Scoped-label virtual field from config '{config_key}'.",
    )


def _taxonomy_specs(config, reserved):
    """Generate virtual FieldSpecs from every '*_labels' taxonomy in config.

    Field names derive from the config key ('piid_labels' -> 'piid');
    'wsjf_labels' fans out to 'wsjf_urgency' / 'wsjf_risk'. A derived name
    that collides with a core field, an alias, 'business_value', or another
    taxonomy's derived name (config 'project_labels' vs the core 'project'
    field) gets '_label' suffixes appended until unique instead of shadowing
    it — registry construction never fails on a user-editable config.
    """
    used  = set(reserved)
    specs = []
    for key in sorted(config):
        if not key.endswith("_labels"):
            continue
        raw = config[key]
        if key == _WSJF_KEY and isinstance(raw, dict):
            groups = [(f"wsjf_{sub}", raw.get(sub) or []) for sub in sorted(raw)]
        elif isinstance(raw, list):
            groups = [(key[:-len("_labels")], raw)]
        else:
            continue
        for name, labels in groups:
            labels = [l for l in labels if isinstance(l, str) and l]
            if not labels:
                continue
            while name.lower() in used:
                name = f"{name}_label"
            used.add(name.lower())
            specs.append(_label_field_spec(name, labels, key))
    return specs


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class FieldRegistry:
    """Name/alias -> FieldSpec lookup with a closed, discoverable vocabulary."""

    def __init__(self, specs):
        self._fields  = {}
        self._aliases = {}
        for spec in specs:
            key = spec.name.lower()
            if key in self._fields or key in self._aliases:
                raise ValueError(f"Duplicate field name '{spec.name}'")
            self._fields[key] = spec
            for alias in spec.aliases:
                akey = alias.lower()
                if akey in self._fields or akey in self._aliases:
                    raise ValueError(f"Duplicate field alias '{alias}'")
                self._aliases[akey] = key

    @classmethod
    def from_config(cls, config):
        """Build the full registry: core table + config taxonomies + business_value."""
        config   = config or {}
        reserved = {s.name.lower() for s in CORE_FIELDS}
        reserved.update(a.lower() for a in JIRA_ALIASES)
        # business_value is appended below — a 'business_value_labels'
        # taxonomy must rename (-> business_value_label), not collide.
        reserved.add("business_value")
        specs = list(CORE_FIELDS)
        specs.extend(_taxonomy_specs(config, reserved))
        bv_name = (config.get("business_value_field") or {}).get("name", "Business Value")
        specs.append(FieldSpec(
            name="business_value", kind="custom", value_type="number",
            custom_field_name=bv_name,
            # The GraphQL customField: filter supports select-option custom
            # fields only (introspection: selectedOptionIds/Values, no numeric
            # comparators) and the sort enum has no custom-field keys, so BV
            # predicates and ordering resolve client-side through the existing
            # BV plumbing (mixins/utils.py:294-450).
            description=f"'{bv_name}' custom field — post-filter only.",
        ))
        return cls(specs)

    # -- lookup --------------------------------------------------------------

    def resolve(self, name):
        """Return the FieldSpec for a canonical name or alias (case-insensitive).

        Raises UnknownFieldError listing the valid vocabulary otherwise.
        """
        key = str(name).strip().lower()
        spec = self._fields.get(key)
        if spec is not None:
            return spec
        canonical = self._aliases.get(key)
        if canonical is not None:
            return self._fields[canonical]
        raise UnknownFieldError(name, self.vocabulary, self.aliases)

    @property
    def vocabulary(self):
        """Sorted canonical field names (aliases excluded)."""
        return tuple(sorted(s.name for s in self._fields.values()))

    @property
    def aliases(self):
        """alias -> canonical name mapping."""
        return {a: self._fields[c].name for a, c in self._aliases.items()}

    def __contains__(self, name):
        key = str(name).strip().lower()
        return key in self._fields or key in self._aliases

    def __iter__(self) -> Iterator[FieldSpec]:
        return iter(sorted(self._fields.values(), key=lambda s: s.name))

    def __len__(self):
        return len(self._fields)
