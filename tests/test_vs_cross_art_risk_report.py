"""Tests for generate_vs_cross_art_risk_report (Refs #24)."""
import sys



from tests.conftest import ReportsHarness, make_epic


def _vs(id=20, name="VS 01"):
    return {"id": id, "name": name,
            "web_url": f"https://gitlab.com/test/vs-{id}",
            "full_path": f"test/vs-{id}"}


def _art(id=30, name="ART 01"):
    return {"id": id, "name": name,
            "web_url": f"https://gitlab.com/test/art-{id}",
            "full_path": f"test/art-{id}"}


def _blocked(id=1, title="Blocked Feature"):
    return {
        "id":      f"gid://gitlab/WorkItem/{id}",
        "id_int":  id,
        "type":    "Feature",
        "title":   title,
        "state":   "opened",
        "web_url": f"https://gitlab.com/test/-/epics/{id}",
    }


def _blocker(id=99, title="Blocker Feature"):
    return {
        "id":      f"gid://gitlab/WorkItem/{id}",
        "id_int":  id,
        "type":    "Feature",
        "title":   title,
        "web_url": f"https://gitlab.com/test/-/epics/{id}",
    }


def _harness_empty():
    vs  = _vs()
    a   = _art(id=30, name="ART Alpha")
    b   = _art(id=31, name="ART Beta")
    return ReportsHarness(
        metrics={"Epic": [], "Capability": [], "Feature": []},
        vs_groups=[vs],
        groups_by_parent={vs["id"]: [a, b]},
    )


def _harness_with_cross_art_dep():
    vs = _vs(id=20)
    a  = _art(id=30, name="ART Alpha")
    b  = _art(id=31, name="ART Beta")

    # Epic 1 is in ART Alpha (group_id=30), blocked by epic 2 in ART Beta (group_id=31)
    blocked_epic = make_epic(id=1, etype="Feature", group_id=30,
                             labels=["Feature"], piid=None)
    blocker_epic = make_epic(id=2, etype="Feature", group_id=31,
                             labels=["Feature"], piid=None)

    rel = {
        "blocked_epic": _blocked(id=1, title="Blocked Feature"),
        "blocked_by":   [_blocker(id=2, title="Blocker Feature")],
        "at_risk_portfolio_epics": [],
    }

    h = ReportsHarness(
        metrics={"Epic": [], "Capability": [], "Feature": [blocked_epic, blocker_epic]},
        vs_groups=[vs],
        groups_by_parent={vs["id"]: [a, b], a["id"]: [], b["id"]: []},
    )
    h._rd_blocking = {"relationships": [rel], "summary": {"total_relationships": 1}}
    return h


def _run(h):
    h.generate_vs_cross_art_risk_report()
    return h._uploaded.get(f"{h._wiki_t3}/VS Cross-ART Risk", "")


class TestCrossArtRiskStructure:
    def test_index_page_uploaded(self):
        h = _harness_empty()
        h.generate_vs_cross_art_risk_report()
        assert f"{h._wiki_t3}/VS Cross-ART Risk" in h._uploaded

    def test_vs_page_uploaded(self):
        h = _harness_empty()
        h.generate_vs_cross_art_risk_report()
        assert f"{h._wiki_t3}/VS Cross-ART Risk/VS 01" in h._uploaded

    def test_empty_state_no_crash(self):
        assert _run(_harness_empty()) != ""

    def test_no_deps_message_in_vs_page(self):
        h = _harness_empty()
        h.generate_vs_cross_art_risk_report()
        vs_page = h._uploaded.get(f"{h._wiki_t3}/VS Cross-ART Risk/VS 01", "")
        assert "No cross-ART blocking relationships found" in vs_page


class TestCrossArtRiskWithData:
    def test_blocked_epic_shown_in_vs_page(self):
        h = _harness_with_cross_art_dep()
        h.generate_vs_cross_art_risk_report()
        vs_page = h._uploaded.get(f"{h._wiki_t3}/VS Cross-ART Risk/VS 01", "")
        assert "Blocked Feature" in vs_page

    def test_blocker_epic_shown_in_vs_page(self):
        h = _harness_with_cross_art_dep()
        h.generate_vs_cross_art_risk_report()
        vs_page = h._uploaded.get(f"{h._wiki_t3}/VS Cross-ART Risk/VS 01", "")
        assert "Blocker Feature" in vs_page

    def test_art_names_shown_in_table(self):
        h = _harness_with_cross_art_dep()
        h.generate_vs_cross_art_risk_report()
        vs_page = h._uploaded.get(f"{h._wiki_t3}/VS Cross-ART Risk/VS 01", "")
        assert "ART Alpha" in vs_page
        assert "ART Beta" in vs_page

    def test_dep_count_in_index_page(self):
        h = _harness_with_cross_art_dep()
        content = _run(h)
        assert "1 cross-ART dependenc" in content

    def test_no_cross_vs_deps_detected(self):
        """A dependency crossing VS boundaries is NOT flagged as cross-ART within a VS."""
        vs1 = _vs(id=20, name="VS 01")
        vs2 = _vs(id=21, name="VS 02")
        a1  = _art(id=30, name="ART A1")
        a2  = _art(id=31, name="ART A2")

        f1 = make_epic(id=1, etype="Feature", group_id=30, labels=["Feature"])
        f2 = make_epic(id=2, etype="Feature", group_id=31, labels=["Feature"])

        rel = {
            "blocked_epic": _blocked(id=1),
            "blocked_by":   [_blocker(id=2)],
            "at_risk_portfolio_epics": [],
        }

        h = ReportsHarness(
            metrics={"Epic": [], "Capability": [], "Feature": [f1, f2]},
            vs_groups=[vs1, vs2],
            groups_by_parent={vs1["id"]: [a1], vs2["id"]: [a2]},
        )
        h._rd_blocking = {"relationships": [rel], "summary": {"total_relationships": 1}}
        h.generate_vs_cross_art_risk_report()
        # Cross-VS deps are excluded — both VS pages should show "No cross-ART" message
        page1 = h._uploaded.get(f"{h._wiki_t3}/VS Cross-ART Risk/VS 01", "")
        assert "No cross-ART blocking relationships found" in page1
