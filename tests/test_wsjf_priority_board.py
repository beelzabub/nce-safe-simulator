"""Tests for generate_wsjf_priority_board (Refs #24)."""
import sys

from unittest.mock import MagicMock

import pytest



from tests.conftest import ReportsHarness, make_epic, make_mock_group


def _epic_with_wsjf(id, urgency=None, risk=None, business_value=None,
                    planned_weight=10, state="opened", piid=None, title=None):
    labels = ["Feature"]
    if urgency is not None:
        labels.append(f"wsjf-urgency::{urgency}")
    if risk is not None:
        labels.append(f"wsjf-risk::{risk}")
    e = make_epic(id=id, title=title or f"Epic {id}", labels=labels,
                  planned_weight=planned_weight, state=state, piid=piid)
    if business_value is not None:
        e["business_value"] = business_value
    return e


def _harness(features=None, epics=None, blocking=None):
    features = features or []
    epics    = epics    or []
    return ReportsHarness(
        epics_all=features + epics,
        metrics={"Epic": epics, "Capability": [], "Feature": features},
        groups_by_parent={},
        vs_groups=[],
    )


def _run(h):
    h.generate_wsjf_priority_board()
    return h._uploaded.get(f"{h._wiki_t2}/WSJF Priority Board", "")


class TestWsjfPriorityBoardStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = _harness()
        h.generate_wsjf_priority_board()
        assert f"{h._wiki_t2}/WSJF Priority Board" in h._uploaded

    def test_page_title_present(self):
        assert "# WSJF Priority Board" in _run(_harness())

    def test_empty_state_shows_guidance_message(self):
        content = _run(_harness())
        assert "No WSJF-scored epics found" in content

    def test_summary_section_present_when_candidates_exist(self):
        e = _epic_with_wsjf(id=1, urgency=3, risk=2)
        content = _run(_harness(features=[e]))
        assert "## Summary" in content

    def test_ranked_board_section_present_when_candidates_exist(self):
        e = _epic_with_wsjf(id=1, urgency=3, risk=2)
        content = _run(_harness(features=[e]))
        assert "## Ranked Board" in content


class TestWsjfScoring:
    def test_score_calculated_as_cost_of_delay_over_job_size(self):
        # (bv=3 + urgency=5 + risk=2) / size=10 = 1.0
        e = _epic_with_wsjf(id=1, business_value=3, urgency=5, risk=2, planned_weight=10)
        content = _run(_harness(features=[e]))
        assert "**1.0**" in content

    def test_partial_score_shown_when_size_is_zero(self):
        e = _epic_with_wsjf(id=1, urgency=5, risk=2, planned_weight=0)
        content = _run(_harness(features=[e]))
        assert "_partial_" in content

    def test_epic_with_all_none_wsjf_excluded(self):
        # no wsjf labels, no business_value → excluded from candidates
        e = make_epic(id=1, labels=["Feature"])
        content = _run(_harness(features=[e]))
        assert "No WSJF-scored epics found" in content

    def test_closed_epic_excluded_from_board(self):
        e = _epic_with_wsjf(id=1, urgency=5, risk=2, state="closed")
        content = _run(_harness(features=[e]))
        assert "No WSJF-scored epics found" in content

    def test_only_urgency_label_qualifies_as_candidate(self):
        # Having any one WSJF component is enough
        e = _epic_with_wsjf(id=1, urgency=8)
        content = _run(_harness(features=[e]))
        assert "## Ranked Board" in content


class TestWsjfRanking:
    def test_higher_score_ranked_before_lower(self):
        high = _epic_with_wsjf(id=1, business_value=8, urgency=8, risk=8, planned_weight=1)
        low  = _epic_with_wsjf(id=2, business_value=1, urgency=1, risk=1, planned_weight=10)
        content = _run(_harness(features=[high, low]))
        pos_high = content.index(high["title"])
        pos_low  = content.index(low["title"])
        assert pos_high < pos_low

    def test_fully_scored_ranked_before_partial(self):
        full    = _epic_with_wsjf(id=1, urgency=5, risk=3, planned_weight=5)
        partial = _epic_with_wsjf(id=2, urgency=5, risk=3, planned_weight=0)
        content = _run(_harness(features=[full, partial]))
        pos_full    = content.index(full["title"])
        pos_partial = content.index(partial["title"])
        assert pos_full < pos_partial

    def test_rank_column_starts_at_one(self):
        e = _epic_with_wsjf(id=1, urgency=5)
        content = _run(_harness(features=[e]))
        assert "| 1 |" in content


