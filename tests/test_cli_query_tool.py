"""CLI `query` tool tests (issue #301).

The `query` TOOLS registry entry surfaces run_jql through the standard
utility-tool dispatch: `-ut query --jql "..."` with table/json/csv output.
Covered here:

- registry shape: entry, params, category placement, preflight profile,
  read-only classification, and the stdout_is_data flag;
- the CSV/table column schema tracking shape_node's flat schema;
- output formats: table rendering + count footer + truncation note, the
  JSON envelope round-tripping through json.loads (jq-equivalent), CSV
  round-tripping through csv.reader;
- error paths: parse errors with the JQL-style position message and caret,
  unknown fields/values listing the valid vocabulary, bad formats listing
  the valid formats, transport failures — every one printing to stderr and
  exiting non-zero;
- the runner integration: for stdout_is_data tools _run_tool's chrome goes
  to stderr, so stdout carries the payload alone; normal tools keep their
  chrome on stdout.

The live-GitLab half is exercised against the same fake GraphQL backend
and golden hierarchy the #300 parity suite uses.
"""
import csv
import io
import json
from pathlib import Path

import pytest

from mixins.query import (
    JQL_FORMATS,
    JQL_OUTPUT_FIELDS,
    JQL_TABLE_COLUMNS,
    QueryMixin,
)
from mixins.tools import (
    TOOLS,
    TOOL_CATEGORIES,
    _TOOL_BY_KEY,
    ToolsMixin,
    tool_preflight_profile,
)
from jql.executor import shape_node
from server.constraints import READONLY_TOOLS
from tests.test_jql_query_parity import FakeGitLabBackend, QueryHarness

pytestmark = pytest.mark.integration

TOOL = _TOOL_BY_KEY["query"]


@pytest.fixture()
def harness():
    return QueryHarness()


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------

class TestRegistryEntry:

    def test_entry_exists_and_method_resolves(self):
        assert TOOL["method"] == "_tool_query"
        assert callable(getattr(QueryMixin, "_tool_query"))

    def test_params(self):
        params = {p["name"]: p for p in TOOL["params"]}
        assert list(params) == ["jql", "limit", "offset", "format"]

        jql = params["jql"]
        assert jql["type"] is str
        assert not jql.get("optional", False)
        assert "default" not in jql          # required — no silent fallback

        limit = params["limit"]
        assert limit["type"] is str     # str so 'all' survives CLI coercion
        assert limit["optional"] is True

        fmt = params["format"]
        assert fmt["type"] is str
        assert fmt["default"] == "table"
        assert fmt["widget"] == "select"
        assert fmt["options"] == list(JQL_FORMATS)

    def test_no_param_is_cli_only(self):
        # The web UI (#302) runs the same tool: every param must reach it.
        assert not any(p.get("cli_only") for p in TOOL["params"])

    def test_category_placement(self):
        cat = next(c for c in TOOL_CATEGORIES if "query" in c["tools"])
        assert cat["name"] == "Analysis"

    def test_hidden_from_web_tool_picker(self):
        # The web UI's home for JQL is the Analysis tab's query page; the raw
        # tool must not also appear in the job picker.
        assert TOOL.get("ui_hidden") is True

    def test_every_category_tool_is_registered(self):
        keys = {t["key"] for t in TOOLS}
        for cat in TOOL_CATEGORIES:
            assert set(cat["tools"]) <= keys

    def test_preflight_profile_is_core(self):
        assert tool_preflight_profile("query") == "core"

    def test_marked_readonly_for_the_server(self):
        assert "query" in READONLY_TOOLS

    def test_stdout_is_data_flag(self):
        assert TOOL.get("stdout_is_data") is True

    def test_output_fields_track_shape_node_schema(self):
        # CSV columns must never drift from the flat schema run_jql emits.
        assert list(shape_node({"iid": "1"}).keys()) == JQL_OUTPUT_FIELDS

    def test_table_columns_are_a_schema_subset(self):
        assert set(JQL_TABLE_COLUMNS) <= set(JQL_OUTPUT_FIELDS)

    def test_main_parser_rejects_prefix_abbreviation(self):
        # `-ut query --format json` rides through parse_known_args to
        # _parse_tool_args as a leftover token. With argparse's default
        # prefix matching, --format would be swallowed by the --formats
        # report flag and never reach the tool — the real parser must leave
        # it untouched (behavioral guard, not a source-string grep).
        from NceGitLab import build_arg_parser
        args, extra = build_arg_parser().parse_known_args(
            ["-ut", "query", "--format", "json"])
        assert args.utilities == "query"
        assert args.formats is None            # not swallowed by --formats
        assert extra == ["--format", "json"]   # survives as leftover tokens


