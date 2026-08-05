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

The CLI surface (issue #301) lives here too: ``_tool_query`` backs the
``query`` entry in the ``TOOLS`` registry (mixins/tools.py) — a thin
wrapper over ``run_jql`` with table/json/csv formatters. Machine formats
print the payload alone on stdout (the runner's chrome goes to stderr via
the registry's ``stdout_is_data`` flag); every error path prints to stderr
and exits non-zero.
"""
import csv
import json
import sys
from pathlib import Path

import gitlab
import requests

from jql import JqlSyntaxError, parse
from jql.dates import JqlEvaluationError
from jql.executor import (
    EvalContext,
    JqlExecutionError,
    _gql_value,
    build_work_items_query,
    evaluate,
    shape_node,
    sort_items,
)
from jql.fields import FieldRegistry, UnknownFieldError, UnknownFieldValueError
from jql.planner import JqlPlanError, plan_query, query_mentions_current_user


#: Output formats the `query` CLI tool accepts.
JQL_FORMATS = ("table", "json", "csv")

#: CSV column order — exactly the flat schema shape_node produces
#: (tests assert the two never drift).
JQL_OUTPUT_FIELDS = [
    "id", "iid", "type", "title", "state", "labels", "assignees",
    "assignee_names", "author", "author_name",
    "milestone", "milestone_due", "iteration", "weight", "business_value",
    "start_date", "due_date", "created_at", "updated_at", "closed_at",
    "parent_iid", "namespace_path", "web_url", "description",
]

#: Columns of the human-readable table (title last: variable width).
JQL_TABLE_COLUMNS = ["iid", "type", "state", "weight", "assignees",
                     "due_date", "title"]

#: Widest a table title cell may grow before truncation.
_JQL_TITLE_WIDTH = 60

#: Query-shaped errors beyond bad syntax: unknown vocabulary, an unplannable
#: query, or bad date arithmetic. All carry a user-facing message (unknown
#: fields/values list the valid vocabulary) — the CLI prints it and exits 2.
_JQL_QUERY_ERRORS = (UnknownFieldError, UnknownFieldValueError,
                     JqlPlanError, JqlEvaluationError)


def _jql_cell(value):
    """One flat-schema value as display/CSV text: lists join with ', ',
    None becomes ''."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _jql_syntax_error_text(query, exc):
    """JQL-style parse-error display: the position/expected-token message
    plus a caret line marking the offset in the query text."""
    offset = getattr(exc, "offset", 0) or 0
    offset = max(0, min(int(offset), len(query)))
    return "Parse error: %s\n  %s\n  %s^" % (exc, query, " " * offset)


def _format_jql_table(result):
    """The default human-readable rendering of a run_jql result dict."""
    items = result["items"]
    lines = []
    if not items:
        lines.append("  No matching work items.")
    else:
        rows = []
        for item in items:
            row = []
            for col in JQL_TABLE_COLUMNS:
                text = _jql_cell(item.get(col))
                if col == "title" and len(text) > _JQL_TITLE_WIDTH:
                    text = text[:_JQL_TITLE_WIDTH - 1] + "…"
                row.append(text)
            rows.append(row)
        widths = [max(len(col), *(len(r[i]) for r in rows))
                  for i, col in enumerate(JQL_TABLE_COLUMNS)]
        lines.append("  " + "  ".join(
            col.ljust(widths[i]) for i, col in enumerate(JQL_TABLE_COLUMNS)).rstrip())
        lines.append("  " + "  ".join("-" * w for w in widths))
        for row in rows:
            lines.append("  " + "  ".join(
                cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    lines.append("")
    lines.append("  %d item(s)" % result["count"])
    if result["truncated"]:
        lines.append("  Truncated at limit %d — more matches may exist; "
                     "raise --limit to see them." % result["limit"])
    return "\n".join(lines)


def _write_jql_csv(result, stream):
    """Write the result's items as CSV (header + one row per item)."""
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(JQL_OUTPUT_FIELDS)
    for item in result["items"]:
        writer.writerow([_jql_cell(item.get(field)) for field in JQL_OUTPUT_FIELDS])


class QueryMixin:
    """Live JQL query executor — ``run_jql(query, limit=...)``."""

    #: Result cap applied when the caller passes no explicit limit.
    JQL_DEFAULT_LIMIT = 100
    #: GraphQL page size for the work-items fetch.
    JQL_PAGE_SIZE = 100

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run_jql(self, query, limit=None, offset=0, push_down=True, now=None):
        """Run a JQL query against the live portfolio group.

        Args:
            query:     the JQL string (e.g. ``state = opened AND weight >= 5
                       ORDER BY due ASC``).
            limit:     max results to return; None applies JQL_DEFAULT_LIMIT.
            offset:    number of matching items to skip before the returned
                       window — offset/limit page through one stable result
                       sequence (the query's order). Each page re-executes
                       the query; deep offsets re-scan the skipped matches.
            push_down: False forces a full scan (entity scope only, every
                       predicate client-side). Results are identical by
                       contract — the flag exists for parity verification
                       and debugging, not for callers to flip casually.
            now:       fixed reference time for relative dates (tests);
                       defaults to the current UTC time.

        Returns a dict: ``items`` (flat dicts in the documented field
        schema), ``count``, ``limit``, ``offset``, ``truncated`` (True when
        the limit cut the returned list *or* fetching stopped early with
        pages still unfetched — more matching items may exist beyond the
        returned window), plus a ``plan`` block
        describing what was pushed down and what ran client-side. The whole
        dict is JSON-serializable (pushed date bounds are reported in their
        ISO-8601 transport form).

        Raises jql.JqlSyntaxError / UnknownFieldError / UnknownFieldValueError
        / JqlPlanError for bad queries and JqlExecutionError for transport
        failures — callers surface these as user-facing errors. *Every*
        transport failure surfaces as JqlExecutionError: raw HTTP errors from
        the GraphQL POST (connection refused, timeouts, 401/5xx via
        raise_for_status) and python-gitlab REST errors from the group /
        custom-field lookups are wrapped here, so callers never see
        requests.RequestException or gitlab.GitlabError leak through.
        """
        try:
            return self._run_jql(query, limit=limit, offset=offset,
                                 push_down=push_down, now=now)
        except (requests.RequestException, gitlab.GitlabError) as exc:
            raise JqlExecutionError(
                "GitLab transport failure: %s" % exc) from exc

    def _run_jql(self, query, limit=None, offset=0, push_down=True, now=None):
        """run_jql body — see run_jql for the contract."""
        parsed = parse(query)
        registry = self._jql_registry()
        current_user = self._jql_current_user() if query_mentions_current_user(parsed) else None
        plan = plan_query(parsed, registry, now=now,
                          current_user=current_user, push_down=push_down)

        effective_limit = self.JQL_DEFAULT_LIMIT if limit is None else int(limit)
        if effective_limit <= 0:
            raise ValueError("limit must be a positive integer")
        offset = int(offset or 0)
        if offset < 0:
            raise ValueError("offset must be zero or a positive integer")
        window_end = offset + effective_limit

        items = []
        scanned = 0
        pages = 0
        truncated = False

        # A provably-empty plan (e.g. a type constraint entirely outside the
        # entity scope) never fetches: the server *skips* blank list filters
        # instead of matching nothing, so the only correct execution of an
        # empty envelope is no execution at all.
        if not plan.empty:
            group_path = self._jql_group_path()

            bv_field_id = None
            if plan.needs_bv:
                bv_field = self._find_bv_field(group=group_path)
                if bv_field:
                    bv_field_id = bv_field["id"]
                else:
                    # stderr: run_jql feeds the CLI's json/csv formats, whose
                    # stdout is a pure data channel — a warning line there
                    # corrupts the payload for jq / CSV readers.
                    print("  WARNING: Business Value custom field not found — "
                          "business_value resolves as EMPTY for every item.",
                          file=sys.stderr)

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
                info = page.get("pageInfo") or {}
                has_next = bool(info.get("hasNextPage"))
                if early_stop and len(items) >= window_end:
                    # Stopping with pages unfetched counts as truncation even
                    # when the count lands exactly on the window — the pages
                    # never fetched may hold more matching items.
                    truncated = len(items) > window_end or has_next
                    break
                if not has_next:
                    break
                cursor = info.get("endCursor")

        if plan.client_sort:
            sort_items(items, plan.client_sort, registry)

        truncated = truncated or len(items) > window_end
        items = items[offset:window_end]
        return {
            "query":     query,
            "items":     items,
            "count":     len(items),
            "limit":     effective_limit,
            "offset":    offset,
            "truncated": truncated,
            "plan": {
                "push_down":     push_down,
                "variables":     _gql_value(plan.variables),
                "sort":          plan.sort,
                "client_sort":   ["%s %s" % (k.field, k.direction)
                                  for k in plan.client_sort],
                "pages_fetched": pages,
                "scanned":       scanned,
            },
        }

    # ------------------------------------------------------------------
    # CLI tool surface (issue #301)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_jql_source(jql):
        """Resolve the ``jql`` param, which accepts query text OR a path to a
        file containing the query. A value naming an existing file is read
        (UTF-8, stripped — the lexer treats newlines as whitespace, so
        multi-line files work); anything else is the query itself. The
        existing-file check is decisive: real queries contain operators and
        spaces no file path has. Returns ``(query_text, source_path_or_None)``.
        """
        raw = "" if jql is None else str(jql)
        candidate = raw.strip()
        if candidate and "\n" not in candidate:
            path = Path(candidate).expanduser()
            try:
                is_file = path.is_file()
            except OSError:       # path longer than NAME_MAX etc. — a query
                is_file = False
            if is_file:
                try:
                    return path.read_text(encoding="utf-8").strip(), str(path)
                except OSError as exc:
                    print("Cannot read query file '%s': %s" % (path, exc),
                          file=sys.stderr)
                    raise SystemExit(2)
        return raw, None

    def _tool_query(self, jql, limit=None, format="table"):
        """`query` utility tool: run a JQL query and print the results.

        ``jql`` is either the query text or a path to a file containing the
        query (see ``_resolve_jql_source``). format: ``table``
        (human-readable, default), ``json`` (the full run_jql envelope —
        items, count, truncated, plan), or ``csv`` (header + one row per
        item, list cells joined with ', ').

        Machine formats land on stdout untouched so they pipe straight into
        ``jq`` / a CSV reader — the runner's chrome is on stderr (the
        registry's ``stdout_is_data`` flag). Errors print to stderr and exit
        non-zero: 2 for a bad query, format, or limit; 1 for a transport
        failure.
        """
        jql, jql_source = self._resolve_jql_source(jql)
        if jql_source:
            print("Query read from %s" % jql_source, file=sys.stderr)
        fmt = str(format or "table").strip().lower()
        if fmt not in JQL_FORMATS:
            print("Unknown format '%s'. Valid formats: %s"
                  % (format, ", ".join(JQL_FORMATS)), file=sys.stderr)
            raise SystemExit(2)
        try:
            result = self.run_jql(jql, limit=limit)
        except JqlSyntaxError as exc:
            print(_jql_syntax_error_text(jql, exc), file=sys.stderr)
            raise SystemExit(2)
        except _JQL_QUERY_ERRORS as exc:
            print("Query error: %s" % exc, file=sys.stderr)
            raise SystemExit(2)
        except JqlExecutionError as exc:
            print("Query execution failed: %s" % exc, file=sys.stderr)
            raise SystemExit(1)
        except ValueError as exc:   # bad limit from run_jql
            print("Query error: %s" % exc, file=sys.stderr)
            raise SystemExit(2)

        if fmt == "json":
            print(json.dumps(result, indent=2))
        elif fmt == "csv":
            _write_jql_csv(result, sys.stdout)
            if result["truncated"]:
                print("Truncated at limit %d — more matches may exist; "
                      "raise --limit to see them." % result["limit"],
                      file=sys.stderr)
        else:
            print(_format_jql_table(result))

    # ------------------------------------------------------------------
    # Wiring helpers
    # ------------------------------------------------------------------

    def jql_vocabulary(self):
        """Serializable JQL field vocabulary for help surfaces (#302).

        One entry per queryable field: canonical name, kind (core / label /
        custom), value type, Jira aliases, and — for taxonomy/enum fields —
        the closed value list from the live config, so help examples can be
        built from values that actually match data in the target group.
        """
        return [
            {
                "name":    spec.name,
                "kind":    spec.kind,
                "type":    spec.value_type,
                "aliases": list(spec.aliases),
                "values":  list(spec.values),
            }
            for spec in self._jql_registry()
        ]

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