class TestWsjfSummaryCounts:
    def test_summary_shows_fully_scored_count(self):
        e = _epic_with_wsjf(id=1, urgency=5, risk=3, planned_weight=5)
        content = _run(_harness(features=[e]))
        assert "Fully scored" in content
        assert "| 1 |" in content

    def test_summary_shows_partial_count(self):
        e = _epic_with_wsjf(id=1, urgency=5, planned_weight=0)
        content = _run(_harness(features=[e]))
        assert "Partially scored" in content

    def test_backlog_vs_inflight_counts(self):
        backlog   = _epic_with_wsjf(id=1, urgency=5)           # no piid
        inflight  = _epic_with_wsjf(id=2, urgency=3, piid="PIID::Q1-FY25")
        content = _run(_harness(features=[backlog, inflight]))
        assert "Portfolio Backlog" in content
        assert "In-flight" in content


def _blocking_harness(pe, blocked, blocker):
    """Build a harness with one blocking relationship."""
    h = _harness(epics=[pe])
    h._rd_blocking = {
        "relationships": [{
            "blocked_epic":             blocked,
            "blocked_by":               [blocker],
            "at_risk_portfolio_epics":  [pe],
        }]
    }
    return h


class TestBlockedBVSummaryTable:
    def test_summary_table_heading_present(self):
        pe      = _epic_with_wsjf(id=10, business_value=8, urgency=5, risk=3, planned_weight=4,
                                  title="Portfolio Epic A")
        blocked = {"id": 20, "title": "Feature X", "web_url": "https://gl/f/20", "type": "Feature"}
        blocker = {"id": 30, "title": "Issue #30", "web_url": "https://gl/i/30"}
        content = _run(_blocking_harness(pe, blocked, blocker))
        assert "Portfolio Epic A" in content

    def test_summary_table_shows_pe_bv(self):
        pe      = _epic_with_wsjf(id=10, business_value=8, title="Portfolio Epic A")
        blocked = {"id": 20, "title": "Feature X", "web_url": "https://gl/f/20", "type": "Feature"}
        blocker = {"id": 30, "title": "Issue #30", "web_url": "https://gl/i/30"}
        content = _run(_blocking_harness(pe, blocked, blocker))
        assert "Portfolio Epic A" in content
        assert "| 8 |" in content

    def test_summary_bullet_shows_bv(self):
        pe      = _epic_with_wsjf(id=10, business_value=8, title="Portfolio Epic A")
        blocked = {"id": 20, "title": "Feature X", "web_url": "https://gl/f/20", "type": "Feature"}
        blocker = {"id": 30, "title": "Issue #30", "web_url": "https://gl/i/30"}
        content = _run(_blocking_harness(pe, blocked, blocker))
        idx = content.index("## Blocked Business Value")
        summary_section = content[idx: content.index("### Blocking Detail", idx)]
        assert "Portfolio Epic A" in summary_section
        assert "BV: 8" in summary_section

    def test_summary_table_blocked_items_count(self):
        pe = _epic_with_wsjf(id=10, business_value=5, title="PE Alpha")
        h  = _harness(epics=[pe])
        h._rd_blocking = {
            "relationships": [
                {"blocked_epic": {"id": 21, "title": "Feat A", "web_url": "https://gl/f/21", "type": "Feature"},
                 "blocked_by": [{"id": 31, "title": "Blocker 1", "web_url": "https://gl/i/31"}],
                 "at_risk_portfolio_epics": [pe]},
                {"blocked_epic": {"id": 22, "title": "Feat B", "web_url": "https://gl/f/22", "type": "Feature"},
                 "blocked_by": [{"id": 32, "title": "Blocker 2", "web_url": "https://gl/i/32"}],
                 "at_risk_portfolio_epics": [pe]},
            ]
        }
        content = _run(h)
        # PE Alpha appears once in the bullet list before the detail table
        idx = content.index("## Blocked Business Value")
        summary_section = content[idx: content.index("### Blocking Detail", idx)]
        assert "PE Alpha" in summary_section
        assert summary_section.count("PE Alpha") == 1

    def test_blocking_detail_heading_present(self):
        pe      = _epic_with_wsjf(id=10, business_value=8, title="PE A")
        blocked = {"id": 20, "title": "Feature X", "web_url": "https://gl/f/20", "type": "Feature"}
        blocker = {"id": 30, "title": "Issue #30", "web_url": "https://gl/i/30"}
        content = _run(_blocking_harness(pe, blocked, blocker))
        assert "### Blocking Detail" in content

    def test_no_blocking_section_when_no_relationships(self):
        content = _run(_harness())
        assert "## Blocked Business Value" not in content
        assert "### Blocking Detail" not in content


