"""Latest Work slide layout: the grouped issue list flows down column 1, then
column 2, then onto continuation slides — nothing may render past the bottom
edge, however many issues land in a week (deck-review fix, 2026-07-24). Deck
deps (python-pptx) are optional in the test env, so the module import is
guarded."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("pptx")
sys.path.insert(0, str(Path(__file__).parent.parent / "deck"))

import build_deck  # noqa: E402

TEMPLATE = Path(__file__).parent.parent / "deck" / "assets" / "template.pptx"
SINCE = datetime(2026, 7, 17, tzinfo=timezone.utc)
TYPE_LABELS = ["type::feature", "type::enhance", "type::bug", "type::chore", ""]


def _builder(n_issues):
    db = build_deck.DeckBuilder(str(TEMPLATE), "/nonexistent", {}, [], {},
                                since_dt=SINCE, spotlights=[])
    db.issues = [build_deck._issue_row(
        {"iid": i, "title": f"Issue number {i} with a reasonably long title",
         "labels": [TYPE_LABELS[i % len(TYPE_LABELS)]] if TYPE_LABELS[i % len(TYPE_LABELS)] else [],
         "closed_at": None, "state": "closed", "assignee": None,
         "description": ""})
        for i in range(1, n_issues + 1)]
    return db


def _build_latest_work(db):
    """Run build_latest_work with every issue counted as completed; return the
    slides it added (divider first, then the list slide(s))."""
    before = len(db.prs.slides)
    with patch.object(build_deck, "fetch_completed_since",
                      return_value={r["iid"] for r in db.issues}):
        db.build_latest_work()
    return list(db.prs.slides)[before:]


def _texts(slide):
    return [sh.text_frame.text for sh in slide.shapes
            if sh.has_text_frame and sh.text_frame.text.strip()]


def test_no_shape_renders_past_the_slide_bottom():
    db = _builder(60)
    for slide in _build_latest_work(db):
        for sh in slide.shapes:
            assert sh.top + sh.height <= db.SH, \
                f"shape runs off the slide: {getattr(sh, 'text', '')!r}"


def test_overflow_continues_onto_extra_slides_with_cont_headings():
    db = _builder(60)
    slides = _build_latest_work(db)
    list_slides = slides[1:]  # slides[0] is the section divider
    assert len(list_slides) >= 2
    assert any("continued" in t for t in _texts(list_slides[1]))
    assert any(t.endswith("(cont.)") for s in list_slides for t in _texts(s))


def test_fit_bullet_size_keeps_font_when_content_fits():
    size, sa = build_deck.DeckBuilder._fit_bullet_size(
        4550000, 3593500, ["short bullet"] * 3, 13, 10)
    assert (size, sa) == (13, 10)


def test_fit_bullet_size_shrinks_font_for_long_content():
    bullets = ["A rather long capability bullet line that wraps several times "
               "when rendered at thirteen points in a half-width column " * 2] * 6
    size, sa = build_deck.DeckBuilder._fit_bullet_size(
        4550000, 3593500, bullets, 13, 10)
    assert 9 <= size < 13
    assert sa == pytest.approx(10 * size / 13)


def test_small_week_stays_on_one_slide():
    db = _builder(6)
    slides = _build_latest_work(db)
    assert len(slides) == 2  # divider + a single list slide
    for sh in slides[1].shapes:
        assert sh.top + sh.height <= db.SH


def test_lone_group_renders_as_plain_list_without_heading():
    """A week where every issue falls into one group (e.g. all untyped → "Other
    Work") renders as a plain list — a heading over the only list is noise."""
    db = _builder(6)
    for row in db.issues:
        row["type"] = ""  # everything sweeps into the fallback group
    slides = _build_latest_work(db)
    texts = [t for s in slides[1:] for t in _texts(s)]
    assert not any("Other Work" in t for t in texts)
    assert any("Issue number 1" in t for t in texts)


def test_mixed_week_keeps_group_headings():
    db = _builder(8)  # cycles through all four types + untyped
    slides = _build_latest_work(db)
    texts = [t for s in slides[1:] for t in _texts(s)]
    assert any("Other Work" in t for t in texts)
    assert any("New Features" in t for t in texts)