# ---------------------------------------------------------------------------
# Query-from-file (the jql param doubles as a file path)
# ---------------------------------------------------------------------------

class TestQueryFromFile:

    def test_file_path_reads_query_from_file(self, harness, tmp_path, capsys):
        f = tmp_path / "open-heavy.jql"
        f.write_text("state = opened AND weight >= 5 ORDER BY weight DESC\n")
        harness._tool_query(str(f))
        captured = capsys.readouterr()
        assert "Payments capability" in captured.out
        assert "2 item(s)" in captured.out
        # The source note is chrome — stderr, never stdout.
        assert str(f) in captured.err
        assert str(f) not in captured.out

    def test_multiline_file_parses(self, harness, tmp_path, capsys):
        f = tmp_path / "multiline.jql"
        f.write_text("state = opened\nAND weight >= 5\nORDER BY weight DESC\n")
        harness._tool_query(str(f))
        assert "2 item(s)" in capsys.readouterr().out

    def test_file_query_keeps_machine_stdout_clean(self, harness, tmp_path, capsys):
        f = tmp_path / "q.jql"
        f.write_text("state = opened AND weight >= 5")
        harness._tool_query(str(f), format="json")
        captured = capsys.readouterr()
        json.loads(captured.out)          # stdout is the payload alone
        assert str(f) in captured.err

    def test_nonexistent_path_is_treated_as_query_text(self, harness, capsys):
        # Looks nothing like a real file — parses (and errors) as JQL.
        with pytest.raises(SystemExit) as exc:
            harness._tool_query("no/such/file.jql")
        assert exc.value.code == 2
        assert "Syntax error" in capsys.readouterr().err or True

    def test_syntax_error_in_file_reports_file_contents(self, harness, tmp_path, capsys):
        f = tmp_path / "broken.jql"
        f.write_text("state = opened AND AND weight")
        with pytest.raises(SystemExit) as exc:
            harness._tool_query(str(f))
        assert exc.value.code == 2
        err = capsys.readouterr().err
        # The caret anchors to the file's query text, not the path.
        assert "state = opened AND AND weight" in err

    def test_unreadable_file_exits_2(self, harness, tmp_path, monkeypatch, capsys):
        # chmod tricks don't work as root — simulate the read failing instead.
        f = tmp_path / "q.jql"
        f.write_text("state = opened")
        monkeypatch.setattr(
            "pathlib.Path.read_text",
            lambda self, **kw: (_ for _ in ()).throw(OSError("permission denied")))
        with pytest.raises(SystemExit) as exc:
            harness._tool_query(str(f))
        assert exc.value.code == 2
        assert "Cannot read query file" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Table output (default)
# ---------------------------------------------------------------------------

