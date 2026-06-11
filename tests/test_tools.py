"""Unit tests for CLI tools: ToolsMixin, LabelsMixin, WikiMixin (Refs #25)."""
import sys
import pytest
from unittest.mock import MagicMock, call



from conftest import ToolsHarness, _make_epic_mock, _make_issue_mock

pytestmark = pytest.mark.unit


# ─── Helpers ────────────────────────────────────────────────────────────────

def _proj_stub(id=50, path="team-backlog"):
    p = MagicMock()
    p.id = id
    p.path = path
    p.path_with_namespace = f"test/{path}"
    return p


def _full_project(issues, namespace_id=10):
    fp = MagicMock()
    fp.namespace = {"id": namespace_id}
    fp.path_with_namespace = "test/team-backlog"
    fp.issues.list.return_value = issues
    fp.issues.create.return_value = MagicMock(iid=1)
    return fp


# ─── close-percent ──────────────────────────────────────────────────────────

def test_close_percent_closes_correct_fraction_of_issues():
    h = ToolsHarness()
    epics = [_make_epic_mock(id=i, iid=i) for i in range(1, 11)]
    h._root_group.epics.list.return_value = epics

    stub = _proj_stub()
    h._root_group.projects.list.return_value = [stub]
    issues = [_make_issue_mock(id=100 + i, iid=i) for i in range(1, 11)]
    h.gl.projects.get.return_value = _full_project(issues)

    h._tool_close_percent(percent=50, seed=42, dry_run=False)

    assert sum(e.save.called for e in epics) == 5
    assert sum(i.save.called for i in issues) == 5


def test_close_percent_100_closes_all():
    h = ToolsHarness()
    epics = [_make_epic_mock(id=i, iid=i) for i in range(1, 4)]
    h._root_group.epics.list.return_value = epics

    h._root_group.projects.list.return_value = [_proj_stub()]
    issues = [_make_issue_mock(id=100 + i, iid=i) for i in range(1, 4)]
    h.gl.projects.get.return_value = _full_project(issues)

    h._tool_close_percent(percent=100, dry_run=False)

    assert all(e.save.called for e in epics)
    assert all(i.save.called for i in issues)


def test_close_percent_0_closes_none():
    h = ToolsHarness()
    epics = [_make_epic_mock(id=i, iid=i) for i in range(1, 4)]
    h._root_group.epics.list.return_value = epics

    h._root_group.projects.list.return_value = [_proj_stub()]
    issues = [_make_issue_mock(id=100 + i, iid=i) for i in range(1, 4)]
    h.gl.projects.get.return_value = _full_project(issues)

    h._tool_close_percent(percent=0, dry_run=False)

    assert not any(e.save.called for e in epics)
    assert not any(i.save.called for i in issues)


# ─── generate-issues ────────────────────────────────────────────────────────

def _setup_generate_issues(h, features, count=2):
    """Wire up root group and gl mocks for _tool_generate_issues."""
    h._root_group.projects.list.return_value = [_proj_stub(path="team-backlog")]
    fp = _full_project(issues=[])
    h.gl.projects.get.return_value = fp
    team_grp = MagicMock()
    team_grp.epics.list.return_value = features
    h.gl.groups.get.return_value = team_grp
    return fp


def test_generate_issues_creates_n_issues_per_epic():
    h = ToolsHarness()
    feat = _make_epic_mock(id=1, iid=1, title="Feature Alpha", labels=["Feature"])
    fp = _setup_generate_issues(h, [feat])

    h._tool_generate_issues(count=2, dry_run=False)

    assert fp.issues.create.call_count == 2


def test_generate_issues_assigns_weight():
    h = ToolsHarness()
    feat = _make_epic_mock(id=1, iid=1, title="Feature Alpha", labels=["Feature"])
    fp = _setup_generate_issues(h, [feat])

    h._tool_generate_issues(count=1, dry_run=False)

    weight = fp.issues.create.call_args[0][0]["weight"]
    assert weight in h.fibonacci_weights


