"""Cross-type file guard: reject an issues export fed to the epics importer
(and vice-versa) instead of silently creating objects from the wrong rows.

Both importers require only `title`, so a mismatched export used to pass
validation. The two exports have disjoint signature columns, so their presence
in the other importer is a reliable "wrong file" signal.
"""
import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin

pytestmark = pytest.mark.unit


class VHarness(ImportExportMixin):
    def __init__(self):
        self.gl = MagicMock()


def test_epics_import_rejects_an_issues_export():
    rows = [{"title": "Issue 1", "project_path": "ns/team/backlog",
             "epic_id": "5", "assignees": "alice", "milestone": "M1"}]
    cleaned, errs = VHarness()._validate_epics(rows)
    assert cleaned is None
    assert errs == 1


def test_issues_import_rejects_an_epics_export():
    rows = [{"title": "Epic 1", "group_path": "ns/vs/art",
             "planned_weight": "3", "parent_id": "2", "start_date": "2026-01-01"}]
    cleaned, errs = VHarness()._validate_issues(rows, override_project=None)
    assert cleaned is None
    assert errs == 1


def test_epics_import_accepts_a_real_epics_export(capsys):
    rows = [{"title": "Epic 1", "group_path": "ns/vs/art",
             "planned_weight": "3", "state": "opened"}]
    cleaned, errs = VHarness()._validate_epics(rows)
    assert cleaned is not None
    assert errs == 0
    # epic-specific columns present → type confirmed → no ambiguity notice
    assert "could NOT be confirmed" not in capsys.readouterr().out


def test_issues_import_accepts_a_real_issues_export(capsys):
    rows = [{"title": "Issue 1", "project_path": "ns/team/backlog",
             "weight": "2", "state": "opened"}]
    cleaned, errs = VHarness()._validate_issues(rows, override_project=None)
    assert cleaned is not None
    assert errs == 0
    assert "could NOT be confirmed" not in capsys.readouterr().out


def test_epics_import_accepts_minimal_but_warns_type_unconfirmed(capsys):
    # title + only columns common to both types → accepted, but stand-out notice
    rows = [{"title": "Row 1", "description": "d", "state": "opened"}]
    cleaned, errs = VHarness()._validate_epics(rows)
    assert cleaned is not None
    assert errs == 0
    out = capsys.readouterr().out
    assert "ACCEPTED" in out
    assert "could NOT be confirmed" in out
    assert "Import Issues" in out


def test_issues_import_accepts_minimal_but_warns_type_unconfirmed(capsys):
    rows = [{"title": "Row 1", "description": "d", "state": "opened"}]
    cleaned, errs = VHarness()._validate_issues(rows, override_project="ns/team/backlog")
    assert cleaned is not None
    assert errs == 0
    out = capsys.readouterr().out
    assert "ACCEPTED" in out
    assert "could NOT be confirmed" in out
    assert "Import Epics" in out
