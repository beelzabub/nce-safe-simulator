"""Issue import must resolve group-level (inherited) milestones.

PI milestones live at the ART/portfolio group level, not on the backlog
project, so a project-only milestone lookup reported "not found" and every
imported issue silently lost its milestone. The lookup now includes ancestor
group milestones.
"""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin
from mixins.bootstrap import BootstrapMixin

pytestmark = pytest.mark.unit


def _ms(title, mid):
    m = MagicMock()
    m.title = title
    m.id = mid
    return m


def _proj(pwn, milestones):
    p = MagicMock()
    p.path_with_namespace = pwn
    p.milestones.list.return_value = milestones
    return p


class IssueImportHarness(ImportExportMixin, BootstrapMixin):
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

    def _build_project_cache(self, root_group):
        return self._cache

    def _validate_issues(self, rows, target_project_path):
        return rows, 0


def _run(tmp_path, milestones):
    root = MagicMock()
    root.full_path = "ns/root"
    proj = _proj("ns/root/team/backlog", milestones)
    cache = {"ns/root/team/backlog": proj}
    rows = [{"title": "I1", "project_path": "ns/root/team/backlog", "milestone": "PI 18"}]
    f = tmp_path / "issues.json"
    f.write_text(json.dumps(rows))
    IssueImportHarness(rows, root, cache)._import_issues(input_path=str(f))
    return proj


def _created_payload(proj):
    args, kwargs = proj.issues.create.call_args
    return args[0] if args else kwargs.get("data", kwargs)


def test_group_milestone_is_resolved_and_assigned(tmp_path):
    proj = _run(tmp_path, [_ms("PI 18", 99)])
    # ancestor-group milestones are requested, not just project milestones
    proj.milestones.list.assert_called_with(
        search="PI 18", include_ancestors=True, all=True)
    assert _created_payload(proj).get("milestone_id") == 99


def test_exact_title_preferred_over_substring_match(tmp_path):
    # search is a substring match — "PI 18" must not grab "PI 180"
    proj = _run(tmp_path, [_ms("PI 180", 1), _ms("PI 18", 2)])
    assert _created_payload(proj).get("milestone_id") == 2


def test_unresolved_milestone_warns_and_skips_only_the_milestone(tmp_path, capsys):
    proj = _run(tmp_path, [])   # nothing matches
    assert "milestone_id" not in _created_payload(proj)
    out = capsys.readouterr().out
    assert "milestone 'PI 18' not found" in out
    # the issue itself is still created
    assert proj.issues.create.called
