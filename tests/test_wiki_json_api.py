"""Tests for the wiki JSON endpoints feeding the Reports tab (issue #167)."""

from fastapi.testclient import TestClient

from server.app import app, _wiki_page_tier


def _write_wiki(reports_dir, date="20260701", time="120000"):
    wiki = reports_dir / date / time / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "grp----portfolio-home.md").write_text(
        "# Portfolio Home\n\nindex\n")
    (wiki / "grp----portfolio-home--00-executive-pulse--portfolio-health-dashboard.md").write_text(
        "# Portfolio Health Dashboard\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    (wiki / "grp----portfolio-home--01-program-management--risk-register.md").write_text(
        "# Risk Register\n\nrisks\n")
    return wiki


def test_index_json_lists_pages_with_tiers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_wiki(tmp_path / "reports")
    r = TestClient(app).get("/api/runs/20260701/120000/wiki/index.json")
    assert r.status_code == 200
    pages = r.json()
    by_title = {p["title"]: p for p in pages}
    assert by_title["Portfolio Home"]["tier"] is None
    assert by_title["Portfolio Health Dashboard"]["tier"] == "00"
    assert by_title["Portfolio Health Dashboard"]["tier_name"] == "Executive Pulse"
    assert by_title["Risk Register"]["tier"] == "01"
    # Untiered index page first, then tier order.
    assert [p["title"] for p in pages] == [
        "Portfolio Home", "Portfolio Health Dashboard", "Risk Register"]


def test_index_json_404_without_wiki(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = TestClient(app).get("/api/runs/20260701/120000/wiki/index.json")
    assert r.status_code == 404


def test_page_json_renders_fragment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_wiki(tmp_path / "reports")
    slug = "grp----portfolio-home--00-executive-pulse--portfolio-health-dashboard"
    r = TestClient(app).get(f"/api/runs/20260701/120000/wiki/{slug}.json")
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
    r = TestClient(app).get(
        "/api/runs/20260701/120000/wiki/grp----portfolio-home")
    assert r.status_code == 200
    assert r.text.startswith("<!DOCTYPE")


def test_runs_report_has_wiki(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_wiki(tmp_path / "reports")
    runs = TestClient(app).get("/api/runs").json()
    assert runs[0]["has_wiki"] is True


def test_tier_parser():
    assert _wiki_page_tier("g--01-program-management--x") == "01"
    assert _wiki_page_tier("g--03-data-quality--orphans") == "03"
    assert _wiki_page_tier("g----portfolio-home") is None
