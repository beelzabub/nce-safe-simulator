"""Transfer bundle export/import (Refs #206).

export-bundle zips the three exports + a merged group-names sidecar + a
manifest; import-bundle validates the manifest and runs the proven sequence
(epics → issues → links) with the epic id map threaded in-memory and the
container-creation flags on.
"""
import csv
import json
import zipfile
from pathlib import Path

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin
from mixins.bootstrap import BootstrapMixin

pytestmark = pytest.mark.unit

ROOT = "ns/source"


# ─── export harness ────────────────────────────────────────────────────────────

class ExportBundleHarness(ImportExportMixin, BootstrapMixin):
    """Stubs the three per-kind exports; the bundle logic runs for real."""

    def __init__(self, with_links=True, with_sidecars=True, external_links=0):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "source"
        self.root = MagicMock()
        self.root.full_path = ROOT
        self._with_links = with_links
        self._with_sidecars = with_sidecars
        self._external = external_links

    def get_group_by_name(self, name):
        return self.root

    def sanitize_name(self, s):
        return s.lower()

    @staticmethod
    def _write_csv(path, fieldnames, rows):
        with Path(path).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

    def _export_epics(self, output_path=None, fmt="csv"):
        self._write_csv(output_path, ["title"], [{"title": "E1"}, {"title": "E2"}])
        if self._with_sidecars:
            p = Path(output_path)
            p.with_name(p.stem + "-group-names.json").write_text(
                json.dumps({"groups": {"vs-01": "Value Stream 01"}, "projects": {}}))

    def _export_issues(self, output_path=None, fmt="csv"):
        self._write_csv(output_path, ["title"], [{"title": "I1"}])
        if self._with_sidecars:
            p = Path(output_path)
            p.with_name(p.stem + "-group-names.json").write_text(
                json.dumps({"groups": {"vs-01": "Value Stream 01"},
                            "projects": {"vs-01/backlog": "Team Backlog"}}))

    def _export_links(self, output_path=None, fmt="csv"):
        if not self._with_links:
            return   # "No blocking links found — nothing written."
        rows = [{"source_container": f"{ROOT}/vs-01", "target_container": f"{ROOT}/vs-01"}]
        rows += [{"source_container": f"{ROOT}/vs-01", "target_container": "other/root"}
                 for _ in range(self._external)]
        self._write_csv(output_path, ["source_container", "target_container"], rows)


class TestExportBundle:
    def test_zip_contains_all_members_and_manifest(self, tmp_path):
        h = ExportBundleHarness()
        out = tmp_path / "b.zip"
        assert h.export_bundle(output_path=str(out)) == out.resolve()
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            assert names == {"epics.csv", "issues.csv", "links.csv",
                             "group-names.json", "manifest.json"}
            m = json.loads(zf.read("manifest.json"))
        assert m["format"] == "nce-bundle"
        assert m["format_version"] == 1
        assert m["source_root"] == ROOT
        assert m["counts"] == {"epics": 2, "issues": 1, "links": 1,
                               "external_links": 0}
        assert m["files"]["group_names"] == "group-names.json"

    def test_sidecars_merged(self, tmp_path):
        h = ExportBundleHarness()
        out = tmp_path / "b.zip"
        h.export_bundle(output_path=str(out))
        with zipfile.ZipFile(out) as zf:
            names = json.loads(zf.read("group-names.json"))
        assert names["groups"] == {"vs-01": "Value Stream 01"}
        assert names["projects"] == {"vs-01/backlog": "Team Backlog"}

    def test_no_links_bundle_still_valid(self, tmp_path):
        h = ExportBundleHarness(with_links=False)
        out = tmp_path / "b.zip"
        h.export_bundle(output_path=str(out))
        with zipfile.ZipFile(out) as zf:
            assert "links.csv" not in zf.namelist()
            m = json.loads(zf.read("manifest.json"))
        assert "links" not in m["files"]
        assert m["counts"]["links"] == 0

    def test_external_links_counted(self, tmp_path, capsys):
        h = ExportBundleHarness(external_links=2)
        out = tmp_path / "b.zip"
        h.export_bundle(output_path=str(out))
        with zipfile.ZipFile(out) as zf:
            m = json.loads(zf.read("manifest.json"))
        assert m["counts"]["links"] == 3
        assert m["counts"]["external_links"] == 2
        assert "2 with external endpoints" in capsys.readouterr().out

    def test_issues_only_hierarchy_still_bundles(self, tmp_path):
        # A subtree with no epics is a legitimate export target (#206 review).
        h = ExportBundleHarness()
        h._export_epics = lambda output_path=None, fmt="csv": None   # writes nothing
        out = tmp_path / "b.zip"
        assert h.export_bundle(output_path=str(out)) == out.resolve()
        with zipfile.ZipFile(out) as zf:
            assert "epics.csv" not in zf.namelist()
            m = json.loads(zf.read("manifest.json"))
        assert "epics" not in m["files"]
        assert m["counts"]["epics"] == 0

    def test_nothing_to_bundle_aborts(self, tmp_path, capsys):
        h = ExportBundleHarness(with_links=False)
        h._export_epics = lambda output_path=None, fmt="csv": None
        h._export_issues = lambda output_path=None, fmt="csv": None
        out = tmp_path / "b.zip"
        assert h.export_bundle(output_path=str(out)) is None
        assert not out.exists()
        assert "bundle aborted" in capsys.readouterr().out

    def test_group_not_found_errors(self, tmp_path, capsys):
        h = ExportBundleHarness()
        h.get_group_by_name = lambda name: None
        assert h.export_bundle(output_path=str(tmp_path / "b.zip")) is None
        assert "not found" in capsys.readouterr().out


