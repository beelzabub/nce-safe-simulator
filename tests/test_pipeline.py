"""Functional pipeline tests: tool mutation → report output (Refs #26).

Pattern for each test:
  1. set up mock GitLab state
  2. call a ToolsHarness method — it mutates the mock objects
  3. bridge the mutated state into a ReportsHarness _rd_* snapshot
  4. call generate_*()
  5. assert specific rendered content
"""
import sys
import pytest
from unittest.mock import MagicMock



from conftest import (
    ToolsHarness, ReportsHarness,
    _make_epic_mock, _make_issue_mock,
    make_epic, make_risk,
)

pytestmark = pytest.mark.unit

_LC_LABELS = [
    "lifecycle::funnel",
    "lifecycle::analyzing",
    "lifecycle::backlog",
    "lifecycle::implementing",
    "lifecycle::done",
]

_PIID = "PIID::2026Q3"
_VS_ID = 10
_ART_ID = 20


# ─── helpers ────────────────────────────────────────────────────────────────

def _vs(id=_VS_ID, name="VS01"):
    return {"id": id, "name": name, "web_url": f"https://gitlab.com/test/vs-{id}"}


def _art(id=_ART_ID, name="ART01"):
    return {"id": id, "name": name, "web_url": f"https://gitlab.com/test/art-{id}"}


def _proj_stub(id=50, path="team-backlog"):
    p = MagicMock()
    p.id = id
    p.path = path
    p.path_with_namespace = f"test/{path}"
    return p


def _full_project(issues=None):
    fp = MagicMock()
    fp.namespace = {"id": _ART_ID}
    fp.path_with_namespace = "test/team-backlog"
    fp.issues.list.return_value = issues or []
    fp.issues.create.return_value = MagicMock(id=101, iid=1)
    return fp


def _epic_ref(epic, etype="Feature"):
    return {
        "id":      f"gid://gitlab/WorkItem/{epic.id}",
        "id_int":  epic.id,
        "type":    etype,
        "title":   epic.title,
        "state":   "opened",
        "web_url": f"https://gitlab.com/test/-/epics/{epic.iid}",
    }


# ─── Pipeline 1: set-lifecycle-labels → generate_epic_lifecycle_report ──────

def test_set_lifecycle_labels_pipeline_epics_land_in_correct_kanban_bucket():
    tool_h = ToolsHarness(lifecycle_labels=_LC_LABELS)
    epics = [_make_epic_mock(id=i, iid=i, title=f"Feature {i}", labels=["Feature"])
             for i in range(1, 4)]
    tool_h._root_group.epics.list.return_value = epics

    tool_h._tool_set_lifecycle_labels(percent=100, dry_run=False)

    # All epics should now carry a lifecycle:: label
    assert all(any(l.startswith("lifecycle::") for l in e.labels) for e in epics)

    # Bridge: build report dicts from the mutated mock labels
    epic_dicts = [
        make_epic(id=e.id, iid=e.iid, title=e.title, etype="Feature", labels=list(e.labels))
        for e in epics
    ]
    report_h = ReportsHarness(
        metrics={"Feature": epic_dicts, "Epic": [], "Capability": []},
        lifecycle_labels=_LC_LABELS,
    )
    report_h.generate_epic_lifecycle_report()
    content = report_h._uploaded[f"{report_h._wiki_t3}/Epic Lifecycle"]

    # Zero unlabelled: all 3 epics bucketed into a lifecycle state
    assert "| _(unlabelled)_ | 0 |" in content


# ─── Pipeline 2: close-percent → generate_portfolio_health_dashboard ─────────

def test_close_percent_pipeline_pct_complete_flows_to_schedule_traffic_light():
    tool_h = ToolsHarness()
    epics = [_make_epic_mock(id=i, iid=i, labels=["Feature"]) for i in range(1, 5)]
    tool_h._root_group.epics.list.return_value = epics
    tool_h._root_group.projects.list.return_value = []  # no issues needed

    tool_h._tool_close_percent(percent=100, dry_run=False)

    assert all(e.save.called for e in epics)

    # Bridge: closed epics → pct_complete=100; actual=planned for green capacity
    epic_dicts = [
        make_epic(id=e.id, iid=e.iid, title=e.title, etype="Feature",
                  pct_complete=100, planned_weight=10, actual_weight=10,
                  piid=_PIID, group_id=_VS_ID, labels=["Feature", _PIID])
        for e in epics
    ]
    report_h = ReportsHarness(
        metrics={"Feature": epic_dicts, "Epic": [], "Capability": []},
        epics_all=epic_dicts,
        piid_labels=[_PIID],
        vs_groups=[_vs()],
    )
    report_h._mock_pct_pi = 50  # PI is 50% elapsed

    report_h.generate_portfolio_health_dashboard()
    content = report_h._uploaded[f"{report_h._wiki_t1}/Portfolio Health Dashboard"]

    # pct_done=100, pct_through=50 → gap=-50 ≤ 10 → 🟢 schedule
    assert "🟢" in content


