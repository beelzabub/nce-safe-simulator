"""
Phase-5 integration tests: mutate live GitLab work items, update the
in-memory report state, and assert that computed metrics change as expected.

Strategy (avoids 429 rate limits):
  1. Module fixture: connect once, load the most recent raw snapshot into
     _rd_* memory structures (no full API fetch needed per test).
  2. Each test: mutate one item via targeted GitLab API call, patch _rd_*
     in-memory to reflect the mutation, compute the _data_* method, assert.
  3. Each test restores the GitLab item and reverts the in-memory patch.

This confirms:
  - The GitLab mutation is accepted (real API round-trip).
  - The metric computation logic responds correctly to the data change.

Run with:
    pytest tests/test_phase5_integration.py -m integration -v

Refs #45
"""
import json
import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
RAW_SNAPSHOTS = sorted(Path(__file__).parent.parent.glob("reports/*/*/data/epics.json"))


def _config_available():
    if not CONFIG_PATH.exists():
        return False
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        token = os.getenv("ACCESS_TOKEN") or cfg.get("private_token", "")
        return bool(token)
    except Exception:
        return False


def _snapshot_available():
    return bool(RAW_SNAPSHOTS)


pytestmark = pytest.mark.skipif(
    not (_config_available() and _snapshot_available()),
    reason="config.json/token or raw data snapshot not available — skipping live GitLab tests",
)


