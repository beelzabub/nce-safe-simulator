"""Business Value round-trip on epic export/import (Refs #196).

BV drives WSJF scoring and the Portfolio Explorer's at-risk metrics; it was
silently dropped on every transfer because the export never carried it.
"""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import (
    ImportExportMixin, EPIC_EXPORT_FIELDS, EPIC_IMPORT_KNOWN,
)
from mixins.bootstrap import BootstrapMixin
from mixins.utils import UtilitiesMixin

pytestmark = pytest.mark.unit

ROOT_PATH = "ns/target"

BV_FIELD = {
    "id": "gid://gitlab/CustomField/77",
    "selectOptions": [
        {"id": "gid://opt/1", "value": "1"},
        {"id": "gid://opt/2", "value": "2"},
        {"id": "gid://opt/3", "value": "3"},
        {"id": "gid://opt/5", "value": "5"},
        {"id": "gid://opt/8", "value": "8"},
    ],
}


class BVHarness(ImportExportMixin, BootstrapMixin):
    BUSINESS_VALUE_FIELD = {"name": "Business Value"}

    def __init__(self, rows, bv_field=BV_FIELD):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "target"
        self._rows = rows
        self._bv_field = bv_field
        self.root = MagicMock()
        self.root.full_path = ROOT_PATH
        self.root.id = 1
        self.root.epics.list.return_value = []
        self.bv_sets = []      # (work_item_id, field_gid, option_gid)
        self._next = iter(range(9001, 9099))

        def _create(payload):
            e = MagicMock()
            e.id = next(self._next)
            e.iid = e.id - 9000
            e.work_item_id = e.id * 10
            e.title = payload["title"]
            return e
        self.root.epics.create.side_effect = _create
        self.bv_result = True  # what the BV setter reports (#202: False = miss)

    def _load_file(self, path):                                return self._rows
    def _resolve_import_target(self, create_missing, dry_run): return self.root
    def _build_group_cache(self, root_group):                  return {ROOT_PATH: self.root}
    def _build_valid_epic_ids(self, root_group):               return set()
    def _find_epic_by_title(self, group, title, cache=None):               return None
    def _set_epic_weight(self, epic, weight):                  pass
    def _find_bv_field(self, group=None):                      return self._bv_field
    def _set_work_item_business_value(self, wid, field_gid, option_gid):
        self.bv_sets.append((wid, field_gid, option_gid))
        return self.bv_result


def _run(h, tmp_path, **kw):
    f = tmp_path / "epics.json"
    f.write_text(json.dumps(h._rows))
    h._import_epics(input_path=str(f), **kw)


class TestFieldDefinitions:
    def test_export_fields_carry_business_value(self):
        assert "business_value" in EPIC_EXPORT_FIELDS

    def test_import_knows_business_value(self):
        assert "business_value" in EPIC_IMPORT_KNOWN


class TestExport:
    def test_export_row_carries_bv(self, tmp_path):
        h = BVHarness([])
        epic = MagicMock()
        epic.id, epic.iid = 42, 7
        epic.title, epic.description, epic.state = "E", "", "opened"
        epic.labels = []
        epic.web_url = "https://x/epics/7"
        epic.author = {"name": "a"}
        epic.group_id = 1
        h.get_group_by_name = lambda name: h.root
        h.root.epics.list.return_value = [epic]
        h._build_gid_path_map = lambda g: {1: ROOT_PATH}
        h._fetch_epic_weights = lambda epics: {}
        h._fetch_epic_business_values = lambda epics, root_namespace=None: {42: 8}
        written = {}
        h._write_file = lambda path, fmt, rows, order: written.update(rows=rows, order=order)
        h._export_epics(output_path=str(tmp_path / "out.json"))
        assert written["rows"][0]["business_value"] == 8
        assert "business_value" in written["order"]

    def test_export_unset_bv_is_blank(self, tmp_path):
        h = BVHarness([])
        epic = MagicMock()
        epic.id, epic.iid = 42, 7
        epic.title, epic.description, epic.state = "E", "", "opened"
        epic.labels = []
        epic.web_url = "https://x/epics/7"
        epic.author = {"name": "a"}
        h.get_group_by_name = lambda name: h.root
        h.root.epics.list.return_value = [epic]
        h._build_gid_path_map = lambda g: {}
        h._fetch_epic_weights = lambda epics: {}
        h._fetch_epic_business_values = lambda epics, root_namespace=None: {}
        written = {}
        h._write_file = lambda path, fmt, rows, order: written.update(rows=rows)
        h._export_epics(output_path=str(tmp_path / "out.json"))
        assert written["rows"][0]["business_value"] == ""