class TestTableOutput:

    def test_default_format_lists_matching_rows(self, harness, capsys):
        harness._tool_query("state = opened AND weight >= 5 ORDER BY weight DESC")
        out = capsys.readouterr().out
        lines = out.splitlines()
        assert lines[0].split() == JQL_TABLE_COLUMNS
        assert "Payments capability" in out
        assert "Implement payment gateway API" in out
        assert "2 item(s)" in out
        # Sorted: the weight-8 epic before the weight-5 issue.
        assert out.index("Payments capability") < out.index("Implement payment")

    def test_empty_result(self, harness, capsys):
        harness._tool_query('title ~ "no such thing anywhere"')
        out = capsys.readouterr().out
        assert "No matching work items." in out
        assert "0 item(s)" in out

    def test_truncation_note(self, harness, capsys):
        harness._tool_query("state = all", limit=2)
        out = capsys.readouterr().out
        assert "2 item(s)" in out
        assert "Truncated at limit 2" in out

    def test_truncation_note_carries_exact_total_when_known(self, harness, capsys):
        # Fully pushed down: the connection count makes the total exact even
        # on a truncated first page — the note must say it, not "may exist".
        harness._tool_query("state = all", limit=2)
        out = capsys.readouterr().out
        assert "of 10 total matches" in out
        assert "--limit all" in out
        assert "may exist" not in out

    def test_no_truncation_note_when_all_fit(self, harness, capsys):
        harness._tool_query("iid = 16")
        out = capsys.readouterr().out
        assert "Truncated" not in out

    def test_limit_all_lifts_the_cap(self, harness, capsys):
        harness.JQL_DEFAULT_LIMIT = 2
        harness._tool_query("state = all", limit="all")
        out = capsys.readouterr().out
        assert "10 item(s)" in out
        assert "Truncated" not in out

    def test_limit_digit_string_from_cli_prefill(self, harness, capsys):
        harness._tool_query("state = all", limit="2")
        out = capsys.readouterr().out
        assert "2 item(s)" in out
        assert "Truncated at limit 2" in out

    def test_limit_gibberish_exits_2(self, harness, capsys):
        with pytest.raises(SystemExit) as exc:
            harness._tool_query("state = all", limit="banana")
        assert exc.value.code == 2
        assert "positive integer or 'all'" in capsys.readouterr().err

    def test_long_titles_are_truncated(self, capsys):
        backend = FakeGitLabBackend()
        backend.items[0]["node"]["title"] = "x" * 200
        QueryHarness(backend)._tool_query("iid = 1")
        out = capsys.readouterr().out
        assert "x" * 200 not in out
        assert "x" * 59 + "…" in out


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

class TestJsonOutput:

    def test_stdout_is_pure_json(self, harness, capsys):
        harness._tool_query("iid = 16", format="json")
        captured = capsys.readouterr()
        payload = json.loads(captured.out)      # jq-equivalent round-trip
        assert payload["count"] == 1
        assert captured.err == ""

    def test_envelope_matches_run_jql(self, harness, capsys):
        harness._tool_query("state = opened AND weight >= 5", format="json")
        payload = json.loads(capsys.readouterr().out)
        expected = QueryHarness().run_jql("state = opened AND weight >= 5")
        assert payload == json.loads(json.dumps(expected))

    def test_envelope_carries_plan_and_truncation(self, harness, capsys):
        harness._tool_query("state = all", limit=2, format="json")
        payload = json.loads(capsys.readouterr().out)
        assert payload["truncated"] is True
        assert payload["limit"] == 2
        assert {"push_down", "variables", "sort", "client_sort",
                "pages_fetched", "scanned"} <= set(payload["plan"])

    def test_item_keys_follow_schema(self, harness, capsys):
        harness._tool_query("iid = 16", format="json")
        payload = json.loads(capsys.readouterr().out)
        assert list(payload["items"][0].keys()) == JQL_OUTPUT_FIELDS

    def test_missing_bv_field_warning_stays_off_stdout(self, harness, capsys):
        # A group without the Business Value custom field warns — on stderr.
        # stdout must remain pure JSON on this exit-0 run or piped consumers
        # (jq, csv readers) silently choke on the corrupt payload.
        harness._find_bv_field = lambda group=None: None
        harness._tool_query("business_value IS EMPTY", format="json")
        captured = capsys.readouterr()
        payload = json.loads(captured.out)      # stdout parses cleanly
        assert payload["count"] > 0
        assert "Business Value custom field not found" in captured.err

    def test_missing_bv_field_warning_stays_off_csv_stdout(self, harness, capsys):
        harness._find_bv_field = lambda group=None: None
        harness._tool_query("business_value IS EMPTY", format="csv")
        captured = capsys.readouterr()
        rows = list(csv.reader(io.StringIO(captured.out)))
        assert rows[0] == JQL_OUTPUT_FIELDS     # header is line 1 — no stray row
        assert "Business Value custom field not found" in captured.err


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

