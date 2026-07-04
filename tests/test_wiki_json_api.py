"""Tests for the wiki JSON endpoints feeding the Reports tab (issue #167).

Fixtures mirror production slugs: upload_to_wiki collapses dash runs, so the
'/' path separators are NOT recoverable from filenames — the real page path
comes from the wiki/pages.json manifest written alongside each page.
"""

import json
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from mixins.wiki import WikiMixin
from server.app import app, _wiki_page_tier


HOME   = "NCE — Portfolio Home"
HEALTH = "NCE — Portfolio Home/00 Executive Pulse/Portfolio Health Dashboard"
RISK   = "NCE — Portfolio Home/01 Program Management/Risk Register"

# Production slugs (dash runs collapsed — no '--' separators survive).
HOME_SLUG   = "nce-portfolio-home"
HEALTH_SLUG = "nce-portfolio-home-00-executive-pulse-portfolio-health-dashboard"
RISK_SLUG   = "nce-portfolio-home-01-program-management-risk-register"


def _write_wiki(reports_dir, date="20260701", time="120000", manifest=True):
    wiki = reports_dir / date / time / "wiki"
    wiki.mkdir(parents=True)
    (wiki / f"{HOME_SLUG}.md").write_text("# Portfolio Home\n\nindex\n")
    (wiki / f"{HEALTH_SLUG}.md").write_text(
        "# Portfolio Health Dashboard\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    (wiki / f"{RISK_SLUG}.md").write_text("# Risk Register\n\nrisks\n")
    if manifest:
        (wiki / "pages.json").write_text(json.dumps({
            HOME_SLUG: HOME, HEALTH_SLUG: HEALTH, RISK_SLUG: RISK,
        }, ensure_ascii=False))
    return wiki


def test_index_json_mirrors_wiki_hierarchy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_wiki(tmp_path / "reports")
    r = TestClient(app).get("/api/runs/20260701/120000/wiki/index.json")
    assert r.status_code == 200
    pages = r.json()

    by_slug = {p["slug"]: p for p in pages}
    home = by_slug[HOME_SLUG]
    assert home["path"] == HOME
    assert home["segments"] == [HOME]
    assert home["title"] == HOME
    assert home["tier"] is None

    health = by_slug[HEALTH_SLUG]
    assert health["segments"] == [
        HOME.split("/")[0], "00 Executive Pulse", "Portfolio Health Dashboard"]
    assert health["title"] == "Portfolio Health Dashboard"
    assert health["tier"] == "00"
    assert health["tier_name"] == "Executive Pulse"

    # Wiki order: home page first, then tier folders in numeric order.
    assert [p["slug"] for p in pages] == [HOME_SLUG, HEALTH_SLUG, RISK_SLUG]


def test_index_json_legacy_run_without_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_wiki(tmp_path / "reports", manifest=False)
    pages = TestClient(app).get(
        "/api/runs/20260701/120000/wiki/index.json").json()
    by_slug = {p["slug"]: p for p in pages}
    # Falls back to the leaf H1 title with no path/segments...
    assert by_slug[RISK_SLUG]["title"] == "Risk Register"
    assert by_slug[RISK_SLUG]["path"] is None
    assert by_slug[RISK_SLUG]["segments"] is None
    # ...but the tier is still recovered from the collapsed slug.
    assert by_slug[RISK_SLUG]["tier"] == "01"
    assert by_slug[HEALTH_SLUG]["tier"] == "00"


def test_index_json_404_without_wiki(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = TestClient(app).get("/api/runs/20260701/120000/wiki/index.json")
    assert r.status_code == 404


def test_page_json_renders_fragment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_wiki(tmp_path / "reports")
    r = TestClient(app).get(
        f"/api/runs/20260701/120000/wiki/{HEALTH_SLUG}.json")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Portfolio Health Dashboard"
    assert "<table>" in body["html"]          # markdown 'extra' tables render
    assert "<!DOCTYPE" not in body["html"]    # fragment, not a document


def test_page_json_404_for_missing_slug(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_wiki(tmp_path / "reports")
    r = TestClient(app).get("/api/runs/20260701/120000/wiki/nope.json")
    assert r.status_code == 404


def test_html_slug_route_still_wins_for_non_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_wiki(tmp_path / "reports")
    r = TestClient(app).get(f"/api/runs/20260701/120000/wiki/{HOME_SLUG}")
    assert r.status_code == 200
    assert r.text.startswith("<!DOCTYPE")


def test_runs_report_has_wiki(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_wiki(tmp_path / "reports")
    runs = TestClient(app).get("/api/runs").json()
    assert runs[0]["has_wiki"] is True


def test_tier_parser_handles_paths_and_collapsed_slugs():
    assert _wiki_page_tier(RISK) == "01"                       # real path
    assert _wiki_page_tier(RISK_SLUG) == "01"                  # collapsed slug
    assert _wiki_page_tier("g-03-data-quality-orphans") == "03"
    assert _wiki_page_tier(HOME) is None
    assert _wiki_page_tier(HOME_SLUG) is None


def test_upload_to_wiki_writes_manifest(tmp_path):
    class Harness(WikiMixin):
        pass

    h = Harness()
    h._wiki_save_dir = tmp_path
    group = MagicMock()

    h.upload_to_wiki(group, HEALTH, "# Portfolio Health Dashboard\n")
    h.upload_to_wiki(group, RISK, "# Risk Register\n")

    manifest = json.loads((tmp_path / "pages.json").read_text())
    assert manifest[HEALTH_SLUG] == HEALTH
    assert manifest[RISK_SLUG] == RISK
    assert (tmp_path / f"{HEALTH_SLUG}.md").is_file()
