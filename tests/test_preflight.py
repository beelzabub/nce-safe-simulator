"""Preflight dependency gate (mixins/preflight.py).

Covers the shared dependency-check engine and the per-job gate: profile
resolution, the check primitives (with forced-missing python / binary / render),
the gap report + manifest, the three-tier skip precedence, and the top-level
crash guard in NceGitLab. All checks are hermetic — no GitLab connection, and
filesystem writes go to a tmp cwd.
"""
import json

import pytest
from unittest.mock import patch

from mixins.preflight import (
    DEP_CHECKS,
    JOB_PROFILES,
    PREFLIGHT_EXIT,
    PreflightMixin,
    profile_for_formats,
    render_report,
    run_checks,
    write_gap_manifest,
)
from mixins.tools import tool_preflight_profile

pytestmark = pytest.mark.unit


def _gate():
    g = PreflightMixin.__new__(PreflightMixin)
    g._preflight_skip_override = None
    g.preflight_skip = False
    return g


# --- profile resolution -----------------------------------------------------

@pytest.mark.parametrize("formats,expected", [
    ({"markdown"},                          "report-markdown"),
    ({"plotly"},                            "report-plotly"),
    ({"interactive"},                       "report-interactive"),
    ({"plotly", "interactive"},             "report-all"),
    ({"markdown", "plotly", "interactive"}, "report-all"),
    (set(),                                 "report-markdown"),
])
def test_profile_for_formats(formats, expected):
    assert profile_for_formats(formats) == expected


def test_tool_preflight_profile():
    assert tool_preflight_profile("epic-cards") == "pdf"     # declares requires:[pdf]
    assert tool_preflight_profile("audit-labels") == "core"  # no requires -> core
    assert tool_preflight_profile("does-not-exist") == "core"


def test_every_profile_references_real_check_keys():
    valid = {c["key"] for c in DEP_CHECKS}
    for name, (required, optional) in JOB_PROFILES.items():
        for k in list(required) + list(optional):
            assert k in valid, f"profile {name} references unknown key {k}"


# --- check primitives -------------------------------------------------------

def test_run_checks_all_present_here():
    results = run_checks(["gitlab", "requests", "pandas", "dateutil"])
    assert results and all(r["ok"] for r in results)
    assert all(r["required"] for r in results)              # None -> all required


def test_run_checks_optional_not_required():
    results = run_checks(["gitlab", "dot"], required_keys={"gitlab"})
    by_key = {r["key"]: r for r in results}
    assert by_key["gitlab"]["required"] is True
    assert by_key["dot"]["required"] is False


def test_missing_python_import_is_caught():
    def boom(mod):
        raise ImportError(f"No module named {mod!r}")
    with patch("mixins.preflight.import_module", side_effect=boom):
        results = run_checks(["pandas"])
    assert results[0]["ok"] is False
    assert results[0]["detail"]                              # a one-line reason, not empty


def test_missing_binary_is_caught():
    with patch("mixins.preflight.shutil.which", return_value=None):
        results = run_checks(["quarto"])
    assert results[0]["ok"] is False
    assert results[0]["detail"] == "not on PATH"


def test_render_probe_failure_is_caught():
    import weasyprint
    with patch.object(weasyprint, "HTML",
                      side_effect=OSError("cannot load library 'libpango-1.0.so.0'")):
        results = run_checks(["weasyprint"])
    assert results[0]["ok"] is False
    assert "libpango" in results[0]["detail"] or "pango" in results[0]["detail"].lower()


# --- reporting --------------------------------------------------------------

def test_preflight_report_lists_missing_first_and_present_summary():
    with patch("mixins.preflight.shutil.which", return_value=None):
        results = run_checks(["gitlab", "quarto"], required_keys={"gitlab", "quarto"})
    text = "\n".join(render_report(results, job_label="reports (report-plotly)",
                                   mode="preflight"))
    assert "cannot start" in text
    assert "quarto" in text and "❌" in text
    assert "fix:" in text and "air-gap" in text and "removable" in text
    assert "Present:" in text                               # gitlab is present here


def test_preflight_report_ok_when_all_present():
    results = run_checks(["gitlab", "requests"])
    lines = render_report(results, job_label="core", mode="preflight")
    assert len(lines) == 1 and "preflight OK" in lines[0]


def test_diagnose_report_has_header_and_verdict():
    results = run_checks([c["key"] for c in DEP_CHECKS],
                         required_keys={"gitlab", "requests", "pandas", "dateutil"})
    text = "\n".join(render_report(results, mode="diagnose"))
    assert "Environment Dependencies" in text
    assert "(optional)" in text


# --- gap manifest -----------------------------------------------------------

def test_write_gap_manifest_shape(tmp_path):
    with patch("mixins.preflight.shutil.which", return_value=None):
        results = run_checks(["gitlab", "quarto"], required_keys={"gitlab", "quarto"})
    path = tmp_path / "logs" / "preflight-gaps.json"
    written = write_gap_manifest(results, path)
    assert written == path and path.exists()
    payload = json.loads(path.read_text())
    assert payload["missing_required"] == 1                 # quarto missing, gitlab present
    assert payload["missing"][0]["key"] == "quarto"
    assert "fix" in payload["missing"][0] and "offline" in payload["missing"][0]