# ─── import harness ────────────────────────────────────────────────────────────

def make_bundle(tmp_path, manifest=None, members=None, name="bundle.zip"):
    """Build a bundle zip; manifest/members can be overridden per test."""
    files = {
        "epics.csv":        "title\nE1\n",
        "issues.csv":       "title\nI1\n",
        "links.csv":        "source_type,target_type\nEpic,Epic\n",
        "group-names.json": json.dumps({"groups": {}, "projects": {}}),
    }
    if members is not None:
        files = members
    if manifest is None:
        manifest = {
            "format": "nce-bundle", "format_version": 1,
            "source_root": ROOT,
            "files": {"epics": "epics.csv", "issues": "issues.csv",
                      "links": "links.csv", "group_names": "group-names.json"},
            "counts": {"epics": 1, "issues": 1, "links": 1, "external_links": 0},
        }
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for arc, content in files.items():
            zf.writestr(arc, content)
        if manifest is not False:
            zf.writestr("manifest.json", json.dumps(manifest))
    return path


class ImportBundleHarness(ImportExportMixin, BootstrapMixin):
    """Records phase calls; the bundle orchestration runs for real."""

    def __init__(self, epics_result=None):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "target"
        self.calls = []
        self._epics_result = ({"100": 900} if epics_result is None
                              else epics_result)

    def _import_epics(self, **kw):
        self.calls.append(("epics", kw))
        return self._epics_result

    def _import_issues(self, **kw):
        self.calls.append(("issues", kw))

    def _import_links(self, **kw):
        self.calls.append(("links", kw))


class TestImportBundle:
    def test_happy_path_threads_map_and_names_in_order(self, tmp_path):
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(make_bundle(tmp_path)))
        assert [c[0] for c in h.calls] == ["epics", "issues", "links"]
        epics, issues, links = (c[1] for c in h.calls)
        assert epics["create_missing"] is True
        assert epics["create_missing_groups"] is True
        assert epics["on_existing"] == "skip"
        assert epics["group_names"].endswith("group-names.json")
        assert issues["epic_id_map"] == {"100": 900}       # in-memory dict
        assert issues["create_missing_projects"] is True
        assert issues["create_missing"] is False           # root exists after phase 1
        assert issues["group_names"].endswith("group-names.json")
        assert links["epic_id_map"] == {"100": 900}

    def test_epics_abort_stops_the_bundle(self, tmp_path, capsys):
        h = ImportBundleHarness(epics_result=False)
        h._epics_result = None
        h.import_bundle(input_path=str(make_bundle(tmp_path)))
        assert [c[0] for c in h.calls] == ["epics"]
        assert "aborted" in capsys.readouterr().out

    def test_dry_run_threads_through_all_phases(self, tmp_path, capsys):
        h = ImportBundleHarness(epics_result={})
        h.import_bundle(input_path=str(make_bundle(tmp_path)), dry_run=True)
        assert all(c[1]["dry_run"] is True for c in h.calls)
        assert "[dry run] no epic id map yet" in capsys.readouterr().out

    def test_on_existing_threads_to_epics_and_issues(self, tmp_path):
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(make_bundle(tmp_path)),
                        on_existing="update")
        epics, issues, _ = (c[1] for c in h.calls)
        assert epics["on_existing"] == "update"
        assert issues["on_existing"] == "update"

    def test_bundle_without_links_skips_phase_3(self, tmp_path, capsys):
        members = {"epics.csv": "title\nE1\n", "issues.csv": "title\nI1\n"}
        manifest = {"format": "nce-bundle", "format_version": 1,
                    "files": {"epics": "epics.csv", "issues": "issues.csv"},
                    "counts": {"epics": 1, "issues": 1, "links": 0}}
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(make_bundle(tmp_path, manifest, members)))
        assert [c[0] for c in h.calls] == ["epics", "issues"]
        assert "none in bundle" in capsys.readouterr().out
        # no names file → group_names is None, not a dead path
        assert h.calls[0][1]["group_names"] is None

    def test_not_a_zip_rejected(self, tmp_path, capsys):
        p = tmp_path / "not.zip"
        p.write_text("title\nE1\n")
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(p))
        assert h.calls == []
        assert "not a zip file" in capsys.readouterr().out

    def test_missing_manifest_rejected(self, tmp_path, capsys):
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(make_bundle(tmp_path, manifest=False)))
        assert h.calls == []
        assert "no manifest.json" in capsys.readouterr().out

    def test_wrong_format_rejected(self, tmp_path, capsys):
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(make_bundle(
            tmp_path, manifest={"format": "other", "format_version": 1})))
        assert h.calls == []
        assert "INVALID" in capsys.readouterr().out

    def test_newer_version_rejected(self, tmp_path, capsys):
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(make_bundle(
            tmp_path, manifest={"format": "nce-bundle", "format_version": 99,
                                "files": {"epics": "epics.csv",
                                          "issues": "issues.csv"}})))
        assert h.calls == []
        assert "newer than this tool supports" in capsys.readouterr().out

    def test_nested_member_path_rejected(self, tmp_path, capsys):
        p = tmp_path / "evil.zip"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("sub/epics.csv", "title\nE1\n")
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(p))
        assert h.calls == []
        assert "unexpected member path" in capsys.readouterr().out

    def test_manifest_missing_required_file_rejected(self, tmp_path, capsys):
        manifest = {"format": "nce-bundle", "format_version": 1,
                    "files": {"epics": "epics.csv", "issues": "gone.csv"}}
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(make_bundle(tmp_path, manifest)))
        assert h.calls == []
        assert "missing its issues file" in capsys.readouterr().out


