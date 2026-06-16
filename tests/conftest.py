"""Shared fixtures and test helpers for the beelzabub-project test suite."""
import sys
import types
from collections import defaultdict
from datetime import date
from unittest.mock import MagicMock, patch, create_autospec

from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mixins.reports import ReportsMixin, _item_risk_reasons
from mixins.tools import ToolsMixin
from mixins.labels import LabelsMixin
from mixins.wiki import WikiMixin
from mixins.utils import UtilitiesMixin
from mixins.bootstrap import BootstrapMixin


# ---------------------------------------------------------------------------
# Minimal mock group / root objects
# ---------------------------------------------------------------------------

def make_mock_group(id=1, name="Test Portfolio", web_url="https://gitlab.com/test"):
    g = MagicMock()
    g.id       = id
    g.name     = name
    g.web_url  = web_url
    g.full_path = name.lower().replace(" ", "-")
    return g


# ---------------------------------------------------------------------------
# Epic dict factory
# ---------------------------------------------------------------------------

def make_epic(
    id=100,
    iid=1,
    title="Test Epic",
    etype="Feature",
    state="opened",
    labels=None,
    pct_complete=0,
    pct_through_pi=None,
    due_date=None,
    blocked_by_count=0,
    roam_risks=None,
    parent_id=None,
    group_id=10,
    work_item_id=None,
    web_url=None,
    piid=None,
    created_at=None,
    planned_weight=10,
    actual_weight=5,
):
    default_labels = [etype]
    if piid:
        default_labels.append(piid)
    epic = {
        "id":               id,
        "iid":              iid,
        "title":            title,
        "type":             etype,
        "state":            state.capitalize(),
        "labels":           labels if labels is not None else default_labels,
        "pct_complete":     pct_complete,
        "pct_through_pi":   pct_through_pi,
        "due_date":         due_date,
        "blocked_by_count": blocked_by_count,
        "roam_risks":       roam_risks or [],
        "parent_id":        parent_id,
        "group_id":         group_id,
        "work_item_id":     work_item_id,
        "web_url":          web_url or f"https://gitlab.com/groups/test/-/epics/{iid}",
        "piid":             piid,
        "planned_weight":   planned_weight,
        "actual_weight":    actual_weight,
        "start_date":       None,
        "created_at":       created_at,
        "updated_at":       None,
    }
    return epic


def make_risk(
    iid=1,
    title="Risk: Something might fail",
    roam_status="roam::owned",
    assignee="Alice",
    state="opened",
    web_url=None,
):
    return {
        "iid":         iid,
        "title":       title,
        "web_url":     web_url or f"https://gitlab.com/test/issues/{iid}",
        "state":       state,
        "roam_status": roam_status,
        "assignee":    assignee,
    }


# ---------------------------------------------------------------------------
# Testable ReportsMixin harness
# ---------------------------------------------------------------------------

class ReportsHarness(ReportsMixin, UtilitiesMixin):
    """Concrete subclass of ReportsMixin with all _rd_ state pre-wired for tests."""

    EPIC_TYPE_ICONS         = {"Epic": "🏆", "Capability": "🧩", "Feature": "🛠️"}
    EPIC_TYPE_LABELS        = ["Epic", "Capability", "Feature"]
    EPIC_TYPE_DISPLAY_NAMES = ["Epic", "Capability", "Feature"]
    RISK_LABELS             = ["ROAM::Resolved", "ROAM::Owned", "ROAM::Accepted", "ROAM::Mitigated"]
    LIFECYCLE_LABELS        = ["Funnel", "Reviewing", "Analyzing", "Portfolio Backlog", "Implementing", "Done"]
    PIID_LABELS             = ["PIID::2025Q1", "PIID::2025Q2"]
    PROJECT_LABELS          = ["project::alpha", "project::beta"]

    def __init__(
        self,
        epics_all=None,
        metrics=None,
        groups_by_id=None,
        groups_by_parent=None,
        vs_groups=None,
        piid_labels=None,
        lifecycle_labels=None,
        project_labels=None,
    ):
        root_id = 1
        self._rd_root_obj     = make_mock_group(id=root_id)
        self._rd_root         = {"id": root_id, "name": "Test Portfolio"}
        self._rd_metrics      = metrics or {"Epic": [], "Capability": [], "Feature": []}
        self._rd_epics_all    = epics_all or []
        self._rd_groups_by_id     = groups_by_id or {}
        self._rd_groups_by_parent = groups_by_parent or {}
        self._vs_groups           = vs_groups or []
        self._rd_issues_by_epic    = defaultdict(list)
        self._rd_issues_by_project = defaultdict(list)
        self._rd_blocking          = {"relationships": [], "summary": {}}
        self._rd_piid_labels       = piid_labels       or []
        self._rd_lifecycle_labels  = lifecycle_labels  or []
        self._rd_project_labels    = project_labels    or []
        self._wiki_t1 = "Portfolio/00 Executive Pulse"
        self._wiki_t2 = "Portfolio/01 Program Management"
        self._wiki_t3 = "Portfolio/02 Operational Detail"
        self._wiki_t4 = "Portfolio/03 Data Quality"
        self._uploaded = {}
        # Additional attributes used by Group C report methods
        self.url = "https://gitlab.com"
        self.parent_group = "test-portfolio"
        self._rd_projects_by_nsid  = {}
        self._rd_epics_by_id       = {e["id"]: e for e in (epics_all or [])}
        self._rd_work_type_labels  = []
        self.gl                    = MagicMock()

    def upload_to_wiki(self, group, title, content):
        self._uploaded[title] = content

    def _iter_vs_groups(self):
        yield from self._vs_groups

    def _pct_through_pi(self, piid):
        if not piid:
            return None
        # Simple stub: return 50 for current PIs in tests that set it
        return getattr(self, "_mock_pct_pi", None)

    def _pi_dates_from_label(self, piid):
        import re
        if not piid:
            return None, None
        m = re.match(r'PIID::(\d{4})Q([1-4])$', piid)
        if not m:
            return None, None
        year, q = int(m.group(1)), int(m.group(2))
        q_starts = {1: (1, 1),  2: (4, 1),  3: (7, 1),  4: (10, 1)}
        q_ends   = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
        return date(year, *q_starts[q]), date(year, *q_ends[q])


