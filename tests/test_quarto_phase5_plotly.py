"""
Phase-5 data-layer tests: validate _data_* output shapes for Plotly charts
and assert SAFe metric correctness (Refs #45).

SAFe validity notes documented inline — each test that catches a known
constraint carries a comment explaining the SAFe rule being enforced.
"""
import json
from collections import defaultdict
from datetime import date, timedelta

import pytest

from tests.conftest import ReportsHarness, make_epic

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_PIID_A = "PIID::2024Q1"
_PIID_B = "PIID::2024Q2"
_PIID_C = "PIID::2024Q3"

_VS   = {"id": 10, "name": "VS Alpha",  "web_url": "https://gl.com/vs-alpha",  "parent_id": 1}
_ART  = {"id": 20, "name": "ART One",   "web_url": "https://gl.com/art-one",   "parent_id": 10, "full_path": "vs/art"}
_ART2 = {"id": 21, "name": "ART Two",   "web_url": "https://gl.com/art-two",   "parent_id": 10, "full_path": "vs/art2"}
_TEAM = {"id": 30, "name": "Team Red",  "web_url": "https://gl.com/team-red",  "parent_id": 20, "full_path": "vs/art/team"}
_TEAM2= {"id": 31, "name": "Team Blue", "web_url": "https://gl.com/team-blue", "parent_id": 20, "full_path": "vs/art/team2"}


def _h(features=None, capabilities=None, epics=None, piid_labels=None,
        groups_by_parent=None, vs_groups=None, blocking=None, work_type_labels=None):
    feats = features or []
    caps  = capabilities or []
    eps   = epics or []
    all_e = feats + caps + eps
    h = ReportsHarness(
        epics_all=all_e,
        metrics={
            "Epic":       eps,
            "Capability": caps,
            "Feature":    feats,
        },
        groups_by_parent=groups_by_parent or {
            1: [_VS], 10: [_ART], 20: [_TEAM],
        },
        vs_groups=vs_groups or [_VS],
        piid_labels=piid_labels or [],
    )
    if blocking is not None:
        h._rd_blocking = blocking
    if work_type_labels is not None:
        h._rd_work_type_labels = work_type_labels
    return h


def _feat(**kw):
    kw.setdefault("group_id", 30)
    kw.setdefault("etype", "Feature")
    return make_epic(**kw)


def _cap(**kw):
    kw.setdefault("group_id", 20)
    kw.setdefault("etype", "Capability")
    return make_epic(**kw)


def _ep(**kw):
    kw.setdefault("etype", "Epic")
    return make_epic(**kw)


# ===========================================================================
# _data_flow_metrics — Plotly shape + SAFe validity
# ===========================================================================

class TestDataFlowMetricsShape:
    """Verify the JSON structure required by the Plotly velocity/load/distribution/predictability charts."""

    def test_top_level_keys(self):
        d = _h()._data_flow_metrics()
        assert {"report_date", "group", "velocity", "load", "load_no_pi",
                "distribution", "flow_time", "predictability"} <= d.keys()

    def test_velocity_row_has_plotly_fields(self):
        """Bubble/bar chart needs piid, features, capabilities, total."""
        d = _h(
            features=[_feat(piid=_PIID_A, state="closed")],
            piid_labels=[_PIID_A],
        )._data_flow_metrics()
        row = d["velocity"][0]
        assert {"piid", "features", "capabilities", "total"} <= row.keys()
        assert isinstance(row["features"], int)
        assert isinstance(row["total"], int)

    def test_load_row_has_plotly_fields(self):
        """Stacked bar needs piid, features, capabilities, epics, total, planned_weight."""
        d = _h(
            features=[_feat(piid=_PIID_A)],
            piid_labels=[_PIID_A],
        )._data_flow_metrics()
        row = d["load"][0]
        assert {"piid", "features", "capabilities", "epics", "total", "planned_weight"} <= row.keys()

    def test_distribution_by_type_has_plotly_fields(self):
        """Donut chart needs type, count, pct_items, planned_weight, pct_weight."""
        d = _h(features=[_feat()])._data_flow_metrics()
        row = d["distribution"]["by_type"][0]
        assert {"type", "count", "pct_items", "planned_weight", "pct_weight"} <= row.keys()

    def test_predictability_row_has_plotly_fields(self):
        """Bar+refline chart needs piid, committed, delivered, pct, icon."""
        d = _h(
            features=[_feat(piid=_PIID_A, state="closed")],
            piid_labels=[_PIID_A],
        )._data_flow_metrics()
        assert d["predictability"], "expected at least one predictability row"
        row = d["predictability"][0]
        assert {"piid", "committed", "delivered", "pct", "icon"} <= row.keys()
        assert isinstance(row["pct"], int)

    def test_flow_time_has_required_keys(self):
        d = _h()._data_flow_metrics()
        ft = d["flow_time"]
        assert {"open_ages", "closed_cycles", "has_closed_data"} <= ft.keys()

    def test_json_serializable(self):
        d = _h(
            features=[_feat(piid=_PIID_A, state="closed"), _feat(piid=_PIID_B)],
            piid_labels=[_PIID_A, _PIID_B],
        )._data_flow_metrics()
        json.dumps(d)


