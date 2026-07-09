"""Tests for the server-side auth gate (epic #135, issue #157).

auth.method "none" must preserve pre-gate behavior; "basic" must gate every
endpoint — including the durable job surface that report/tool runs use (#219) —
except the login page's own surface.
"""
import base64
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from server import auth_gate
from server.app import app


def _gl(method):
    return SimpleNamespace(auth={"method": method})


def _basic(username="asdf", password="asdf"):
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def clean_sessions():
    auth_gate._sessions.clear()
    yield
    auth_gate._sessions.clear()


@pytest.fixture()
def client_none():
    app.state.gl = _gl("none")
    return TestClient(app)


@pytest.fixture()
def client_basic():
    app.state.gl = _gl("basic")
    return TestClient(app)


# ---------------------------------------------------------------------------
# method "none" — today's behavior, nothing gated
# ---------------------------------------------------------------------------

def test_none_mode_leaves_api_open(client_none):
    assert client_none.get("/api/tools").status_code == 200


def test_none_mode_login_is_cosmetic(client_none):
    resp = client_none.post("/api/auth/login", json={"username": "x", "password": "y"})
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": True, "method": "none"}
    assert "set-cookie" not in resp.headers


def test_none_mode_session_reports_authenticated(client_none):
    assert client_none.get("/api/auth/session").json() == {
        "authenticated": True, "method": "none",
    }


# ---------------------------------------------------------------------------
# method "basic" — everything gated except the login surface
# ---------------------------------------------------------------------------

def test_basic_mode_rejects_unauthenticated_api(client_basic):
    resp = client_basic.get("/api/tools")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"].startswith("Basic")


@pytest.mark.parametrize("path", [
    "/api/reports", "/api/groups", "/api/config/full",
    "/api/download/foo.json", "/data/foo.json",
    "/reports/x", "/logs/x", "/quarto/x",
])
def test_basic_mode_gates_everything(client_basic, path):
    assert client_basic.get(path).status_code == 401


def test_basic_mode_accepts_basic_header(client_basic):
    assert client_basic.get("/api/tools", headers=_basic()).status_code == 200


def test_basic_mode_rejects_wrong_credentials(client_basic):
    assert client_basic.get("/api/tools", headers=_basic("asdf", "wrong")).status_code == 401
    assert client_basic.get("/api/tools", headers=_basic("admin", "asdf")).status_code == 401


def test_basic_mode_rejects_malformed_basic_header(client_basic):
    assert client_basic.get(
        "/api/tools", headers={"Authorization": "Basic not-base64!!"}
    ).status_code == 401


@pytest.mark.parametrize("path", [
    "/api/auth/backgrounds", "/api/config", "/api/auth/session",
])
def test_basic_mode_login_surface_stays_open(client_basic, path):
    assert client_basic.get(path).status_code == 200


def test_basic_mode_root_redirect_open(client_basic):
    resp = client_basic.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)


def test_basic_mode_app_shell_open(client_basic, tmp_path, monkeypatch):
    app_dir = tmp_path / "public" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "index.html").write_text("<html>shell</html>")
    monkeypatch.chdir(tmp_path)
    assert client_basic.get("/app/login").status_code == 200


# ---------------------------------------------------------------------------
# login / session / logout round trip
# ---------------------------------------------------------------------------

def test_login_session_logout_round_trip(client_basic):
    # wrong credentials rejected
    resp = client_basic.post("/api/auth/login", json={"username": "asdf", "password": "nope"})
    assert resp.status_code == 401

    # right credentials issue an HttpOnly Lax cookie
    resp = client_basic.post("/api/auth/login", json={"username": "asdf", "password": "asdf"})
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is True
    set_cookie = resp.headers["set-cookie"].lower()
    assert auth_gate.SESSION_COOKIE in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie

    # cookie authenticates protected endpoints and the session probe
    assert client_basic.get("/api/tools").status_code == 200
    assert client_basic.get("/api/auth/session").json()["authenticated"] is True

    # logout invalidates server-side and clears the cookie
    resp = client_basic.post("/api/auth/logout")
    assert resp.status_code == 200
    assert client_basic.get("/api/tools").status_code == 401
    assert client_basic.get("/api/auth/session").json()["authenticated"] is False


def test_logout_without_session_is_ok(client_basic):
    assert client_basic.post("/api/auth/logout").status_code == 200


def test_login_requires_json_body(client_basic):
    assert client_basic.post("/api/auth/login", content=b"not json").status_code == 400


def test_expired_session_rejected(client_basic):
    client_basic.post("/api/auth/login", json={"username": "asdf", "password": "asdf"})
    for token in list(auth_gate._sessions):
        auth_gate._sessions[token] = time.time() - 1
    assert client_basic.get("/api/tools").status_code == 401


# ---------------------------------------------------------------------------
# Durable job surface gate (report/tool runs, #219)
# ---------------------------------------------------------------------------
# An empty body 400s at request validation, so these assert only that the gate
# lets the request reach the handler (or blocks it), never launching anything.

def test_jobs_launch_rejected_without_auth(client_basic):
    assert client_basic.post("/api/jobs", json={}).status_code == 401


def test_jobs_launch_accepts_basic_header(client_basic):
    # Past the gate: the handler rejects the empty body (400), not the gate (401).
    resp = client_basic.post("/api/jobs", json={}, headers=_basic())
    assert resp.status_code != 401


def test_jobs_launch_open_in_none_mode(client_none):
    assert client_none.post("/api/jobs", json={}).status_code != 401
