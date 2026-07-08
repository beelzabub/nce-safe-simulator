"""Tests for the Portfolio Explorer report (Refs #182).

The report publishes what the app's Portfolio Explorer shows, so the pinning
test asserts the data builder's payload is exactly
server.analysis.build_portfolio_view over the same snapshot structures —
one source of truth, no drift.
"""

from mixins.reports import REPORTS
from server.analysis import build_portfolio_view
from tests.conftest import ReportsHarness, make_epic


# ---------------------------------------------------------------------------
# Fixture portfolio (mirrors tests/test_analysis_portfolio.py):
#   Epic 1  — blocked work below it (F3 via Capability 2, F4 directly);
#             F3 has a closed child F8 (downstream excludes, subtree includes)
#   Epic 5  — healthy, ahead of schedule
#   Epic 7  — nothing blocked, but behind schedule
# ---------------------------------------------------------------------------

def _epic(id, etype, title=None, parent_id=None, planned=None, actual=None,
          bv=None, state="opened", pct_complete=0, pct_through_pi=None):
    e = make_epic(id=id, iid=id, etype=etype, title=title or f"{etype} {id}",
                  parent_id=parent_id, state=state, pct_complete=pct_complete,
                  pct_through_pi=pct_through_pi, planned_weight=planned,
                  actual_weight=actual, piid="PIID::2026Q3",
                  web_url=f"https://gitlab.example/epics/{id}")
    e["business_value"] = bv
    return e


def _ref(epic, item_type=None):
    ref = {"id": epic["id"], "id_int": epic["id"], "title": epic["title"],
           "type": epic.get("type"), "web_url": epic["web_url"]}
    if item_type:
        ref["item_type"] = item_type
    return ref


def _fixture():
    e1 = _epic(1, "Epic", title="Alpha Epic", planned=233, bv=21,
               pct_complete=40, pct_through_pi=30)
    c2 = _epic(2, "Capability", parent_id=1, planned=34, bv=8)
    f3 = _epic(3, "Feature", title="Blocked Feature", parent_id=2,
               planned=13, bv=5)
    f4 = _epic(4, "Feature", title="Directly Blocked", parent_id=1,
               planned=None, actual=8, bv=None)
    e5 = _epic(5, "Epic", title="Healthy Epic", planned=89, bv=13,
               pct_complete=80, pct_through_pi=50)
    f6 = _epic(6, "Feature", title="The Blocker", parent_id=5, planned=5, bv=3)
    e7 = _epic(7, "Epic", title="Late Epic", planned=144, bv=2,
               pct_complete=10, pct_through_pi=60)
    f8 = _epic(8, "Feature", title="Closed Child", parent_id=3, state="closed",
               planned=2, bv=1)
    epics = [e1, c2, f3, f4, e5, f6, e7, f8]
    blocking = {
        "summary": {"total_blocked": 2, "total_relationships": 2},
        "relationships": [
            {"blocked_epic": _ref(f3), "blocked_by": [_ref(f6)],
             "at_risk_portfolio_epics": [_ref(e1)]},
            {"blocked_epic": _ref(f4), "blocked_by": [_ref(f6)],
             "at_risk_portfolio_epics": [_ref(e1)]},
        ],
    }
    return epics, blocking


def _harness(epics=None, blocking=None, raw_extra=None):
    """raw_extra: epics present only in all_epics_raw (untyped), not in the
    typed lookup — mirrors production where _rd_epics_by_id holds typed epics
    and _rd_epics_all holds all_epics_raw."""
    epics = epics if epics is not None else []
    h = ReportsHarness(epics_all=epics)
    if raw_extra:
        h._rd_epics_all = epics + raw_extra
    if blocking is not None:
        h._rd_blocking = blocking
    return h


def _run_md(h):
    h.generate_portfolio_explorer_report()
    return h._uploaded.get(f"{h._wiki_t1}/Portfolio Explorer", "")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_portfolio_explorer_in_reports_registry(self):
        entry = next((r for r in REPORTS if r["key"] == "portfolio-explorer"), None)
        assert entry is not None
        assert entry["method"] == "generate_portfolio_explorer_report"
        assert entry["needs_group"] is False

    def test_data_builder_registered_for_quarto_layer(self):
        """write_report_json must actually emit portfolio-explorer.json —
        guards the registry tuple, not just the method's existence."""
        import tempfile
        from pathlib import Path
        h = _harness(*_fixture())
        with tempfile.TemporaryDirectory() as tmp:
            h.write_report_json(tmp)
            assert (Path(tmp) / "portfolio-explorer.json").exists()


# ---------------------------------------------------------------------------
# Data builder pins to server.analysis (single source of truth)
# ---------------------------------------------------------------------------