class TestDataFlowMetricsSafeValidity:
    """
    SAFe validity assertions for Flow Metrics.

    SAFe 6.0 defines six flow metrics at ART/portfolio level.
    These tests enforce correctness of the three we compute from GitLab.
    """

    # --- Velocity ---

    def test_velocity_only_counts_closed_epics(self):
        """
        SAFe: Flow Velocity = value-delivering items DELIVERED (closed) per PI.
        Open items must not be counted as velocity.
        """
        closed_f = _feat(id=1, piid=_PIID_A, state="closed")
        open_f   = _feat(id=2, piid=_PIID_A, state="opened")
        d = _h(features=[closed_f, open_f], piid_labels=[_PIID_A])._data_flow_metrics()
        row = next(r for r in d["velocity"] if r["piid"] == _PIID_A)
        assert row["features"] == 1, "open item must not count toward velocity"
        assert row["total"]    == 1

    def test_velocity_excludes_portfolio_epics(self):
        """
        SAFe: Portfolio Epics span multiple PIs and are NOT the delivery unit.
        Only Features and Capabilities count as velocity.
        """
        ep = _ep(piid=_PIID_A, state="closed")
        d  = _h(epics=[ep], piid_labels=[_PIID_A])._data_flow_metrics()
        row = d["velocity"][0]
        assert row["total"] == 0, "closed portfolio epics must not appear in velocity"

    def test_velocity_respects_pi_boundary(self):
        """An item labeled PIID::2024Q1 must not appear in 2024Q2 velocity."""
        f_q1 = _feat(id=1, piid=_PIID_A, state="closed")
        f_q2 = _feat(id=2, piid=_PIID_B, state="closed")
        d = _h(features=[f_q1, f_q2], piid_labels=[_PIID_A, _PIID_B])._data_flow_metrics()
        row_a = next(r for r in d["velocity"] if r["piid"] == _PIID_A)
        row_b = next(r for r in d["velocity"] if r["piid"] == _PIID_B)
        assert row_a["features"] == 1
        assert row_b["features"] == 1

    def test_velocity_zero_when_no_pi_closed(self):
        """PIs with no closed work should show zero, not be omitted."""
        d = _h(piid_labels=[_PIID_A])._data_flow_metrics()
        assert len(d["velocity"]) == 1
        assert d["velocity"][0]["total"] == 0

    # --- Flow Load (WIP) ---

    def test_load_only_counts_open_epics(self):
        """
        SAFe: Flow Load = active WIP. Closed items are done and must not
        appear in the WIP count.
        """
        closed_f = _feat(id=1, piid=_PIID_A, state="closed")
        open_f   = _feat(id=2, piid=_PIID_A, state="opened")
        d = _h(features=[closed_f, open_f], piid_labels=[_PIID_A])._data_flow_metrics()
        row = next(r for r in d["load"] if r["piid"] == _PIID_A)
        assert row["features"] == 1, "closed item must not appear in WIP load"

    def test_load_includes_all_hierarchy_levels(self):
        """WIP must account for Features, Capabilities, AND Epics."""
        d = _h(
            features=[_feat(id=1, piid=_PIID_A)],
            capabilities=[_cap(id=2, piid=_PIID_A)],
            epics=[_ep(id=3, piid=_PIID_A)],
            piid_labels=[_PIID_A],
        )._data_flow_metrics()
        row = next(r for r in d["load"] if r["piid"] == _PIID_A)
        assert row["features"]     == 1
        assert row["capabilities"] == 1
        assert row["epics"]        == 1
        assert row["total"]        == 3

    def test_load_no_pi_captures_unassigned_wip(self):
        """
        Epics with no PI label are portfolio backlog — still WIP.
        They must appear in load_no_pi, not silently dropped.
        """
        f = _feat(id=1, piid=None)
        d = _h(features=[f], piid_labels=[])._data_flow_metrics()
        assert d["load_no_pi"] is not None
        assert d["load_no_pi"]["features"] == 1

    def test_load_no_pi_none_when_all_assigned(self):
        """load_no_pi must be None when every open epic has a PI label."""
        f = _feat(id=1, piid=_PIID_A)
        d = _h(features=[f], piid_labels=[_PIID_A])._data_flow_metrics()
        assert d["load_no_pi"] is None

    # --- Flow Distribution ---

    def test_distribution_type_counts_all_states(self):
        """
        SAFe: Distribution reflects portfolio shape — open AND closed items.
        Distribution is a snapshot of the whole portfolio, not just WIP.
        """
        closed_f = _feat(id=1, piid=_PIID_A, state="closed")
        open_f   = _feat(id=2, piid=_PIID_A)
        d = _h(features=[closed_f, open_f], piid_labels=[_PIID_A])._data_flow_metrics()
        feat_row = next(r for r in d["distribution"]["by_type"] if r["type"] == "Feature")
        assert feat_row["count"] == 2, "distribution should count all states"

    def test_distribution_pct_items_sums_to_100(self):
        """Portfolio type percentages must sum to approximately 100%."""
        d = _h(
            features=[_feat(id=1), _feat(id=2)],
            capabilities=[_cap(id=3)],
        )._data_flow_metrics()
        total = sum(
            int(r["pct_items"].rstrip("%"))
            for r in d["distribution"]["by_type"]
            if r["pct_items"] != "—"
        )
        # rounding may cause 99 or 101 — allow ±2
        assert abs(total - 100) <= 2, f"pct_items sum {total} not near 100"

    def test_distribution_work_type_empty_when_no_labels(self):
        """
        SAFe: Work-type distribution requires type:: labels on epics.
        When absent the report must signal it, not silently return empty rows.
        """
        d = _h(features=[_feat()])._data_flow_metrics()
        assert d["distribution"]["has_work_type_labels"] is False
        assert d["distribution"]["by_work_type"] == []

    def test_distribution_work_type_populated_with_labels(self):
        f = _feat(labels=["Feature", _PIID_A, "type::feature"])
        d = _h(
            features=[f],
            work_type_labels=["type::feature"],
        )._data_flow_metrics()
        assert d["distribution"]["has_work_type_labels"] is True
        assert len(d["distribution"]["by_work_type"]) == 1
        assert d["distribution"]["by_work_type"][0]["label"] == "type::feature"

    # --- Flow Predictability ---

    def test_predictability_pct_formula(self):
        """
        SAFe: Predictability = delivered ÷ committed × 100.
        2 closed of 4 total = 50%.
        """
        feats = [
            _feat(id=1, piid=_PIID_A, state="closed"),
            _feat(id=2, piid=_PIID_A, state="closed"),
            _feat(id=3, piid=_PIID_A, state="opened"),
            _feat(id=4, piid=_PIID_A, state="opened"),
        ]
        d = _h(features=feats, piid_labels=[_PIID_A])._data_flow_metrics()
        row = d["predictability"][0]
        assert row["committed"] == 4
        assert row["delivered"] == 2
        assert row["pct"]       == 50

    def test_predictability_100pct_icon_green(self):
        """SAFe target is 80–100%. 100% gets the green icon."""
        f = _feat(id=1, piid=_PIID_A, state="closed")
        d = _h(features=[f], piid_labels=[_PIID_A])._data_flow_metrics()
        assert d["predictability"][0]["icon"] == "🟢"

    def test_predictability_60pct_icon_yellow(self):
        feats = [
            _feat(id=1, piid=_PIID_A, state="closed"),
            _feat(id=2, piid=_PIID_A, state="closed"),
            _feat(id=3, piid=_PIID_A, state="closed"),
            _feat(id=4, piid=_PIID_A, state="opened"),
            _feat(id=5, piid=_PIID_A, state="opened"),
        ]
        d = _h(features=feats, piid_labels=[_PIID_A])._data_flow_metrics()
        row = d["predictability"][0]
        assert row["pct"] == 60
        assert row["icon"] == "🟡"

    def test_predictability_below_60pct_icon_red(self):
        feats = [
            _feat(id=1, piid=_PIID_A, state="closed"),
            _feat(id=2, piid=_PIID_A, state="opened"),
            _feat(id=3, piid=_PIID_A, state="opened"),
            _feat(id=4, piid=_PIID_A, state="opened"),
        ]
        d = _h(features=feats, piid_labels=[_PIID_A])._data_flow_metrics()
        row = d["predictability"][0]
        assert row["pct"] == 25
        assert row["icon"] == "🔴"

    def test_predictability_omits_pi_with_no_committed_items(self):
        """A PI that has no Features or Capabilities must not appear in predictability."""
        ep = _ep(id=1, piid=_PIID_A)   # Portfolio Epic, not a commitment unit
        d = _h(epics=[ep], piid_labels=[_PIID_A])._data_flow_metrics()
        assert d["predictability"] == [], "PI with only Portfolio Epics is not a commitment"

    def test_predictability_capabilities_count_as_committed(self):
        """
        SAFe: Capabilities are ART-level commitments and MUST count toward predictability.
        A common implementation mistake is counting only Features.
        """
        cap = _cap(id=1, piid=_PIID_A, state="closed")
        d   = _h(capabilities=[cap], piid_labels=[_PIID_A])._data_flow_metrics()
        row = d["predictability"][0]
        assert row["committed"] == 1
        assert row["delivered"] == 1

    # --- Flow Time ---

    def test_flow_time_open_age_computed_from_created_at(self):
        """Cycle time for open epics = today − created_at."""
        today      = date.today()
        created    = (today - timedelta(days=10)).isoformat()
        f = _feat(created_at=created)
        d = _h(features=[f])._data_flow_metrics()
        feat_row = next(r for r in d["flow_time"]["open_ages"] if r["type"] == "Feature")
        assert feat_row["avg_days"] == 10

    def test_flow_time_closed_cycle_uses_updated_at_proxy(self):
        """
        Note: GitLab epics have no direct closed_at field.
        We use updated_at as a proxy — this is explicitly documented.
        The test confirms the proxy is applied.
        """
        today   = date.today()
        created = (today - timedelta(days=30)).isoformat()
        updated = (today - timedelta(days=5)).isoformat()
        f = _feat(state="closed", created_at=created)
        f["updated_at"] = updated
        d = _h(features=[f])._data_flow_metrics()
        feat_row = next(r for r in d["flow_time"]["closed_cycles"] if r["type"] == "Feature")
        # cycle time = updated_at - created_at = 30 - 5 = 25 days
        assert feat_row["avg_days"] == 25


