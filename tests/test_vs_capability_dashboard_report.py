"""Tests for generate_vs_capability_dashboard_report (Refs #24)."""
import sys

sys.path.insert(0, "/root/.venv/beelzabub-project")

from tests.conftest import ReportsHarness, make_epic, make_risk


# ---------------------------------------------------------------------------
# Hierarchy helpers
# ---------------------------------------------------------------------------

def _vs(id=20, name="VS 01"):
    return {"id": id, "name": name,
            "web_url": f"https://gitlab.com/test/vs-{id}",
            "full_path": f"test/vs-{id}"}


def _art(id=30, name="ART 01"):
    return {"id": id, "name": name,
            "web_url": f"https://gitlab.com/test/art-{id}",
            "full_path": f"test/art-{id}"}


def _team(id=40, name="Team Alpha"):
    return {"id": id, "name": name,
            "web_url": f"https://gitlab.com/test/team-{id}",
            "full_path": f"test/team-{id}"}


def _harness(capabilities=None, features=None):
    vs   = _vs()
    art  = _art()
    team = _team()
    return ReportsHarness(
        metrics={
            "Epic":       [],
            "Capability": capabilities or [],
            "Feature":    features or [],
        },
        vs_groups=[vs],
        groups_by_parent={vs["id"]: [art], art["id"]: [team]},
    )


def _capability(art_id=30, **kw):
    """Capability at ART level with a PIID so it lands in a bucket."""
    return make_epic(etype="Capability", group_id=art_id, piid="PIID::2026Q1", **kw)


def _direct_feature(art_id=30, **kw):
    """Feature with no Capability parent — qualifies as a direct feature."""
    return make_epic(etype="Feature", group_id=art_id, piid="PIID::2026Q1",
                     parent_id=None, **kw)


def _run(h):
    h.generate_vs_capability_dashboard_report()


def _top_page(h):
    return h._uploaded.get(f"{h._wiki_t3}/VS Capability Dashboard", "")


def _vs_page(h, vs="VS 01"):
    return h._uploaded.get(f"{h._wiki_t3}/VS Capability Dashboard/{vs}", "")


# ---------------------------------------------------------------------------
# Structure / upload tests
# ---------------------------------------------------------------------------

class TestVsCapabilityDashboardStructure:
    def test_top_level_page_always_uploaded(self):
        h = _harness()
        _run(h)
        assert f"{h._wiki_t3}/VS Capability Dashboard" in h._uploaded

    def test_empty_state_no_crash(self):
        h = _harness()
        _run(h)

    def test_vs_page_uploaded_when_capabilities_present(self):
        h = _harness(capabilities=[_capability()])
        _run(h)
        assert f"{h._wiki_t3}/VS Capability Dashboard/VS 01" in h._uploaded

    def test_vs_page_uploaded_when_direct_features_present(self):
        h = _harness(features=[_direct_feature()])
        _run(h)
        assert f"{h._wiki_t3}/VS Capability Dashboard/VS 01" in h._uploaded

    def test_vs_page_not_uploaded_when_no_data(self):
        h = _harness()
        _run(h)
        assert f"{h._wiki_t3}/VS Capability Dashboard/VS 01" not in h._uploaded

    def test_vs_name_shown_in_top_level_page(self):
        h = _harness(capabilities=[_capability()])
        _run(h)
        assert "VS 01" in _top_page(h)


# ---------------------------------------------------------------------------
# Section rendering
# ---------------------------------------------------------------------------

class TestVsCapabilityDashboardSections:
    def test_capability_section_rendered(self):
        h = _harness(capabilities=[_capability()])
        _run(h)
        assert "🧩 Capabilities" in _vs_page(h)

    def test_direct_feature_section_rendered(self):
        h = _harness(features=[_direct_feature()])
        _run(h)
        assert "🛠️ Direct Features" in _vs_page(h)

    def test_capability_section_absent_when_no_capabilities(self):
        h = _harness(features=[_direct_feature()])
        _run(h)
        assert "🧩 Capabilities" not in _vs_page(h)

    def test_direct_feature_section_absent_when_no_direct_features(self):
        h = _harness(capabilities=[_capability()])
        _run(h)
        assert "🛠️ Direct Features" not in _vs_page(h)

    def test_feature_with_capability_parent_excluded_from_direct(self):
        # parent_id resolves to a Capability → not a direct feature
        cap  = _capability(id=200)
        feat = make_epic(etype="Feature", group_id=30, piid="PIID::2026Q1",
                         parent_id=200)
        h = _harness(capabilities=[cap], features=[feat])
        _run(h)
        assert "🛠️ Direct Features" not in _vs_page(h)


# ---------------------------------------------------------------------------
# At Risk Reason column and ROAM count
# ---------------------------------------------------------------------------

class TestVsCapabilityDashboardRiskReason:
    def test_detail_rows_have_at_risk_reason_column_for_capabilities(self):
        # At Risk Reason column required in capability detail (Refs #8)
        h = _harness(capabilities=[_capability()])
        _run(h)
        assert "At Risk Reason" in _vs_page(h)

    def test_detail_rows_have_at_risk_reason_column_for_direct_features(self):
        h = _harness(features=[_direct_feature()])
        _run(h)
        assert "At Risk Reason" in _vs_page(h)

    def test_roam_count_shown_in_reason_for_capability(self):
        risk = make_risk(roam_status="roam::owned")
        h    = _harness(capabilities=[_capability(roam_risks=[risk])])
        _run(h)
        assert "risk" in _vs_page(h).lower()

    def test_roam_count_shown_in_reason_for_direct_feature(self):
        risk = make_risk(roam_status="roam::mitigated")
        h    = _harness(features=[_direct_feature(roam_risks=[risk])])
        _run(h)
        assert "risk" in _vs_page(h).lower()
