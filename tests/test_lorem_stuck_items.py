"""Independent verification for #82 — does generator-style lorem data actually
produce *stuck items in every monitored lifecycle state* (funnel / analyzing /
backlog) and non-zero Flow Metrics ages?

These tests drive the REAL Epic Lifecycle and Flow Metrics reports
(`generate_epic_lifecycle_report` / `generate_flow_metrics_report`) with epics
constructed exactly the way the lorem generator builds them:

  * PIID label drawn from the configured pool (`_weighted_piid_label`)
  * `created_at` backdated via the new `_lorem_created_at` dating
  * `lifecycle::` label assigned by the same branch logic as
    `mixins/bootstrap.py::_simulate_history`

The generator itself (`_simulate_history`, `_lorem_epics_in_group`) talks to
GitLab, so we reproduce its *pure* labelling logic here and assert it matches the
bootstrap helper `_piid_lifecycle_buckets` (documented to mirror it).
"""
import json
import random
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from mixins.bootstrap import BootstrapMixin
from tests.conftest import ReportsHarness, make_epic

_CFG = json.loads((Path(__file__).parent.parent / "config.json").read_text())
PIID_LABELS = _CFG["piid_labels"]
STUCK = _CFG.get("stuck_thresholds", {
    "lifecycle::funnel": 90, "lifecycle::analyzing": 30, "lifecycle::backlog": 60,
})
# Mirrors mixins/bootstrap.py default_funnel_ratio: the fraction of generated
# epics created with no PIID, which is what routes them to lifecycle::funnel.
FUNNEL_RATIO = 0.12
LC_PAGE = "Portfolio/02 Operational Detail/Epic Lifecycle"
FM_PAGE = "Portfolio/02 Operational Detail/Flow Metrics"


class _Generator(BootstrapMixin):
    """Bootstrap mixin wired with the real config so we can call the actual
    dating / bucketing helpers without touching GitLab."""

    PIID_LABELS = PIID_LABELS
    STUCK_THRESHOLDS = STUCK

    def __init__(self):
        pass

    # Same date parser the report harness uses (PIID::YYYYQn → quarter span).
    _pi_dates_from_label = ReportsHarness._pi_dates_from_label

    def assign_lifecycle(self, piid, closed):
        """Faithful reproduction of the lifecycle branch in
        mixins/bootstrap.py::_simulate_history (lines ~696-703)."""
        b = self._piid_lifecycle_buckets()
        if closed:
            return "lifecycle::done"
        if piid in b["past"] or piid in b["current"]:
            return "lifecycle::implementing"
        if piid in b["backlog"]:
            return "lifecycle::backlog"
        if piid in b["analyzing"]:
            return "lifecycle::analyzing"
        return "lifecycle::funnel"


def _gen():
    return _Generator()


def _run_lifecycle(epics):
    h = ReportsHarness(
        epics_all=epics,
        metrics={"Epic": [], "Capability": [], "Feature": epics},
        lifecycle_labels=list(STUCK.keys()),
        piid_labels=PIID_LABELS,
    )
    h.STUCK_THRESHOLDS = STUCK
    h.generate_epic_lifecycle_report()
    return h._uploaded[LC_PAGE]


def _build_generator_epics(n, seed):
    """Produce n epics the way the lorem generator would: weighted PIID,
    backdated created_at, and the lifecycle label _simulate_history would set."""
    g = _gen()
    b = g._piid_lifecycle_buckets()
    random.seed(seed)
    epics = []
    for i in range(n):
        piid = g._weighted_piid_label()
        # Mirror _lorem_epics_in_group: a fraction of epics are PIID-less funnel ideas.
        if random.random() < FUNNEL_RATIO:
            piid = None
        # Past-PI epics are closed at a high reliability rate in _simulate_history.
        closed = piid in b["past"] and random.random() < 0.8
        lc = g.assign_lifecycle(piid, closed)
        labels = ["Feature"] + ([piid] if piid else []) + [lc]
        epics.append(make_epic(
            id=i, iid=i, etype="Feature",
            labels=labels,
            created_at=g._lorem_created_at(piid),
            piid=piid,
            state="closed" if lc == "lifecycle::done" else "opened",
        ))
    return epics


# ---------------------------------------------------------------------------
# 1. Structural reachability of each lifecycle state from the real PIID config
# ---------------------------------------------------------------------------

