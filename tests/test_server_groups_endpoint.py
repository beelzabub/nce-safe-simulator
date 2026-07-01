"""Tests for the read-only GET /api/groups endpoint (Refs #133).

The endpoint powers the web-UI group picker: it lists the groups discovered
under the configured parent_group via mixins/groups.py, and degrades to an
empty list (HTTP 200) whenever the GitLab client is absent or unreachable so
the frontend can fall back to free-text entry.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from server.app import app

pytestmark = pytest.mark.unit


def _group(full_path, name):
    return SimpleNamespace(full_path=full_path, name=name)


@pytest.fixture()
def client():
    yield TestClient(app)
    app.state.gl = None  # reset shared app state after each test


# ─── happy path: discovered groups under the namespace ─────────────────────────

def test_groups_returns_discovered_groups():
    gl = MagicMock()
    gl.parent_group = "Portfolio"
    root = _group("saic-study-group/portfolio", "Portfolio")
    gl.get_group_by_name.return_value = root
    gl.get_all_subgroups.return_value = [
        root,
        _group("saic-study-group/portfolio/team-a", "Team A"),
        _group("saic-study-group/portfolio/team-b", "Team B"),
    ]
    app.state.gl = gl

    resp = TestClient(app).get("/api/groups")
    assert resp.status_code == 200
    data = resp.json()
    assert data == [
        {"path": "saic-study-group/portfolio", "name": "Portfolio"},
        {"path": "saic-study-group/portfolio/team-a", "name": "Team A"},
        {"path": "saic-study-group/portfolio/team-b", "name": "Team B"},
    ]
    # scoped to the configured group via mixins/groups.py
    gl.get_group_by_name.assert_called_once_with("Portfolio")
    gl.get_all_subgroups.assert_called_once_with(root, include_self=True)
    app.state.gl = None


def test_groups_dedupes_repeated_paths():
    gl = MagicMock()
    gl.parent_group = "Portfolio"
    root = _group("ns/portfolio", "Portfolio")
    gl.get_group_by_name.return_value = root
    gl.get_all_subgroups.return_value = [root, root]  # include_self + traversal overlap
    app.state.gl = gl

    data = TestClient(app).get("/api/groups").json()
    assert data == [{"path": "ns/portfolio", "name": "Portfolio"}]
    app.state.gl = None


# ─── graceful degradation → [] (never 500) ─────────────────────────────────────

def test_groups_empty_when_client_absent(client):
    app.state.gl = None
    resp = client.get("/api/groups")
    assert resp.status_code == 200
    assert resp.json() == []


def test_groups_empty_when_no_parent_group():
    gl = MagicMock()
    gl.parent_group = ""
    app.state.gl = gl
    resp = TestClient(app).get("/api/groups")
    assert resp.status_code == 200
    assert resp.json() == []
    gl.get_group_by_name.assert_not_called()
    app.state.gl = None


def test_groups_empty_when_root_not_found():
    gl = MagicMock()
    gl.parent_group = "Missing"
    gl.get_group_by_name.return_value = None
    app.state.gl = gl
    resp = TestClient(app).get("/api/groups")
    assert resp.status_code == 200
    assert resp.json() == []
    gl.get_all_subgroups.assert_not_called()
    app.state.gl = None


def test_groups_empty_when_gitlab_unreachable():
    gl = MagicMock()
    gl.parent_group = "Portfolio"
    gl.get_group_by_name.side_effect = RuntimeError("gitlab unreachable")
    app.state.gl = gl
    resp = TestClient(app).get("/api/groups")
    assert resp.status_code == 200
    assert resp.json() == []
    app.state.gl = None
