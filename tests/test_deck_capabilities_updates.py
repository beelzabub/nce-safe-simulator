"""Capability-area drift detection + weekly-update merging (issue #258 flavor):
capabilities_coverage_gap finds closed issues cited in no area, and
merge_capability_updates folds the authoring step's proposed deltas into the
loaded capability list at build time. Deck deps (python-pptx) are optional in
the test env, so the module import is guarded."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("pptx")
sys.path.insert(0, str(Path(__file__).parent.parent / "deck"))

import build_deck  # noqa: E402


def _row(iid, repo="", state="closed"):
    return {"iid": iid, "repo": repo,
            "ref": f"{repo}#{iid}" if repo else f"#{iid}",
            "title": f"Issue {iid}", "state": state, "type": "",
            "assignee": "", "closed_at": "2026-07-20T00:00:00Z"}


CAPS = [
    {"title": "Area A", "count": 2, "all_issues": "#21, #210",
     "blurb": "", "bullets": ["#21 did a thing"]},
    {"title": "Platform", "count": 1, "all_issues": "nce-git-ops#7",
     "blurb": "", "bullets": []},
]


def test_gap_finds_uncited_closed_issue():
    gap = build_deck.capabilities_coverage_gap(CAPS, [_row(21), _row(99)])
    assert [r["ref"] for r in gap] == ["#99"]


def test_gap_ignores_open_issues():
    assert build_deck.capabilities_coverage_gap(CAPS, [_row(99, state="opened")]) == []


def test_gap_bare_ref_is_not_a_prefix_match():
    # #2 must not be satisfied by the #21/#210 citations
    gap = build_deck.capabilities_coverage_gap(CAPS, [_row(2)])
    assert [r["ref"] for r in gap] == ["#2"]


def test_gap_simulator_ref_not_matched_by_companion_citation():
    # simulator #7 is not covered by the nce-git-ops#7 citation, but
    # companion nce-git-ops#7 is
    gap = build_deck.capabilities_coverage_gap(
        CAPS, [_row(7), _row(7, repo="nce-git-ops")])
    assert [r["ref"] for r in gap] == ["#7"]


def test_merge_extends_area_and_appends_new():
    merged = build_deck.merge_capability_updates(CAPS, {
        "extend": [{"title": "Area A", "add_issues": "#300, #301",
                    "add_bullets": ["#300 new flagship bullet"]}],
        "new_areas": [{"title": "Brand New", "count": 1,
                       "all_issues": "#400", "blurb": "", "bullets": []}],
    })
    a = next(c for c in merged if c["title"] == "Area A")
    assert a["count"] == 4 and a["all_issues"].endswith("#300, #301")
    assert a["bullets"][-1] == "#300 new flagship bullet"
    assert merged[-1]["title"] == "Brand New"
    # inputs are not mutated
    assert CAPS[0]["count"] == 2 and len(CAPS) == 2


def test_merge_unknown_title_is_skipped(capsys):
    merged = build_deck.merge_capability_updates(
        CAPS, {"extend": [{"title": "No Such Area", "add_issues": "#1"}]})
    assert merged[0]["count"] == 2
    assert "unknown area" in capsys.readouterr().out


def test_merged_updates_close_the_gap():
    updates = {"extend": [{"title": "Area A", "add_issues": "#99"}]}
    merged = build_deck.merge_capability_updates(CAPS, updates)
    assert build_deck.capabilities_coverage_gap(merged, [_row(99)]) == []
