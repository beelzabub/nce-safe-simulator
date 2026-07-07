"""Re-run visibility and batching (Refs #201).

Field finding (2026-07-07 JamieGroup case-1 re-import): the run stalled
silently on GitLab 429 backoff, and the per-row existence searches were what
tripped the rate limit. Fixes: a visible 429 hook, one existence listing per
container instead of one search per row, and container-qualified SKIP lines.
"""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin
from mixins.bootstrap import BootstrapMixin
from mixins.utils import UtilitiesMixin

pytestmark = pytest.mark.unit

ROOT_PATH = "ns/target"


# ─── 429 visibility ───────────────────────────────────────────────────────────

class TestRateLimitHook:
    def _resp(self, status, retry_after=None):
        r = MagicMock()
        r.status_code = status
        r.headers = {"Retry-After": retry_after} if retry_after else {}
        return r

    def test_prints_on_429_with_retry_after(self, capsys):
        UtilitiesMixin._rate_limit_hook(self._resp(429, "45"))
        assert "rate limit hit (429) — retrying after 45s" in capsys.readouterr().out

    def test_prints_unknown_delay_without_header(self, capsys):
        UtilitiesMixin._rate_limit_hook(self._resp(429))
        assert "retrying after ?s" in capsys.readouterr().out

    def test_silent_on_success(self, capsys):
        UtilitiesMixin._rate_limit_hook(self._resp(200))
        assert capsys.readouterr().out == ""

    def test_returns_response_unchanged(self):
        r = self._resp(200)
        assert UtilitiesMixin._rate_limit_hook(r) is r

    def test_make_session_attaches_hook(self):
        class H(UtilitiesMixin):
            private_token = "x"
        sess = H()._make_session()
        assert UtilitiesMixin._rate_limit_hook in sess.hooks["response"]


# ─── Batched existence checks ─────────────────────────────────────────────────

class BatchHarness(ImportExportMixin, BootstrapMixin):
    def __init__(self, rows, existing_epics=None):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "target"
        self._rows = rows
        self.root = MagicMock()
        self.root.full_path = ROOT_PATH
        self.root.id = 1
        self.list_calls = 0
        eps = []
        for iid, title in (existing_epics or []):
            e = MagicMock()
            e.iid, e.title, e.group_id, e.id = iid, title, 1, 7000 + iid
            eps.append(e)

        def _list(**kw):
            self.list_calls += 1
            return list(eps)
        self.root.epics.list.side_effect = _list
        self._created = []

        def _create(payload):
            e = MagicMock()
            e.id = 9001 + len(self._created)
            e.iid = e.id - 9000
            e.title = payload["title"]
            e.group_id = 1
            self._created.append(dict(payload))
            return e
        self.root.epics.create.side_effect = _create

    def _load_file(self, path):                                return self._rows
    def _resolve_import_target(self, create_missing, dry_run): return self.root
    def _build_group_cache(self, root_group):                  return {ROOT_PATH: self.root}
    def _build_valid_epic_ids(self, root_group):               return set()
    def _set_epic_weight(self, epic, weight):                  pass
    def sanitize_name(self, s):                                return s.lower()
    def _default_export_name(self, stem, fmt):
        import tempfile, pathlib
        return pathlib.Path(tempfile.mkdtemp()) / f"{stem}.{fmt}"


def _run(h, tmp_path, **kw):
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(h._rows))
    h._import_epics(input_path=str(f), **kw)


class TestBatchedEpicExistence:
    def test_one_listing_for_many_rows_in_one_container(self, tmp_path):
        rows = [{"title": f"E{n}", "group_path": ROOT_PATH} for n in range(10)]
        h = BatchHarness(rows, existing_epics=[(n + 1, f"E{n}") for n in range(10)])
        base = h.list_calls
        _run(h, tmp_path, on_existing="skip")
        # pre-flight _build_valid_epic_ids is stubbed; the existence check
        # itself must have listed the container exactly once
        assert h.list_calls - base == 1
        assert h._created == []

    def test_intra_run_duplicate_still_detected(self, tmp_path, capsys):
        """Two identical rows into an empty container: the first creates and
        must be visible to the second through the cache append."""
        rows = [{"title": "Same", "group_path": ROOT_PATH},
                {"title": "Same", "group_path": ROOT_PATH}]
        h = BatchHarness(rows)
        _run(h, tmp_path, on_existing="skip")
        assert len(h._created) == 1
        assert "SKIP — epic 'Same' already exists" in capsys.readouterr().out

    def test_skip_message_names_container(self, tmp_path, capsys):
        h = BatchHarness([{"title": "E0", "group_path": ROOT_PATH}],
                         existing_epics=[(4, "E0")])
        _run(h, tmp_path, on_existing="skip")
        assert f"already exists (#4 in {ROOT_PATH})" in capsys.readouterr().out

    def test_create_mode_never_lists(self, tmp_path):
        h = BatchHarness([{"title": "E0", "group_path": ROOT_PATH}])
        base = h.list_calls
        _run(h, tmp_path, on_existing="create")
        assert h.list_calls - base == 0
        assert len(h._created) == 1


class TestBatchedIssueExistence:
    def _harness(self, rows, existing_titles=()):
        from tests.test_import_full_fidelity import CMPHarness
        h = CMPHarness(rows)
        proj = MagicMock()
        proj.id, proj.path_with_namespace = 71, f"{ROOT_PATH}/team/backlog"
        h.list_calls = 0
        existing = []
        for n, t in enumerate(existing_titles, 1):
            iss = MagicMock()
            iss.iid, iss.title = n, t
            existing.append(iss)

        def _list(**kw):
            h.list_calls += 1
            return list(existing)
        proj.issues.list.side_effect = _list
        proj.issues.create.side_effect = lambda ip: MagicMock(iid=99)
        h.project_cache[proj.path_with_namespace] = proj
        # CMPHarness stubs _find_issue_by_title to None; restore the real one
        h._find_issue_by_title = ImportExportMixin._find_issue_by_title.__get__(h)
        return h

    def test_one_listing_and_qualified_skip(self, tmp_path, capsys):
        rows = [{"title": f"I{n}", "project_path": f"{ROOT_PATH}/team/backlog"}
                for n in range(5)]
        h = self._harness(rows, existing_titles=[f"I{n}" for n in range(5)])
        f = tmp_path / "issues.json"
        f.write_text(json.dumps(rows))
        h._import_issues(input_path=str(f), on_existing="skip")
        assert h.list_calls == 1
        assert f"already exists (#1 in {ROOT_PATH}/team/backlog)" in capsys.readouterr().out
