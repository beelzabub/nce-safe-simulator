"""Shared fixtures and test helpers for the beelzabub-project test suite."""
import sys
import types
from collections import defaultdict
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "/root/.venv/beelzabub-project")

from mixins.reports import ReportsMixin, _item_risk_reasons


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

class ReportsHarness(ReportsMixin):
    """Concrete subclass of ReportsMixin with all _rd_ state pre-wired for tests."""

    EPIC_TYPE_ICONS = {"Epic": "🏆", "Capability": "🧩", "Feature": "🛠️"}

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
        return None, None


@pytest.fixture
def reports():
    return ReportsHarness()