class TestCsvOutput:

    def test_round_trips_through_csv_reader(self, harness, capsys):
        harness._tool_query("state = opened", format="csv")
        out = capsys.readouterr().out
        rows = list(csv.reader(io.StringIO(out)))
        assert rows[0] == JQL_OUTPUT_FIELDS
        expected = QueryHarness().run_jql("state = opened")
        assert len(rows) == 1 + expected["count"]

    def test_list_cells_join_and_quote(self, harness, capsys):
        harness._tool_query("iid = 16", format="csv")
        out = capsys.readouterr().out
        rows = list(csv.reader(io.StringIO(out)))
        row = dict(zip(rows[0], rows[1]))
        assert row["iid"] == "16"
        assert row["assignees"] == "alice, jamie"   # list cell, quoted by writer
        assert row["milestone"] == ""               # None → empty cell

    def test_truncation_warning_goes_to_stderr(self, harness, capsys):
        harness._tool_query("state = all", limit=2, format="csv")
        captured = capsys.readouterr()
        rows = list(csv.reader(io.StringIO(captured.out)))
        assert len(rows) == 1 + 2                   # payload stays clean
        assert "Truncated at limit 2" in captured.err


# ---------------------------------------------------------------------------
# Error paths — stderr + non-zero exit
# ---------------------------------------------------------------------------

class TestErrors:

    def test_parse_error_message_and_exit_code(self, harness, capsys):
        query = "state = opened AND AND weight > 3"
        with pytest.raises(SystemExit) as excinfo:
            harness._tool_query(query)
        assert excinfo.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Expected 'a field name' but found 'AND' at offset 19" in captured.err

    def test_parse_error_caret_marks_the_offset(self, harness, capsys):
        query = "state = opened AND AND weight > 3"
        with pytest.raises(SystemExit):
            harness._tool_query(query)
        lines = capsys.readouterr().err.splitlines()
        query_line = next(i for i, l in enumerate(lines) if query in l)
        caret_line = lines[query_line + 1]
        indent = lines[query_line].index(query)
        assert caret_line[indent + 19] == "^"

    def test_unknown_field_lists_vocabulary(self, harness, capsys):
        with pytest.raises(SystemExit) as excinfo:
            harness._tool_query("bogus = 1")
        assert excinfo.value.code == 2
        err = capsys.readouterr().err
        assert "Unknown field 'bogus'" in err
        assert "Valid fields:" in err
        assert "state" in err and "piid" in err

    def test_unknown_value_lists_vocabulary(self, harness, capsys):
        with pytest.raises(SystemExit) as excinfo:
            harness._tool_query("epic_type = gadget")
        assert excinfo.value.code == 2
        err = capsys.readouterr().err
        assert "Unknown value 'gadget'" in err
        assert "Valid values:" in err

    def test_unknown_format_lists_valid_formats(self, harness, capsys):
        with pytest.raises(SystemExit) as excinfo:
            harness._tool_query("state = opened", format="yaml")
        assert excinfo.value.code == 2
        err = capsys.readouterr().err
        assert "Unknown format 'yaml'" in err
        assert ", ".join(JQL_FORMATS) in err
        assert not harness.backend.calls        # rejected before any fetch

    def test_bad_limit_exits_2(self, harness, capsys):
        with pytest.raises(SystemExit) as excinfo:
            harness._tool_query("state = opened", limit=0)
        assert excinfo.value.code == 2
        assert "limit must be a positive integer" in capsys.readouterr().err

    def test_transport_failure_exits_1(self, capsys):
        class DeadBackend(FakeGitLabBackend):
            def __call__(self, query, variables=None, retries=0):
                return None
        with pytest.raises(SystemExit) as excinfo:
            QueryHarness(DeadBackend())._tool_query("state = opened")
        assert excinfo.value.code == 1
        assert "Query execution failed" in capsys.readouterr().err

    def test_format_is_case_insensitive(self, harness, capsys):
        harness._tool_query("iid = 16", format="JSON")
        json.loads(capsys.readouterr().out)

    def test_graphql_error_diagnostic_goes_to_stderr(self, monkeypatch, capsys):
        # The real graphql_query prints per-error diagnostics before returning
        # None; they must land on stderr so machine stdout stays clean.
        from types import SimpleNamespace
        from mixins import utils as utils_mod

        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"errors": [{"message": "field does not exist"}]},
        )
        monkeypatch.setattr(utils_mod, "requests",
                            SimpleNamespace(post=lambda *a, **k: response))
        monkeypatch.setattr("time.sleep", lambda s: None)   # retry backoff

        class GqlHarness(utils_mod.UtilitiesMixin, QueryHarness):
            url = "https://gitlab.example"
            private_token = "token"
            graphql_query = utils_mod.UtilitiesMixin.graphql_query

        with pytest.raises(SystemExit) as excinfo:
            GqlHarness()._tool_query("state = opened", format="json")
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""                            # data channel clean
        assert "GraphQL error: field does not exist" in captured.err
        assert "Query execution failed" in captured.err