# ─── Pipeline 3: generate-roam-risks → generate_risk_register ───────────────

def test_generate_roam_risks_pipeline_risk_appears_in_register():
    tool_h = ToolsHarness()
    epic = _make_epic_mock(id=1, iid=1, title="Feature Alpha", labels=["Feature"])
    tool_h._root_group.epics.list.return_value = [epic]
    tool_h._root_group.projects.list.return_value = [_proj_stub()]
    fp = _full_project()
    tool_h.gl.projects.get.return_value = fp

    tool_h._tool_generate_roam_risks(count=1, relations_min=1, relations_max=1,
                                     seed=42, dry_run=False)

    assert fp.issues.create.call_count == 1
    create_kwargs = fp.issues.create.call_args[0][0]
    roam_status = create_kwargs["labels"][0]
    risk_title = create_kwargs["title"]

    # Bridge: attach the created risk to the epic dict
    risk_dict = make_risk(iid=1, title=risk_title, roam_status=roam_status)
    epic_dict = make_epic(id=1, iid=1, title="Feature Alpha", etype="Feature",
                          roam_risks=[risk_dict])

    report_h = ReportsHarness(
        epics_all=[epic_dict],
        metrics={"Feature": [epic_dict], "Epic": [], "Capability": []},
    )
    report_h.generate_risk_register()
    content = report_h._uploaded[f"{report_h._wiki_t2}/Risk Register"]

    # Risk table header appears when at least one risk is rendered
    assert "| Risk Issue | Assignee |" in content


# ─── Pipeline 4: set-piid-labels → generate_piid_project_report ─────────────

def test_set_piid_labels_pipeline_epics_appear_in_correct_pi_column():
    tool_h = ToolsHarness()
    epics = [
        _make_epic_mock(id=i, iid=i, title=f"Feature {i}",
                        labels=["Feature", "project::DO"])
        for i in range(1, 3)
    ]
    tool_h._root_group.epics.list.return_value = epics

    tool_h._tool_set_piid_labels(piid=_PIID, dry_run=False)

    # Both epics should now carry the PIID label
    assert all(_PIID in e.labels for e in epics)

    # Bridge: extract piid from mutated labels, build epic dicts
    epic_dicts = [
        make_epic(id=e.id, iid=e.iid, title=e.title, etype="Feature",
                  labels=list(e.labels),
                  piid=next((l for l in e.labels if l.startswith("PIID::")), None))
        for e in epics
    ]
    report_h = ReportsHarness(
        metrics={"Feature": epic_dicts, "Epic": [], "Capability": []},
        piid_labels=[_PIID],
        project_labels=["project::DO"],
    )
    report_h.generate_piid_project_report()
    content = report_h._uploaded[f"{report_h._wiki_t2}/Program × PI Matrix"]

    assert "project::DO" in content
    assert _PIID in content
    # Cell is populated — not a "— " empty cell
    assert "🔵 Planned" in content


# ─── Pipeline 5: audit-hierarchy (validation only) ───────────────────────────

def test_audit_hierarchy_pipeline_reports_orphaned_feature_violation(capsys):
    h = ToolsHarness()
    epic = _make_epic_mock(id=1, iid=1, title="Top Epic", labels=["Epic"])
    feat = _make_epic_mock(id=2, iid=2, title="Orphan Feature", labels=["Feature"])
    # feat.parent_id is None → Feature has no parent → violation
    h._root_group.epics.list.return_value = [epic, feat]

    h._tool_audit_hierarchy()

    out = capsys.readouterr().out
    assert "violation" in out.lower()
    assert "FAIL" in out


def test_audit_hierarchy_pipeline_passes_valid_safe_hierarchy(capsys):
    h = ToolsHarness()
    epic = _make_epic_mock(id=1, iid=1, title="Epic A",        labels=["Epic"])
    cap  = _make_epic_mock(id=2, iid=2, title="Cap B",         labels=["Capability"], parent_id=1)
    feat = _make_epic_mock(id=3, iid=3, title="Feature C",     labels=["Feature"],    parent_id=2)
    h._root_group.epics.list.return_value = [epic, cap, feat]

    h._tool_audit_hierarchy()

    out = capsys.readouterr().out
    assert "PASS" in out


# ─── Pipeline 6: generate-epic-blocks → generate_blocking_report ────────────

