"""Tests for generate_flow_metrics_report (Refs #24)."""
import sys



from tests.conftest import ReportsHarness, make_epic


def _harness(epics=None, piid_labels=None, work_type_labels=None):
    all_epics = epics or []
    h = ReportsHarness(
        metrics={
            "Epic":       [e for e in all_epics if e.get("type") == "Epic"],
            "Capability": [e for e in all_epics if e.get("type") == "Capability"],
            "Feature":    [e for e in all_epics if e.get("type") == "Feature"],
        },
        piid_labels=piid_labels or [],
    )
    h._rd_work_type_labels = work_type_labels or []
    return h


def _run(h):
    h.generate_flow_metrics_report()
    return h._uploaded.get(f"{h._wiki_t3}/Flow Metrics", "")


class TestFlowMetricsStructure:
    def test_uploads_to_correct_wiki_page(self):
        h = _harness()
        h.generate_flow_metrics_report()
        assert f"{h._wiki_t3}/Flow Metrics" in h._uploaded

    def test_velocity_section_present(self):
        assert "## 📈 Flow Velocity" in _run(_harness())

    def test_wip_section_present(self):
        assert "## 📦 Flow Load" in _run(_harness())

    def test_distribution_section_present(self):
        assert "## 🔀 Flow Distribution" in _run(_harness())

    def test_cycle_time_section_present(self):
        assert "## ⏱ Flow Time" in _run(_harness())

    def test_empty_state_no_crash(self):
        assert _run(_harness()) != ""


class TestFlowMetricsVelocity:
    def test_pi_label_in_velocity_table(self):
        feat = make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         state="closed", labels=["Feature", "PIID::2026Q1"])
        content = _run(_harness(epics=[feat], piid_labels=["PIID::2026Q1"]))
        assert "PIID::2026Q1" in content

    def test_zero_velocity_guidance_shown_when_no_closed(self):
        content = _run(_harness(piid_labels=["PIID::2026Q1"]))
        assert "No closed epics found" in content

    def test_closed_feature_counted_in_velocity(self):
        feats = [
            make_epic(id=i, etype="Feature", piid="PIID::2026Q1",
                      state="closed", labels=["Feature", "PIID::2026Q1"])
            for i in range(1, 4)
        ]
        content = _run(_harness(epics=feats, piid_labels=["PIID::2026Q1"]))
        # 3 features closed → **3** in total delivered column
        assert "**3**" in content


class TestFlowMetricsDistribution:
    def test_safe_hierarchy_table_present(self):
        assert "By SAFe Hierarchy Level" in _run(_harness())

    def test_no_work_type_labels_shows_safe_targets_guidance(self):
        content = _run(_harness())
        assert "SAFe 6.0 target distribution" in content or "No `type::` labels found" in content

    def test_open_epic_counted_in_wip_table(self):
        feat = make_epic(id=10, etype="Feature", piid="PIID::2026Q1",
                         state="opened", labels=["Feature", "PIID::2026Q1"])
        content = _run(_harness(epics=[feat], piid_labels=["PIID::2026Q1"]))
        assert "PIID::2026Q1" in content


class TestFlowMetricsCycleTime:
    def test_age_of_open_epics_table_present(self):
        assert "Age of Open Epics" in _run(_harness())

    def test_cycle_time_section_shown_when_closed_epics_exist(self):
        feat = make_epic(id=10, etype="Feature", state="closed",
                         labels=["Feature"], created_at="2025-01-01")
        feat["updated_at"] = "2025-06-01"
        content = _run(_harness(epics=[feat]))
        assert "Cycle Time" in content
