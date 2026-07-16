"""Unit tests for the epic-card PDF renderer and the epic→card mapping (#249)."""
import json
from types import SimpleNamespace

import pytest

from mixins.epic_cards import (
    build_html, render_cards, _dims, _page_dims, _truncate, _bucket_chips,
    _BUCKET_MAX, _DESC_BUDGET, _parse_page_size, _parse_grid, _card_dims,
)
from mixins.importexport import ImportExportMixin


# ── Pure renderer ─────────────────────────────────────────────────────────────

def _sample_card(**over):
    c = {
        "title": "Secure Data Fabric", "weight": 13, "description": "A long-ish description.",
        "mission_thread": "Thread 3", "buckets": ["bucket7", "bucket12"],
        "main_system": "DOO", "related_systems": ["ABC", "DEF"], "due_date": "2026-09-30",
        "color": "#2f6f4f",
    }
    c.update(over)
    return c


@pytest.mark.unit
def test_build_html_contains_all_fields():
    html = build_html([_sample_card()], per_page=2)
    for token in ("Secure Data Fabric", "13", "A long-ish description.",
                  "Thread 3", "Buckets", "bucket7", "bucket12",
                  "DOO", "ABC", "DEF", "2026-09-30", "#2f6f4f"):
        assert token in html, f"missing {token!r}"


@pytest.mark.unit
def test_build_html_escapes_and_handles_missing_fields():
    html = build_html([{"title": "A & B <x>", "description": None, "weight": None}], per_page=2)
    assert "A &amp; B &lt;x&gt;" in html      # escaped
    assert "Wt</span> —" in html               # missing weight -> em dash
    assert ">—<" in html                        # missing main system -> em dash


@pytest.mark.unit
@pytest.mark.parametrize("per_page,cards,pages", [(1, 3, 3), (2, 4, 2), (4, 4, 1), (2, 1, 1)])
def test_build_html_paginates(per_page, cards, pages):
    html = build_html([_sample_card() for _ in range(cards)], per_page=per_page)
    assert html.count('class="sheet"') == pages


@pytest.mark.unit
def test_build_html_empty_still_valid():
    html = build_html([], per_page=2)
    assert 'class="sheet"' in html   # one empty sheet, never a crash


@pytest.mark.unit
def test_truncate_marks_only_when_cut():
    assert _truncate("short and sweet", 100) == "short and sweet"   # untouched
    long = "word " * 100
    out = _truncate(long, 40)
    assert out.endswith(" …") and len(out) <= 44                    # cut + marker
    assert _truncate("a\n\n  b   c\nd", 100) == "a b c d"           # whitespace collapsed


@pytest.mark.unit
def test_description_truncated_at_budget_with_ellipsis():
    budget = _DESC_BUDGET[1]
    card = _sample_card(description="lorem ipsum dolor sit amet " * 400)
    html = build_html([card], per_page=1)
    assert " …</div>" in html                                       # visible cut marker
    # the rendered description never exceeds the budget (+ the ' …' marker)
    body = html.split('class="desc">', 1)[1].split("</div>", 1)[0]
    assert len(body) <= budget + 2


@pytest.mark.unit
def test_buckets_cutoff_collapses_to_ellipsis_chip():
    over = ["bucket%d" % i for i in range(1, _BUCKET_MAX[1] + 6)]   # more than the cap
    chips = _bucket_chips(over, per_page=1)
    assert chips.count('class="chip bucket"') == _BUCKET_MAX[1]     # exactly the cap shown
    assert 'class="chip bucket more">…' in chips                    # trailing '…' chip
    # under the cap → no ellipsis
    assert "more" not in _bucket_chips(["bucket1", "bucket2"], per_page=1)


@pytest.mark.unit
def test_all_bucket_shorthand_wins():
    chips = _bucket_chips(["bucket3", "ALL", "bucket9"], per_page=1)
    assert chips == '<span class="chip bucket all">ALL</span>'      # ALL subsumes the rest
    assert _bucket_chips(["all"], per_page=1).endswith('>ALL</span>')  # case-insensitive