@pytest.fixture
def reports():
    return ReportsHarness()


# ---------------------------------------------------------------------------
# Epic / issue mock factories (shared by report AND tool tests)
# ---------------------------------------------------------------------------

def _make_epic_mock(id=100, iid=1, title="Test Epic", labels=None, group_id=1, parent_id=None):
    """Return a MagicMock that looks like a python-gitlab Epic object."""
    epic = MagicMock()
    epic.id = id
    epic.iid = iid
    epic.title = title
    epic.labels = labels if labels is not None else []
    epic.group_id = group_id
    epic.parent_id = parent_id
    epic.work_item_id = None
    return epic


def _make_issue_mock(id=200, iid=1, title="Test Issue", epic_id=None):
    """Return a MagicMock that looks like a python-gitlab Issue object."""
    issue = MagicMock()
    issue.id = id
    issue.iid = iid
    issue.title = title
    issue.epic = {"id": epic_id} if epic_id is not None else None
    return issue


# ---------------------------------------------------------------------------
# Testable ToolsMixin harness
# ---------------------------------------------------------------------------

class ToolsHarness(ToolsMixin, LabelsMixin, WikiMixin, UtilitiesMixin):
    """Concrete subclass of ToolsMixin with all external calls pre-wired for tests."""

    EPIC_TYPE_ICONS         = {"Epic": "🏆", "Capability": "🧩", "Feature": "🛠️"}
    EPIC_TYPE_LABELS        = ["Epic", "Capability", "Feature"]
    EPIC_TYPE_DISPLAY_NAMES = ["Epic", "Capability", "Feature"]
    ROAM_LABELS = ["roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"]
    EPIC_TYPE_PLANNED_WEIGHTS = {
        "Epic": [100, 150, 200],
        "Capability": [30, 50, 80],
        "Feature": [5, 8, 13],
    }

    def __init__(self, lifecycle_labels=None, piid_labels=None, metrics=None):
        self.gl = MagicMock()
        self.parent_group = "test-portfolio"
        self.url = "https://gitlab.com"
        self.default_close_percent = 50.0
        self.default_generate_issues_count = 3
        self.default_generate_blocks_count = 2
        self.default_simulate_pi_percent = 50.0
        self.default_weight_drift_threshold = 20.0
        self.fibonacci_weights = [1, 2, 3, 5, 8, 13]

        # Root group: flat (no subgroups) so all _walk loops terminate after root
        self._root_group = MagicMock()
        self._root_group.id = 1
        self._root_group.full_path = "test-portfolio"
        self._root_group.subgroups.list.return_value = []

        self._lifecycle_labels = lifecycle_labels or []
        self._piid_labels      = piid_labels or []
        self._metrics          = metrics or {}

    def get_group_by_name(self, name):
        return self._root_group

    def _discover_labels(self, group, prefix):
        if prefix == "lifecycle::":
            return list(self._lifecycle_labels)
        if prefix == "PIID::":
            return list(self._piid_labels)
        return []

    def calculate_portfolio_metrics(self, group_name):
        return self._metrics

    def _make_session(self):
        return MagicMock()


@pytest.fixture
def tools():
    return ToolsHarness()