class TestDataBuilderPinsToAnalysis:
    def test_payload_equals_build_portfolio_view(self):
        """Typed lookup and raw lookup differ (an untyped epic sits only in
        the raw list, as in production snapshots), so this pin fails if the
        builder swaps or drops either argument."""
        epics, blocking = _fixture()
        untyped = _epic(9, "Feature", title="Untyped Intermediate",
                        parent_id=1, planned=3, bv=2)
        untyped["type"] = None
        h = _harness(epics, blocking, raw_extra=[untyped])
        data = h._data_portfolio_explorer()

        expected = build_portfolio_view(
            {e["id"]: e for e in epics}, blocking,
            {e["id"]: e for e in epics + [untyped]},
        )
        assert data["totals"] == expected["totals"]
        assert data["portfolio_epics"] == expected["portfolio_epics"]
        # The untyped raw-only epic is an open child of blocked Epic 1's
        # subtree root — sanity-check it actually influenced the result.
        assert expected["totals"]["blocked_business_value_subtree"] >= 6

    def test_payload_carries_report_date_and_group(self):
        h = _harness(*_fixture())
        data = h._data_portfolio_explorer()
        assert data["group"]["name"] == "Test Portfolio"
        assert "report_date" in data

    def test_three_tier_semantics_in_totals(self):
        """Downstream excludes the closed child F8; subtree includes it."""
        h = _harness(*_fixture())
        totals = h._data_portfolio_explorer()["totals"]
        # direct: F3 (bv 5) + F4 (bv None) = 5; downstream: F8 closed, excluded
        assert totals["blocked_business_value"] == 5
        assert totals["blocked_business_value_downstream"] == 5
        assert totals["blocked_business_value_subtree"] == 6
        # weight: F3 planned 13 + F4 actual-fallback 8 = 21. F3's set
        # weight is authoritative for its subtree (#179), so closed child
        # F8 is already covered — subtree is 21, not 23.
        assert totals["blocked_weight"] == 21
        assert totals["blocked_weight_downstream"] == 21
        assert totals["blocked_weight_subtree"] == 21


# ---------------------------------------------------------------------------
# Wiki markdown
# ---------------------------------------------------------------------------

class TestWikiPage:
    def test_uploads_to_tier1_portfolio_explorer(self):
        h = _harness(*_fixture())
        h.generate_portfolio_explorer_report()
        assert f"{h._wiki_t1}/Portfolio Explorer" in h._uploaded

    def test_title_and_summary_counts(self):
        md = _run_md(_harness(*_fixture()))
        assert "# 🧭 Portfolio Explorer" in md
        assert "| Portfolio Epics | 3 |" in md
        assert "| Need attention | 2 |" in md
        assert "| Blocked items (deduped) | 2 |" in md

    def test_totals_tier_table_bolds_downstream(self):
        md = _run_md(_harness(*_fixture()))
        assert "| ★ Business Value | 5 | **5** | 6 |" in md
        assert "| ⚓ Weight | 21 | **21** | 21 |" in md

    def test_metric_definitions_table_present(self):
        md = _run_md(_harness(*_fixture()))
        for term in ("**Direct**", "**Downstream**", "**Subtree**"):
            assert term in md

    def test_chain_rendered_with_blocked_node_and_blocker(self):
        md = _run_md(_harness(*_fixture()))
        assert " → " in md
        assert "⛔" in md
        assert "Blocked Feature" in md
        assert "blocked by" in md
        assert "The Blocker" in md

    def test_behind_schedule_flag_on_late_epic(self):
        md = _run_md(_harness(*_fixture()))
        assert "⏱ behind schedule" in md

    def test_healthy_epic_reads_on_track(self):
        md = _run_md(_harness(*_fixture()))
        assert "✅ on track" in md

    def test_attention_epics_sort_first(self):
        md = _run_md(_harness(*_fixture()))
        assert md.index("Alpha Epic") < md.index("Late Epic") < md.index("Healthy Epic")

    def test_empty_portfolio_shows_guidance(self):
        md = _run_md(_harness([], {"relationships": [], "summary": {}}))
        assert "No portfolio epics" in md

    def test_closed_blocked_item_struck_through_with_cleanup_note(self):
        epics, blocking = _fixture()
        for e in epics:
            if e["id"] == 3:
                e["state"] = "Closed"
        md = _run_md(_harness(epics, blocking))
        assert "<s>" in md
        assert "blocked · closed" in md
        assert "consider clearing the blocking links" in md

    def test_untyped_chain_node_flagged(self):
        epics, blocking = _fixture()
        for e in epics:
            if e["id"] == 2:
                e["type"] = None
        md = _run_md(_harness(epics, blocking))
        assert "*(untyped)*" in md
        assert "❓ Untyped epics in chains | 1" in md

    def test_issue_type_blocker_uses_issue_icon(self):
        epics, blocking = _fixture()
        issue_ref = {"id": 900, "id_int": 900, "title": "Blocking Issue",
                     "type": None, "item_type": "Issue",
                     "web_url": "https://gitlab.example/issues/900"}
        blocking["relationships"][0]["blocked_by"] = [issue_ref]
        md = _run_md(_harness(epics, blocking))
        assert "📋" in md
        assert "Blocking Issue" in md


# ---------------------------------------------------------------------------
# Wiki index integration
# ---------------------------------------------------------------------------

class TestWikiIndexListsExplorer:
    def test_home_index_links_portfolio_explorer(self):
        h = _harness(*_fixture())
        h.url = "https://gitlab.com"
        h.generate_wiki_index()
        joined = "\n".join(h._uploaded.values())
        assert "Portfolio Explorer" in joined
        assert "three-tier BV/weight at risk" in joined