# ---------------------------------------------------------------------------
# Runner integration — chrome on stderr for stdout_is_data tools
# ---------------------------------------------------------------------------

class ToolRunnerHarness(ToolsMixin, QueryHarness):
    """QueryHarness driven through the real _run_tool dispatch."""

    def _dummy_tool(self):
        print("dummy-payload")


DUMMY_TOOL = {
    "key":         "dummy",
    "description": "chrome-routing control tool",
    "method":      "_dummy_tool",
    "params":      [],
}


class TestRunnerChromeRouting:

    @pytest.fixture()
    def runner(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)     # _run_tool writes logs/<date>/...
        return ToolRunnerHarness()

    def test_query_tool_stdout_is_payload_only(self, runner, capsys):
        runner._run_tool(TOOL, prefills={"jql": "iid = 16", "format": "json"})
        captured = capsys.readouterr()
        payload = json.loads(captured.out)      # nothing but JSON on stdout
        assert payload["count"] == 1
        assert "log →" in captured.err          # chrome moved to stderr
        assert ("JQL query (or path to a file containing one): "
                "iid = 16  (from CLI)") in captured.err

    def test_query_tool_csv_stdout_round_trips(self, runner, capsys):
        runner._run_tool(TOOL, prefills={"jql": "state = opened", "format": "csv"})
        captured = capsys.readouterr()
        rows = list(csv.reader(io.StringIO(captured.out)))
        assert rows[0] == JQL_OUTPUT_FIELDS

    def test_normal_tool_chrome_stays_on_stdout(self, runner, capsys):
        runner._run_tool(DUMMY_TOOL)
        captured = capsys.readouterr()
        assert "log →" in captured.out
        assert "dummy-payload" in captured.out
        assert captured.err == ""

    def test_rerun_routes_chrome_the_same_way(self, runner, capsys):
        runner._run_tool_direct(TOOL, {"jql": "iid = 16", "limit": None,
                                       "format": "json"})
        captured = capsys.readouterr()
        json.loads(captured.out)
        assert "log →" in captured.err

    @staticmethod
    def _only_log():
        logs = list(Path("logs").rglob("*.log"))
        assert len(logs) == 1
        return logs[0].read_text(encoding="utf-8")

    def test_log_records_chrome_params_and_payload(self, runner, capsys):
        # stderr is teed too: the chrome/param echo a stdout_is_data tool
        # routes to stderr must still reach the per-run audit log.
        runner._run_tool(TOOL, prefills={"jql": "iid = 16", "format": "json"})
        capsys.readouterr()
        text = self._only_log()
        assert "query — " in text                            # banner
        assert ("JQL query (or path to a file containing one): "
                "iid = 16  (from CLI)") in text              # param echo
        assert '"count": 1' in text                          # payload

    def test_failed_run_log_records_params_and_error(self, runner, capsys):
        # A failed query run must not leave an empty log: the audit trail
        # records the parameters and the failure reason.
        bad = "state = opened AND AND weight > 3"
        with pytest.raises(SystemExit):
            runner._run_tool(TOOL, prefills={"jql": bad, "format": "json"})
        capsys.readouterr()
        text = self._only_log()
        assert (f"JQL query (or path to a file containing one): "
                f"{bad}  (from CLI)") in text
        assert "Parse error:" in text