# ── Epic-at-Risk vs Blocked-Item distinction (Refs #108) ─────────────────────

def _raw_epic(id, iid, title, etype, parent_id=None, gid=10, state="Opened"):
    """A raw _all_epics_cache entry as produced by calculate_portfolio_metrics."""
    return {
        "id":        id,
        "iid":       iid,
        "title":     title,
        "type":      etype,
        "state":     state,
        "web_url":   f"https://gitlab.com/test/-/epics/{iid}",
        "labels":    [etype],
        "parent_id": parent_id,
        "group_id":  gid,
    }


def _blocking_graph_harness():
    """Harness whose _all_epics_cache holds a properly-labelled hierarchy:

        Portfolio Epic (10) ← Capability (20) ← Feature (30, blocked)
        Feature (40) is the blocker.

    The Feature's /related_epics endpoint reports `is_blocked_by` the blocker.
    """
    pe      = _raw_epic(10, 10, "Portfolio Epic A", "Epic")
    cap     = _raw_epic(20, 20, "Capability B",     "Capability", parent_id=10)
    feat    = _raw_epic(30, 30, "Feature C",        "Feature",    parent_id=20)
    blocker = _raw_epic(40, 40, "Feature Blocker",  "Feature")

    raw = [pe, cap, feat, blocker]
    h = _harness()
    h._all_epics_cache = {h.parent_group: raw}

    session = MagicMock()

    def _get(url, *a, **k):
        resp = MagicMock()
        resp.ok = True
        if f"/epics/{feat['iid']}/related_epics" in url:
            resp.json.return_value = [{
                "id":        blocker["id"],
                "link_type": "is_blocked_by",
                "title":     blocker["title"],
                "web_url":   blocker["web_url"],
            }]
        else:
            resp.json.return_value = []
        return resp

    session.get.side_effect = _get
    h._make_session = MagicMock(return_value=session)
    return h, pe, cap, feat, blocker