@pytest.mark.unit
def test_bucket_chips_honor_live_colors():
    # light bg → dark ink; dark bg → white ink (YIQ, matching GitLab)
    chips = _bucket_chips(["bucket3"], per_page=1, colors={"bucket3": "#E6C594"})
    assert "background:#E6C594;color:#1a1a1a;" in chips
    allc = _bucket_chips(["ALL"], per_page=1, colors={"ALL": "#2C6D4D"})
    assert "background:#2C6D4D;color:#ffffff;" in allc
    # no color for a label → default class styling, no inline style
    assert "style=" not in _bucket_chips(["bucket3"], per_page=1, colors={})


@pytest.mark.unit
def test_dims_geometry():
    # 1-up is a full-page card; 2-up halves the height; 4-up keeps that height
    # but halves the width (two columns). Uses the portrait usable area.
    uw, uh = 7.7, 10.2
    assert _dims(1, uw, uh)[1] > _dims(2, uw, uh)[1]                    # fewer per page -> taller
    assert _dims(2, uw, uh)[1] == pytest.approx(_dims(4, uw, uh)[1])    # same row height
    assert _dims(2, uw, uh)[0] > _dims(4, uw, uh)[0]                    # 4-up is two columns -> narrower


@pytest.mark.unit
def test_render_cards_writes_pdf(tmp_path):
    out = tmp_path / "cards.pdf"
    render_cards([_sample_card(), _sample_card(title="Second")], out, per_page=2)
    assert out.is_file()
    assert out.read_bytes()[:5] == b"%PDF-"


# ── orientation (#254) ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_page_dims_portrait_and_landscape():
    assert _page_dims("portrait")  == (8.5, 11.0, 7.7, 10.2)
    assert _page_dims("landscape") == (11.0, 8.5, 10.2, 7.7)


@pytest.mark.unit
@pytest.mark.parametrize("orientation", [None, "", "portrait", "PORTRAIT", "bogus"])
def test_page_dims_defaults_to_portrait(orientation):
    # Anything that isn't "landscape" (case-insensitive) is portrait.
    assert _page_dims(orientation) == (8.5, 11.0, 7.7, 10.2)


@pytest.mark.unit
def test_build_html_emits_orientation_page_size():
    portrait  = build_html([_sample_card()], per_page=1, orientation="portrait")
    landscape = build_html([_sample_card()], per_page=1, orientation="landscape")
    assert "@page { size: 8.5in 11in;" in portrait
    assert ".sheet { width: 7.700in; height: 10.200in;" in portrait
    assert "@page { size: 11in 8.5in;" in landscape
    assert ".sheet { width: 10.200in; height: 7.700in;" in landscape


@pytest.mark.unit
def test_build_html_default_is_portrait():
    # Omitting orientation must render exactly as portrait (backward compatible).
    assert build_html([_sample_card()], per_page=2) == \
           build_html([_sample_card()], per_page=2, orientation="portrait")


@pytest.mark.unit
def test_render_cards_landscape_writes_pdf(tmp_path):
    out = tmp_path / "cards-landscape.pdf"
    render_cards([_sample_card()], out, per_page=1, orientation="landscape")
    assert out.is_file()
    assert out.read_bytes()[:5] == b"%PDF-"


# ── large-format plotter 'wall' (#241) ────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize("value,expected", [
    ("arch-e",     (36.0, 48.0)),
    ("arch-d",     (24.0, 36.0)),
    ("tabloid",    (11.0, 17.0)),
    ("36x48",      (36.0, 48.0)),
    ("36 x 48in",  (36.0, 48.0)),
    ("24X36",      (24.0, 36.0)),
    ("bogus",      None),
    ("",           None),
    (None,         None),
    ("0x10",       None),          # non-positive rejected
])
def test_parse_page_size(value, expected):
    assert _parse_page_size(value) == expected


@pytest.mark.unit
def test_parse_page_size_landscape_swaps_presets_only():
    assert _parse_page_size("arch-e", "landscape") == (48.0, 36.0)   # preset swaps
    assert _parse_page_size("36x48", "landscape")  == (36.0, 48.0)   # explicit is verbatim