# ─── id-map dict passthrough (#206 building block) ─────────────────────────────

class _MapHarness(ImportExportMixin):
    pass


class TestIdMapDictPassthrough:
    def test_dict_accepted_and_normalized(self):
        h = _MapHarness()
        assert h._load_epic_id_map({"100": 900, 101: "901"}) == \
            {"100": 900, "101": 901}

    def test_malformed_dict_degrades_with_warn(self, capsys):
        h = _MapHarness()
        assert h._load_epic_id_map({"100": "not-an-int"}) == {}
        assert "malformed" in capsys.readouterr().out

    def test_empty_and_none_still_empty(self):
        h = _MapHarness()
        assert h._load_epic_id_map(None) == {}
        assert h._load_epic_id_map({}) == {}


class TestReviewGaps:
    """Gaps the #206 adversarial review found: override threading, flag
    threading, garbage manifests, issues-only imports."""

    def test_export_group_override_threads(self, tmp_path):
        h = ExportBundleHarness()
        seen = []
        orig = h.get_group_by_name
        h.get_group_by_name = lambda name: seen.append(
            (name, h.gitlab_namespace, h.parent_group)) or orig(name)
        h.export_bundle(output_path=str(tmp_path / "b.zip"),
                        group="other-ns/Other Group")
        assert seen[0] == ("Other Group", "other-ns", "Other Group")
        assert h.parent_group == "source"          # restored after the run

    def test_import_group_override_threads(self, tmp_path):
        h = ImportBundleHarness()
        during = []
        real = h._import_epics
        h._import_epics = lambda **kw: during.append(
            (h.gitlab_namespace, h.parent_group)) or real(**kw)
        h.import_bundle(input_path=str(make_bundle(tmp_path)),
                        group="other-ns/Other Target")
        assert during == [("other-ns", "Other Target")]
        assert h.parent_group == "target"          # restored after the run

    def test_create_missing_false_threads_to_epics(self, tmp_path):
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(make_bundle(tmp_path)),
                        create_missing=False)
        assert h.calls[0][1]["create_missing"] is False

    def test_garbage_format_version_rejected_gracefully(self, tmp_path, capsys):
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(make_bundle(
            tmp_path, manifest={"format": "nce-bundle",
                                "format_version": "2.0-beta",
                                "files": {"epics": "epics.csv",
                                          "issues": "issues.csv"}})))
        assert h.calls == []
        assert "is not a number" in capsys.readouterr().out

    def test_issues_only_bundle_skips_epics_and_creates_root(self, tmp_path, capsys):
        members = {"issues.csv": "title\nI1\n"}
        manifest = {"format": "nce-bundle", "format_version": 1,
                    "files": {"issues": "issues.csv"},
                    "counts": {"epics": 0, "issues": 1, "links": 0}}
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(make_bundle(tmp_path, manifest, members)))
        assert [c[0] for c in h.calls] == ["issues"]
        issues = h.calls[0][1]
        # with no epics phase to create the root, the issues phase inherits it
        assert issues["create_missing"] is True
        assert issues["epic_id_map"] == {}
        assert "epics — none in bundle, skipped" in capsys.readouterr().out

    def test_neither_epics_nor_issues_rejected(self, tmp_path, capsys):
        members = {"links.csv": "source_type,target_type\nEpic,Epic\n"}
        manifest = {"format": "nce-bundle", "format_version": 1,
                    "files": {"links": "links.csv"}, "counts": {}}
        h = ImportBundleHarness()
        h.import_bundle(input_path=str(make_bundle(tmp_path, manifest, members)))
        assert h.calls == []
        assert "neither an epics nor an issues file" in capsys.readouterr().out

    def test_dry_run_missing_root_message(self, tmp_path, capsys):
        h = ImportBundleHarness(epics_result=False)
        h._epics_result = None                     # phase 1 could not preview
        h.import_bundle(input_path=str(make_bundle(tmp_path)), dry_run=True)
        out = capsys.readouterr().out
        assert "preview stopped" in out
        assert "aborted" not in out                # a dry run is not a failure