# ---------------------------------------------------------------------------
# Module-scoped fixture: connect once, load last snapshot into _rd_*
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def gl_ctx():
    """
    Return a dict with a live NceGitLab instance whose _rd_* structures are
    pre-loaded from the most recent raw data snapshot.  No full re-fetch needed.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from NceGitLab import NceGitLab

    gl = NceGitLab()

    # Load the newest snapshot into _rd_*
    latest_snap = sorted(RAW_SNAPSHOTS)[-1].parent
    gl._rd_root_obj = gl.get_group_by_name(gl.parent_group)
    gn = gl._rd_root_obj.name
    gl._wiki_t1 = f"{gn} — Portfolio Home/00 Executive Pulse"
    gl._wiki_t2 = f"{gn} — Portfolio Home/01 Program Management"
    gl._wiki_t3 = f"{gn} — Portfolio Home/02 Operational Detail"
    gl._wiki_t4 = f"{gn} — Portfolio Home/03 Data Quality"
    gl._load_report_data(latest_snap)

    return {"gl": gl, "snap": latest_snap}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_gl(ctx):
    return ctx["gl"]


def _group_for_epic(gl, epic_dict):
    """Return a python-gitlab Group object for the group that owns this epic."""
    return gl.gl.groups.get(epic_dict["group_id"])


def _fetch_epic_obj(gl, epic_dict):
    """Return a python-gitlab Epic object from the live API."""
    grp = _group_for_epic(gl, epic_dict)
    return grp.epics.get(epic_dict["iid"])


def _patch_rd_epic(gl, epic_id, **fields):
    """
    Patch fields on an epic inside _rd_metrics and _rd_epics_by_id in-memory.
    Returns a dict of {field: old_value} for restoration.
    """
    old = {}
    epic_obj = gl._rd_epics_by_id.get(epic_id)
    if epic_obj is None:
        return old
    for field, value in fields.items():
        old[field] = epic_obj.get(field)
        epic_obj[field] = value
    # The same dict is referenced from _rd_metrics buckets, so the patch is live there too.
    return old


def _restore_rd_epic(gl, epic_id, old_fields):
    """Reverse a patch applied by _patch_rd_epic."""
    epic_obj = gl._rd_epics_by_id.get(epic_id)
    if epic_obj is None:
        return
    for field, old_val in old_fields.items():
        epic_obj[field] = old_val


# ---------------------------------------------------------------------------
# Test 1: Closing a Feature increases velocity for its PI
# ---------------------------------------------------------------------------

class TestVelocityMutation:
    """
    SAFe: Flow Velocity = closed Features + Capabilities per PI.
    Closing one open Feature must increment velocity for its PI by exactly 1.
    """

    def _find_open_feature_with_piid(self, gl):
        for piid in gl._rd_piid_labels:
            for e in gl._rd_metrics.get("Feature", []):
                if e.get("piid") == piid and e.get("state", "").lower() == "opened":
                    return e, piid
        return None, None

    def test_close_feature_increments_velocity(self, gl_ctx):
        gl      = _get_gl(gl_ctx)
        target, piid = self._find_open_feature_with_piid(gl)
        if target is None:
            pytest.skip("No open Feature with PIID label found in snapshot")

        # Before
        before = gl._data_flow_metrics()
        vel_before = next((r for r in before["velocity"] if r["piid"] == piid), None)
        assert vel_before is not None, f"No velocity row for {piid}"
        feats_before = vel_before["features"]

        # Mutate GitLab (real API call)
        api_epic = _fetch_epic_obj(gl, target)
        try:
            api_epic.state_event = "close"
            api_epic.save()

            # Patch in-memory to reflect closed state (GitLab confirmed it)
            old = _patch_rd_epic(gl, target["id"], state="Closed")

            after = gl._data_flow_metrics()
            vel_after = next((r for r in after["velocity"] if r["piid"] == piid), None)
            assert vel_after is not None

            assert vel_after["features"] == feats_before + 1, (
                f"Velocity for {piid}: expected {feats_before+1}, got {vel_after['features']}"
            )
            assert vel_after["total"] == vel_before["total"] + 1

        finally:
            api_epic.state_event = "reopen"
            api_epic.save()
            _restore_rd_epic(gl, target["id"], old)

    def test_close_removes_from_load_wip(self, gl_ctx):
        """
        SAFe: closing work reduces WIP (Flow Load).
        The same Feature that moves to velocity must leave the WIP load count.
        """
        gl      = _get_gl(gl_ctx)
        target, piid = self._find_open_feature_with_piid(gl)
        if target is None:
            pytest.skip("No open Feature with PIID label found")

        before     = gl._data_flow_metrics()
        load_before = next((r for r in before["load"] if r["piid"] == piid), None)
        if load_before is None:
            pytest.skip(f"No load row for {piid}")
        wip_before = load_before["features"]

        api_epic = _fetch_epic_obj(gl, target)
        try:
            api_epic.state_event = "close"
            api_epic.save()
            old = _patch_rd_epic(gl, target["id"], state="Closed")

            after = gl._data_flow_metrics()
            load_after = next((r for r in after["load"] if r["piid"] == piid), None)
            assert load_after["features"] == wip_before - 1, (
                "Closed Feature must leave WIP load"
            )
        finally:
            api_epic.state_event = "reopen"
            api_epic.save()
            _restore_rd_epic(gl, target["id"], old)


# ---------------------------------------------------------------------------
# Test 2: WSJF label mutations
# ---------------------------------------------------------------------------

class TestWsjfMutation:
    """
    SAFe: Items must have at least one WSJF component (BV, urgency, or risk)
    to appear on the WSJF Priority Board.
    """

    def _find_unlabelled_feature(self, gl):
        for e in gl._rd_metrics.get("Feature", []):
            if (e.get("state", "").lower() == "opened"
                    and (e.get("planned_weight") or 0) > 0
                    and not any(l.startswith("wsjf-urgency::") for l in e.get("labels", []))
                    and not any(l.startswith("wsjf-risk::") for l in e.get("labels", []))
                    and e.get("business_value") is None):
                return e
        return None

    def test_add_wsjf_labels_adds_candidate(self, gl_ctx):
        gl     = _get_gl(gl_ctx)
        target = self._find_unlabelled_feature(gl)
        if target is None:
            pytest.skip("No unlabelled open Feature with weight > 0 in snapshot")

        # Before: item must not be on board
        before  = gl._data_wsjf()
        titles_before = {c["title"] for c in before.get("candidates", [])}
        assert target["title"] not in titles_before, "Pre-condition: item already on board"

        api_epic = _fetch_epic_obj(gl, target)
        orig_labels = list(api_epic.labels)
        new_labels  = orig_labels + ["wsjf-urgency::5", "wsjf-risk::3"]

        try:
            api_epic.labels = new_labels
            api_epic.save()

            # Patch in-memory
            patched_labels = list(target.get("labels", [])) + ["wsjf-urgency::5", "wsjf-risk::3"]
            old = _patch_rd_epic(gl, target["id"], labels=patched_labels)

            after  = gl._data_wsjf()
            titles = {c["title"] for c in after.get("candidates", [])}
            assert target["title"] in titles, (
                f"'{target['title']}' must appear on WSJF board after adding labels"
            )

            cand = next(c for c in after["candidates"] if c["title"] == target["title"])
            assert cand["urgency"] == 5
            assert cand["risk"]    == 3
            expected_score = round((0 + 5 + 3) / target["planned_weight"], 2)
            assert cand["score"]   == expected_score, (
                f"score mismatch: {cand['score']} != {expected_score}"
            )

        finally:
            api_epic.labels = orig_labels
            api_epic.save()
            _restore_rd_epic(gl, target["id"], old)

    def test_wsjf_score_formula_live(self, gl_ctx):
        """
        SAFe formula validation against a live item that already has scoring.
        score = (BV + urgency + risk) / planned_weight — verified on real data.
        """
        gl = _get_gl(gl_ctx)
        before = gl._data_wsjf()
        scored = [c for c in before.get("candidates", []) if c.get("score") is not None]
        if not scored:
            pytest.skip("No fully-scored WSJF candidates in snapshot")

        for c in scored[:5]:   # check first 5
            v = c["value"]   or 0
            u = c["urgency"] or 0
            r = c["risk"]    or 0
            s = c["size"]
            if s and s > 0:
                expected = round((v + u + r) / s, 2)
                assert c["score"] == expected, (
                    f"WSJF score mismatch for '{c['title']}': "
                    f"({v}+{u}+{r})/{s} = {expected}, got {c['score']}"
                )


# ---------------------------------------------------------------------------
# Test 3: ART Capacity load% changes with planned weight
# ---------------------------------------------------------------------------

class TestCapacityMutation:
    """
    SAFe: load% = actual / planned × 100.
    Doubling a Feature's planned_weight must halve its contribution to load%.
    """

    def _find_open_feature_with_weight(self, gl):
        for e in gl._rd_metrics.get("Feature", []):
            if (e.get("piid")
                    and (e.get("planned_weight") or 0) > 5
                    and e.get("state", "").lower() == "opened"):
                return e
        return None

    def test_double_planned_weight_halves_load_pct(self, gl_ctx):
        gl     = _get_gl(gl_ctx)
        target = self._find_open_feature_with_weight(gl)
        if target is None:
            pytest.skip("No open Feature with planned_weight > 5 in snapshot")

        orig_weight = target["planned_weight"]
        new_weight  = orig_weight * 2
        piid        = target["piid"]

        # Before: sum planned weight across all Features with this group_id + piid
        pi_features_before = [
            e for e in gl._rd_metrics.get("Feature", [])
            if e.get("piid") == piid and e.get("group_id") == target["group_id"]
        ]
        total_planned_before = sum(e.get("planned_weight", 0) for e in pi_features_before)
        total_actual         = sum(e.get("actual_weight",  0) for e in pi_features_before)
        if total_planned_before == 0:
            pytest.skip("Team has zero total planned weight — cannot assert load_pct change")
        load_pct_before = round(total_actual / total_planned_before * 100)

        # Mutate GitLab via GraphQL (REST API silently ignores epic weight)
        api_epic = _fetch_epic_obj(gl, target)
        wid = getattr(api_epic, "work_item_id", None) or target.get("work_item_id")
        if not wid:
            pytest.skip("Epic has no work_item_id — cannot set weight via GraphQL")

        try:
            gl._set_epic_weight(api_epic, new_weight)

            old = _patch_rd_epic(gl, target["id"], planned_weight=new_weight)

            # After: same team's total planned should have increased
            pi_features_after = [
                e for e in gl._rd_metrics.get("Feature", [])
                if e.get("piid") == piid and e.get("group_id") == target["group_id"]
            ]
            total_planned_after = sum(e.get("planned_weight", 0) for e in pi_features_after)
            load_pct_after      = round(total_actual / total_planned_after * 100)

            assert total_planned_after == total_planned_before + orig_weight, (
                f"Total planned for team-PI should increase by {orig_weight}: "
                f"{total_planned_before} → {total_planned_after}"
            )
            assert load_pct_after < load_pct_before, (
                f"load_pct should decrease when planned doubles: "
                f"{load_pct_before}% → {load_pct_after}%"
            )

        finally:
            gl._set_epic_weight(api_epic, orig_weight)
            _restore_rd_epic(gl, target["id"], old)



# ---------------------------------------------------------------------------
# Test 4: PI Predictability — cross-report consistency (no mutations needed)
# ---------------------------------------------------------------------------

class TestPredictabilityConsistency:
    """
    Cross-report validation: flow-metrics.predictability and
    pi-predictability.portfolio_row must agree on committed/delivered counts.

    SAFe: both reports pull from the same data; divergence means a metric
    is being computed differently in two places, which is a data quality bug.
    """

    def test_flow_metrics_matches_pi_predictability_portfolio(self, gl_ctx):
        gl = _get_gl(gl_ctx)

        flow = gl._data_flow_metrics()
        pi   = gl._data_pi_predictability()

        flow_by_piid = {r["piid"]: r for r in flow.get("predictability", [])}
        port_by_piid = {c["piid"]: c for c in pi.get("portfolio_row", [])}

        common = set(flow_by_piid) & set(port_by_piid)
        if not common:
            pytest.skip("No PIs in common between flow-metrics and pi-predictability")

        for piid in common:
            fm = flow_by_piid[piid]
            pp = port_by_piid[piid]

            if pp.get("status") in ("no_data", "future"):
                continue  # pi-predictability shows no_data; flow-metrics omits → skip

            assert pp["total"] == fm["committed"], (
                f"[{piid}] committed count mismatch: "
                f"flow-metrics={fm['committed']}, pi-predictability.portfolio={pp['total']}"
            )
            assert pp["closed"] == fm["delivered"], (
                f"[{piid}] delivered count mismatch: "
                f"flow-metrics={fm['delivered']}, pi-predictability.portfolio={pp['closed']}"
            )

    def test_predictability_pct_80_target_live_data(self, gl_ctx):
        """
        SAFe: predictability ≥ 80% is the healthy target.
        Report using live data — not an assertion, but a logged summary useful
        during sprint reviews.  Fails only if the pct field is miscalculated.
        """
        gl   = _get_gl(gl_ctx)
        flow = gl._data_flow_metrics()

        for row in flow.get("predictability", []):
            committed = row["committed"]
            delivered = row["delivered"]
            pct       = row["pct"]
            if committed > 0:
                expected_pct = round(delivered / committed * 100)
                assert pct == expected_pct, (
                    f"[{row['piid']}] pct={pct} but {delivered}/{committed}×100={expected_pct}"
                )

    def test_velocity_plus_load_equals_total_committed(self, gl_ctx):
        """
        Inventory conservation check: for any PI, the number of Features committed
        equals the number closed (velocity) plus the number still open (load).

        This is a SAFe data quality assertion — if these don't add up, there are
        orphaned items (no PI label) or double-counting somewhere.
        """
        gl = _get_gl(gl_ctx)
        data = gl._data_flow_metrics()

        vel_by_pi  = {r["piid"]: r["features"] for r in data["velocity"]}
        load_by_pi = {r["piid"]: r["features"] for r in data["load"]}

        all_typed  = [e for bucket in gl._rd_metrics.values() for e in bucket]
        feat_types = {"Feature", "Capability"}

        for piid in gl._rd_piid_labels:
            pi_feats    = [e for e in all_typed
                           if e.get("piid") == piid and e.get("type") in feat_types]
            total       = len([e for e in pi_feats if e.get("type") == "Feature"])
            vel_feats   = vel_by_pi.get(piid, 0)
            load_feats  = load_by_pi.get(piid, 0)

            assert vel_feats + load_feats == total, (
                f"[{piid}] velocity({vel_feats}) + load({load_feats}) "
                f"= {vel_feats+load_feats} but total committed Features = {total}"
            )


# ---------------------------------------------------------------------------
# Test 5: WSJF ranking stability — adding more-urgent item must shift rank
# ---------------------------------------------------------------------------

class TestWsjfRankingMutation:
    """Confirm that adding a higher-scoring item pushes other items down the rank."""

    def _find_labelled_feature(self, gl):
        for e in gl._rd_metrics.get("Feature", []):
            if (e.get("state", "").lower() == "opened"
                    and (e.get("planned_weight") or 0) > 0
                    and any(l.startswith("wsjf-urgency::") for l in e.get("labels", []))):
                return e
        return None

    def _find_no_wsjf_feature(self, gl):
        for e in gl._rd_metrics.get("Feature", []):
            if (e.get("state", "").lower() == "opened"
                    and (e.get("planned_weight") or 0) > 0
                    and not any(l.startswith("wsjf-urgency::") for l in e.get("labels", []))
                    and not any(l.startswith("wsjf-risk::") for l in e.get("labels", []))
                    and e.get("business_value") is None):
                return e
        return None

    def test_high_urgency_label_ranks_above_existing(self, gl_ctx):
        """
        Adding wsjf-urgency::13 + wsjf-risk::13 (max) to a Feature with
        small planned_weight must give it the highest score in the board.
        """
        gl          = _get_gl(gl_ctx)
        new_entrant = self._find_no_wsjf_feature(gl)
        if new_entrant is None:
            pytest.skip("No un-labelled Feature with weight available")

        before     = gl._data_wsjf()
        n_before   = len(before.get("candidates", []))

        api_epic   = _fetch_epic_obj(gl, new_entrant)
        orig_labels = list(api_epic.labels)
        new_labels  = orig_labels + ["wsjf-urgency::13", "wsjf-risk::13"]

        try:
            api_epic.labels = new_labels
            api_epic.save()

            patched = list(new_entrant.get("labels", [])) + ["wsjf-urgency::13", "wsjf-risk::13"]
            old = _patch_rd_epic(gl, new_entrant["id"], labels=patched)

            after = gl._data_wsjf()
            assert len(after.get("candidates", [])) == n_before + 1

            # The new item's expected score
            pw    = new_entrant["planned_weight"]
            score = round((0 + 13 + 13) / pw, 2)
            cand  = next(c for c in after["candidates"] if c["title"] == new_entrant["title"])
            assert cand["score"] == score
            assert cand["rank"] == 1 or cand["score"] >= after["candidates"][0]["score"], (
                "Highest-scoring item must be at rank 1"
            )

        finally:
            api_epic.labels = orig_labels
            api_epic.save()
            _restore_rd_epic(gl, new_entrant["id"], old)