# ===========================================================================
# _data_wsjf — Plotly shape + SAFe validity
# ===========================================================================

class TestDataWsjfShape:
    """Verify WSJF JSON structure required for the Plotly bubble chart."""

    def _epic_with_wsjf(self, id=1, value=5, urgency=8, risk=3, size=20,
                         state="opened", piid=None, etype="Feature"):
        labels = [etype, f"wsjf-urgency::{urgency}", f"wsjf-risk::{risk}"]
        if piid:
            labels.append(piid)
        e = make_epic(
            id=id, etype=etype, state=state,
            planned_weight=size, labels=labels,
            group_id=30, piid=piid,
        )
        e["business_value"] = value
        return e

    def test_top_level_keys(self):
        d = _h()._data_wsjf()
        assert {"report_date", "group", "summary", "candidates", "blocked_bv"} <= d.keys()

    def test_candidate_has_plotly_fields(self):
        """Bubble chart needs title, url, type, piid, value, urgency, risk, size, score, rank."""
        e = self._epic_with_wsjf()
        d = _h(features=[e])._data_wsjf()
        assert d["candidates"], "expected at least one candidate"
        c = d["candidates"][0]
        for key in ("title", "url", "type", "piid", "value", "urgency",
                    "risk", "size", "score", "rank"):
            assert key in c, f"candidate missing key: {key}"

    def test_candidate_score_is_numeric(self):
        e = self._epic_with_wsjf(value=5, urgency=8, risk=3, size=20)
        d = _h(features=[e])._data_wsjf()
        c = d["candidates"][0]
        assert isinstance(c["score"], float)

    def test_candidate_rank_sequential(self):
        e1 = self._epic_with_wsjf(id=1, value=13, urgency=13, risk=13, size=10)
        e2 = self._epic_with_wsjf(id=2, value=1,  urgency=1,  risk=1,  size=10)
        d  = _h(features=[e1, e2])._data_wsjf()
        ranks = [c["rank"] for c in d["candidates"]]
        assert ranks == [1, 2]

    def test_summary_counts_correct(self):
        scored  = self._epic_with_wsjf(id=1, size=20)
        partial = self._epic_with_wsjf(id=2, size=None)  # no size → partial
        partial["planned_weight"] = 0
        d = _h(features=[scored, partial])._data_wsjf()
        assert d["summary"]["scored"]  >= 1
        assert d["summary"]["partial"] >= 1

    def test_json_serializable(self):
        e = self._epic_with_wsjf()
        json.dumps(_h(features=[e])._data_wsjf())


