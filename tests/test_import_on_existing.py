"""on_existing flag (create | skip | update) for re-importing epics/issues.

Default 'create' preserves today's create-only behavior (duplicates on
re-import). 'skip' leaves an existing same-title item untouched; 'update'
applies the row's fields to it. Matching is by exact title in the target.
"""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin
from mixins.bootstrap import BootstrapMixin

pytestmark = pytest.mark.unit


def _grp(full_path):
    g = MagicMock()
    g.full_path = full_path
    return g


def _proj(pwn):
    p = MagicMock()
    p.path_with_namespace = pwn
    return p


class IEHarness(ImportExportMixin, BootstrapMixin):
    def __init__(self, rows, root, cache):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "Configured Group"
        self._rows = rows
        self._root = root
        self._cache = cache

    def _load_file(self, path):
        return self._rows

    def _resolve_import_target(self, create_missing, dry_run):
        return self._root

    def _build_group_cache(self, root_group):
        return self._cache

    def _build_project_cache(self, root_group):
        return self._cache

    def _build_valid_epic_ids(self, root_group):
        return set()

    def _resolve_parent_ids(self, cleaned, valid_ids, root_group, unresolved_parent):
        return ({}, set())

    def _validate_epics(self, rows):
        return rows, 0

    def _validate_issues(self, rows, target_project_path):
        return rows, 0

    def _set_epic_weight(self, epic, weight):
        pass


def _write(tmp_path, rows):
    f = tmp_path / "in.json"
    f.write_text(json.dumps(rows))
    return str(f)


# ─── Issues ────────────────────────────────────────────────────────────────────

def _issue_setup():
    root = _grp("ns/root")
    proj = _proj("ns/root/team/backlog")
    existing = MagicMock()
    existing.iid = 42
    existing.title = "Issue A"
    proj.issues.list.return_value = [existing]
    cache = {"ns/root/team/backlog": proj}
    rows = [{"title": "Issue A", "project_path": "ns/root/team/backlog", "description": "new"}]
    return root, proj, existing, cache, rows


def test_issues_default_skips_duplicate(tmp_path, capsys):
    # Default is 'skip' — re-importing a same-title issue does not duplicate it.
    root, proj, existing, cache, rows = _issue_setup()
    IEHarness(rows, root, cache)._import_issues(input_path=_write(tmp_path, rows))
    proj.issues.create.assert_not_called()
    existing.save.assert_not_called()
    assert "SKIP" in capsys.readouterr().out


def test_issues_explicit_create_duplicates(tmp_path):
    # Opt back in to the old create-only behaviour.
    root, proj, existing, cache, rows = _issue_setup()
    IEHarness(rows, root, cache)._import_issues(
        input_path=_write(tmp_path, rows), on_existing="create")
    proj.issues.create.assert_called_once()


def test_issues_skip_leaves_existing_untouched(tmp_path, capsys):
    root, proj, existing, cache, rows = _issue_setup()
    IEHarness(rows, root, cache)._import_issues(
        input_path=_write(tmp_path, rows), on_existing="skip")
    proj.issues.create.assert_not_called()
    existing.save.assert_not_called()
    assert "SKIP" in capsys.readouterr().out


def test_issues_update_applies_to_existing(tmp_path):
    root, proj, existing, cache, rows = _issue_setup()
    IEHarness(rows, root, cache)._import_issues(
        input_path=_write(tmp_path, rows), on_existing="update")
    proj.issues.create.assert_not_called()
    assert existing.description == "new"
    existing.save.assert_called()


def test_issues_update_creates_when_no_match(tmp_path):
    root, proj, existing, cache, rows = _issue_setup()
    proj.issues.list.return_value = []          # nothing matches
    IEHarness(rows, root, cache)._import_issues(
        input_path=_write(tmp_path, rows), on_existing="update")
    proj.issues.create.assert_called_once()


# ─── Epics ─────────────────────────────────────────────────────────────────────

def _epic_setup():
    root = _grp("ns/root")
    existing = MagicMock()
    existing.iid = 7
    existing.title = "Epic A"
    root.epics.list.return_value = [existing]
    cache = {"ns/root": root}
    rows = [{"title": "Epic A", "group_path": "ns/root", "description": "new"}]
    return root, existing, cache, rows


def test_epics_skip_leaves_existing_untouched(tmp_path, capsys):
    root, existing, cache, rows = _epic_setup()
    IEHarness(rows, root, cache)._import_epics(
        input_path=_write(tmp_path, rows), on_existing="skip")
    root.epics.create.assert_not_called()
    assert "SKIP" in capsys.readouterr().out


def test_epics_update_applies_to_existing(tmp_path):
    root, existing, cache, rows = _epic_setup()
    IEHarness(rows, root, cache)._import_epics(
        input_path=_write(tmp_path, rows), on_existing="update")
    root.epics.create.assert_not_called()
    assert existing.description == "new"
    existing.save.assert_called()


def test_epics_invalid_on_existing_aborts(tmp_path, capsys):
    root, existing, cache, rows = _epic_setup()
    IEHarness(rows, root, cache)._import_epics(
        input_path=_write(tmp_path, rows), on_existing="bogus")
    root.epics.create.assert_not_called()
    assert "on_existing must be" in capsys.readouterr().out
