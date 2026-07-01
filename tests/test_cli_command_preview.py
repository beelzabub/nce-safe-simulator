"""End-to-end contract test for the UI's "equivalent CLI command" feature (#140).

The command string is built in the browser (frontend/src/composables/useCliCommand.js),
but it only has value if it actually runs: the flags it emits must tokenize (as a
POSIX shell would) and parse back — through the real CLI parser `_parse_tool_args`
— into the exact prefills the operation was launched with.

So this test drives the **real JS builder** via Node and feeds its output through
the **real Python parser**, closing the loop across both languages. It is skipped
when Node isn't on PATH (the builder is still exercised in the browser).
"""
import json
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from NceGitLab import _parse_tool_args
from mixins.tools import TOOLS

pytestmark = pytest.mark.unit

_NODE = shutil.which("node")
_COMPOSABLE = (
    Path(__file__).resolve().parent.parent
    / "frontend" / "src" / "composables" / "useCliCommand.js"
)

_HARNESS = """
import { buildToolCommand, buildReportCommand, shellQuote } from './useCliCommand.mjs'
import { readFileSync } from 'node:fs'
const scenarios = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const out = scenarios.map(s => {
  if (s.kind === 'tool')   return buildToolCommand(s.tool, s.values)
  if (s.kind === 'report') return buildReportCommand(s.reports, s.formats, s.useLast)
  if (s.kind === 'quote')  return shellQuote(s.value)
  return null
})
process.stdout.write(JSON.stringify(out))
"""


