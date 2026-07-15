"""Unit tests for the epic-card PDF renderer and the epic→card mapping (#249)."""
from types import SimpleNamespace

import pytest

from mixins.epic_cards import build_html, render_cards, _dims
from mixins.importexport import ImportExportMixin


# ── Pure renderer ─────────────────────────────────────────────────────────────

def _sample_card(**over):
    c = {
        "title": "Secure Data Fabric", "weight": 13, "description": "A long-ish description.",
        "mission_thread": "Thread 3", "phase": "Deliver", "actions": ["Transport", "Tagging"],
        "main_system": "DOO", "related_systems": ["ABC", "DEF"], "due_date": "2026-09-30",
        "color": "#2f6f4f",
    }
    c.update(over)
    return c


@pytest.mark.unit
def test_build_html_contains_all_fields():
    html = build_html([_sample_card()], per_page=2)
    for token in ("Secure Data Fabric", "13", "A long-ish description.",
                  "Thread 3", "Phase: Deliver", "Transport", "Tagging",
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
def test_dims_geometry():
    # 1-up is a full-page card; 2-up halves the height; 4-up keeps that height
    # but halves the width (two columns).
    assert _dims(1)[1] > _dims(2)[1]                 # fewer per page -> taller
    assert _dims(2)[1] == pytest.approx(_dims(4)[1])  # same row height
    assert _dims(2)[0] > _dims(4)[0]                 # 4-up is two columns -> narrower


@pytest.mark.unit
def test_render_cards_writes_pdf(tmp_path):
    out = tmp_path / "cards.pdf"
    render_cards([_sample_card(), _sample_card(title="Second")], out, per_page=2)
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
def test_program_color_is_deterministic():
    assert ImportExportMixin._program_color("DOO") == ImportExportMixin._program_color("DOO")
    assert ImportExportMixin._program_color(None) == "#3b6ea5"


@pytest.mark.unit
def test_epic_to_card_splits_labels_by_taxonomy():
    epic = SimpleNamespace(
        title="Cap A", web_url="http://x/1", description="desc",
        due_date="2026-09-30", end_date=None,
        labels=["project::DOO", "mission-thread::T3", "phase::Deliver",
                "activity1", "activity2", "ABC", "DEF", "bucket7"],
    )
    taxonomy = {"activity": {"activity1", "activity2"}, "project": {"DOO", "ABC", "DEF"}}
    card = _mixin()._epic_to_card(epic, {"http://x/1": 13}, taxonomy)

    assert card["title"] == "Cap A"
    assert card["weight"] == 13
    assert card["mission_thread"] == "T3"
    assert card["phase"] == "Deliver"
    assert card["main_system"] == "DOO"
    assert sorted(card["actions"]) == ["activity1", "activity2"]
    # related = project-vocab unscoped labels EXCLUDING the primary DOO
    assert sorted(card["related_systems"]) == ["ABC", "DEF"]
    assert "bucket7" not in card["related_systems"]   # not in project vocab


@pytest.mark.unit
def test_epic_to_card_without_taxonomy_leaves_unscoped_empty():
    epic = SimpleNamespace(
        title="Cap B", web_url="http://x/2", description="d",
        due_date=None, end_date="2026-01-01",
        labels=["project::AIS", "mission-thread::T1", "activity9", "COP"],
    )
    card = _mixin()._epic_to_card(epic, {}, {})
    assert card["main_system"] == "AIS"          # scoped still resolves
    assert card["mission_thread"] == "T1"
    assert card["actions"] == []                  # can't classify without taxonomy
    assert card["related_systems"] == []
    assert card["due_date"] == "2026-01-01"       # falls back to end_date
    assert card["weight"] is None