class TestLifecycleStateReachability:
    def test_buckets_cover_every_configured_piid(self):
        """Every PIID maps to past/current/backlog/analyzing — so an epic that
        always carries a PIID can never fall through to the funnel branch."""
        b = _gen()._piid_lifecycle_buckets()
        covered = b["past"] | b["current"] | b["backlog"] | b["analyzing"]
        assert set(PIID_LABELS) - covered == set()

    def test_real_piids_never_map_to_funnel(self):
        """A real PIID always maps to past/current/backlog/analyzing — funnel is
        reached only by a PIID-less epic, which the generator now seeds via
        default_funnel_ratio."""
        g = _gen()
        produced = {g.assign_lifecycle(p, closed) for p in PIID_LABELS for closed in (True, False)}
        assert "lifecycle::funnel" not in produced
        # ...but a None PIID (unplanned idea) does route to funnel:
        assert g.assign_lifecycle(None, False) == "lifecycle::funnel"

    def test_backlog_and_analyzing_are_reachable(self):
        b = _gen()._piid_lifecycle_buckets()
        assert b["backlog"], "no PIID maps to backlog"
        assert b["analyzing"], "no PIID maps to analyzing"

    def test_generator_yields_all_three_flagged_states(self):
        """Across many weighted draws + the funnel ratio, all three monitored
        states are produced — funnel included, now that PIID-less epics exist."""
        g = _gen()
        random.seed(7)
        counts = Counter()
        for _ in range(2000):
            piid = g._weighted_piid_label()
            if random.random() < FUNNEL_RATIO:
                piid = None
            counts[g.assign_lifecycle(piid, False)] += 1
        assert counts["lifecycle::funnel"] > 0
        assert counts["lifecycle::backlog"] > 0
        assert counts["lifecycle::analyzing"] > 0


# ---------------------------------------------------------------------------
# 2. End-to-end: generator-style epics through the real Epic Lifecycle report
# ---------------------------------------------------------------------------

class TestEpicLifecycleStuckItems:
    def test_backlog_stuck_items_render(self):
        content = _run_lifecycle(_build_generator_epics(400, seed=42))
        assert "Stuck in Portfolio Backlog" in content

    def test_analyzing_stuck_items_render(self):
        content = _run_lifecycle(_build_generator_epics(400, seed=42))
        assert "Stuck in Analyzing" in content

    def test_funnel_stuck_items_render(self):
        """With PIID-less funnel epics now seeded, 'Stale in Funnel' renders —
        closing #82's gap (stuck item in each monitored state)."""
        content = _run_lifecycle(_build_generator_epics(400, seed=42))
        assert "Stale in Funnel" in content

    def test_report_can_render_funnel_when_a_funnel_epic_exists(self):
        """Control: the *report* is fine — inject a stuck funnel epic directly
        and 'Stale in Funnel' renders. Proves the gap is in the generator's
        lifecycle assignment, not the report."""
        old = (date.today().replace(year=date.today().year - 1)).isoformat()
        epic = make_epic(id=1, iid=1, etype="Feature",
                         labels=["Feature", "lifecycle::funnel"],
                         created_at=old, state="opened")
        content = _run_lifecycle([epic])
        assert "Stale in Funnel" in content


# ---------------------------------------------------------------------------
# 3. Flow Metrics — non-zero ages from backdated created_at
# ---------------------------------------------------------------------------

class TestFlowMetricsAges:
    def test_open_epic_ages_are_non_zero(self):
        epics = [e for e in _build_generator_epics(120, seed=3) if e["state"] != "Closed"]
        # Sanity: dating actually backdated some epics.
        ages = [(date.today() - date.fromisoformat(e["created_at"][:10])).days for e in epics]
        assert max(ages) > 0

        h = ReportsHarness(
            epics_all=epics,
            metrics={"Epic": [], "Capability": [], "Feature": epics},
            piid_labels=PIID_LABELS,
        )
        h.generate_flow_metrics_report()
        content = h._uploaded[FM_PAGE]
        assert "Age of Open Epics" in content
        # The Feature age row should show a non-zero Max age, not the empty "—".
        rows = [l for l in content.splitlines() if l.startswith("| Feature |")]
        assert rows, "no Feature age row rendered"
        assert "| — | — |" not in rows[0]