def _run_builder(scenarios, tmp_path):
    """Copy the (dependency-free) composable next to a Node harness and run it,
    returning the list of generated strings — one per scenario."""
    # The composable imports nothing, so a verbatim copy is a faithful module.
    (tmp_path / "useCliCommand.mjs").write_text(_COMPOSABLE.read_text())
    (tmp_path / "harness.mjs").write_text(_HARNESS)
    scen_file = tmp_path / "scenarios.json"
    scen_file.write_text(json.dumps(scenarios))
    res = subprocess.run(
        [_NODE, str(tmp_path / "harness.mjs"), str(scen_file)],
        capture_output=True, text=True, timeout=30,
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def _tool(key):
    return next(t for t in TOOLS if t["key"] == key)


def _web_params(tool):
    """The params the web payload exposes (cli_only ones are hidden from the UI,
    so the builder never sees them)."""
    return [p for p in tool["params"] if not p.get("cli_only")]


def _coerce_like_cli(param, raw):
    """Mirror _run_tool's prefill coercion so we compare against the launched value."""
    t = param["type"]
    if t is bool:
        return raw if isinstance(raw, bool) else str(raw).lower() in ("y", "yes", "true", "1")
    if t is int:
        return int(raw)
    if t is float:
        return float(raw)
    return raw


requires_node = pytest.mark.skipif(_NODE is None, reason="node not on PATH")


# ── Tool command round-trips through _parse_tool_args ──────────────────────────

@requires_node
def test_import_epics_command_round_trips(tmp_path):
    tool = _tool("import-epics")
    # Values with a space (must be shell-quoted) and a bool.
    values = {
        "input_path": "/data/epics export.csv",   # space → quoted
        "group": "saic-study-group/My Portfolio",  # slash + space
        "dest_group": "saic-study-group/My Portfolio/team-a",
        "source_root": "ns-a/port",
        "on_existing": "update",
        "unresolved_parent": "label",
        "create_missing": True,                    # bool → --flag
    }
    scenarios = [{"kind": "tool", "tool": {"key": tool["key"], "params": _web_params_json(tool)}, "values": values}]
    cmd = _run_builder(scenarios, tmp_path)[0]

    tokens = shlex.split(cmd)                       # exactly what a shell hands argv
    assert tokens[:4] == ["python3", "NceGitLab.py", "-ut", "import-epics"]

    prefills = _parse_tool_args(tokens[4:])
    # Every set value comes back, correctly coerced; the space survived quoting.
    assert prefills["input_path"] == "/data/epics export.csv"
    assert prefills["group"] == "saic-study-group/My Portfolio"
    assert prefills["dest_group"] == "saic-study-group/My Portfolio/team-a"
    assert prefills["source_root"] == "ns-a/port"
    assert prefills["on_existing"] == "update"
    assert prefills["create_missing"] is True      # bare flag → True


@requires_node
def test_blank_and_false_values_are_omitted(tmp_path):
    tool = _tool("import-issues")
    values = {
        "input_path": "issues.csv",
        "group": "",                    # blank → omitted (CLI uses config default)
        "target_project_path": None,    # blank → omitted
        "source_root": "",              # blank → omitted
        "create_missing": False,        # false bool → omitted (no negative flag)
        "on_existing": "skip",
    }
    scenarios = [{"kind": "tool", "tool": {"key": tool["key"], "params": _web_params_json(tool)}, "values": values}]
    cmd = _run_builder(scenarios, tmp_path)[0]
    prefills = _parse_tool_args(shlex.split(cmd)[4:])

    assert prefills == {"input_path": "issues.csv", "on_existing": "skip"}
    assert "group" not in prefills
    assert "create_missing" not in prefills


@requires_node
def test_every_tool_emits_only_valid_param_names(tmp_path):
    """Drift guard: for every tool, a command built from one value per web param
    parses back into names that are all real params of that tool."""
    scenarios = []
    metas = []
    for tool in TOOLS:
        wp = _web_params(tool)
        values = {}
        for p in wp:
            if p["type"] is bool:
                values[p["name"]] = True
            elif p["type"] in (int,):
                values[p["name"]] = 3
            elif p["type"] in (float,):
                values[p["name"]] = 0.5
            else:
                values[p["name"]] = f"val for {p['name']}"   # space → forces quoting
        scenarios.append({"kind": "tool", "tool": {"key": tool["key"], "params": _web_params_json(tool)}, "values": values})
        metas.append((tool["key"], {p["name"] for p in wp}))

    cmds = _run_builder(scenarios, tmp_path)
    for (key, valid_names), cmd in zip(metas, cmds):
        tokens = shlex.split(cmd)
        assert tokens[2:4] == ["-ut", key]
        prefills = _parse_tool_args(tokens[4:])
        assert set(prefills).issubset(valid_names), f"{key}: stray flags {set(prefills) - valid_names}"


# ── Report command shape ───────────────────────────────────────────────────────

@requires_node
def test_report_command_one_line_per_report(tmp_path):
    scenarios = [{
        "kind": "report",
        "reports": ["wsjf", "flow_metrics"],
        "formats": ["markdown", "plotly"],
        "useLast": True,
    }]
    cmd = _run_builder(scenarios, tmp_path)[0]
    lines = cmd.splitlines()
    assert len(lines) == 2
    for line, rk in zip(lines, ["wsjf", "flow_metrics"]):
        tokens = shlex.split(line)
        assert tokens[:4] == ["python3", "NceGitLab.py", "-r", rk]
        assert "--formats" in tokens
        fi = tokens.index("--formats")
        assert tokens[fi + 1:fi + 3] == ["markdown", "plotly"]
        assert "--last" in tokens


@requires_node
def test_report_command_without_last_or_formats(tmp_path):
    scenarios = [{"kind": "report", "reports": ["wsjf"], "formats": [], "useLast": False}]
    cmd = _run_builder(scenarios, tmp_path)[0]
    assert cmd == "python3 NceGitLab.py -r wsjf"


# ── Shell quoting ──────────────────────────────────────────────────────────────

@requires_node
def test_shell_quoting_survives_tokenization(tmp_path):
    tricky = ["plain", "has space", "has'quote", "a/b:c-d", "semi;colon", ""]
    scenarios = [{"kind": "quote", "value": v} for v in tricky]
    quoted = _run_builder(scenarios, tmp_path)
    for original, q in zip(tricky, quoted):
        # A shell tokenizing "--x <quoted>" must recover the original verbatim.
        assert shlex.split(f"--x {q}") == ["--x", original]


def _web_params_json(tool):
    """The web param list as the /api/tools payload would serialize it (type as a
    string), which is what the JS builder receives."""
    type_name = {str: "str", bool: "bool", int: "int", float: "float"}
    return [
        {"name": p["name"], "type": type_name[p["type"]]}
        for p in _web_params(tool)
    ]
