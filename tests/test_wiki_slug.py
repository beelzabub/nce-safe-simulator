"""Unit tests for _wiki_slug() in mixins/reports.py."""
import sys
import pytest



from mixins.reports import _wiki_slug


class TestWikiSlug:
    def test_spaces_become_dashes(self):
        assert _wiki_slug("Hello World") == "Hello-World"

    def test_slashes_preserved(self):
        assert _wiki_slug("Tier1/Tier2/Page") == "Tier1/Tier2/Page"

    def test_consecutive_spaces_collapsed(self):
        assert _wiki_slug("Hello   World") == "Hello-World"

    def test_special_chars_become_spaces(self):
        slug = _wiki_slug("A!B@C#D")
        assert "!" not in slug
        assert "@" not in slug
        assert "#" not in slug

    def test_em_dash_preserved(self):
        slug = _wiki_slug("PMW-120 — Portfolio Home")
        assert "—" in slug

    def test_leading_trailing_dashes_stripped(self):
        slug = _wiki_slug("  Hello  ")
        assert not slug.startswith("-")
        assert not slug.endswith("-")

    def test_nested_wiki_path(self):
        slug = _wiki_slug("Portfolio/01 Program Management/Risk Register")
        assert slug == "Portfolio/01-Program-Management/Risk-Register"

    def test_empty_string(self):
        assert _wiki_slug("") == ""

    def test_consecutive_dashes_collapsed(self):
        slug = _wiki_slug("A  B")
        assert "--" not in slug