@pytest.mark.unit
@pytest.mark.parametrize("value,expected", [
    ("6x8", (6, 8)), ("1x1", (1, 1)), ("10X4", (10, 4)),
    ("6 x 8", (6, 8)), ("0x5", None), ("x", None), ("6", None), ("", None), (None, None),
])
def test_parse_grid(value, expected):
    assert _parse_grid(value) == expected


@pytest.mark.unit
def test_card_dims_tiles_exactly():
    # cols x rows cards + (n-1) gaps must exactly fill the usable sheet.
    uw, uh = 35.2, 47.2
    w, h = _card_dims(6, 8, uw, uh)
    assert pytest.approx(6 * w + 5 * 0.28) == uw
    assert pytest.approx(8 * h + 7 * 0.28) == uh


@pytest.mark.unit
def test_build_html_large_format_page_and_grid():
    html = build_html([_sample_card()], page_size="arch-e", grid="6x8")
    assert "@page { size: 36in 48in;" in html
    assert ".sheet { width: 35.200in; height: 47.200in;" in html


@pytest.mark.unit
@pytest.mark.parametrize("cards,grid,sheets", [
    (20, "6x8", 1),     # 20 <= 48 per sheet
    (48, "6x8", 1),     # exactly one sheet
    (50, "6x8", 2),     # overflow flows onto a second sheet
    (5,  "2x2", 2),     # 4 per sheet -> 2 sheets
])
def test_build_html_grid_paginates(cards, grid, sheets):
    html = build_html([_sample_card() for _ in range(cards)], page_size="arch-e", grid=grid)
    assert html.count('class="sheet"') == sheets


@pytest.mark.unit
def test_grid_overrides_per_page():
    # When grid is given, per_page is ignored for the card count per sheet.
    html = build_html([_sample_card() for _ in range(9)], per_page=1, grid="3x3")
    assert html.count('class="sheet"') == 1     # 9 cards, 3x3 = 9 per sheet


@pytest.mark.unit
def test_invalid_page_size_and_grid_fall_back_to_letter():
    # Renderer tolerates junk and produces the default Letter/per-page output.
    fallback = build_html([_sample_card()], per_page=2, page_size="nope", grid="bad")
    assert fallback == build_html([_sample_card()], per_page=2)


@pytest.mark.unit
def test_render_cards_large_format_writes_pdf(tmp_path):
    out = tmp_path / "wall.pdf"
    cards = [_sample_card(title=f"E{i}") for i in range(12)]
    render_cards(cards, out, page_size="36x48", grid="6x8")
    assert out.is_file()
    assert out.read_bytes()[:5] == b"%PDF-"


# ── epic → card mapping ───────────────────────────────────────────────────────

def _mixin():
    """A bare ImportExportMixin instance (no __init__) — enough for the pure
    mapping helpers, which only touch static methods and the passed args."""
    return ImportExportMixin.__new__(ImportExportMixin)


@pytest.mark.unit
def test_scoped_value():
    labels = ["project::DOO", "mission-thread::Thread 3", "ABC", "epic::capability"]
    assert ImportExportMixin._scoped_value(labels, "project") == "DOO"
    assert ImportExportMixin._scoped_value(labels, "mission-thread") == "Thread 3"
    assert ImportExportMixin._scoped_value(labels, "phase") is None


@pytest.mark.unit
def test_epic_label_match_wildcard():
    m = ImportExportMixin._epic_label_match
    caps = ["epic::capability", "mission-thread::Thread3", "bucket7"]
    # the capability-card definition: epic::capability AND any mission-thread::*
    assert m(caps, ["epic::capability", "mission-thread::*"])
    # missing the mission-thread scope → excluded
    assert not m(["epic::capability", "bucket7"], ["epic::capability", "mission-thread::*"])
    # exact tokens still require an exact label
    assert not m(caps, ["epic::feature"])
    assert m(caps, ["bucket7"])


@pytest.mark.unit
def test_filter_tokens_accepts_string_and_list():
    f = ImportExportMixin._filter_tokens
    assert f("epic::capability, mission-thread::*") == ["epic::capability", "mission-thread::*"]
    assert f(["epic::capability", " mission-thread::* "]) == ["epic::capability", "mission-thread::*"]
    assert f("") == []
    assert f(None) == []
    assert f([" ", ""]) == []