class TestImport:
    def test_bv_set_with_matching_option_gid(self, tmp_path):
        h = BVHarness([{"title": "E1", "group_path": ROOT_PATH, "business_value": 5}])
        _run(h, tmp_path)
        assert len(h.bv_sets) == 1
        wid, field_gid, opt_gid = h.bv_sets[0]
        assert field_gid == BV_FIELD["id"]
        assert opt_gid == "gid://opt/5"

    def test_value_not_in_options_warns_and_skips(self, tmp_path, capsys):
        h = BVHarness([{"title": "E1", "group_path": ROOT_PATH, "business_value": 99}])
        _run(h, tmp_path)
        assert h.bv_sets == []
        assert "99 is not an option" in capsys.readouterr().out

    def test_missing_field_warns_once_and_continues(self, tmp_path, capsys):
        h = BVHarness(
            [{"title": "E1", "group_path": ROOT_PATH, "business_value": 5},
             {"title": "E2", "group_path": ROOT_PATH, "business_value": 3}],
            bv_field=None,
        )
        _run(h, tmp_path)
        out = capsys.readouterr().out
        assert h.bv_sets == []
        assert out.count("not found on the target") == 1
        assert "created #" in out          # rows still imported

    def test_rows_without_bv_never_resolve_field(self, tmp_path):
        h = BVHarness([{"title": "E1", "group_path": ROOT_PATH}])
        calls = []
        h._find_bv_field = lambda group=None: calls.append(1) or BV_FIELD
        _run(h, tmp_path)
        assert calls == []
        assert h.bv_sets == []

    def test_update_path_sets_bv_on_existing(self, tmp_path):
        existing = MagicMock()
        existing.id, existing.iid = 7777, 42
        existing.title = "E1"
        existing.work_item_id = 555
        h = BVHarness([{"title": "E1", "group_path": ROOT_PATH, "business_value": 3}])
        h._find_epic_by_title = lambda group, title, cache=None: existing
        _run(h, tmp_path, on_existing="update")
        assert h.bv_sets == [(555, BV_FIELD["id"], "gid://opt/3")]

    def test_dry_run_previews_bv_without_graphql(self, tmp_path, capsys):
        h = BVHarness([{"title": "E1", "group_path": ROOT_PATH, "business_value": 5}])
        calls = []
        h._find_bv_field = lambda group=None: calls.append(1) or BV_FIELD
        _run(h, tmp_path, dry_run=True)
        out = capsys.readouterr().out
        assert "bv=5" in out
        assert calls == []
        assert h.bv_sets == []

    def test_epic_without_work_item_id_warns(self, tmp_path, capsys):
        h = BVHarness([{"title": "E1", "group_path": ROOT_PATH, "business_value": 5}])
        def _create(payload):
            e = MagicMock(spec=["id", "iid", "title", "state_event", "save"])
            e.id, e.iid, e.title = 9001, 1, payload["title"]
            return e
        h.root.epics.create.side_effect = _create
        _run(h, tmp_path)
        assert h.bv_sets == []
        assert "no work_item_id" in capsys.readouterr().out