def test_write_gap_manifest_never_raises_on_bad_path():
    # a path whose parent cannot be created returns None, not an exception
    assert write_gap_manifest([], "\x00/nope/gaps.json") is None


# --- the gate ---------------------------------------------------------------

def test_preflight_passes_when_all_present():
    assert _gate()._preflight("report-markdown", phase_label="reports") is True


def test_preflight_exits_2_on_missing_required(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)                              # gap manifest -> tmp
    g = _gate()
    with patch("mixins.preflight.shutil.which", return_value=None):
        with pytest.raises(SystemExit) as ei:
            g._preflight("report-plotly", phase_label="reports (report-plotly)")
    assert ei.value.code == PREFLIGHT_EXIT
    out = capsys.readouterr().out
    assert "cannot start" in out and "quarto" in out
    assert (tmp_path / "logs" / "preflight-gaps.json").exists()


def test_skip_via_flag(monkeypatch):
    monkeypatch.delenv("PREFLIGHT_SKIP", raising=False)
    g = _gate()
    g._preflight_skip_override = True                        # --skip-preflight
    with patch("mixins.preflight.shutil.which", return_value=None):
        assert g._preflight("report-plotly") is True        # skipped -> no exit


def test_skip_via_env(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_SKIP", "1")               # env, no flag/config
    g = _gate()
    with patch("mixins.preflight.shutil.which", return_value=None):
        assert g._preflight("report-plotly") is True


def test_skip_via_config(monkeypatch):
    monkeypatch.delenv("PREFLIGHT_SKIP", raising=False)
    g = _gate()
    g.preflight_skip = True                                 # defaults.preflight.skip
    with patch("mixins.preflight.shutil.which", return_value=None):
        assert g._preflight("report-plotly") is True


# --- pre-construction gate (run_preflight, used by main() before the client) --

def test_run_preflight_reads_config_file_skip(tmp_path, monkeypatch):
    from mixins.preflight import run_preflight
    monkeypatch.delenv("PREFLIGHT_SKIP", raising=False)
    cfg = tmp_path / "config.json"
    cfg.write_text('{"defaults": {"preflight": {"skip": true}}}')
    with patch("mixins.preflight.shutil.which", return_value=None):
        assert run_preflight("report-plotly", config_file=str(cfg)) is True  # config skip


def test_run_preflight_exits_when_config_absent_and_dep_missing(tmp_path, monkeypatch):
    from mixins.preflight import run_preflight
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PREFLIGHT_SKIP", raising=False)
    with patch("mixins.preflight.shutil.which", return_value=None):
        with pytest.raises(SystemExit) as ei:
            run_preflight("report-plotly", config_file="nonexistent.json")
    assert ei.value.code == PREFLIGHT_EXIT                  # missing config -> no skip -> gate


def _args(**kw):
    import argparse
    base = dict(utilities=None, scaffold=None, all=False, report=None,
                clean=False, create=False)
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.mark.parametrize("args,formats,expected_profile", [
    (_args(report="__menu__"),           {"markdown"},              "report-markdown"),
    (_args(all=True),                    {"plotly", "interactive"}, "report-all"),
    (_args(utilities="epic-cards"),      set(),                     "pdf"),
    (_args(utilities="audit-labels"),    set(),                     "core"),
    (_args(scaffold="__prompt__"),       set(),                     "scaffold"),
    (_args(create=True),                 set(),                     "core"),
])
def test_resolve_preflight_profile(args, formats, expected_profile):
    from NceGitLab import _resolve_preflight_profile
    prof, label = _resolve_preflight_profile(args, formats)
    assert prof == expected_profile and label


@pytest.mark.parametrize("args", [
    _args(),                             # bare -> interactive menu
    _args(utilities="__menu__"),         # utilities menu (no specific tool)
])
def test_resolve_preflight_profile_ungated(args):
    from NceGitLab import _resolve_preflight_profile
    assert _resolve_preflight_profile(args, set()) == (None, None)


def test_env_false_overrides_config_true(monkeypatch):
    g = _gate()
    g.preflight_skip = True                                  # config says skip
    monkeypatch.setenv("PREFLIGHT_SKIP", "false")            # env says don't
    with patch("mixins.preflight.shutil.which", return_value=None):
        with pytest.raises(SystemExit):
            g._preflight("report-plotly")


# --- top-level crash guard --------------------------------------------------

def test_handle_uncaught_writes_log_and_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    import NceGitLab
    with pytest.raises(SystemExit) as ei:
        NceGitLab._handle_uncaught(ValueError("boom in the middle"),
                                   "reports (report-all)")
    assert ei.value.code == 1
    out = capsys.readouterr().out
    assert "Unexpected error" in out
    assert "reports (report-all)" in out and "ValueError" in out
    logs = list(tmp_path.glob("logs/**/*_crash.log"))
    assert logs, "a crash log should be written"
    assert "boom in the middle" in logs[0].read_text()
