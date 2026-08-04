"""JQL duration and date-function evaluation (issue #298, jql/dates.py).

Deterministic: every evaluation pins ``now``. Covers durations (single and
compound, signed), date parsing forms, every start/end function with and
without offsets, month/year boundaries (leap February), and the contract that
non-date functions (currentUser) are refused — they belong to the executor.
"""
from datetime import datetime, timedelta

import pytest

from jql import ast, parse
from jql.dates import (
    DATE_FUNCTIONS,
    JqlEvaluationError,
    evaluate_function,
    is_date_function,
    parse_date,
    parse_duration,
    resolve_datetime,
)

pytestmark = pytest.mark.unit

# A Wednesday, mid-2026, mid-day: exercises week/month/year truncation.
NOW = datetime(2026, 8, 5, 14, 30, 45, 123456)


# ---------------------------------------------------------------------------
# Durations
# ---------------------------------------------------------------------------

class TestParseDuration:

    @pytest.mark.parametrize("text,expected", [
        ("-4w", timedelta(weeks=-4)),
        ("4w", timedelta(weeks=4)),
        ("+4w", timedelta(weeks=4)),
        ("1d", timedelta(days=1)),
        ("-1d", timedelta(days=-1)),
        ("2h", timedelta(hours=2)),
        ("30m", timedelta(minutes=30)),
        ("-10D", timedelta(days=-10)),          # units are case-insensitive
        ("1W", timedelta(weeks=1)),
    ])
    def test_single_component(self, text, expected):
        assert parse_duration(text) == expected

    def test_compound(self):
        assert parse_duration("4w 2d") == timedelta(weeks=4, days=2)
        assert parse_duration("1d 2h 30m") == timedelta(days=1, hours=2, minutes=30)

    def test_sign_applies_to_whole_compound(self):
        assert parse_duration("-4w 2d") == -timedelta(weeks=4, days=2)

    def test_surrounding_whitespace_tolerated(self):
        assert parse_duration("  -4w ") == timedelta(weeks=-4)

    @pytest.mark.parametrize("bad", ["", "w", "4", "4x", "w4", "4w2", "--4w", "four weeks"])
    def test_invalid_durations_raise(self, bad):
        with pytest.raises(JqlEvaluationError):
            parse_duration(bad)


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

class TestParseDate:

    @pytest.mark.parametrize("text,expected", [
        ("2026-01-31", datetime(2026, 1, 31)),
        ("2026/01/31", datetime(2026, 1, 31)),
        ("2026-01-31 10:30", datetime(2026, 1, 31, 10, 30)),
        ("2026-01-31 10:30:15", datetime(2026, 1, 31, 10, 30, 15)),
        ("2026-01-31T10:30", datetime(2026, 1, 31, 10, 30)),
        ("2026-01-31T10:30:15", datetime(2026, 1, 31, 10, 30, 15)),
        ("2026/01/31 10:30", datetime(2026, 1, 31, 10, 30)),
    ])
    def test_accepted_forms(self, text, expected):
        assert parse_date(text) == expected

    @pytest.mark.parametrize("bad", ["", "yesterday", "2026-13-01", "2026-01-32",
                                     "31-01-2026", "2026"])
    def test_invalid_dates_raise(self, bad):
        with pytest.raises(JqlEvaluationError):
            parse_date(bad)


# ---------------------------------------------------------------------------
# Date functions
# ---------------------------------------------------------------------------

