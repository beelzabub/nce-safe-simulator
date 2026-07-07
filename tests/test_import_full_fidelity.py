"""create_missing_projects + blocking-link export/import (Refs #198)."""
import json

import pytest
from unittest.mock import MagicMock

from mixins.importexport import ImportExportMixin, LINK_EXPORT_FIELDS, _gid_int
from mixins.bootstrap import BootstrapMixin

pytestmark = pytest.mark.unit

ROOT_PATH = "ns/target"


# ─── create_missing_projects ──────────────────────────────────────────────────

class CMPHarness(ImportExportMixin, BootstrapMixin):
    def __init__(self, rows, extra_projects=None):
        self.gl = MagicMock()
        self.gitlab_namespace = "ns"
        self.parent_group = "target"
        self._rows = rows
        self.root = MagicMock()
        self.root.full_path = ROOT_PATH
        self.root.id = 1
        self.root.epics.list.return_value = []
        self.group_cache = {ROOT_PATH: self.root}
        self.project_cache = dict(extra_projects or {})
        self.created_groups, self.created_projects = [], []
        self.issues_by_project = {}
        self._next_gid = iter(range(500, 599))

        def _mk_group(payload):
            g = MagicMock()
            g.id = next(self._next_gid)
            parent_path = next(
                (p for p, gr in list(self.group_cache.items()) if gr.id == payload["parent_id"]),
                ROOT_PATH)
            g.full_path = f"{parent_path}/{payload['path']}"
            self.created_groups.append(dict(payload, _full_path=g.full_path, _id=g.id))
            return g
        self.gl.groups.create.side_effect = _mk_group

        def _mk_project(payload):
            p = MagicMock()
            p.id = next(self._next_gid)
            parent_path = next(
                (gp for gp, gr in list(self.group_cache.items()) if gr.id == payload["namespace_id"]),
                ROOT_PATH)
            p.path_with_namespace = f"{parent_path}/{payload['path']}"
            p.issues.list.return_value = []
            p.issues.create.side_effect = lambda ip, _p=p: self._issue(_p, ip)
            self.created_projects.append(dict(payload, _pwn=p.path_with_namespace))
            return p
        self.gl.projects.create.side_effect = _mk_project

    def _issue(self, proj, payload):
        iss = MagicMock()
        iss.iid = 1
        self.issues_by_project.setdefault(proj.path_with_namespace, []).append(dict(payload))
        return iss

    def _load_file(self, path):                                return self._rows
    def _resolve_import_target(self, create_missing, dry_run): return self.root
    def _build_group_cache(self, root_group):                  return self.group_cache
    def _build_project_cache(self, root_group):                return self.project_cache
    def _find_issue_by_title(self, project, title, cache=None):            return None


def _run_issues(h, tmp_path, **kw):
    f = tmp_path / "issues.json"
    f.write_text(json.dumps(h._rows))
    h._import_issues(input_path=str(f), **kw)


def _irow(title="I1", project_path="ns/source/vs-01/team-01/backlog",
          source_root="ns/source"):
    r = {"title": title, "project_path": project_path}
    if source_root is not None:
        r["source_root"] = source_root
    return r


class TestCreateMissingProjects:
    def test_chain_and_project_created_issue_placed(self, tmp_path):
        h = CMPHarness([_irow()])
        _run_issues(h, tmp_path, create_missing_projects=True)
        assert [g["_full_path"] for g in h.created_groups] == [
            f"{ROOT_PATH}/vs-01", f"{ROOT_PATH}/vs-01/team-01"]
        assert [p["_pwn"] for p in h.created_projects] == [
            f"{ROOT_PATH}/vs-01/team-01/backlog"]
        assert "I1" in [i["title"] for i in
                        h.issues_by_project[f"{ROOT_PATH}/vs-01/team-01/backlog"]]

    def test_project_directly_under_root(self, tmp_path):
        h = CMPHarness([_irow(project_path="ns/source/backlog")])
        _run_issues(h, tmp_path, create_missing_projects=True)
        assert h.created_groups == []
        assert h.created_projects[0]["namespace_id"] == h.root.id

    def test_second_row_reuses_created_project(self, tmp_path):
        h = CMPHarness([_irow("I1"), _irow("I2")])
        _run_issues(h, tmp_path, create_missing_projects=True)
        assert len(h.created_projects) == 1
        assert len(h.issues_by_project[f"{ROOT_PATH}/vs-01/team-01/backlog"]) == 2

    def test_guessed_root_never_creates(self, tmp_path, capsys):
        h = CMPHarness([_irow(source_root=None),
                        _irow("I2", project_path="ns/source/vs-01/team-02/backlog",
                              source_root=None)])
        _run_issues(h, tmp_path, create_missing_projects=True)
        assert h.created_projects == []
        assert "SKIP" in capsys.readouterr().out

    def test_flag_off_unchanged_skip(self, tmp_path, capsys):
        h = CMPHarness([_irow()])
        _run_issues(h, tmp_path)
        assert h.created_projects == []
        assert "SKIP" in capsys.readouterr().out

    def test_dry_run_plans_creates_nothing(self, tmp_path, capsys):
        h = CMPHarness([_irow()])
        _run_issues(h, tmp_path, create_missing_projects=True, dry_run=True)
        out = capsys.readouterr().out
        assert h.created_projects == [] and h.created_groups == []
        assert f"[dry] would create project '{ROOT_PATH}/vs-01/team-01/backlog'" in out
        assert "would be created" in out