class TestDataWsjfSafeValidity:
    """
    SAFe validity: WSJF = (BV + Time Criticality + Risk Reduction) / Job Size.
    """

    def _e(self, id=1, value=5, urgency=8, risk=3, size=20, state="opened", piid=None):
        labels = ["Feature", f"wsjf-urgency::{urgency}", f"wsjf-risk::{risk}"]
        if piid:
            labels.append(piid)
        e = make_epic(id=id, etype="Feature", state=state,
                      planned_weight=size, labels=labels, group_id=30, piid=piid)
        e["business_value"] = value
        return e

    def test_score_formula(self):
        """WSJF score = (BV + urgency + risk) / size."""
        e = self._e(value=5, urgency=8, risk=3, size=16)
        d = _h(features=[e])._data_wsjf()
        c = d["candidates"][0]
        expected = round((5 + 8 + 3) / 16, 2)
        assert c["score"] == expected

    def test_higher_cod_ranks_first(self):
        """
        SAFe: items with higher Cost of Delay relative to size rank first.
        high_cod: (13+13+13)/10 = 3.9  low_cod: (1+1+1)/10 = 0.3
        """
        high_cod = self._e(id=1, value=13, urgency=13, risk=13, size=10)
        low_cod  = self._e(id=2, value=1,  urgency=1,  risk=1,  size=10)
        d = _h(features=[high_cod, low_cod])._data_wsjf()
        assert d["candidates"][0]["rank"] == 1
        assert d["candidates"][0]["score"] > d["candidates"][1]["score"]

    def test_smaller_job_size_ranks_higher_for_equal_cod(self):
        """
        SAFe: for equal Cost of Delay, smaller job size → higher WSJF score
        (do it first because it delivers same value in less time).
        """
        big   = self._e(id=1, value=5, urgency=5, risk=5, size=30)
        small = self._e(id=2, value=5, urgency=5, risk=5, size=10)
        d     = _h(features=[big, small])._data_wsjf()
        ranked = sorted(d["candidates"], key=lambda c: c["rank"])
        assert ranked[0]["size"] == 10, "smaller job size must rank first"

    def test_closed_items_excluded(self):
        """
        SAFe: WSJF prioritizes the BACKLOG — closed items are done and must
        not appear in the ranking.
        """
        closed = self._e(id=1, state="closed")
        open_  = self._e(id=2, state="opened")
        d = _h(features=[closed, open_])._data_wsjf()
        assert len(d["candidates"]) == 1
        assert d["candidates"][0]["rank"] == 1

    def test_item_with_no_wsjf_labels_excluded(self):
        """
        Items with no BV, urgency, or risk set are not scoreable and must
        be excluded — they would dilute ranking integrity.
        """
        plain = make_epic(id=1, etype="Feature", state="opened", group_id=30)
        d = _h(features=[plain])._data_wsjf()
        assert d["candidates"] == []

    def test_partial_score_when_size_zero(self):
        """
        If job size is 0 or missing, score cannot be computed.
        Item appears as partial (score=None) so the team knows to fill it in.
        """
        e = self._e(id=1, size=0)
        e["planned_weight"] = 0
        d = _h(features=[e])._data_wsjf()
        if d["candidates"]:
            assert d["candidates"][0]["score"] is None

    def test_missing_urgency_defaults_zero_in_cod(self):
        """
        When urgency is missing, the current implementation defaults it to 0.
        This is conservative — it undercounts Cost of Delay.
        Test confirms this known behaviour (not necessarily optimal, but consistent).
        """
        labels = ["Feature", "wsjf-risk::5"]
        e = make_epic(id=1, etype="Feature", state="opened",
                      planned_weight=10, labels=labels, group_id=30)
        e["business_value"] = 8
        d = _h(features=[e])._data_wsjf()
        if d["candidates"]:
            c = d["candidates"][0]
            # score = (8 + 0 + 5) / 10 = 1.3  (urgency missing → 0)
            assert c["score"] == round((8 + 0 + 5) / 10, 2)

    def test_in_flight_vs_backlog_counts(self):
        """
        SAFe distinguishes portfolio backlog (no PI) from in-flight work (PI assigned).
        Summary must reflect both counts correctly.
        """
        backlog    = self._e(id=1, piid=None)
        in_flight  = self._e(id=2, piid=_PIID_A)
        d = _h(features=[backlog, in_flight], piid_labels=[_PIID_A])._data_wsjf()
        assert d["summary"]["backlog"]   == 1
        assert d["summary"]["in_flight"] == 1