class TestDateFunctions:

    def test_registry_and_predicate(self):
        assert "startofweek" in DATE_FUNCTIONS
        assert is_date_function("now")
        assert is_date_function("StartOfDay")       # any case
        assert not is_date_function("currentUser")
        assert not is_date_function("membersOf")

    def test_now(self):
        assert evaluate_function("now", now=NOW) == NOW

    def test_now_rejects_args(self):
        with pytest.raises(JqlEvaluationError):
            evaluate_function("now", (ast.Number(1),), now=NOW)

    def test_start_of_day(self):
        assert evaluate_function("startOfDay", now=NOW) == datetime(2026, 8, 5)

    def test_start_of_week_is_monday(self):
        assert evaluate_function("startOfWeek", now=NOW) == datetime(2026, 8, 3)

    def test_start_of_month(self):
        assert evaluate_function("startOfMonth", now=NOW) == datetime(2026, 8, 1)

    def test_start_of_year(self):
        assert evaluate_function("startOfYear", now=NOW) == datetime(2026, 1, 1)

    def test_end_of_day(self):
        assert evaluate_function("endOfDay", now=NOW) == (
            datetime(2026, 8, 6) - timedelta(microseconds=1))

    def test_end_of_week_is_sunday_night(self):
        assert evaluate_function("endOfWeek", now=NOW) == (
            datetime(2026, 8, 10) - timedelta(microseconds=1))

    def test_end_of_month(self):
        assert evaluate_function("endOfMonth", now=NOW) == (
            datetime(2026, 9, 1) - timedelta(microseconds=1))

    def test_end_of_year(self):
        assert evaluate_function("endOfYear", now=NOW) == (
            datetime(2027, 1, 1) - timedelta(microseconds=1))

    # -- integer offsets shift by the function's own unit -------------------

    def test_start_of_day_minus_one(self):
        assert evaluate_function("startOfDay", (ast.Number(-1),), now=NOW) == (
            datetime(2026, 8, 4))

    def test_start_of_week_plus_one(self):
        assert evaluate_function("startOfWeek", (ast.Number(1),), now=NOW) == (
            datetime(2026, 8, 10))

    def test_start_of_month_minus_one_handles_month_arithmetic(self):
        assert evaluate_function("startOfMonth", (ast.Number(-1),), now=NOW) == (
            datetime(2026, 7, 1))

    def test_start_of_month_across_year_boundary(self):
        assert evaluate_function("startOfMonth", (ast.Number(-8),), now=NOW) == (
            datetime(2025, 12, 1))

    def test_start_of_year_minus_one(self):
        assert evaluate_function("startOfYear", (ast.Number(-1),), now=NOW) == (
            datetime(2025, 1, 1))

    def test_end_of_month_offset_hits_leap_february(self):
        # Feb 2028 is a leap February: endOfMonth(-6) from Aug 2026 -> Feb 2026 (28d)
        assert evaluate_function("endOfMonth", (ast.Number(-6),), now=NOW) == (
            datetime(2026, 3, 1) - timedelta(microseconds=1))
        leap_now = datetime(2028, 3, 15)
        assert evaluate_function("endOfMonth", (ast.Number(-1),), now=leap_now) == (
            datetime(2028, 3, 1) - timedelta(microseconds=1))
        assert evaluate_function("startOfMonth", (ast.Number(-1),), now=leap_now) == (
            datetime(2028, 2, 1))

    # -- duration-string offsets shift the result ---------------------------

    def test_duration_string_arg_shifts_result(self):
        assert evaluate_function("startOfDay", (ast.String("-1w", quoted=True),),
                                 now=NOW) == datetime(2026, 7, 29)

    def test_duration_node_arg(self):
        assert evaluate_function("startOfDay", (ast.Duration("1d"),), now=NOW) == (
            datetime(2026, 8, 6))

    def test_quoted_integer_arg(self):
        assert evaluate_function("startOfDay", (ast.String("-2", quoted=True),),
                                 now=NOW) == datetime(2026, 8, 3)

    def test_plain_python_args_accepted(self):
        assert evaluate_function("startOfDay", (-1,), now=NOW) == datetime(2026, 8, 4)
        assert evaluate_function("startOfDay", ("-1d",), now=NOW) == datetime(2026, 8, 4)

    # -- refusals -----------------------------------------------------------

    def test_current_user_is_not_a_date_function(self):
        with pytest.raises(JqlEvaluationError, match="executor"):
            evaluate_function("currentUser", now=NOW)

    def test_unknown_function_raises(self):
        with pytest.raises(JqlEvaluationError):
            evaluate_function("membersOf", (ast.String("x"),), now=NOW)

    def test_too_many_args_raises(self):
        with pytest.raises(JqlEvaluationError):
            evaluate_function("startOfDay", (ast.Number(1), ast.Number(2)), now=NOW)

    def test_bad_arg_raises(self):
        with pytest.raises(JqlEvaluationError):
            evaluate_function("startOfDay", (ast.String("soon"),), now=NOW)


# ---------------------------------------------------------------------------
# resolve_datetime over AST nodes (the parser -> dates handoff)
# ---------------------------------------------------------------------------

class TestResolveDatetime:

    def _value(self, query):
        return parse(query).where.value

    def test_duration_node_is_relative_to_now(self):
        value = self._value("updated >= -4w")
        assert resolve_datetime(value, now=NOW) == NOW - timedelta(weeks=4)

    def test_date_literal_node(self):
        value = self._value("created >= 2026-01-31")
        assert resolve_datetime(value, now=NOW) == datetime(2026, 1, 31)

    def test_quoted_datetime_string(self):
        value = self._value('created >= "2026-01-31 10:30"')
        assert resolve_datetime(value, now=NOW) == datetime(2026, 1, 31, 10, 30)

    def test_quoted_duration_string(self):
        value = self._value('created >= "-1d"')
        assert resolve_datetime(value, now=NOW) == NOW - timedelta(days=1)

    def test_function_node(self):
        value = self._value("created >= startOfWeek(-1)")
        assert resolve_datetime(value, now=NOW) == datetime(2026, 7, 27)

    def test_now_function_node(self):
        value = self._value("created <= now()")
        assert resolve_datetime(value, now=NOW) == NOW

    def test_datetime_passthrough(self):
        assert resolve_datetime(NOW, now=NOW) == NOW

    def test_plain_string(self):
        assert resolve_datetime("2026-01-31", now=NOW) == datetime(2026, 1, 31)

    def test_number_node_is_not_a_date(self):
        value = self._value("weight >= 5")
        with pytest.raises(JqlEvaluationError):
            resolve_datetime(value, now=NOW)

    def test_empty_node_is_not_a_date(self):
        value = self._value("due = EMPTY")
        with pytest.raises(JqlEvaluationError):
            resolve_datetime(value, now=NOW)

    def test_current_user_function_refused(self):
        value = self._value("assignee = currentUser()")
        with pytest.raises(JqlEvaluationError):
            resolve_datetime(value, now=NOW)
