"""Contract test for the server-side "equivalent CLI command" builder (#140).

`build_cli_command` is the authoritative rendering of the command the web server
is about to run — echoed into every run's output so the record carries the exact
command that reproduces it. It must cover all launch classes (parameterised
tools, no-param utilities like diagnose, single/multi reports) and, like the
frontend builder, produce commands that tokenise and parse back through the real
CLI parser into the operation that was launched.

This runs in pure Python (no Node), so it always executes.
"""
import shlex

import pytest

from NceGitLab import _parse_tool_args
from mixins.tools import TOOLS
from server.app import build_cli_command

pytestmark = pytest.mark.unit


def _tool(key):
    return next(t for t in TOOLS if t["key"] == key)


def _coerce_like_cli(param, raw):
    """Mirror _run_tool's prefill coercion."""
    t = param["type"]
    if t is bool:
        return raw if isinstance(raw, bool) else str(raw).lower() in ("y", "yes", "true", "1")
    if t is int:
        return int(raw)
    if t is float:
        return float(raw)
    return raw


# ── No-param tool (the diagnose class) ─────────────────────────────────────────

def test_no_param_tool_builds_complete_command():
    cmd = build_cli_command({"tool": "diagnose"})
    assert cmd == "python3 NceGitLab.py -ut diagnose"
    # And it parses back to no prefills — a clean, runnable invocation.
    assert _parse_tool_args(shlex.split(cmd)[4:]) == {}


def test_unknown_tool_yields_empty():
    assert build_cli_command({"tool": "does-not-exist"}) == ""


# ── Parameterised tool round-trips ─────────────────────────────────────────────

def test_tool_with_values_round_trips():
    tool = _tool("import-issues")
    params = {
        "input_path": "/data/my issues.csv",   # space → quoted
        "group": "",                            # blank → omitted
        "on_existing": "skip",
        "create_missing": True,                 # default-off bool on → --flag
    }
    cmd = build_cli_command({"tool": "import-issues", "params": params})
    tokens = shlex.split(cmd)
    assert tokens[:4] == ["python3", "NceGitLab.py", "-ut", "import-issues"]
    prefills = _parse_tool_args(tokens[4:])
    assert prefills["input_path"] == "/data/my issues.csv"
    assert "group" not in prefills
    assert prefills["on_existing"] == "skip"
    assert prefills["create_missing"] is True
    # cli_only params (dry_run) never appear.
    assert "dry_run" not in prefills


def test_negative_count_round_trips():
    """generate-epic-blocks --count -10 removes relationships; the value must
    survive as -10, not collapse into a valueless boolean flag."""
    cmd = build_cli_command({"tool": "generate-epic-blocks", "params": {"count": -10}})
    prefills = _parse_tool_args(shlex.split(cmd)[4:])
    count_param = next(p for p in _tool("generate-epic-blocks")["params"] if p["name"] == "count")
    assert _coerce_like_cli(count_param, prefills["count"]) == -10


def test_default_on_bool_off_round_trips():
    """set-issue-weights' fibonacci defaults True; turning it off must be stated
    explicitly (--fibonacci=false), not omitted."""
    fib = next(p for p in _tool("set-issue-weights")["params"] if p["name"] == "fibonacci")
    off = build_cli_command({"tool": "set-issue-weights", "params": {"fibonacci": False}})
    p_off = _parse_tool_args(shlex.split(off)[4:])
    assert "fibonacci" in p_off and _coerce_like_cli(fib, p_off["fibonacci"]) is False

    on = build_cli_command({"tool": "set-issue-weights", "params": {"fibonacci": True}})
    p_on = _parse_tool_args(shlex.split(on)[4:])
    assert _coerce_like_cli(fib, p_on["fibonacci"]) is True


def test_every_tool_command_parses_to_valid_names():
    """Drift guard: for every tool, a command built from one value per param
    parses back into names that are all real params of that tool."""
    for tool in TOOLS:
        params = {}
        for p in tool["params"]:
            if p.get("cli_only"):
                continue
            t = p["type"]
            params[p["name"]] = True if t is bool else 3 if t is int else 0.5 if t is float else f"v {p['name']}"
        cmd = build_cli_command({"tool": tool["key"], "params": params})
        prefills = _parse_tool_args(shlex.split(cmd)[4:])
        valid = {p["name"] for p in tool["params"] if not p.get("cli_only")}
        assert set(prefills).issubset(valid), f"{tool['key']}: stray {set(prefills) - valid}"


# ── Report commands ────────────────────────────────────────────────────────────

def test_single_report_command():
    cmd = build_cli_command({"report": "wsjf", "formats": ["markdown"]})
    assert cmd == "python3 NceGitLab.py -r wsjf --formats markdown"


def test_multi_report_one_line_each_with_last():
    cmd = build_cli_command({
        "reports": ["wsjf", "flow_metrics"],
        "formats": ["markdown", "plotly"],
        "reuse_data": "last",
    })
    lines = cmd.splitlines()
    assert len(lines) == 2
    for line, key in zip(lines, ["wsjf", "flow_metrics"]):
        toks = shlex.split(line)
        assert toks[:4] == ["python3", "NceGitLab.py", "-r", key]
        assert "--last" in toks
        fi = toks.index("--formats")
        assert toks[fi + 1:fi + 3] == ["markdown", "plotly"]