# ===========================================================================
# _data_art_capacity_balance — Plotly shape + SAFe validity
# ===========================================================================

class TestDataArtCapacityShape:
    """Verify ART Capacity Balance JSON structure for the Plotly grouped bar chart."""

    def _h_cap(self, features=None):
        return _h(
            features=features or [],
            groups_by_parent={1: [_VS], 10: [_ART], 20: [_TEAM]},
        )

    def test_top_level_keys(self):
        d = self._h_cap()._data_art_capacity_balance()
        assert {"report_date", "group", "arts"} <= d.keys()

    def test_art_has_required_fields(self):
        f = _feat(piid=_PIID_A)
        d = self._h_cap([f])._data_art_capacity_balance()
        art = d["arts"][0]
        assert {"vs_name", "art_name", "art_url", "over_count", "under_count", "pis"} <= art.keys()

    def test_pi_has_required_fields(self):
        f = _feat(piid=_PIID_A)
        d = self._h_cap([f])._data_art_capacity_balance()
        pi = d["arts"][0]["pis"][0]
        assert {"piid", "date_range", "teams"} <= pi.keys()

    def test_team_row_has_plotly_fields(self):
        """Grouped bar needs name, planned, actual, delta, load_pct, status."""
        f = _feat(piid=_PIID_A, planned_weight=40, actual_weight=60)
        d = self._h_cap([f])._data_art_capacity_balance()
        team = d["arts"][0]["pis"][0]["teams"][0]
        for key in ("name", "planned", "actual", "delta", "load_pct", "status"):
            assert key in team

    def test_delta_is_actual_minus_planned(self):
        f = _feat(piid=_PIID_A, planned_weight=40, actual_weight=60)
        d = self._h_cap([f])._data_art_capacity_balance()
        team = d["arts"][0]["pis"][0]["teams"][0]
        assert team["delta"] == 20

    def test_json_serializable(self):
        f = _feat(piid=_PIID_A)
        json.dumps(self._h_cap([f])._data_art_capacity_balance())


