"""Duration and date-function evaluation for JQL values (issue #298).

Resolves the date-shaped AST value nodes — Duration (``-4w``), DateLiteral
(``2026-01-31``), quoted date strings, and the date functions ``now()``,
``startOfDay/Week/Month/Year(±n)``, ``endOf*(±n)`` — to concrete datetimes.

Only *date* semantics live here. Non-date functions (``currentUser()``,
anything unknown) raise JqlEvaluationError: their execution belongs to the
query executor, which resolves them against the live connection.

Conventions (documented, deterministic):
- Weeks start on Monday (ISO), so ``startOfWeek()`` is the most recent Monday
  at 00:00 and ``endOfWeek()`` is Sunday just before midnight.
- ``endOf*`` returns the last representable instant of the period (one
  microsecond before the next period starts).
- Function offsets: a bare integer shifts by that many of the function's own
  unit (``startOfMonth(-1)`` = start of last month); a duration string arg
  shifts the result by that duration (``startOfDay("-1w")``).
"""
import calendar
import re
from datetime import datetime, timedelta

from . import ast

_DURATION_PART_RE = re.compile(r"(\d+)\s*([wdhm])", re.IGNORECASE)
_DURATION_RE = re.compile(r"^[+-]?\s*(?:\d+\s*[wdhm]\s*)+$", re.IGNORECASE)
_INT_RE = re.compile(r"^[+-]?\d+$")

_UNIT_TIMEDELTAS = {
    "w": timedelta(weeks=1),
    "d": timedelta(days=1),
    "h": timedelta(hours=1),
    "m": timedelta(minutes=1),
}

_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
)

#: Lower-cased names of every function this module can evaluate.
DATE_FUNCTIONS = frozenset({
    "now",
    "startofday", "startofweek", "startofmonth", "startofyear",
    "endofday", "endofweek", "endofmonth", "endofyear",
})


class JqlEvaluationError(ValueError):
    """A value or function that cannot be resolved to a datetime here."""


def is_date_function(name):
    """True if ``name`` (any case) is a function this module evaluates."""
    return name.lower() in DATE_FUNCTIONS


def parse_duration(text):
    """Parse a JQL relative duration into a timedelta.

    Accepts a single signed component (``-4w``, ``1d``, ``+2h``, ``30m``) or
    a compound one (``4w 2d``); a leading sign applies to the whole duration.
    Units: w(eeks), d(ays), h(ours), m(inutes).
    """
    text = text.strip()
    if not _DURATION_RE.match(text):
        raise JqlEvaluationError("Invalid duration: %r" % text)
    sign = -1 if text.startswith("-") else 1
    total = timedelta()
    for amount, unit in _DURATION_PART_RE.findall(text):
        total += int(amount) * _UNIT_TIMEDELTAS[unit.lower()]
    return sign * total


def parse_date(text):
    """Parse a date / datetime string in the accepted JQL forms."""
    text = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise JqlEvaluationError("Invalid date: %r" % text)


def _add_months(dt, n):
    month_index = dt.month - 1 + n
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _period_start(name, now):
    """Start of the current period for a startOf*/endOf* function name."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    unit = name[len("startof"):] if name.startswith("startof") else name[len("endof"):]
    if unit == "day":
        return midnight
    if unit == "week":
        return midnight - timedelta(days=midnight.weekday())  # Monday
    if unit == "month":
        return midnight.replace(day=1)
    if unit == "year":
        return midnight.replace(month=1, day=1)
    raise JqlEvaluationError("Unknown date function: %r" % name)


def _shift_periods(name, start, n):
    """Shift a period start by n of the function's own unit."""
    if name.endswith("day"):
        return start + timedelta(days=n)
    if name.endswith("week"):
        return start + timedelta(weeks=n)
    if name.endswith("month"):
        return _add_months(start, n)
    return start.replace(year=start.year + n)  # year


def _next_period(name, start):
    return _shift_periods(name, start, 1)


def _offset_arg(arg):
    """Interpret a function argument as (periods, extra_timedelta)."""
    if isinstance(arg, ast.Number):
        arg = arg.value
    elif isinstance(arg, (ast.String, ast.Duration, ast.DateLiteral)):
        arg = arg.value
    if isinstance(arg, int):
        return arg, timedelta()
    if isinstance(arg, str):
        text = arg.strip()
        if _INT_RE.match(text):
            return int(text), timedelta()
        return 0, parse_duration(text)
    raise JqlEvaluationError("Invalid date function argument: %r" % (arg,))


def evaluate_function(name, args=(), now=None):
    """Evaluate a date function (by name, any case) to a datetime.

    ``args`` may hold AST value nodes, ints, or strings. Raises
    JqlEvaluationError for non-date functions such as ``currentUser()`` —
    those are the executor's job.
    """
    lname = name.lower()
    if lname not in DATE_FUNCTIONS:
        raise JqlEvaluationError(
            "Not a date function: %r — execution belongs to the query executor"
            % name
        )
    now = now or datetime.now()
    if lname == "now":
        if args:
            raise JqlEvaluationError("now() takes no arguments")
        return now
    if len(args) > 1:
        raise JqlEvaluationError("%s() takes at most one argument" % name)
    periods, extra = _offset_arg(args[0]) if args else (0, timedelta())
    start = _shift_periods(lname, _period_start(lname, now), periods)
    if lname.startswith("endof"):
        return _next_period(lname, start) - timedelta(microseconds=1) + extra
    return start + extra


def resolve_datetime(value, now=None):
    """Resolve a date-shaped value (AST node, str, or datetime) to a datetime.

    - Duration nodes / duration strings are relative to ``now``.
    - DateLiteral nodes, quoted Strings, and plain strings are parsed as
      dates (a string that lexes as a duration is treated as one).
    - Function nodes are evaluated via evaluate_function().
    """
    now = now or datetime.now()
    if isinstance(value, datetime):
        return value
    if isinstance(value, ast.Duration):
        return now + parse_duration(value.value)
    if isinstance(value, ast.DateLiteral):
        return parse_date(value.value)
    if isinstance(value, ast.Function):
        return evaluate_function(value.name, value.args, now=now)
    if isinstance(value, ast.String):
        value = value.value
    if isinstance(value, str):
        if _DURATION_RE.match(value.strip()) or value.strip().startswith(("-", "+")):
            return now + parse_duration(value)
        return parse_date(value)
    raise JqlEvaluationError("Cannot resolve %r to a datetime" % (value,))
