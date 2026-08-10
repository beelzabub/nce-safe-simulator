"""A failed site build must fail the report run.

_build_site already prints "FAILED (exit 1)" for whichever stage broke, but
its return value used to be discarded by _run_reports_inner. The run then
exited 0 and the durable job manifest recorded state=done — so a container
where BOTH the Quarto render and every Marimo export failed still looked like
a clean run for a full day. The markdown reports genuinely had published to
the wiki, which is exactly why nothing else looked wrong.
"""

from pathlib import Path

import pytest

from tests.conftest import ReportsHarness


class _SiteBuildHarness(ReportsHarness):
    """Drives _run_reports_inner past its data phases to the site-build seam."""

    def __init__(self, site_ok):
        super().__init__()
        self._site_ok = site_ok
        self.build_site_calls = 0
        self.gitlab_namespace = "ns"

    # --- the seam under test -------------------------------------------
    def _build_site(self, formats=None):
        """Mirrors the real contract: nothing to build → True, whatever the
        stubbed outcome, so a markdown-only run can never be failed here."""
        self.build_site_calls += 1
        formats = formats or set()
        if not ({"plotly", "interactive"} & set(formats)):
            return True
        return self._site_ok

    # --- everything the run does before reaching it ---------------------
    def get_group_by_name(self, name):
        return self._rd_root_obj

    def _write_report_data(self, data_dir, needed=None):
        pass

    def _load_report_data(self, src):
        pass

    def write_report_json(self, *args, **kwargs):
        pass

    def _write_snapshot_manifest(self, data_dir, reports):
        pass


def _run(harness, tmp_path):
    """Site-build formats only — no markdown, so no report method is invoked."""
    harness._run_reports_inner(
        reports=[],
        run_dir=Path(tmp_path),
        data_dir=Path(tmp_path) / "data",
        reuse_data=None,
        formats={"plotly", "interactive"},
    )


def test_failed_site_build_exits_nonzero(tmp_path, capsys):
    harness = _SiteBuildHarness(site_ok=False)
    with pytest.raises(SystemExit) as exc:
        _run(harness, tmp_path)
    assert exc.value.code == 1
    assert harness.build_site_calls == 1

    out = capsys.readouterr().out
    assert "SITE BUILD FAILED" in out, "the failure has to be visible in the log, not just the exit code"


def test_successful_site_build_does_not_exit(tmp_path):
    harness = _SiteBuildHarness(site_ok=True)
    _run(harness, tmp_path)          # must not raise
    assert harness.build_site_calls == 1


def test_markdown_only_run_is_unaffected(tmp_path):
    """No site build was requested, so there is no site result to fail on."""
    harness = _SiteBuildHarness(site_ok=False)
    harness._run_reports_inner(
        reports=[],
        run_dir=Path(tmp_path),
        data_dir=Path(tmp_path) / "data",
        reuse_data=None,
        formats={"markdown"},
    )
    assert harness.build_site_calls == 1, (
        "_build_site is still called; it returns True early when no site "
        "format was selected, so the run must not be failed by this stub"
    )
