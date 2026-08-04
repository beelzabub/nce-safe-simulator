"""JQL query execution against live GitLab (issue #300).

The transport half of the query engine: ``run_jql`` is the single entry
point the CLI (#301) and API (#302) surfaces call. Everything pure —
parsing, planning, evaluation, sorting — lives in the ``jql`` package;
this mixin only wires it to the live connection:

- resolves ``currentUser()`` once via the token identity,
- builds the field registry from the loaded config taxonomies,
- pages ``Group.workItems(includeDescendants: true)`` through
  ``graphql_query`` (the existing transport chokepoint, mixins/utils.py),
- re-evaluates the exact expression tree over every fetched item — the
  planner's push-down variables only narrow the fetch, never the result set,
- resolves Business Value through the existing custom-field plumbing
  (``_find_bv_field``) when a query references ``business_value``.
"""
import json
from pathlib import Path

from jql import parse
from jql.executor import (
    EvalContext,
    JqlExecutionError,
    build_work_items_query,
    evaluate,
    shape_node,
    sort_items,
)
from jql.fields import FieldRegistry
from jql.planner import plan_query, query_mentions_current_user


class QueryMixin:
    """Live JQL query executor — ``run_jql(query, limit=...)``."""

    #: Result cap applied when the caller passes no explicit limit.
    JQL_DEFAULT_LIMIT = 100
    #: GraphQL page size for the work-items fetch.
    JQL_PAGE_SIZE = 100

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run_jql(self, query, limit=None, push_down=True, now=None):
        """Run a JQL query against the live portfolio group.

        Args:
            query:     the JQL string (e.g. ``state = opened AND weight >= 5
                       ORDER BY due ASC``).
            limit:     max results to return; None applies JQL_DEFAULT_LIMIT.
            push_down: False forces a full scan (entity scope only, every
                       predicate client-side). Results are identical by
                       contract — the flag exists for parity verification
                       and debugging, not for callers to flip casually.
            now:       fixed reference time for relative dates (tests);
                       defaults to the current UTC time.

        Returns a dict: ``items`` (flat dicts in the documented field
        schema), ``count``, ``limit``, ``truncated``, plus a ``plan`` block
        describing what was pushed down and what ran client-side.

        Raises jql.JqlSyntaxError / UnknownFieldError / UnknownFieldValueError
        / JqlPlanError for bad queries and JqlExecutionError for transport
        failures — callers surface these as user-facing errors.
        """
        parsed = parse(query)
        registry = self._jql_registry()
        current_user = self._jql_current_user() if query_mentions_current_user(parsed) else None
        plan = plan_query(parsed, registry, now=now,
                          current_user=current_user, push_down=push_down)

        effective_limit = self.JQL_DEFAULT_LIMIT if limit is None else int(limit)
        if effective_limit <= 0:
            raise ValueError("limit must be a positive integer")

        group_path = self._jql_group_path()

        bv_field_id = None
        if plan.needs_bv:
            bv_field = self._find_bv_field(group=group_path)
            if bv_field:
                bv_field_id = bv_field["id"]
            else:
                print("  WARNING: Business Value custom field not found — "
                      "business_value resolves as EMPTY for every item.")

        query_text, base_vars = build_work_items_query(
            plan.variables,
            needs_bv=plan.needs_bv,
            needs_description=plan.needs_description,
        )
        ctx = EvalContext(registry=registry, now=plan.now,
                          current_user=plan.current_user)

        # Early termination is only sound when the final order is already
        # settled at fetch time: no ORDER BY at all, or the single sort key
        # pushed down to the server (post-filtering preserves server order).
        early_stop = not plan.client_sort

        items = []
        scanned = 0
        pages = 0
        cursor = None
        while True:
            request = dict(base_vars)
            request.update({"fullPath": group_path,
                            "first": self.JQL_PAGE_SIZE,
                            "after": cursor})
            data = self.graphql_query(query_text, variables=request, retries=2)
            if data is None:
                raise JqlExecutionError("GraphQL work-items query failed")
            group = data.get("group")
            if not group:
                raise JqlExecutionError(
                    "Group '%s' not found or not accessible" % group_path)
            page = group.get("workItems") or {}
            for node in page.get("nodes") or []:
                scanned += 1
                item = shape_node(node, bv_field_id=bv_field_id)
                if plan.expr is None or evaluate(plan.expr, item, ctx):
                    items.append(item)
            pages += 1
            if early_stop and len(items) >= effective_limit:
                break
            info = page.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                break
            cursor = info.get("endCursor")

        if plan.client_sort:
            sort_items(items, plan.client_sort, registry)

        truncated = len(items) > effective_limit
        items = items[:effective_limit]
        return {
            "query":     query,
            "items":     items,
            "count":     len(items),
            "limit":     effective_limit,
            "truncated": truncated,
            "plan": {
                "push_down":     push_down,
                "variables":     plan.variables,
                "sort":          plan.sort,
                "client_sort":   ["%s %s" % (k.field, k.direction)
                                  for k in plan.client_sort],
                "pages_fetched": pages,
                "scanned":       scanned,
            },
        }

    # ------------------------------------------------------------------
    # Wiring helpers
    # ------------------------------------------------------------------

    def _jql_registry(self):
        """Build the field registry from the loaded configuration.

        Reads ``config.json`` for any ``*_labels`` taxonomy, then overlays
        the config-derived instance attributes (which honor the env-var
        overrides applied by reload_config) so the query vocabulary always
        matches what the rest of the tooling is using.
        """
        config = {}
        config_file = getattr(self, "config_file", None)
        if config_file:
            try:
                raw = json.loads(Path(config_file).read_text(encoding="utf-8")) or {}
                config = {k: v for k, v in raw.items()
                          if k.endswith("_labels") and isinstance(v, (list, dict))}
            except (OSError, ValueError):
                pass

        overlay = {
            "project_labels":   getattr(self, "PROJECT_LABELS", None),
            "piid_labels":      getattr(self, "PIID_LABELS", None),
            "epic_type_labels": getattr(self, "EPIC_TYPE_LABELS", None),
            "risk_labels":      getattr(self, "RISK_LABELS", None),
            "roam_labels":      getattr(self, "ROAM_LABELS", None),
            "work_type_labels": getattr(self, "WORK_TYPE_LABELS", None),
            "lifecycle_labels": getattr(self, "LIFECYCLE_LABELS", None),
        }
        for key, value in overlay.items():
            if value:
                config[key] = value
        wsjf = {
            "urgency": getattr(self, "WSJF_URGENCY_LABELS", None),
            "risk":    getattr(self, "WSJF_RISK_LABELS", None),
        }
        wsjf = {k: v for k, v in wsjf.items() if v}
        if wsjf:
            config["wsjf_labels"] = wsjf

        bv = getattr(self, "BUSINESS_VALUE_FIELD", None)
        if bv:
            config["business_value_field"] = {"name": bv.get("name", "Business Value")}
        return FieldRegistry.from_config(config)

    def _jql_group_path(self):
        """Full path of the configured portfolio group (cached)."""
        cached = getattr(self, "_jql_group_path_cache", None)
        if cached:
            return cached
        group = self.get_group_by_name(self.parent_group)
        if group is None:
            raise JqlExecutionError(
                "Portfolio group '%s' not found" % self.parent_group)
        self._jql_group_path_cache = group.full_path
        return self._jql_group_path_cache

    def _jql_current_user(self):
        """Username behind the token, resolved once and cached.

        python-gitlab's auth() populates ``gl.user``; the GraphQL
        ``currentUser`` query is the fallback when it hasn't run.
        """
        cached = getattr(self, "_jql_current_user_cache", None)
        if cached:
            return cached
        username = getattr(getattr(getattr(self, "gl", None), "user", None),
                           "username", None)
        if not username:
            data = self.graphql_query("query { currentUser { username } }", retries=1)
            username = ((data or {}).get("currentUser") or {}).get("username")
        if username:
            self._jql_current_user_cache = username
        return username
