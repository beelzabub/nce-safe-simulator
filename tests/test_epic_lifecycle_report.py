"""Tests for generate_epic_lifecycle_report (Refs #24)."""
import sys
from datetime import date, timedelta

import pytest



from tests.conftest import ReportsHarness, make_epic

_LC_LABELS = [
    "lifecycle::funnel",
    "lifecycle::analyzing",
    "lifecycle::backlog",
    "lifecycle::implementing",
    "lifecycle::done",
]


def _harness(features=None, epics=None, lifecycle_labels=None):
    all_typed = (features or []) + (epics or [])
    return ReportsHarness(
        epics_all=all_typed,
        metrics={
            "Epic":       epics    or [],
            "Capability": [],
            "Feature":    features or [],
        },
        lifecycle_labels=lifecycle_labels if lifecycle_labels is not None else _LC_LABELS,
    )


def _run(h):
    h.generate_epic_lifecycle_report()
    return h._uploaded.get(f"{h._wiki_t3}/Epic Lifecycle", "")


class TestEpicLifecycleStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = _harness()
        h.generate_epic_lifecycle_report()
        assert f"{h._wiki_t3}/Epic Lifecycle" in h._uploaded

    def test_page_title_present(self):
        assert "# Epic Lifecycle / Portfolio Kanban" in _run(_harness())

    def test_kanban_state_section_present(self):
        assert "## Portfolio Kanban — Current State" in _run(_harness())

    def test_all_five_kanban_states_in_table(self):
        content = _run(_harness())
        for label in ["💡 Funnel", "🔍 Analyzing", "📋 Portfolio Backlog",
                      "⚙️ Implementing", "✅ Done"]:
            assert label in content

    def test_empty_metrics_no_crash(self):
        content = _run(_harness())
        assert content != ""


class TestEpicLifecycleBucketing:
    def test_funnel_epic_counted_in_funnel_bucket(self):
        epic = make_epic(id=1, etype="Feature",
                         labels=["Feature", "lifecycle::funnel"])
        content = _run(_harness(features=[epic]))
        assert "💡 Funnel" in content
        assert ">1<" in content

    def test_implementing_epic_counted_in_implementing_bucket(self):
        epic = make_epic(id=1, etype="Feature",
                         labels=["Feature", "lifecycle::implementing"])
        content = _run(_harness(features=[epic]))
        assert ">1<" in content

    def test_done_epic_counted_in_done_bucket(self):
        epic = make_epic(id=1, etype="Feature",
                         labels=["Feature", "lifecycle::done"])
        content = _run(_harness(features=[epic]))
        assert ">1<" in content

    def test_epic_with_no_lifecycle_label_goes_to_unlabelled(self):
        epic = make_epic(id=1, etype="Feature", labels=["Feature"])
        content = _run(_harness(features=[epic]))
        assert "_(unlabelled)_" in content

    def test_multiple_lifecycle_labels_picks_first_in_state_order(self):
        # funnel comes before implementing in state order; epic should land in funnel
        epic = make_epic(id=1, etype="Feature",
                         labels=["Feature", "lifecycle::implementing", "lifecycle::funnel"])
        content = _run(_harness(features=[epic]))
        # funnel count should be 1, implementing count should be 0
        lines = content.splitlines()
        funnel_line = next((l for l in lines if "💡 Funnel" in l), "")
        assert ">1<" in funnel_line


class TestEpicLifecycleUnlabelled:
    def test_unlabelled_count_shown_when_epics_present(self):
        epic = make_epic(id=1, etype="Feature", labels=["Feature"])
        content = _run(_harness(features=[epic]))
        assert "_(unlabelled)_" in content
        assert ">1<" in content

    def test_unlabelled_count_is_anchor_link_to_lifecycle_page(self):
        epic = make_epic(id=1, etype="Feature", labels=["Feature"])
        h = _harness(features=[epic])
        content = _run(h)
        assert '<a href=' in content
        assert '#unlabelled' in content
        assert 'target="_blank"' in content

    def test_unlabelled_link_points_to_epic_lifecycle_wiki_page(self):
        epic = make_epic(id=1, etype="Feature", labels=["Feature"])
        h = _harness(features=[epic])
        content = _run(h)
        assert "Epic-Lifecycle" in content

    def test_unlabelled_shows_zero_when_all_labelled(self):
        epic = make_epic(id=1, etype="Feature",
                         labels=["Feature", "lifecycle::funnel"])
        content = _run(_harness(features=[epic]))
        # unlabelled row should show "0" (not an <a> link)
        lines = content.splitlines()
        unlab_line = next((l for l in lines if "_(unlabelled)_" in l), "")
        assert "| 0 |" in unlab_line


class TestEpicLifecycleNoLabelsWarning:
    def test_warning_shown_when_no_lifecycle_labels_configured(self):
        content = _run(_harness(lifecycle_labels=[]))
        assert "No `lifecycle::` labels found" in content

    def test_warning_suppressed_when_lifecycle_labels_present(self):
        epic = make_epic(id=1, etype="Feature",
                         labels=["Feature", "lifecycle::funnel"])
        content = _run(_harness(features=[epic], lifecycle_labels=["lifecycle::funnel"]))
        assert "No `lifecycle::` labels found" not in content


class TestEpicLifecycleAgeAndThresholds:
    def test_threshold_shown_for_funnel_state(self):
        content = _run(_harness())
        # funnel threshold is 90d
        assert "90d" in content

    def test_threshold_shown_for_analyzing_state(self):
        content = _run(_harness())
        assert "30d" in content

    def test_stuck_epic_flagged_with_warning_icon(self):
        old_date = (date.today() - timedelta(days=100)).isoformat()
        epic = make_epic(id=1, etype="Feature",
                         labels=["Feature", "lifecycle::funnel"],
                         created_at=old_date)
        content = _run(_harness(features=[epic]))
        # oldest age (100d) > funnel threshold (90d) → ⚠️ in the Oldest column
        assert "⚠️" in content

    def test_epic_under_threshold_not_flagged(self):
        recent_date = (date.today() - timedelta(days=30)).isoformat()
        epic = make_epic(id=1, etype="Feature",
                         labels=["Feature", "lifecycle::funnel"],
                         created_at=recent_date)
        content = _run(_harness(features=[epic]))
        # 30d < funnel threshold 90d → no ⚠️ in table rows
        lines = content.splitlines()
        funnel_line = next((l for l in lines if "💡 Funnel" in l and "|" in l), "")
        assert "⚠️" not in funnel_line

    def test_age_displayed_in_days(self):
        recent_date = (date.today() - timedelta(days=15)).isoformat()
        epic = make_epic(id=1, etype="Feature",
                         labels=["Feature", "lifecycle::funnel"],
                         created_at=recent_date)
        content = _run(_harness(features=[epic]))
        assert "15d" in content