# ─── Blocking-link import ─────────────────────────────────────────────────────

class LinkHarness(ImportExportMixin, BootstrapMixin):
    def __init__(self, rows, target_epics=None, projects=None):
        self.gl = MagicMock()
        self.url = "https://gl.example"
        self.gitlab_namespace = "ns"
        self.parent_group = "target"
        self._rows = rows
        self.root = MagicMock()
        self.root.full_path = ROOT_PATH
        self.root.id = 1
        eps = []
        for eid, iid, title, gid in (target_epics or []):
            e = MagicMock()
            e.id, e.iid, e.title, e.group_id = eid, iid, title, gid
            e.work_item_id = eid * 10
            eps.append(e)
        self.root.epics.list.return_value = eps
        self._projects = projects or {}
        self.session = MagicMock()
        self.session.post.return_value = MagicMock(status_code=201)
        self.gql_calls = []

    def _load_file(self, path):                 return self._rows
    def get_group_by_name(self, name):          return self.root
    def _build_project_cache(self, root_group): return self._projects
    def _make_session(self):                    return self.session
    def graphql_query(self, q, variables=None, retries=0):
        self.gql_calls.append(variables)
        return {"workItemAddLinkedItems": {"errors": []}}


def _run_links(h, tmp_path, **kw):
    f = tmp_path / "links.json"
    f.write_text(json.dumps(h._rows))
    h._import_links(input_path=str(f), **kw)


def _lrow(s_type="Epic", s_id=100, s_iid=1, s_title="Blocked E",
          s_cont="ns/source/vs-01", t_type="Epic", t_id=200, t_iid=2,
          t_title="Blocker E", t_cont="ns/source/vs-01"):
    return {"link_type": "is_blocked_by",
            "source_type": s_type, "source_id": s_id, "source_iid": s_iid,
            "source_title": s_title, "source_container": s_cont,
            "target_type": t_type, "target_id": t_id, "target_iid": t_iid,
            "target_title": t_title, "target_container": t_cont,
            "source_root": "ns/source"}