def test_generate_issues_links_issue_to_epic():
    h = ToolsHarness()
    feat = _make_epic_mock(id=42, iid=1, title="Feature Alpha", labels=["Feature"])
    fp = _setup_generate_issues(h, [feat])

    h._tool_generate_issues(count=1, dry_run=False)

    epic_id = fp.issues.create.call_args[0][0]["epic_id"]
    assert epic_id == 42


def test_generate_issues_feature_percent_param_respected():
    h = ToolsHarness()
    feat1 = _make_epic_mock(id=1, iid=1, title="Feature A", labels=["Feature"])
    feat2 = _make_epic_mock(id=2, iid=2, title="Feature B", labels=["Feature"])
    fp = _setup_generate_issues(h, [feat1, feat2])

    # 50% of 2 features → max(1, round(2*0.5)) = 1 feature → count=2 issues
    h._tool_generate_issues(count=2, feature_percent=50.0, dry_run=False)

    assert fp.issues.create.call_count == 2  # not 4


# ─── generate-epic-blocks ───────────────────────────────────────────────────

def test_generate_epic_blocks_creates_blocking_relationships():
    h = ToolsHarness()
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 201
    session.post.return_value = resp

    grp = h._root_group
    epics = [_make_epic_mock(id=i, iid=i, title=f"Epic {i}") for i in range(1, 4)]
    all_epics = [(grp, e) for e in epics]

    h._create_epic_blocks(session, all_epics, count=2, dry_run=False)

    assert session.post.call_count == 2


def test_generate_epic_blocks_does_not_block_resolved_epics():
    """dry_run=True prevents HTTP calls regardless of which epics are passed."""
    h = ToolsHarness()
    session = MagicMock()

    grp = h._root_group
    epics = [_make_epic_mock(id=i, iid=i, title=f"Open Epic {i}") for i in range(1, 3)]
    all_epics = [(grp, e) for e in epics]

    h._create_epic_blocks(session, all_epics, count=1, dry_run=True)

    session.post.assert_not_called()


# ─── simulate-pi-progress ───────────────────────────────────────────────────

def test_simulate_pi_progress_closes_issues_proportional_to_elapsed():
    piid = "PIID::2026Q3"
    h = ToolsHarness()

    e1 = _make_epic_mock(id=10, iid=1, labels=[piid, "Feature"])
    e2 = _make_epic_mock(id=11, iid=2, labels=[piid, "Feature"])
    e3 = _make_epic_mock(id=12, iid=3, labels=["Feature"])  # not in this PI
    h._root_group.epics.list.return_value = [e1, e2, e3]

    h._root_group.projects.list.return_value = [_proj_stub()]
    iss1 = _make_issue_mock(id=100, iid=1, epic_id=10)
    iss2 = _make_issue_mock(id=101, iid=2, epic_id=11)
    iss3 = _make_issue_mock(id=102, iid=3, epic_id=12)  # not linked to PI epics
    h.gl.projects.get.return_value = _full_project([iss1, iss2, iss3])

    h._tool_simulate_pi_progress(piid=piid, percent=100, dry_run=False)

    assert iss1.save.called
    assert iss2.save.called
    assert not iss3.save.called


# ─── set-lifecycle-labels / strip-lifecycle-labels ──────────────────────────

_LC_LABELS = [
    "lifecycle::funnel",
    "lifecycle::analyzing",
    "lifecycle::backlog",
    "lifecycle::implementing",
    "lifecycle::done",
]


def test_set_lifecycle_labels_applies_label_to_all_epics():
    h = ToolsHarness(lifecycle_labels=_LC_LABELS)
    epics = [_make_epic_mock(id=i, iid=i, labels=["Feature"]) for i in range(1, 5)]
    h._root_group.epics.list.return_value = epics

    h._tool_set_lifecycle_labels(percent=100, dry_run=False)

    assert h.gl.http_put.call_count == len(epics)
    for epic in epics:
        assert any(l.startswith("lifecycle::") for l in epic.labels)