@pytest.mark.unit
def test_normalize_taxonomy_builds_name_sets():
    n = ImportExportMixin._normalize_taxonomy
    assert n({"bucket": ["b1", "b2"], "project": ["DCGS"]}) == {
        "bucket": {"b1", "b2"}, "project": {"DCGS"}}
    # nested {"names": [...]} form is honored too
    assert n({"bucket": {"names": ["b1"]}}) == {"bucket": {"b1"}}
    assert n({}) == {}
    assert n(None) == {}


@pytest.mark.unit
def test_load_card_spec_reads_filter_and_taxonomy(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "filter": ["epic::capability", "mission-thread::*"],
        "taxonomy": {"bucket": ["ALL", "bucket7"], "project": ["DCGS"]},
    }))
    loaded = _mixin()._load_card_spec(str(spec))
    assert _mixin()._filter_tokens(loaded["filter"]) == ["epic::capability", "mission-thread::*"]
    assert _mixin()._normalize_taxonomy(loaded["taxonomy"]) == {
        "bucket": {"ALL", "bucket7"}, "project": {"DCGS"}}


@pytest.mark.unit
def test_load_card_spec_missing_path_returns_empty(tmp_path):
    assert _mixin()._load_card_spec(str(tmp_path / "nope.json")) == {}


@pytest.mark.unit
def test_shipped_card_spec_is_valid():
    """The repo-root epic-cards-spec.json (the operator-editable default) must
    parse and carry the capability filter plus a bucket vocab including ALL."""
    from mixins.importexport import _CARD_SPEC_DEFAULT
    spec = _mixin()._load_card_spec(None)          # None → shipped default
    assert _CARD_SPEC_DEFAULT.name == "epic-cards-spec.json"
    tokens = _mixin()._filter_tokens(spec["filter"])
    assert "epic::capability" in tokens
    assert any(t.startswith("mission-thread::") for t in tokens)
    tax = _mixin()._normalize_taxonomy(spec["taxonomy"])
    assert "ALL" in tax["bucket"]
    assert tax["project"]                          # non-empty related-systems vocab


@pytest.mark.unit
def test_program_color_is_deterministic():
    assert ImportExportMixin._program_color("DOO") == ImportExportMixin._program_color("DOO")
    assert ImportExportMixin._program_color(None) == "#3b6ea5"


@pytest.mark.unit
def test_epic_to_card_splits_labels_by_taxonomy():
    epic = SimpleNamespace(
        title="Cap A", web_url="http://x/1", description="desc",
        due_date="2026-09-30", end_date=None,
        labels=["project::DOO", "mission-thread::T3",
                "bucket7", "bucket12", "ABC", "DEF"],
    )
    taxonomy = {"bucket": {"bucket7", "bucket12"}, "project": {"DOO", "ABC", "DEF"}}
    card = _mixin()._epic_to_card(epic, {"http://x/1": 13}, taxonomy)

    assert card["title"] == "Cap A"
    assert card["weight"] == 13
    assert card["mission_thread"] == "T3"
    assert card["main_system"] == "DOO"
    assert sorted(card["buckets"]) == ["bucket12", "bucket7"]
    # related = project-vocab unscoped labels EXCLUDING the primary DOO
    assert sorted(card["related_systems"]) == ["ABC", "DEF"]
    assert "bucket7" not in card["related_systems"]   # not in project vocab


@pytest.mark.unit
def test_epic_to_card_without_taxonomy_leaves_unscoped_empty():
    epic = SimpleNamespace(
        title="Cap B", web_url="http://x/2", description="d",
        due_date=None, end_date="2026-01-01",
        labels=["project::AIS", "mission-thread::T1", "bucket9", "COP"],
    )
    card = _mixin()._epic_to_card(epic, {}, {})
    assert card["main_system"] == "AIS"          # scoped still resolves
    assert card["mission_thread"] == "T1"
    assert card["buckets"] == []                  # can't classify without taxonomy
    assert card["related_systems"] == []
    assert card["due_date"] == "2026-01-01"       # falls back to end_date
    assert card["weight"] is None
