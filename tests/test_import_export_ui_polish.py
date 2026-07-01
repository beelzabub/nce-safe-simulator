"""Tests for the import/export UI polish (Refs #126).

Covers the three deliverables, and — critically — the hard constraint that the
explicit-path CLI contract is unchanged:

  1. UI (auto-named) exports get a unique, UTC-timestamped filename so repeated
     exports never clobber one another.
  2. An explicit CSV/JSON format selector (fmt) drives both the auto-named
     extension and the serialization format; explicit CLI output paths still
     take their format from the path extension (fmt is ignored on that path).
  3. dry_run is hidden from the web UI (cli_only) but retained for the CLI, and
     mutating imports keep a confirmation safety net (Refs #132).

Plus the select/enum widget wiring exposed through the tool payload.
"""
import re

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin
from server.app import _tool_payload
from mixins.tools import TOOLS

pytestmark = pytest.mark.unit


# ─── Harness ──────────────────────────────────────────────────────────────────

class ExportHarness(ImportExportMixin):
    """Concrete host that stubs the heavy GitLab calls and records the write."""

    def __init__(self):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "Configured Group"
        self.written = None  # (path, fmt, rows, field_order)
        # A group object that yields no epics/issues — enough to reach the write.
        self._group = MagicMock()
        self._group.full_path = "ns/configured-group"
        self._group.epics.list.return_value = []
        self._group.issues.list.return_value = []

    def get_group_by_name(self, name):
        return self._group

    def sanitize_name(self, s):
        return s.lower().replace(" ", "-")

    # Stub the heavy resolvers used by the export methods.
    def _build_gid_path_map(self, group):
        return {}

    def _build_pid_path_map(self, group):
        return {}

    def _fetch_epic_weights(self, epics):
        return {}

    # Capture the write instead of touching disk.
    def _write_file(self, path, fmt, rows, field_order):
        self.written = (path, fmt, rows, field_order)


def _tool(key):
    return next(t for t in TOOLS if t["key"] == key)


# ─── Deliverable 1: timestamped, non-clobbering auto-named exports ────────────

_TS_RE = re.compile(r"-(\d{8})-(\d{6})\.(csv|json)$")


def test_default_export_name_is_timestamped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = ExportHarness()
    path = h._default_export_name("epics-export", "csv")
    assert _TS_RE.search(path.name), f"expected a UTC timestamp suffix in {path.name}"
    assert path.name.startswith("configured-group-epics-export-")
    assert path.parent.name == "exports"


def test_default_export_names_do_not_clobber(tmp_path, monkeypatch):
    """Two exports separated by a tick get distinct filenames."""
    monkeypatch.chdir(tmp_path)
    h = ExportHarness()

    stamps = iter(["20260101-000000", "20260101-000001"])

    class _FakeDT:
        @staticmethod
        def utcnow():
            class _S:
                def strftime(self_inner, _fmt):
                    return next(stamps)
            return _S()

    monkeypatch.setattr("mixins.importexport.datetime", _FakeDT)
    first  = h._default_export_name("epics-export", "csv")
    second = h._default_export_name("epics-export", "csv")
    assert first.name != second.name


# ─── Deliverable 2: fmt selector drives auto-named export ─────────────────────

def test_export_epics_fmt_json_auto_named(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = ExportHarness()
    h.export_epics(fmt="json")
    path, fmt, _rows, _fields = h.written
    assert fmt == "json"
    assert path.suffix == ".json"


def test_export_epics_fmt_defaults_to_csv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = ExportHarness()
    h.export_epics()
    path, fmt, _rows, _fields = h.written
    assert fmt == "csv"
    assert path.suffix == ".csv"


def test_export_issues_fmt_json_auto_named(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = ExportHarness()
    h.export_issues(fmt="json")
    path, fmt, _rows, _fields = h.written
    assert fmt == "json"
    assert path.suffix == ".json"


# ─── Hard constraint: explicit CLI path is unchanged ──────────────────────────

def test_explicit_path_ignores_fmt_and_is_not_timestamped(tmp_path, monkeypatch):
    """An explicit output_path (CLI) is honoured verbatim: extension wins over
    fmt, and no timestamp is injected."""
    monkeypatch.chdir(tmp_path)
    h = ExportHarness()
    target = tmp_path / "my-export.csv"
    # fmt='json' must NOT override the explicit .csv path.
    h.export_epics(output_path=str(target), fmt="json")
    path, fmt, _rows, _fields = h.written
    assert fmt == "csv"
    assert path == target.resolve()
    assert not _TS_RE.search(path.name)  # no timestamp on the explicit path


def test_explicit_json_path_detects_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = ExportHarness()
    target = tmp_path / "explicit.json"
    h.export_issues(output_path=str(target))  # fmt default csv, but path is .json
    path, fmt, _rows, _fields = h.written
    assert fmt == "json"
    assert path == target.resolve()


# ─── Select/enum widget wiring through the tool payload ───────────────────────

def _gl_stub():
    gl = MagicMock()
    gl.gitlab_namespace = "saic-study-group"
    gl.parent_group = "Portfolio"
    return gl


@pytest.mark.parametrize("key", ["export-epics", "export-issues"])
def test_export_exposes_fmt_select_widget(key):
    payload = _tool_payload(_tool(key), _gl_stub())
    fmt = next(p for p in payload["params"] if p["name"] == "fmt")
    assert fmt["widget"] == "select"
    assert fmt["options"] == ["csv", "json"]
    assert fmt["default"] == "csv"
    assert fmt["type"] == "str"


def test_non_select_params_have_null_options():
    """options is threaded through for every param (None when not a select)."""
    payload = _tool_payload(_tool("export-epics"), _gl_stub())
    grp = next(p for p in payload["params"] if p["name"] == "group")
    assert grp["options"] is None


# ─── #132: dry_run is hidden from the web UI but kept for the CLI ─────────────

def _tools_with_dry_run():
    return [t["key"] for t in TOOLS
            if any(p["name"] == "dry_run" for p in t.get("params", []))]


@pytest.mark.parametrize("key", _tools_with_dry_run())
def test_dry_run_absent_from_ui_payload(key):
    """No tool's UI payload exposes dry_run (#132)."""
    payload = _tool_payload(_tool(key), _gl_stub())
    assert all(p["name"] != "dry_run" for p in payload["params"])


@pytest.mark.parametrize("key", _tools_with_dry_run())
def test_dry_run_retained_in_raw_registry_as_cli_only(key):
    """The raw tool registry (CLI path) still carries dry_run, flagged cli_only."""
    dry = next(p for p in _tool(key)["params"] if p["name"] == "dry_run")
    assert dry["type"] is bool
    assert dry["cli_only"] is True


@pytest.mark.parametrize("key", ["import-epics", "import-issues"])
def test_import_tools_require_confirmation(key):
    """Mutating imports keep a safety net via the confirmation step (#132)."""
    assert _tool(key).get("confirm") is True