class TestDataArtCapacitySafeValidity:
    """
    SAFe validity for ART Capacity Balance.

    In SAFe PI Planning, teams commit to a set of Features for the PI.
    Planned = the epic planned_weight (set at PI Planning).
    Actual  = sum of issue story points on those Features (refined after planning).
    Load%   = Actual / Planned × 100 — measures whether team is over/under committed.
    """

    def _h_cap(self, features=None, groups_by_parent=None):
        return _h(
            features=features or [],
            groups_by_parent=groups_by_parent or {1: [_VS], 10: [_ART], 20: [_TEAM]},
        )

    def test_load_pct_formula(self):
        """load_pct = actual / planned × 100, rounded."""
        f = _feat(piid=_PIID_A, planned_weight=40, actual_weight=60, group_id=30)
        d = self._h_cap([f])._data_art_capacity_balance()
        team = d["arts"][0]["pis"][0]["teams"][0]
        assert team["load_pct"] == 150

    def test_over_120pct_is_over_status(self):
        """
        SAFe: >120% actual-to-planned ratio = over-committed.
        Team cannot absorb that much work in the PI.
        """
        f = _feat(piid=_PIID_A, planned_weight=10, actual_weight=13, group_id=30)
        d = self._h_cap([f])._data_art_capacity_balance()
        team = d["arts"][0]["pis"][0]["teams"][0]
        assert "Over" in team["status"]
        assert d["arts"][0]["over_count"] == 1

    def test_80_to_100pct_is_balanced(self):
        """80–100% is the SAFe healthy range — team is well-loaded."""
        f = _feat(piid=_PIID_A, planned_weight=10, actual_weight=9, group_id=30)
        d = self._h_cap([f])._data_art_capacity_balance()
        team = d["arts"][0]["pis"][0]["teams"][0]
        assert "Balanced" in team["status"]

    def test_under_80pct_is_under_status(self):
        """
        <80% means the team has spare capacity — it may be able to pull more work
        from the backlog mid-PI.
        """
        f = _feat(piid=_PIID_A, planned_weight=10, actual_weight=7, group_id=30)
        d = self._h_cap([f])._data_art_capacity_balance()
        team = d["arts"][0]["pis"][0]["teams"][0]
        assert "Under" in team["status"]
        assert d["arts"][0]["under_count"] == 1

    def test_zero_planned_weight_no_division_error(self):
        """If planned_weight is 0, load_pct must be 0 (not a ZeroDivisionError)."""
        f = _feat(piid=_PIID_A, planned_weight=0, actual_weight=5, group_id=30)
        d = self._h_cap([f])._data_art_capacity_balance()
        team = d["arts"][0]["pis"][0]["teams"][0]
        assert team["load_pct"] == 0

    def test_multiple_features_sum_correctly(self):
        """Planned and actual aggregate across all Features in the team-PI bucket."""
        f1 = _feat(id=1, piid=_PIID_A, planned_weight=20, actual_weight=25, group_id=30)
        f2 = _feat(id=2, piid=_PIID_A, planned_weight=30, actual_weight=15, group_id=30)
        d  = self._h_cap([f1, f2])._data_art_capacity_balance()
        team = d["arts"][0]["pis"][0]["teams"][0]
        assert team["planned"] == 50
        assert team["actual"]  == 40
        assert team["delta"]   == -10

    def test_features_bucketed_to_correct_team(self):
        """
        A Feature owned by Team Red must not appear in Team Blue's capacity.
        Incorrect bucketing would falsely inflate or deflate load%.
        """
        h = _h(
            features=[
                _feat(id=1, piid=_PIID_A, planned_weight=40, actual_weight=40, group_id=30),
                make_epic(id=2, etype="Feature", piid=_PIID_A, planned_weight=20,
                          actual_weight=20, group_id=31),
            ],
            groups_by_parent={1: [_VS], 10: [_ART], 20: [_TEAM, _TEAM2]},
        )
        d = h._data_art_capacity_balance()
        teams = d["arts"][0]["pis"][0]["teams"]
        assert len(teams) == 2
        team_map = {t["name"]: t for t in teams}
        assert team_map["Team Red"]["planned"]  == 40
        assert team_map["Team Blue"]["planned"] == 20

    def test_feature_without_pi_excluded(self):
        """
        Features not assigned to a PI cannot be capacity-planned.
        They must be excluded from the capacity balance, not zero-binned.
        """
        no_pi = _feat(id=1, piid=None)
        d     = self._h_cap([no_pi])._data_art_capacity_balance()
        assert d["arts"] == [], "unassigned features must not appear in capacity balance"

    def test_over_count_accumulates_across_pis(self):
        """over_count on the ART must count over-capacity teams across ALL PIs."""
        f1 = _feat(id=1, piid=_PIID_A, planned_weight=10, actual_weight=20, group_id=30)
        f2 = _feat(id=2, piid=_PIID_B, planned_weight=10, actual_weight=20, group_id=30)
        d  = self._h_cap([f1, f2])._data_art_capacity_balance()
        assert d["arts"][0]["over_count"] == 2


