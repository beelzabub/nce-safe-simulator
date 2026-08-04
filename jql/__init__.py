"""JQL query language front-end for the simulator (issue #298, epic #297).

Pure Python: lexer, recursive-descent parser, AST node dataclasses, and
date/duration evaluation helpers. Zero I/O and no GitLab dependency — this
package never imports the client. Execution semantics (field resolution,
push-down planning, currentUser()) belong to the executor built on top of it.
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
