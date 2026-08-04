"""AST node dataclasses for the JQL grammar subset.

Every node carries a ``pos`` attribute: the 0-based character offset of the
construct in the source string. ``pos`` is excluded from equality so tests and
callers can compare trees structurally without threading offsets through.

Value nodes (usable on the right-hand side of a predicate or as function args):
    String, Number, DateLiteral, Duration, Empty, Function

Expression nodes (boolean clause tree, precedence NOT > AND > OR):
    Comparison, InList, IsEmpty, Not, And, Or

Top level:
    Query(where, order_by) with SortKey entries for ORDER BY.
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple, Union


# ---------------------------------------------------------------------------
# Value nodes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class String:
    """A string value. ``quoted`` records whether it appeared in quotes."""
    value: str
    quoted: bool = False
    pos: int = field(default=-1, compare=False)


@dataclass(frozen=True)
class Number:
    """A numeric literal — int when written without a decimal point."""
    value: Union[int, float]
    pos: int = field(default=-1, compare=False)


@dataclass(frozen=True)
class DateLiteral:
    """An unquoted ISO-style date such as ``2026-01-31`` (raw text kept)."""
    value: str
    pos: int = field(default=-1, compare=False)


@dataclass(frozen=True)
class Duration:
    """A relative duration such as ``-4w`` or ``1d`` (raw text kept)."""
    value: str
    pos: int = field(default=-1, compare=False)


@dataclass(frozen=True)
class Empty:
    """The EMPTY / NULL keyword used as a value (``assignee = EMPTY``)."""
    pos: int = field(default=-1, compare=False)


@dataclass(frozen=True)
class Function:
    """A function call such as ``now()`` or ``startOfDay(-1)``.

    ``name`` keeps the original spelling; consumers match case-insensitively.
    """
    name: str
    args: Tuple["Value", ...] = ()
    pos: int = field(default=-1, compare=False)


Value = Union[String, Number, DateLiteral, Duration, Empty, Function]


# ---------------------------------------------------------------------------
# Expression nodes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Comparison:
    """``field <op> value`` with op in = != > >= < <= ~ !~."""
    field: str
    op: str
    value: Value
    pos: int = field(default=-1, compare=False)


@dataclass(frozen=True)
class InList:
    """``field [NOT] IN (v1, v2, ...)``."""
    field: str
    values: Tuple[Value, ...]
    negated: bool = False
    pos: int = field(default=-1, compare=False)


@dataclass(frozen=True)
class IsEmpty:
    """``field IS [NOT] EMPTY`` (NULL is a synonym for EMPTY)."""
    field: str
    negated: bool = False
    pos: int = field(default=-1, compare=False)


@dataclass(frozen=True)
class Not:
    operand: "Expr"
    pos: int = field(default=-1, compare=False)


@dataclass(frozen=True)
class And:
    """N-ary conjunction: ``a AND b AND c`` parses to one And with 3 operands.

    Parenthesized subexpressions keep their own node, so ``(a AND b) AND c``
    is And(And(a, b), c) — semantically identical, structurally faithful.
    """
    operands: Tuple["Expr", ...]
    pos: int = field(default=-1, compare=False)


@dataclass(frozen=True)
class Or:
    """N-ary disjunction (see And for flattening rules)."""
    operands: Tuple["Expr", ...]
    pos: int = field(default=-1, compare=False)


Expr = Union[Comparison, InList, IsEmpty, Not, And, Or]


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SortKey:
    """One ORDER BY key. ``direction`` is "ASC" or "DESC" (default ASC)."""
    field: str
    direction: str = "ASC"
    pos: int = field(default=-1, compare=False)


@dataclass(frozen=True)
class Query:
    """A full query: optional boolean clause plus optional ORDER BY keys.

    ``where`` is None for an empty query or a bare ``ORDER BY ...``.
    """
    where: Optional[Expr] = None
    order_by: Tuple[SortKey, ...] = ()
    pos: int = field(default=0, compare=False)
