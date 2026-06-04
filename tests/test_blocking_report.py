"""Tests for generate_blocking_report (Refs #24)."""
import sys

import pytest

sys.path.insert(0, "/root/.venv/beelzabub-project")

from tests.conftest import ReportsHarness, make_epic


def _vs(id=10, name="VS 01"):
    return {"id": id, "name": name, "web_url": f"https://gitlab.com/test/vs-{id:02d}"}


def _blocked_epic(id=1, title="Blocked Epic", etype="Feature"):
    return {
        "id":      f"gid://gitlab/WorkItem/{id}",
        "id_int":  id,
        "type":    etype,
        "title":   title,
        "state":   "opened",
        "web_url": f"https://gitlab.com/test/-/epics/{id}",
    }


def _blocker_epic(id=99, title="Blocker Epic"):
    return {
        "id":      f"gid://gitlab/WorkItem/{id}",
        "id_int":  id,
        "type":    "Feature",
        "title":   title,
        "web_url": f"https://gitlab.com/test/-/epics/{id}",
    }


def _rel(blocked, blockers=None, ancestors=None):
    return {
        "blocked_epic":            blocked,
        "blocked_by":              blockers or [],
        "at_risk_portfolio_epics": ancestors or [],
    }


def _harness(rels=None, total_relationships=None, vs_groups=None):
    blocking = {
        "relationships": rels or [],
        "summary":       {"total_relationships": total_relationships or len(rels or [])},
    }
    return ReportsHarness(
        vs_groups=vs_groups or [],
        groups_by_parent={},
    )


def _harness_with_blocking(rels=None, total_relationships=None, vs_groups=None):
    blocking = {
        "relationships": rels or [],
        "summary":       {"total_relationships": total_relationships or len(rels or [])},
    }
    h = ReportsHarness(
        vs_groups=vs_groups or [],
        groups_by_parent={},
    )
    h._rd_blocking = blocking
    return h


def _run(h):
    h.generate_blocking_report()
    return h._uploaded.get(f"{h._wiki_t2}/Blocking & Cross-ART Risk", "")


class TestBlockingReportStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = _harness_with_blocking()
        h.generate_blocking_report()
        assert f"{h._wiki_t2}/Blocking & Cross-ART Risk" in h._uploaded

    def test_page_title_present(self):
        assert "# Blocking & Cross-ART Risk" in _run(_harness_with_blocking())

    def test_summary_section_present(self):
        assert "## Summary" in _run(_harness_with_blocking())

    def test_cross_art_risk_section_present(self):
        assert "## Cross-ART Risk by Value Stream" in _run(_harness_with_blocking())

    def test_empty_blocking_no_crash(self):
        content = _run(_harness_with_blocking())
        assert content != ""


class TestBlockingReportEmptyState:
    def test_no_blocked_items_message_shown(self):
        content = _run(_harness_with_blocking(rels=[]))
        assert "_No blocked epics found._" in content

    def test_summary_counts_zero_when_empty(self):
        content = _run(_harness_with_blocking(rels=[]))
        assert "| Directly blocked epics | **0** |" in content

    def test_vs_row_shows_none_when_no_cross_art_deps(self):
        vs      = _vs(id=10, name="VS Alpha")
        content = _run(_harness_with_blocking(rels=[], vs_groups=[vs]))
        assert "VS Alpha" in content
        assert "✅ None" in content


class TestBlockingReportWithData:
    def test_blocked_epic_count_shown_in_summary(self):
        rel = _rel(_blocked_epic(id=1), blockers=[_blocker_epic(id=99)])
        content = _run(_harness_with_blocking(rels=[rel], total_relationships=1))
        assert "| Directly blocked epics | **1** |" in content

    def test_total_relationships_from_summary(self):
        rel = _rel(_blocked_epic(id=1), blockers=[_blocker_epic(id=98), _blocker_epic(id=99)])
        content = _run(_harness_with_blocking(rels=[rel], total_relationships=2))
        assert "| Total blocking relationships | **2** |" in content

    def test_blocked_item_detail_section_shown(self):
        rel = _rel(_blocked_epic(id=1, title="My Blocked Epic"),
                   blockers=[_blocker_epic(id=99)])
        content = _run(_harness_with_blocking(rels=[rel]))
        assert "## Blocked Items (Detail)" in content
        assert "My Blocked Epic" in content

    def test_blocked_epic_shows_stop_icon(self):
        rel = _rel(_blocked_epic(id=1), blockers=[_blocker_epic(id=99)])
        content = _run(_harness_with_blocking(rels=[rel]))
        assert "⛔" in content

    def test_portfolio_epic_ancestor_shown_in_risk_table(self):
        ancestor = {
            "id": 500, "type": "Epic",
            "title": "Portfolio Parent Epic",
            "web_url": "https://gitlab.com/test/-/epics/500",
        }
        rel = _rel(
            _blocked_epic(id=1),
            blockers=[_blocker_epic(id=99)],
            ancestors=[ancestor],
        )
        content = _run(_harness_with_blocking(rels=[rel]))
        assert "## Portfolio-Level Risk" in content
        assert "Portfolio Parent Epic" in content

    def test_ancestor_propagation_icon_present(self):
        ancestor = {
            "id": 500, "type": "Epic",
            "title": "Top Epic",
            "web_url": "https://gitlab.com/test/-/epics/500",
        }
        rel = _rel(_blocked_epic(id=1),
                   blockers=[_blocker_epic(id=99)],
                   ancestors=[ancestor])
        content = _run(_harness_with_blocking(rels=[rel]))
        assert "⬆️" in content