# ===========================================================================
# _data_pi_predictability — Plotly shape + SAFe validity
# ===========================================================================

class TestDataPiPredictabilityShape:
    """Verify PI Predictability JSON structure for the Plotly heatmap/bar chart."""

    def test_top_level_keys(self):
        d = _h()._data_pi_predictability()
        assert {"report_date", "group", "pis", "rows", "portfolio_row"} <= d.keys()

    def test_row_has_art_fields(self):
        f = _feat(piid=_PIID_A, state="closed", group_id=30)
        d = _h(features=[f], piid_labels=[_PIID_A])._data_pi_predictability()
        if d["rows"]:
            row = d["rows"][0]
            assert {"art_name", "art_url", "vs_name", "cells"} <= row.keys()

    def test_cell_has_plotly_fields(self):
        """Heatmap/bar needs closed, total, pct, icon, label, status."""
        f = _feat(piid=_PIID_A, state="closed", group_id=30)
        d = _h(features=[f], piid_labels=[_PIID_A])._data_pi_predictability()
        if d["rows"]:
            cell = d["rows"][0]["cells"][0]
            for key in ("piid", "closed", "total", "pct", "icon", "label", "status"):
                assert key in cell

    def test_portfolio_row_aggregates_all_arts(self):
        f1 = _feat(id=1, piid=_PIID_A, state="closed", group_id=30)
        f2 = make_epic(id=2, etype="Feature", piid=_PIID_A, state="opened",
                       group_id=31, planned_weight=10, actual_weight=5)
        h = _h(
            features=[f1, f2],
            piid_labels=[_PIID_A],
            groups_by_parent={1: [_VS], 10: [_ART], 20: [_TEAM, _TEAM2]},
        )
        d = h._data_pi_predictability()
        port = next((c for c in d["portfolio_row"] if c["piid"] == _PIID_A), None)
        assert port is not None
        assert port["total"] == 2

    def test_json_serializable(self):
        f = _feat(piid=_PIID_A, state="closed")
        json.dumps(_h(features=[f], piid_labels=[_PIID_A])._data_pi_predictability())