def test_generate_epic_blocks_pipeline_block_appears_in_blocking_report():
    tool_h = ToolsHarness()
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 201
    session.post.return_value = resp

    grp = tool_h._root_group
    epic1 = _make_epic_mock(id=1, iid=1, title="Epic Alpha")
    epic2 = _make_epic_mock(id=2, iid=2, title="Epic Beta")
    all_epics = [(grp, epic1), (grp, epic2)]

    tool_h._create_epic_blocks(session, all_epics, count=1, dry_run=False)

    assert session.post.call_count == 1

    # Extract source/target from the recorded POST call
    url_str   = session.post.call_args[0][0]
    body      = session.post.call_args[1]["json"]
    src_iid   = int(url_str.split(f"/groups/{grp.id}/epics/")[1].split("/")[0])
    tgt_iid   = body["target_epic_iid"]
    link_type = body["link_type"]

    by_iid = {1: epic1, 2: epic2}
    src, tgt = by_iid[src_iid], by_iid[tgt_iid]
    blocked, blocker = (tgt, src) if link_type == "blocks" else (src, tgt)

    rel = {
        "blocked_epic": _epic_ref(blocked),
        "blocked_by":   [_epic_ref(blocker)],
        "at_risk_portfolio_epics": [],
    }
    report_h = ReportsHarness()
    report_h._rd_blocking = {"relationships": [rel], "summary": {"total_relationships": 1}}
    report_h.generate_blocking_report()
    content = report_h._uploaded[f"{report_h._wiki_t2}/Blocking & Cross-ART Risk"]

    assert "## Blocked Items (Detail)" in content
    assert blocked.title in content


# ─── Pipeline 7: reset-pi-progress → generate_portfolio_health_dashboard ────

def test_reset_pi_progress_pipeline_reopened_epics_show_low_pct_complete():
    tool_h = ToolsHarness()
    closed_epic = _make_epic_mock(id=1, iid=1, labels=["Feature"])
    closed_epic.state = "closed"
    tool_h._root_group.epics.list.return_value = [closed_epic]
    tool_h._root_group.projects.list.return_value = []

    tool_h._tool_reset_pi_progress(all=True, dry_run=False)

    assert closed_epic.save.called  # epic was reopened

    # Bridge: reopened epic → pct_complete=0 (no work done yet)
    epic_dicts = [
        make_epic(id=1, iid=1, title="Feature A", etype="Feature",
                  pct_complete=0, planned_weight=10, actual_weight=10,
                  piid=_PIID, group_id=_VS_ID, labels=["Feature", _PIID])
    ]
    report_h = ReportsHarness(
        metrics={"Feature": epic_dicts, "Epic": [], "Capability": []},
        epics_all=epic_dicts,
        piid_labels=[_PIID],
        vs_groups=[_vs()],
    )
    report_h._mock_pct_pi = 50  # PI 50% elapsed

    report_h.generate_portfolio_health_dashboard()
    content = report_h._uploaded[f"{report_h._wiki_t1}/Portfolio Health Dashboard"]

    # pct_done=0, pct_through=50 → gap=50 > 20 → 🔴 schedule
    assert "🔴" in content


# ─── Pipeline 8: close-percent → generate_pi_predictability_scorecard ────────

def test_close_percent_pipeline_close_rate_reflected_in_scorecard():
    tool_h = ToolsHarness()
    epics = [_make_epic_mock(id=i, iid=i, labels=["Feature"]) for i in range(1, 5)]
    tool_h._root_group.epics.list.return_value = epics
    tool_h._root_group.projects.list.return_value = []

    tool_h._tool_close_percent(percent=100, dry_run=False)

    assert all(e.save.called for e in epics)

    # Bridge: all epics closed → state="closed" in report dicts; group_id=ART_ID
    epic_dicts = [
        make_epic(id=e.id, iid=e.iid, title=e.title, etype="Feature",
                  state="closed", piid=_PIID, group_id=_ART_ID,
                  labels=["Feature", _PIID])
        for e in epics
    ]
    vs, art = _vs(), _art()
    report_h = ReportsHarness(
        metrics={"Feature": epic_dicts, "Epic": [], "Capability": []},
        vs_groups=[vs],
        groups_by_parent={vs["id"]: [art], art["id"]: []},
        piid_labels=[_PIID],
    )
    report_h._mock_pct_pi = 100  # past PI — final predictability calculated

    report_h.generate_pi_predictability_scorecard()
    content = report_h._uploaded[f"{report_h._wiki_t2}/PI Predictability Scorecard"]

    # 4/4 closed → 100% predictability
    assert "100%" in content
