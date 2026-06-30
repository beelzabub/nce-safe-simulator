"""Lifecycle-aware created_at dating for lorem epics (Refs #82, Item 2)."""
from datetime import date, timedelta

from mixins.bootstrap import BootstrapMixin


class CB(BootstrapMixin):
    PIID_LABELS = []
    STUCK_THRESHOLDS = {
        "lifecycle::funnel": 90,
        "lifecycle::analyzing": 30,
        "lifecycle::backlog": 60,
    }

    def __init__(self):
        pass


def _age_days(iso):
    return (date.today() - date.fromisoformat(iso[:10])).days


class TestPiidLifecycleBuckets:
    def test_classifies_past_current_backlog_analyzing(self):
        h = CB()
        today = date.today()
        h.PIID_LABELS = ["P_PAST", "P_CUR", "P_F1", "P_F2", "P_F3"]
        dates = {
            "P_PAST": (today - timedelta(days=400), today - timedelta(days=310)),
            "P_CUR":  (today - timedelta(days=10),  today + timedelta(days=80)),
            "P_F1":   (today + timedelta(days=100), today + timedelta(days=190)),  # nearest future
            "P_F2":   (today + timedelta(days=200), today + timedelta(days=290)),
            "P_F3":   (today + timedelta(days=300), today + timedelta(days=390)),
        }
        h._pi_dates_from_label = lambda p: dates[p]
        b = h._piid_lifecycle_buckets()
        assert b["past"]      == {"P_PAST"}
        assert b["current"]   == {"P_CUR"}
        assert b["backlog"]   == {"P_F1"}          # only the nearest future PI
        assert b["analyzing"] == {"P_F2", "P_F3"}  # the farther-out ones


class TestLoremCreatedAt:
    def _harness(self):
        h = CB()
        # Bypass date parsing — pin the buckets directly.
        h._pi_lifecycle_buckets_cache = {
            "past":      {"PIID::PAST"},
            "current":   {"PIID::CUR"},
            "backlog":   {"PIID::BL"},
            "analyzing": {"PIID::AN"},
        }
        return h

    def test_age_ranges_per_bucket(self):
        h = self._harness()
        # 2x threshold for the flagged states; fixed ranges for the rest.
        bounds = {
            "PIID::AN":      60,    # analyzing: 2 * 30
            "PIID::BL":      120,   # backlog:   2 * 60
            "PIID::CUR":     120,   # implementing
            "PIID::PAST":    365,   # done/implementing
            "PIID::UNKNOWN": 180,   # funnel fallback: 2 * 90
        }
        for piid, hi in bounds.items():
            for _ in range(300):
                assert 0 <= _age_days(h._lorem_created_at(piid)) <= hi, piid

    def test_threshold_states_straddle_their_threshold(self):
        # Over ~600 samples, funnel (2x90) should yield both stuck (>90) and
        # not-stuck (<=90) epics, proving both render paths get exercised.
        h = self._harness()
        ages = [_age_days(h._lorem_created_at("PIID::UNKNOWN")) for _ in range(600)]
        assert any(a > 90 for a in ages)
        assert any(a <= 90 for a in ages)

    def test_iso_format(self):
        assert self._harness()._lorem_created_at("PIID::AN").endswith("T12:00:00Z")

    def test_respects_configured_thresholds(self):
        h = self._harness()
        h.STUCK_THRESHOLDS = {"lifecycle::funnel": 10, "lifecycle::analyzing": 30, "lifecycle::backlog": 60}
        # funnel range becomes 2*10=20 days max
        for _ in range(300):
            assert 0 <= _age_days(h._lorem_created_at("PIID::UNKNOWN")) <= 20
