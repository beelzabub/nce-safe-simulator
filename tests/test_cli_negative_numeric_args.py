"""A numeric tool param given as a bare flag must fail, not coerce to 1.

`--count -15` does not survive the argv scan: -15 begins with '-', so it reads
as the next flag and `count` lands in the prefills as True. int(True) is 1, so
`generate-epic-blocks --count -15` — "remove 15 blocking links" — silently ran
as "create 1 blocking link", and reported success the whole way.

The attached form `--count=-15` is the one that works; these tests pin both
halves of that contract, driving the real _run_tool dispatch rather than a
copy of its coercion.
"""

import pytest

from NceGitLab import _parse_tool_args
from mixins.tools import ToolsMixin


class _Recorder(ToolsMixin):
    """Captures the kwargs _run_tool would hand the tool method."""

    def __init__(self):
        self.called_with = None

    def _numeric_tool(self, count=None, dry_run=False):
        self.called_with = {"count": count, "dry_run": dry_run}


TOOL = {
    "key":         "numeric-probe",
    "description": "int + bool params, mirroring generate-epic-blocks",
    "method":      "_numeric_tool",
    "params": [
        {"name": "count",   "prompt": "Relationships (negative = remove)", "type": int,  "default": 10},
        {"name": "dry_run", "prompt": "Dry run?",                          "type": bool, "default": False},
    ],
}


@pytest.fixture()
def runner(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)          # _run_tool writes logs/<date>/...
    return _Recorder()


def test_detached_negative_value_is_swallowed_by_the_scan():
    """Documents the parser behaviour the guard exists to catch."""
    assert _parse_tool_args(["--count", "-15"])["count"] is True


def test_bare_numeric_flag_is_refused_instead_of_becoming_one(runner):
    prefills = _parse_tool_args(["--count", "-15"])
    with pytest.raises(SystemExit) as exc:
        runner._run_tool(TOOL, prefills=prefills)
    assert "--count" in str(exc.value)
    assert runner.called_with is None, "the tool must not run on a mis-parsed argument"


def test_attached_negative_value_reaches_the_tool(runner):
    prefills = _parse_tool_args(["--count=-15"])
    assert prefills["count"] == "-15"
    runner._run_tool(TOOL, prefills=prefills)
    assert runner.called_with["count"] == -15


def test_positive_int_and_bool_are_unaffected(runner):
    runner._run_tool(TOOL, prefills=_parse_tool_args(["--count", "15", "--dry_run", "true"]))
    assert runner.called_with == {"count": 15, "dry_run": True}


def test_bare_bool_flag_still_means_true(runner):
    """The guard is numeric-only — a valueless bool flag is legitimate."""
    runner._run_tool(TOOL, prefills=_parse_tool_args(["--count=1", "--dry_run"]))
    assert runner.called_with == {"count": 1, "dry_run": True}
