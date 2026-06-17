"""Tests for generate_wsjf_priority_board (Refs #24)."""
import sys

import pytest



from tests.conftest import ReportsHarness, make_epic


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
