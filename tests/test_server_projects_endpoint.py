"""Tests for the read-only GET /api/projects endpoint (Refs #138).

Mirrors tests/test_server_groups_endpoint.py. The endpoint powers the web-UI
import-issues project picker: it lists the projects discovered under the
configured parent_group (root_group.projects.list, the same source as
_build_project_cache), and degrades to an empty list (HTTP 200) whenever the
GitLab client is absent or unreachable so the frontend can fall back to
free-text entry.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from server.app import app

pytestmark = pytest.mark.unit


def _project(path_with_namespace, name):
    return SimpleNamespace(path_with_namespace=path_with_namespace, name=name)


@pytest.fixture()
def client():
    yield TestClient(app)
    app.state.gl = None  # reset shared app state after each test


# ─── happy path: discovered projects under the namespace ───────────────────────

def test_projects_returns_discovered_projects():
    gl = MagicMock()
    gl.parent_group = "Portfolio"
    root = MagicMock()
    gl.get_group_by_name.return_value = root
    root.projects.list.return_value = [
        _project("saic-study-group/portfolio/team-a/backlog", "Backlog"),
        _project("saic-study-group/portfolio/team-b/backlog", "Backlog"),
    ]
    app.state.gl = gl

    resp = TestClient(app).get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert data == [
        {"path": "saic-study-group/portfolio/team-a/backlog", "name": "Backlog"},
        {"path": "saic-study-group/portfolio/team-b/backlog", "name": "Backlog"},
    ]
    # scoped to the configured group; include_subgroups so nested projects show
    gl.get_group_by_name.assert_called_once_with("Portfolio")
    root.projects.list.assert_called_once_with(all=True, include_subgroups=True)
    app.state.gl = None


def test_projects_dedupes_repeated_paths():
    gl = MagicMock()
    gl.parent_group = "Portfolio"
    root = MagicMock()
    gl.get_group_by_name.return_value = root
    p = _project("ns/portfolio/team/backlog", "Backlog")
    root.projects.list.return_value = [p, p]
    app.state.gl = gl

    data = TestClient(app).get("/api/projects").json()
    assert data == [{"path": "ns/portfolio/team/backlog", "name": "Backlog"}]
    app.state.gl = None


# ─── graceful degradation → [] (never 500) ─────────────────────────────────────

def test_projects_empty_when_client_absent(client):
    app.state.gl = None
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert resp.json() == []


def test_projects_empty_when_no_parent_group():
    gl = MagicMock()
    gl.parent_group = ""
    app.state.gl = gl
    resp = TestClient(app).get("/api/projects")
    assert resp.status_code == 200
    assert resp.json() == []
    gl.get_group_by_name.assert_not_called()
    app.state.gl = None


def test_projects_empty_when_root_not_found():
    gl = MagicMock()
    gl.parent_group = "Missing"
    gl.get_group_by_name.return_value = None
    app.state.gl = gl
    resp = TestClient(app).get("/api/projects")
    assert resp.status_code == 200
    assert resp.json() == []
    app.state.gl = None


def test_projects_empty_when_gitlab_unreachable():
    gl = MagicMock()
    gl.parent_group = "Portfolio"
    gl.get_group_by_name.side_effect = RuntimeError("gitlab unreachable")
    app.state.gl = gl
    resp = TestClient(app).get("/api/projects")
    assert resp.status_code == 200
    assert resp.json() == []
    app.state.gl = None