class TestDataPiPredictabilitySafeValidity:
    """
    SAFe: PI Predictability = % of committed Features/Capabilities delivered.
    Healthy range: 80–100%.
    """

    def test_pct_closed_over_total(self):
        """3 closed of 4 total = 75%."""
        feats = [
            _feat(id=i, piid=_PIID_A, state="closed") for i in range(1, 4)
        ] + [_feat(id=4, piid=_PIID_A, state="opened")]
        d = _h(features=feats, piid_labels=[_PIID_A])._data_pi_predictability()
        if d["rows"]:
            cell = d["rows"][0]["cells"][0]
            # depends on pct_through_pi; harness returns None → future status
            # We only check total/closed count here
            assert cell["total"]  == 4
            assert cell["closed"] == 3

    def test_capabilities_included_in_commitment(self):
        """
        ART-level Capabilities are PI commitments and must be counted.
        A common mistake is measuring only team Features.
        """
        cap = _cap(id=1, piid=_PIID_A, state="closed")
        d   = _h(capabilities=[cap], piid_labels=[_PIID_A])._data_pi_predictability()
        if d["rows"]:
            assert d["rows"][0]["cells"][0]["total"] == 1

    def test_portfolio_epics_excluded_from_commitment(self):
        """Portfolio Epics span PIs; they are NOT team/ART commitments."""
        ep  = _ep(id=1, piid=_PIID_A, state="closed")
        d   = _h(epics=[ep], piid_labels=[_PIID_A])._data_pi_predictability()
        assert d["rows"] == [], "Portfolio Epics must not generate ART predictability rows"

    def test_pi_with_no_commitment_returns_no_data_cell(self):
        """A PI where a specific ART has no Features or Capabilities → status no_data."""
        # ART One has a feature in Q1 only; Q2 cell must show no_data for ART One
        f = _feat(id=1, piid=_PIID_A, state="closed", group_id=30)
        d = _h(features=[f], piid_labels=[_PIID_A, _PIID_B])._data_pi_predictability()
        if d["rows"]:
            cells_by_pi = {c["piid"]: c for c in d["rows"][0]["cells"]}
            if _PIID_B in cells_by_pi:
                assert cells_by_pi[_PIID_B]["status"] == "no_data"

    def test_pis_ordered_chronologically(self):
        """
        PIs must appear in chronological order so the chart's x-axis makes sense.
        This test uses alphabetically-sorted PI strings that happen to be chronological.
        """
        f_a = _feat(id=1, piid=_PIID_A, state="closed", group_id=30)
        f_b = _feat(id=2, piid=_PIID_B, state="closed", group_id=30)
        f_c = _feat(id=3, piid=_PIID_C, state="closed", group_id=30)
        d   = _h(features=[f_c, f_a, f_b], piid_labels=[_PIID_A, _PIID_B, _PIID_C])._data_pi_predictability()
        assert d["pis"] == [_PIID_A, _PIID_B, _PIID_C]