class TestLinkImport:
    def test_epic_epic_link_via_titles(self, tmp_path):
        h = LinkHarness([_lrow()],
                        target_epics=[(9001, 11, "Blocked E", 5),
                                      (9002, 12, "Blocker E", 6)])
        _run_links(h, tmp_path)
        url, kwargs = h.session.post.call_args[0][0], h.session.post.call_args[1]
        assert "/groups/5/epics/11/related_epics" in url
        assert kwargs["json"] == {"target_group_id": 6, "target_epic_iid": 12,
                                  "link_type": "is_blocked_by"}

    def test_epic_endpoints_via_id_map(self, tmp_path):
        h = LinkHarness([_lrow(s_title="renamed", t_title="also renamed")],
                        target_epics=[(9001, 11, "New A", 5),
                                      (9002, 12, "New B", 6)])
        m = tmp_path / "map.json"
        m.write_text(json.dumps({"100": 9001, "200": 9002}))
        _run_links(h, tmp_path, epic_id_map=str(m))
        assert "/groups/5/epics/11/related_epics" in h.session.post.call_args[0][0]

    def test_issue_issue_link_via_project_and_title(self, tmp_path):
        proj_a, proj_b = MagicMock(), MagicMock()
        proj_a.id, proj_a.path_with_namespace = 71, f"{ROOT_PATH}/team/backlog"
        proj_b.id, proj_b.path_with_namespace = 72, f"{ROOT_PATH}/other/backlog"
        src_issue = MagicMock(); src_issue.iid = 3; src_issue.title = "Blocked I"; src_issue.project_id = 71
        tgt_issue = MagicMock(); tgt_issue.iid = 4; tgt_issue.title = "Blocker I"; tgt_issue.project_id = 72
        proj_a.issues.list.return_value = [src_issue]
        proj_b.issues.list.return_value = [tgt_issue]
        h = LinkHarness(
            [_lrow(s_type="Issue", s_title="Blocked I", s_cont="ns/source/team/backlog",
                   t_type="Issue", t_title="Blocker I", t_cont="ns/source/other/backlog")],
            projects={proj_a.path_with_namespace: proj_a,
                      proj_b.path_with_namespace: proj_b})
        _run_links(h, tmp_path)
        url, kwargs = h.session.post.call_args[0][0], h.session.post.call_args[1]
        assert "/projects/71/issues/3/links" in url
        assert kwargs["json"]["target_project_id"] == 72
        assert kwargs["json"]["target_issue_iid"] == 4

    def test_cross_type_uses_graphql_mutation(self, tmp_path):
        proj = MagicMock()
        proj.id, proj.path_with_namespace = 71, f"{ROOT_PATH}/team/backlog"
        blocker = MagicMock(); blocker.iid = 4; blocker.title = "Blocking Issue"; blocker.id = 4444
        proj.issues.list.return_value = [blocker]
        h = LinkHarness(
            [_lrow(t_type="Issue", t_title="Blocking Issue",
                   t_cont="ns/source/team/backlog")],
            target_epics=[(9001, 11, "Blocked E", 5)],
            projects={proj.path_with_namespace: proj})
        _run_links(h, tmp_path)
        assert h.gql_calls, "GraphQL mutation not called"
        vars = h.gql_calls[-1]
        assert vars["id"] == "gid://gitlab/WorkItem/90010"     # epic work_item_id
        assert vars["items"] == ["gid://gitlab/WorkItem/4444"]  # issue global id

    def test_unresolved_endpoint_drops_with_warn(self, tmp_path, capsys):
        h = LinkHarness([_lrow()], target_epics=[(9001, 11, "Blocked E", 5)])
        _run_links(h, tmp_path)
        out = capsys.readouterr().out
        h.session.post.assert_not_called()
        assert "link dropped" in out
        assert "1 dropped" in out

    def test_existing_link_409_counts_skipped(self, tmp_path, capsys):
        h = LinkHarness([_lrow()],
                        target_epics=[(9001, 11, "Blocked E", 5),
                                      (9002, 12, "Blocker E", 6)])
        h.session.post.return_value = MagicMock(status_code=409)
        _run_links(h, tmp_path)
        assert "1 already existed" in capsys.readouterr().out

    def test_dry_run_resolves_but_never_posts(self, tmp_path, capsys):
        h = LinkHarness([_lrow()],
                        target_epics=[(9001, 11, "Blocked E", 5),
                                      (9002, 12, "Blocker E", 6)])
        _run_links(h, tmp_path, dry_run=True)
        h.session.post.assert_not_called()
        assert "would link" in capsys.readouterr().out

    def test_titleless_source_issue_dropped_never_iid_guessed(self, tmp_path, capsys):
        """Legacy export with no source title: iids on a re-imported project
        are unstable, so the link is dropped rather than guessed by iid."""
        proj = MagicMock()
        proj.id, proj.path_with_namespace = 71, f"{ROOT_PATH}/team/backlog"
        proj.issues.list.return_value = []
        h = LinkHarness(
            [_lrow(s_type="Issue", s_title="", s_cont="ns/source/team/backlog",
                   t_type="Issue", t_title="Blocker I", t_cont="ns/source/team/backlog")],
            projects={proj.path_with_namespace: proj})
        _run_links(h, tmp_path)
        h.session.post.assert_not_called()
        proj.issues.get.assert_not_called()
        assert "link dropped" in capsys.readouterr().out

    def test_cross_type_without_work_item_id_fails_not_guesses(self, tmp_path, capsys):
        proj = MagicMock()
        proj.id, proj.path_with_namespace = 71, f"{ROOT_PATH}/team/backlog"
        blocker = MagicMock(); blocker.iid = 4; blocker.title = "Blocking Issue"; blocker.id = 4444
        proj.issues.list.return_value = [blocker]
        h = LinkHarness([_lrow(t_type="Issue", t_title="Blocking Issue",
                               t_cont="ns/source/team/backlog")],
                        projects={proj.path_with_namespace: proj})
        # strip work_item_id from the target epic
        epic = MagicMock(spec=["id", "iid", "title", "group_id"])
        epic.id, epic.iid, epic.title, epic.group_id = 9001, 11, "Blocked E", 5
        h.root.epics.list.return_value = [epic]
        _run_links(h, tmp_path)
        assert h.gql_calls == []
        out = capsys.readouterr().out
        assert "no work_item_id" in out
        assert "1 failed" in out

    def test_wrong_file_rejected(self, tmp_path, capsys):
        h = LinkHarness([{"title": "not a link"}])
        _run_links(h, tmp_path)
        assert "does not look like a links export" in capsys.readouterr().out