class TestEpicAtRiskDistinctFromBlockedItem:
    def test_fetch_blocking_graph_resolves_portfolio_ancestor(self):
        h, pe, cap, feat, blocker = _blocking_graph_harness()
        result = h._fetch_blocking_graph(make_mock_group())

        rels = result["relationships"]
        assert len(rels) == 1
        rel = rels[0]

        # Blocked item is the Feature, not the Portfolio Epic
        assert rel["blocked_epic"]["id"] == feat["id"]
        assert rel["blocked_epic"]["type"] == "Feature"

        # The at-risk Portfolio Epic is resolved via the parent chain …
        ancs = rel["at_risk_portfolio_epics"]
        assert [a["id"] for a in ancs] == [pe["id"]]
        assert ancs[0]["type"] == "Epic"

        # … and is DISTINCT from the blocked item
        assert ancs[0]["id"] != rel["blocked_epic"]["id"]
        assert result["summary"]["portfolio_epics_at_risk"] == 1

    def test_wsjf_blocking_detail_columns_are_distinct(self):
        h, pe, cap, feat, blocker = _blocking_graph_harness()
        h._rd_blocking = h._fetch_blocking_graph(make_mock_group())

        # The Portfolio Epic must be a WSJF candidate (so the board renders) and
        # carry a business value (so the rollup has a number to report).
        pe_metric = _epic_with_wsjf(id=10, urgency=5, risk=3, business_value=8,
                                    planned_weight=4, title="Portfolio Epic A")
        pe_metric["labels"] = ["Epic", "wsjf-urgency::5", "wsjf-risk::3"]
        pe_metric["type"] = "Epic"
        h._rd_metrics = {"Epic": [pe_metric], "Capability": [], "Feature": []}

        content = _run(h)

        assert "### Blocking Detail" in content
        # Locate the data row of the Blocking Detail table
        detail = content[content.index("### Blocking Detail"):]
        data_rows = [ln for ln in detail.splitlines()
                     if ln.startswith("|") and "Portfolio Epic A" in ln]
        assert data_rows, "expected a Blocking Detail row referencing the Portfolio Epic"
        cells = [c.strip() for c in data_rows[0].split("|")]
        # | <Epic at Risk> | BV | <Blocked Item> | Type | Blocker(s) |
        epic_at_risk, blocked_item = cells[1], cells[3]
        assert "Portfolio Epic A" in epic_at_risk
        assert "Feature C" in blocked_item
        assert epic_at_risk != blocked_item


# ── Orphan blocked item: blank Epic-at-Risk, excluded from BV rollup (Refs #108) ──
class TestOrphanBlockedItemBlankEpicAtRisk:
    """When a non-Portfolio-Epic blocked item has no Portfolio Epic ancestor, the
    report keeps its row but leaves "Epic at Risk" blank and omits it from the
    Business-Value-at-risk rollup, instead of collapsing the column onto the
    blocked item."""

    def _orphan_harness(self):
        pe = _epic_with_wsjf(id=10, business_value=8, title="PE Alpha")
        h  = _harness(epics=[pe])
        h._rd_blocking = {
            "relationships": [
                # Well-formed: Feature X rolls up to PE Alpha.
                {"blocked_epic": {"id": 20, "title": "Feature X",
                                  "web_url": "https://gl/f/20", "type": "Feature"},
                 "blocked_by": [{"id": 30, "title": "Blocker 1", "web_url": "https://gl/i/30"}],
                 "at_risk_portfolio_epics": [pe]},
                # Orphan: Feature Y has NO Portfolio Epic ancestor.
                {"blocked_epic": {"id": 21, "title": "Orphan Feature Y",
                                  "web_url": "https://gl/f/21", "type": "Feature"},
                 "blocked_by": [{"id": 31, "title": "Blocker 2", "web_url": "https://gl/i/31"}],
                 "at_risk_portfolio_epics": []},
            ]
        }
        return h

    def test_orphan_row_present_with_blank_epic_at_risk(self):
        content = _run(self._orphan_harness())
        detail  = content[content.index("### Blocking Detail"):]
        rows = [ln for ln in detail.splitlines()
                if ln.startswith("|") and "Orphan Feature Y" in ln]
        assert rows, "orphan blocked item should still appear as a Blocking Detail row"
        cells = [c.strip() for c in rows[0].split("|")]
        # | <Epic at Risk> | BV | <Blocked Item> | Type | Blocker(s) |
        epic_at_risk, blocked_item = cells[1], cells[3]
        assert epic_at_risk == "", f"Epic at Risk must be blank for an orphan, got {epic_at_risk!r}"
        assert "Orphan Feature Y" in blocked_item

    def test_orphan_excluded_from_bv_rollup(self):
        content = _run(self._orphan_harness())
        # Only PE Alpha (BV 8) is counted; the orphan contributes nothing.
        assert "Total Business Value at Risk: 8" in content
        assert "sum of 1 distinct Portfolio Epic" in content
        # The well-formed row still resolves to its Portfolio Epic.
        detail = content[content.index("### Blocking Detail"):]
        assert any(ln.startswith("|") and "PE Alpha" in ln for ln in detail.splitlines())
