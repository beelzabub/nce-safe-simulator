"""Tests for the /app SPA history fallback (epic #135).

Hard loads of client-side routes (e.g. /app/login) must serve the built app
shell; real built files still win; nothing outside public/app is reachable.
"""
import pytest
from fastapi.testclient import TestClient

from server.app import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    app_dir = tmp_path / "public" / "app"
    (app_dir / "assets").mkdir(parents=True)
    (app_dir / "index.html").write_text("<html>shell</html>")
    (app_dir / "assets" / "main.js").write_text("console.log('built')")
    (tmp_path / "secret.txt").write_text("nope")
    monkeypatch.chdir(tmp_path)
    app.state.gl = None
    return TestClient(app)


def test_client_route_serves_app_shell(client):
    resp = client.get("/app/login")
    assert resp.status_code == 200
    assert resp.text == "<html>shell</html>"


def test_app_root_serves_shell(client):
    assert client.get("/app/").text == "<html>shell</html>"


def test_real_built_file_wins(client):
    resp = client.get("/app/assets/main.js")
    assert resp.status_code == 200
    assert resp.text == "console.log('built')"


def test_traversal_gets_shell_not_files_outside_app_dir(client):
    # Resolved path escapes public/app -> not served as a file; the SPA shell
    # is returned instead (the client router will show its own 404 state).
    resp = client.get("/app/%2e%2e/%2e%2e/secret.txt")
    assert resp.status_code == 200
    assert "nope" not in resp.text


def test_404_when_frontend_not_built(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path / "public")  # cwd without a public/app below it
    assert client.get("/app/login").status_code == 404