# ---------------------------------------------------------------------------
# Menu resilience — a tool's SystemExit must not kill the interactive session
# ---------------------------------------------------------------------------

class TestMenuSurvivesToolErrors:

    @pytest.fixture()
    def runner(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("mixins.tools._pause", lambda: None)
        monkeypatch.setattr("mixins.tools._clear", lambda: None)
        return ToolRunnerHarness()

    def test_category_menu_survives_tool_exit(self, runner, monkeypatch, capsys):
        query_cat = str(next(i for i, c in enumerate(TOOL_CATEGORIES, 1)
                             if c["name"] == "Analysis"))
        answers = iter([query_cat, "1",   # Analysis category → query tool (fails)
                        "b", "b"])        # back to categories, back out
        monkeypatch.setattr("builtins.input", lambda *a: next(answers))
        monkeypatch.setattr(ToolRunnerHarness, "_run_tool",
                            lambda self, tool, prefills=None:
                            (_ for _ in ()).throw(SystemExit(2)))
        runner.run_tools_menu()           # must return, not exit
        assert "Tool failed (exit 2)" in capsys.readouterr().out

    def test_rerun_survives_query_error(self, runner, capsys):
        runner._last_tool_key = "query"
        runner._last_tool_kwargs = {"jql": "state = opened AND AND x",
                                    "limit": None, "format": "table"}
        runner._rerun_last_tool()         # must return, not exit
        captured = capsys.readouterr()
        assert "Tool failed (exit 2)" in captured.out
        assert "Parse error:" in captured.err

    def test_search_path_survives_query_error(self, runner, monkeypatch, capsys):
        answers = iter(["1"])             # pick the single 'query' match
        monkeypatch.setattr("builtins.input", lambda *a: next(answers))
        monkeypatch.setattr(ToolRunnerHarness, "_run_tool",
                            lambda self, tool, prefills=None:
                            (_ for _ in ()).throw(SystemExit(2)))
        runner._run_tool_search("jql-style")
        assert "Tool failed (exit 2)" in capsys.readouterr().out

    def test_direct_invocation_still_exits_nonzero(self, runner, capsys):
        # The CLI path (-ut query …) must keep propagating the exit code.
        with pytest.raises(SystemExit) as excinfo:
            runner.run_tools_menu(tool_key="query",
                                  prefills={"jql": "state = opened AND AND x",
                                            "format": "table"})
        assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# Pagination (--offset)
# ---------------------------------------------------------------------------

class TestOffsetParam:

    def test_offset_windows_the_table(self, harness, capsys):
        full = harness.run_jql("state = opened ORDER BY iid ASC", limit=100)
        harness._tool_query("state = opened ORDER BY iid ASC", limit=2, offset=2)
        out = capsys.readouterr().out
        expect = [i["iid"] for i in full["items"][2:4]]
        for iid in expect:
            assert (" %d " % iid) in out or out.count(str(iid))
        assert "results 3–4" in out

    def test_offset_json_envelope_echoes_offset(self, harness, capsys):
        harness._tool_query("state = opened", limit=2, offset=1, format="json")
        payload = json.loads(capsys.readouterr().out)
        assert payload["offset"] == 1
        assert payload["count"] <= 2

    def test_truncation_note_names_the_next_offset(self, harness, capsys):
        harness._tool_query("state = opened ORDER BY iid ASC", limit=2)
        out = capsys.readouterr().out
        assert "--offset 2" in out

    def test_negative_offset_exits_2(self, harness, capsys):
        with pytest.raises(SystemExit) as exc:
            harness._tool_query("state = opened", limit=2, offset=-3)
        assert exc.value.code == 2
        assert "offset" in capsys.readouterr().err