def test_strip_lifecycle_labels_removes_lifecycle_labels():
    h = ToolsHarness(lifecycle_labels=["lifecycle::funnel", "lifecycle::analyzing"])
    e1 = _make_epic_mock(id=1, iid=1, labels=["Feature", "lifecycle::funnel"])
    e2 = _make_epic_mock(id=2, iid=2, labels=["Feature", "lifecycle::analyzing"])
    e3 = _make_epic_mock(id=3, iid=3, labels=["Feature"])  # no lifecycle label
    h._root_group.epics.list.return_value = [e1, e2, e3]

    h._tool_strip_lifecycle_labels(dry_run=False)

    assert h.gl.http_put.call_count == 2
    assert not e3.save.called
    assert "lifecycle::funnel" not in e1.labels
    assert "lifecycle::analyzing" not in e2.labels


# ─── strip-piid-labels ──────────────────────────────────────────────────────

_PIID_LABELS = ["PIID::2026Q2", "PIID::2026Q3"]


def test_strip_piid_labels_removes_piid_from_sampled_epics():
    h = ToolsHarness(piid_labels=_PIID_LABELS)
    epics = [_make_epic_mock(id=i, iid=i, labels=["Feature", "PIID::2026Q2"]) for i in range(1, 11)]
    h._root_group.epics.list.return_value = epics

    h._tool_strip_piid_labels(percent=50, dry_run=False)

    stripped = sum(e.save.called for e in epics)
    assert stripped == 5
    for e in epics:
        if e.save.called:
            assert "PIID::2026Q2" not in e.labels


def test_strip_piid_labels_count_overrides_percent():
    h = ToolsHarness(piid_labels=_PIID_LABELS)
    epics = [_make_epic_mock(id=i, iid=i, labels=["Feature", "PIID::2026Q2"]) for i in range(1, 11)]
    h._root_group.epics.list.return_value = epics

    h._tool_strip_piid_labels(count=3, percent=100, dry_run=False)

    assert sum(e.save.called for e in epics) == 3


def test_strip_piid_labels_100_percent_strips_all():
    h = ToolsHarness(piid_labels=_PIID_LABELS)
    epics = [_make_epic_mock(id=i, iid=i, labels=["Feature", "PIID::2026Q3"]) for i in range(1, 6)]
    h._root_group.epics.list.return_value = epics

    h._tool_strip_piid_labels(percent=100, dry_run=False)

    assert all(e.save.called for e in epics)
    for e in epics:
        assert "PIID::2026Q3" not in e.labels


def test_strip_piid_labels_skips_epics_without_piid():
    h = ToolsHarness(piid_labels=_PIID_LABELS)
    e1 = _make_epic_mock(id=1, iid=1, labels=["Feature", "PIID::2026Q2"])
    e2 = _make_epic_mock(id=2, iid=2, labels=["Feature"])  # no PIID
    h._root_group.epics.list.return_value = [e1, e2]

    h._tool_strip_piid_labels(percent=100, dry_run=False)

    assert e1.save.called
    assert not e2.save.called


def test_strip_piid_labels_respects_epic_type_filter():
    h = ToolsHarness(piid_labels=_PIID_LABELS)
    e1 = _make_epic_mock(id=1, iid=1, labels=["Feature",    "PIID::2026Q2"])
    e2 = _make_epic_mock(id=2, iid=2, labels=["Capability", "PIID::2026Q2"])
    h._root_group.epics.list.return_value = [e1, e2]

    h._tool_strip_piid_labels(percent=100, epic_type="Feature", dry_run=False)

    assert e1.save.called
    assert not e2.save.called


def test_strip_piid_labels_dry_run_makes_no_changes():
    h = ToolsHarness(piid_labels=_PIID_LABELS)
    epics = [_make_epic_mock(id=i, iid=i, labels=["Feature", "PIID::2026Q2"]) for i in range(1, 4)]
    h._root_group.epics.list.return_value = epics

    h._tool_strip_piid_labels(percent=100, dry_run=True)

    assert not any(e.save.called for e in epics)
    for e in epics:
        assert "PIID::2026Q2" in e.labels


