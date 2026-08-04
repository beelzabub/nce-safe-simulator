"""JQL query language front-end for the simulator (epic #297).

Pure Python: lexer, recursive-descent parser, AST node dataclasses,
date/duration evaluation helpers, the field registry with its GitLab
filter mapping, and the planner/executor pair — conjunctive-envelope
push-down planning plus client-side expression evaluation, result shaping,
and ORDER BY. Zero I/O and no GitLab dependency — this package never
imports the client; transport stays in ``mixins/utils.py``
(``graphql_query``) and is driven by ``mixins/query.py`` (QueryMixin),
which exposes the single ``run_jql`` entry point.
"""
from . import ast
from .lexer import JqlSyntaxError, Token, tokenize
from .parser import parse
from .dates import (
    DATE_FUNCTIONS,
    JqlEvaluationError,
    evaluate_function,
    is_date_function,
    parse_date,
    parse_duration,
    resolve_datetime,
)
from .planner import JqlPlanError, Plan, plan_query, query_mentions_current_user
from .executor import (
    EvalContext,
    JqlExecutionError,
    build_work_items_query,
    evaluate,
    shape_node,
    sort_items,
)

__all__ = [
    "ast",
    "parse",
    "tokenize",
    "Token",
    "JqlSyntaxError",
    "JqlEvaluationError",
    "DATE_FUNCTIONS",
    "is_date_function",
    "evaluate_function",
    "parse_date",
    "parse_duration",
    "resolve_datetime",
    "JqlPlanError",
    "Plan",
    "plan_query",
    "query_mentions_current_user",
    "EvalContext",
    "JqlExecutionError",
    "build_work_items_query",
    "evaluate",
    "shape_node",
    "sort_items",
]
