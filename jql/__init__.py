"""JQL query language front-end for the simulator (epic #297).

Pure Python: lexer, recursive-descent parser, AST node dataclasses,
date/duration evaluation helpers, and the field registry with its GitLab
filter mapping. Zero I/O and no GitLab dependency — this package never
imports the client; transport stays in ``mixins/utils.py``
(``graphql_query``) and is invoked by the executor mixin, not from here.
Execution semantics (field resolution, push-down planning, currentUser())
belong to the executor built on top of it.
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
]