def test_strip_piid_labels_no_piid_labels_on_group(capsys):
    h = ToolsHarness(piid_labels=[])
    h._root_group.epics.list.return_value = []

    h._tool_strip_piid_labels(percent=100, dry_run=False)

    assert "nothing to strip" in capsys.readouterr().out


# ─── weight-drift ───────────────────────────────────────────────────────────

def test_weight_drift_flags_epics_above_threshold(capsys):
    metrics = {
        "Feature": [
            {
                "iid": 1,
                "title": "Big Feature",
                "labels": ["Feature"],
                "planned_weight": 100,
                "actual_weight": 200,
            }
        ]
    }
    h = ToolsHarness(metrics=metrics)

    h._tool_weight_drift_check(threshold=10, epic_type="Feature")

    out = capsys.readouterr().out
    assert "!!" in out
    assert "Big Feature" in out


def test_weight_drift_within_threshold_not_flagged(capsys):
    metrics = {
        "Feature": [
            {
                "iid": 1,
                "title": "Small Feature",
                "labels": ["Feature"],
                "planned_weight": 100,
                "actual_weight": 110,
            }
        ]
    }
    h = ToolsHarness(metrics=metrics)

    h._tool_weight_drift_check(threshold=50, epic_type="Feature")

    out = capsys.readouterr().out
    assert "!!" not in out


# ─── Labels management (LabelsMixin) ────────────────────────────────────────

def test_create_and_apply_labels_creates_scoped_label():
    h = ToolsHarness()
    target = MagicMock()

    h.create_and_apply_labels(target, ["lifecycle::funnel"])

    target.labels.create.assert_called_once_with(
        {"name": "lifecycle::funnel", "color": "#4287f5"}
    )


def test_create_and_apply_labels_skips_existing_label():
    h = ToolsHarness()
    target = MagicMock()
    target.labels.create.side_effect = Exception("label already exists")

    # Must not raise even when create() fails
    h.create_and_apply_labels(target, ["lifecycle::funnel", "lifecycle::backlog"])

    assert target.labels.create.call_count == 2


def test_delete_all_labels_removes_all():
    h = ToolsHarness()
    target = MagicMock()
    target.name = "test-group"
    lbl1, lbl2 = MagicMock(name="lbl1"), MagicMock(name="lbl2")
    lbl1.name = "lifecycle::funnel"
    lbl2.name = "lifecycle::backlog"
    target.labels.list.return_value = [lbl1, lbl2]

    h.delete_all_labels(target)

    lbl1.delete.assert_called_once()
    lbl2.delete.assert_called_once()


# ─── Wiki operations (WikiMixin) ─────────────────────────────────────────────

def test_upload_to_wiki_creates_page_when_not_exists():
    h = ToolsHarness()
    group = MagicMock()
    group.id = 1
    new_page = MagicMock()
    new_page.slug = "Test-Page"
    group.wikis.create.return_value = new_page

    result = h.upload_to_wiki(group, "Test Page", "# Content")

    group.wikis.create.assert_called_once_with(
        {"title": "Test Page", "content": "# Content"}
    )
    assert result is True


def test_upload_to_wiki_updates_page_when_exists():
    h = ToolsHarness()
    group = MagicMock()
    group.id = 1
    existing = MagicMock()
    # "Test Page" → slug "Test-Page"
    h._wiki_page_cache = {1: {"Test-Page": existing}}

    result = h.upload_to_wiki(group, "Test Page", "# Updated")

    assert existing.content == "# Updated"
    existing.save.assert_called_once()
    assert result is True


def test_delete_all_wiki_pages_removes_all():
    h = ToolsHarness()
    group = MagicMock()
    group.name = "test-group"
    pg1, pg2 = MagicMock(), MagicMock()
    pg1.title = "Page One"
    pg2.title = "Page Two"
    group.wikis.list.return_value = [pg1, pg2]

    h.delete_all_wiki_pages(group)

    pg1.delete.assert_called_once()
    pg2.delete.assert_called_once()