class TestMissSummary:
    """A BV value the mutation could not set must surface in the run summary
    (Refs #202: a transient GraphQL failure lost a value while the summary
    still said '0 failed')."""

    def test_setter_failure_warns_and_counts_in_summary(self, tmp_path, capsys):
        h = BVHarness([{"title": "E1", "group_path": ROOT_PATH, "business_value": 5}])
        h.bv_result = False
        _run(h, tmp_path)
        out = capsys.readouterr().out
        assert "GraphQL mutation failed after retries" in out
        assert "1 business_value value(s) could not be set" in out
        assert "1 created" in out                    # the epic itself still imports

    def test_success_leaves_summary_clean(self, tmp_path, capsys):
        h = BVHarness([{"title": "E1", "group_path": ROOT_PATH, "business_value": 5}])
        _run(h, tmp_path)
        assert "could not be set" not in capsys.readouterr().out

    def test_update_path_miss_also_counted(self, tmp_path, capsys):
        existing = MagicMock()
        existing.id, existing.iid = 7777, 42
        existing.title = "E1"
        existing.work_item_id = 555
        h = BVHarness([{"title": "E1", "group_path": ROOT_PATH, "business_value": 3}])
        h._find_epic_by_title = lambda group, title, cache=None: existing
        h.bv_result = False
        _run(h, tmp_path, on_existing="update")
        assert "1 business_value value(s) could not be set" in capsys.readouterr().out

    def test_option_and_wid_misses_count_too(self, tmp_path, capsys):
        h = BVHarness(
            [{"title": "E1", "group_path": ROOT_PATH, "business_value": 99},
             {"title": "E2", "group_path": ROOT_PATH, "business_value": 5}])
        _run(h, tmp_path)
        # E1's value isn't an option → miss; E2 succeeds.
        assert "1 business_value value(s) could not be set" in capsys.readouterr().out


class _SetterHarness(UtilitiesMixin):
    """Real _set_work_item_business_value over a stubbed graphql_query."""

    def __init__(self, reply):
        self._reply = reply
        self.calls = []        # (retries,)

    def graphql_query(self, query, variables=None, retries=0):
        self.calls.append(retries)
        return self._reply


class TestSetterReturnValue:
    def test_success_returns_true(self):
        h = _SetterHarness({"workItemUpdate": {"workItem": {"id": "x"}, "errors": []}})
        assert h._set_work_item_business_value(1, "f", "o") is True

    def test_graphql_none_returns_false(self):
        h = _SetterHarness(None)
        assert h._set_work_item_business_value(1, "f", "o") is False

    def test_mutation_errors_return_false(self, capsys):
        h = _SetterHarness({"workItemUpdate": {"workItem": None, "errors": ["nope"]}})
        assert h._set_work_item_business_value(1, "f", "o") is False
        assert "Business Value set error" in capsys.readouterr().out

    def test_uses_two_retries(self):
        h = _SetterHarness(None)
        h._set_work_item_business_value(1, "f", "o")
        assert h.calls == [2]


class TestImportReturnsIdMap:
    """#206: _import_epics returns the source→new id map (the bundle importer
    threads it in-memory); abort paths return None."""

    def test_success_returns_map(self, tmp_path):
        h = BVHarness([{"title": "E1", "group_path": ROOT_PATH, "id": 100}])
        f = tmp_path / "epics.json"
        f.write_text(json.dumps(h._rows))
        result = h._import_epics(input_path=str(f))
        assert result == {"100": 9001}

    def test_abort_returns_none(self, tmp_path):
        h = BVHarness([{"title": "E1", "group_path": ROOT_PATH}])
        h._resolve_import_target = lambda create_missing, dry_run: None
        f = tmp_path / "epics.json"
        f.write_text(json.dumps(h._rows))
        assert h._import_epics(input_path=str(f)) is None

    def test_dry_run_returns_empty_map_not_none(self, tmp_path):
        h = BVHarness([{"title": "E1", "group_path": ROOT_PATH, "id": 100}])
        f = tmp_path / "epics.json"
        f.write_text(json.dumps(h._rows))
        assert h._import_epics(input_path=str(f), dry_run=True) == {}