class TestHelpers:
    def test_gid_int(self):
        assert _gid_int("gid://gitlab/WorkItem/123") == 123
        assert _gid_int(45) == 45
        assert _gid_int(None) is None

    def test_link_export_fields_shape(self):
        assert {"link_type", "source_type", "source_container",
                "target_title", "source_root"} <= set(LINK_EXPORT_FIELDS)


# ─── Blocking-link export ─────────────────────────────────────────────────────

class ExportLinksHarness(ImportExportMixin, BootstrapMixin):
    def __init__(self):
        self.gl = MagicMock()
        self.url = "https://gl.example"
        self.gitlab_namespace = "ns"
        self.parent_group = "source"
        self.root = MagicMock()
        self.root.full_path = "ns/source"
        epic = MagicMock()
        epic.id, epic.iid, epic.title, epic.group_id = 100, 1, "Blocked E", 5
        self.root.epics.list.return_value = [epic]
        self.session = MagicMock()

        def _get(url):
            resp = MagicMock()
            resp.ok = True
            if "related_epics" in url:
                resp.json.return_value = [
                    {"id": 200, "iid": 2, "title": "Blocker E", "group_id": 6,
                     "link_type": "is_blocked_by"},
                    {"id": 300, "iid": 3, "title": "Relates", "group_id": 6,
                     "link_type": "relates_to"},
                ]
            else:   # issue links
                resp.json.return_value = [
                    {"id": 400, "iid": 9, "title": "Blocker I", "project_id": 71,
                     "link_type": "is_blocked_by"},
                ]
            return resp
        self.session.get.side_effect = _get
        self._gql_pages = iter([
            # cross-type pass: one epic blocked by one Issue
            {"group": {"workItems": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [{
                    "id": "gid://gitlab/WorkItem/1000", "iid": 1, "title": "Blocked E",
                    "namespace": {"fullPath": "ns/source/vs-01"},
                    "widgets": [{"linkedItems": {"nodes": [{
                        "linkType": "is_blocked_by",
                        "workItem": {"id": "gid://gitlab/WorkItem/4444", "iid": 7,
                                     "title": "Blocking Issue",
                                     "namespace": {"fullPath": "ns/source/team/backlog"},
                                     "workItemType": {"name": "Issue"}}}]}}],
                }],
            }}},
            # issue flag pass: one blocked issue
            {"group": {"issues": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [{"iid": 8, "title": "Blocked I", "blocked": True,
                           "blockedByCount": 1,
                           "projectId": "gid://gitlab/Project/71"}],
            }}},
        ])
        self.written = None

    def get_group_by_name(self, name):           return self.root
    def _make_session(self):                     return self.session
    def _build_gid_path_map(self, group):        return {5: "ns/source/vs-01", 6: "ns/source/vs-02"}
    def _build_pid_path_map(self, group):        return {71: "ns/source/team/backlog"}
    def graphql_query(self, q, variables=None, retries=0):
        return next(self._gql_pages)
    def _write_file(self, path, fmt, rows, order):
        self.written = rows
    def sanitize_name(self, s):                  return s.lower()
    def _default_export_name(self, stem, fmt):
        import tempfile, pathlib
        return pathlib.Path(tempfile.mkdtemp()) / f"{stem}.{fmt}"


class TestLinkExport:
    def test_all_three_kinds_exported(self, tmp_path):
        h = ExportLinksHarness()
        h._export_links(output_path=str(tmp_path / "links.json"))
        kinds = {(r["source_type"], r["target_type"]) for r in h.written}
        assert kinds == {("Epic", "Epic"), ("Epic", "Issue"), ("Issue", "Issue")}

    def test_non_blocking_links_excluded(self, tmp_path):
        h = ExportLinksHarness()
        h._export_links(output_path=str(tmp_path / "links.json"))
        assert all(r["link_type"] == "is_blocked_by" for r in h.written)
        assert "Relates" not in [r["target_title"] for r in h.written]

    def test_rows_carry_containers_and_stamp(self, tmp_path):
        h = ExportLinksHarness()
        h._export_links(output_path=str(tmp_path / "links.json"))
        ee = next(r for r in h.written
                  if (r["source_type"], r["target_type"]) == ("Epic", "Epic"))
        assert ee["source_container"] == "ns/source/vs-01"
        assert ee["target_container"] == "ns/source/vs-02"
        assert ee["source_root"] == "ns/source"
        cross = next(r for r in h.written if r["target_type"] == "Issue"
                     and r["source_type"] == "Epic")
        assert cross["target_id"] == 4444
        assert cross["target_container"] == "ns/source/team/backlog"
        # Cross-type source id is the LEGACY epic id (the id-map key space),
        # never the WorkItem id from the GraphQL node.
        assert cross["source_id"] == 100
        ii = next(r for r in h.written
                  if (r["source_type"], r["target_type"]) == ("Issue", "Issue"))
        assert ii["source_title"] == "Blocked I"
