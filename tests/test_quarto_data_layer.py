"""Tests for _data_portfolio_health and write_report_json (Refs #39)."""
import json
import sys
import tempfile
from pathlib import Path

import pytest



from tests.conftest import ReportsHarness, make_epic

_PIID = "PIID::Q1-FY25"
_VS   = {"id": 10, "name": "Value Stream 01", "web_url": "https://gitlab.com/test/vs-01"}


def _harness(epics=None, vs_groups=None, piid_labels=None, pct_pi=None):
    epics = epics or []
    h = ReportsHarness(
        epics_all=epics,
        metrics={
            "Epic":       [e for e in epics if e.get("type") == "Epic"],
            "Capability": [e for e in epics if e.get("type") == "Capability"],
            "Feature":    [e for e in epics if e.get("type") == "Feature"],
        },
        vs_groups=vs_groups or [],
        piid_labels=piid_labels or [],
    )
    if pct_pi is not None:
        h._mock_pct_pi = pct_pi
    return h


# ---------------------------------------------------------------------------
# _data_portfolio_health — schema
# ---------------------------------------------------------------------------

class TestDataPortfolioHealthSchema:
    def test_returns_dict(self):
        d = _harness()._data_portfolio_health()
        assert isinstance(d, dict)

    def test_top_level_keys_present(self):
        d = _harness()._data_portfolio_health()
        assert {"generated_at", "report_date", "group", "pi",
                "portfolio", "vs_rows", "top_blocked", "at_risk_epics"} <= d.keys()

    def test_group_subkeys(self):
        d = _harness()._data_portfolio_health()
        assert {"name", "url", "wiki_t2"} <= d["group"].keys()

    def test_pi_subkeys(self):
        d = _harness()._data_portfolio_health()
        assert {"current", "pct_elapsed", "start", "end"} <= d["pi"].keys()

    def test_portfolio_subkeys(self):
        d = _harness()._data_portfolio_health()
        p = d["portfolio"]
        assert {"epics_total", "pi_epics_count", "pct_done", "tl_schedule",
                "blocked_total", "risk_epics", "unassigned", "capacity_str"} <= p.keys()

    def test_json_serializable(self):
        d = _harness()._data_portfolio_health()
        json.dumps(d)  # must not raise


# ---------------------------------------------------------------------------
# _data_portfolio_health — computed values
# ---------------------------------------------------------------------------

class TestDataPortfolioHealthValues:
    def test_epics_total_excludes_cross_group(self):
        normal = make_epic(id=1, etype="Epic")
        cross  = make_epic(id=2, etype="Epic")
        cross["is_cross_group"] = True
        d = _harness(epics=[normal, cross])._data_portfolio_health()
        assert d["portfolio"]["epics_total"] == 1

    def test_risk_epics_counts_active_roam(self):
        epic = make_epic(id=1, etype="Epic",
                         roam_risks=[{"roam_status": "roam::owned"}])
        d = _harness(epics=[epic])._data_portfolio_health()
        assert d["portfolio"]["risk_epics"] == 1

    def test_risk_epics_excludes_resolved_roam(self):
        epic = make_epic(id=1, etype="Epic",
                         roam_risks=[{"roam_status": "roam::resolved"}])
        d = _harness(epics=[epic])._data_portfolio_health()
        assert d["portfolio"]["risk_epics"] == 0

    def test_no_current_pi_returns_none(self):
        d = _harness()._data_portfolio_health()
        assert d["pi"]["current"] is None

    def test_pi_pct_elapsed_zero_when_no_pi(self):
        d = _harness()._data_portfolio_health()
        assert d["pi"]["pct_elapsed"] == 0

    def test_vs_row_structure(self):
        epic = make_epic(id=1, etype="Feature", group_id=10,
                         piid=_PIID, pct_complete=55, planned_weight=10)
        epic["type"] = "Feature"
        d = _harness(epics=[epic], vs_groups=[_VS],
                     piid_labels=[_PIID], pct_pi=50)._data_portfolio_health()
        assert len(d["vs_rows"]) == 1
        row = d["vs_rows"][0]
        assert row["vs"]["name"] == "Value Stream 01"
        assert row["vs"]["web_url"] == "https://gitlab.com/test/vs-01"
        assert {"overall", "tl_sched", "sched_detail", "tl_cap", "cap_detail",
                "tl_risk", "risk_detail", "tl_block", "block_detail",
                "epics_total", "pi_epics", "blocked", "unassigned"} <= row.keys()

    def test_vs_schedule_green(self):
        epic = make_epic(id=1, etype="Feature", group_id=10,
                         piid=_PIID, pct_complete=55, planned_weight=10)
        epic["type"] = "Feature"
        d = _harness(epics=[epic], vs_groups=[_VS],
                     piid_labels=[_PIID], pct_pi=50)._data_portfolio_health()
        assert d["vs_rows"][0]["tl_sched"] == "🟢"

    def test_vs_schedule_yellow(self):
        epic = make_epic(id=1, etype="Feature", group_id=10,
                         piid=_PIID, pct_complete=40, planned_weight=10)
        epic["type"] = "Feature"
        d = _harness(epics=[epic], vs_groups=[_VS],
                     piid_labels=[_PIID], pct_pi=55)._data_portfolio_health()
        assert d["vs_rows"][0]["tl_sched"] == "🟡"

    def test_vs_schedule_red(self):
        epic = make_epic(id=1, etype="Feature", group_id=10,
                         piid=_PIID, pct_complete=10, planned_weight=10)
        epic["type"] = "Feature"
        d = _harness(epics=[epic], vs_groups=[_VS],
                     piid_labels=[_PIID], pct_pi=60)._data_portfolio_health()
        assert d["vs_rows"][0]["tl_sched"] == "🔴"

    def test_at_risk_epic_included(self):
        epic = make_epic(id=1, etype="Feature", group_id=10,
                         piid=_PIID, pct_complete=10, planned_weight=10)
        epic["type"] = "Feature"
        d = _harness(epics=[epic], vs_groups=[_VS],
                     piid_labels=[_PIID], pct_pi=60)._data_portfolio_health()
        assert len(d["at_risk_epics"]) == 1
        item = d["at_risk_epics"][0]
        assert item["gap"] == 50
        assert item["pct_done"] == 10
        assert item["pct_elapsed"] == 60

    def test_at_risk_epic_weight_str_both(self):
        epic = make_epic(id=1, etype="Feature", group_id=10,
                         piid=_PIID, pct_complete=10,
                         planned_weight=10, actual_weight=5)
        epic["type"] = "Feature"
        d = _harness(epics=[epic], vs_groups=[_VS],
                     piid_labels=[_PIID], pct_pi=60)._data_portfolio_health()
        assert d["at_risk_epics"][0]["weight_str"] == "5pt/10pt"

    def test_at_risk_epic_weight_str_epic_only(self):
        epic = make_epic(id=1, etype="Feature", group_id=10,
                         piid=_PIID, pct_complete=10,
                         planned_weight=10, actual_weight=0)
        epic["type"] = "Feature"
        d = _harness(epics=[epic], vs_groups=[_VS],
                     piid_labels=[_PIID], pct_pi=60)._data_portfolio_health()
        assert d["at_risk_epics"][0]["weight_str"] == "10pt (epic)"

    def test_not_at_risk_when_gap_le_20(self):
        epic = make_epic(id=1, etype="Feature", group_id=10,
                         piid=_PIID, pct_complete=40, planned_weight=10)
        epic["type"] = "Feature"
        d = _harness(epics=[epic], vs_groups=[_VS],
                     piid_labels=[_PIID], pct_pi=55)._data_portfolio_health()
        assert len(d["at_risk_epics"]) == 0

    def test_empty_top_blocked_when_no_relationships(self):
        d = _harness()._data_portfolio_health()
        assert d["top_blocked"] == []

    def test_group_name_matches_root(self):
        d = _harness()._data_portfolio_health()
        assert d["group"]["name"] == "Test Portfolio"


# ---------------------------------------------------------------------------
# write_report_json
# ---------------------------------------------------------------------------

class TestWriteReportJson:
    def test_creates_health_dashboard_json(self):
        h = _harness()
        with tempfile.TemporaryDirectory() as tmp:
            h.write_report_json(tmp)
            out = Path(tmp) / "health-dashboard.json"
            assert out.exists()

    def test_json_is_valid(self):
        h = _harness()
        with tempfile.TemporaryDirectory() as tmp:
            h.write_report_json(tmp)
            data = json.loads((Path(tmp) / "health-dashboard.json").read_text())
            assert "portfolio" in data

    def test_creates_data_dir_if_missing(self):
        h = _harness()
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "new_dir" / "data"
            h.write_report_json(nested)
            assert (nested / "health-dashboard.json").exists()

    def test_epics_total_in_json(self):
        epics = [make_epic(id=i, etype="Epic") for i in range(1, 4)]
        h = _harness(epics=epics)
        with tempfile.TemporaryDirectory() as tmp:
            h.write_report_json(tmp)
            data = json.loads((Path(tmp) / "health-dashboard.json").read_text())
            assert data["portfolio"]["epics_total"] == 3
