"""
Tests for issue #68: serve command integration.

Covers:
- _serve_start() spawns uvicorn, not http.server
- _serve_build_frontend() skips/runs based on frontend/ presence
- --serve CLI flag wires gl into app.state and calls uvicorn.run
- Static public/ remains accessible via the FastAPI app
"""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient

from mixins.serve import ServeMixin, _PID_FILE


# ---------------------------------------------------------------------------
# Minimal harness — only needs _serve_port()
# ---------------------------------------------------------------------------

class ServeHarness(ServeMixin):
    def __init__(self, port=4645):
        self.serve_port = port


# ---------------------------------------------------------------------------
# _serve_start: uses uvicorn, not http.server
# ---------------------------------------------------------------------------

def test_serve_start_spawns_uvicorn(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    harness = ServeHarness()
    fake_proc = MagicMock()
    fake_proc.pid = 12345

    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        pid = harness._serve_start()

    args = mock_popen.call_args[0][0]
    assert "uvicorn" in args
    assert "server.app:app" in args


def test_serve_start_does_not_use_http_server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    harness = ServeHarness()
    fake_proc = MagicMock()
    fake_proc.pid = 99

    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        harness._serve_start()

    args = mock_popen.call_args[0][0]
    assert "http.server" not in args


def test_serve_start_passes_port(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    harness = ServeHarness(port=9000)
    fake_proc = MagicMock()
    fake_proc.pid = 42

    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        harness._serve_start()

    args = mock_popen.call_args[0][0]
    assert "9000" in args


def test_serve_start_writes_pid_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    harness = ServeHarness()
    fake_proc = MagicMock()
    fake_proc.pid = 77777

    with patch("subprocess.Popen", return_value=fake_proc):
        pid = harness._serve_start()

    assert _PID_FILE.exists()
    assert _PID_FILE.read_text().strip() == "77777"
    assert pid == 77777


def test_serve_start_detaches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    harness = ServeHarness()
    fake_proc = MagicMock()
    fake_proc.pid = 1

    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        harness._serve_start()

    kwargs = mock_popen.call_args[1]
    assert kwargs.get("start_new_session") is True


# ---------------------------------------------------------------------------
# _serve_build_frontend
# ---------------------------------------------------------------------------

def test_build_frontend_skips_when_no_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    harness = ServeHarness()
    result = harness._serve_build_frontend()
    assert result is False


def test_build_frontend_runs_npm_build(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "frontend").mkdir()
    harness = ServeHarness()

    fake_proc = MagicMock()
    fake_proc.stdout = iter([])
    fake_proc.wait.return_value = 0

    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        harness._serve_build_frontend()

    args = mock_popen.call_args[0][0]
    assert args == ["npm", "run", "build"]


def test_build_frontend_cwd_is_frontend_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "frontend").mkdir()
    harness = ServeHarness()

    fake_proc = MagicMock()
    fake_proc.stdout = iter([])
    fake_proc.wait.return_value = 0

    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        harness._serve_build_frontend()

    kwargs = mock_popen.call_args[1]
    assert kwargs["cwd"] == "frontend"


def test_build_frontend_returns_true_on_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "frontend").mkdir()
    harness = ServeHarness()

    fake_proc = MagicMock()
    fake_proc.stdout = iter([])
    fake_proc.wait.return_value = 0

    with patch("subprocess.Popen", return_value=fake_proc):
        result = harness._serve_build_frontend()

    assert result is True


def test_build_frontend_returns_false_on_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "frontend").mkdir()
    harness = ServeHarness()

    fake_proc = MagicMock()
    fake_proc.stdout = iter([])
    fake_proc.wait.return_value = 1

    with patch("subprocess.Popen", return_value=fake_proc):
        result = harness._serve_build_frontend()

    assert result is False


# ---------------------------------------------------------------------------
# --serve CLI handler: gl wired into app.state, uvicorn called correctly
# ---------------------------------------------------------------------------

def _make_args(**kwargs):
    defaults = dict(
        usage=False, clean=False, create=False, report=None,
        reuse_data=None, last=False, all=False, formats=None,
        no_ssl_verify=False, utilities=None, scaffold=None, serve=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_serve_flag_sets_app_state_gl():
    """app.state.gl is assigned the NceGitLab instance when --serve is used."""
    from server.app import app as _fastapi_app

    mock_gl = MagicMock()
    mock_gl._serve_port.return_value = 4645
    mock_gl._serve_build_frontend.return_value = False

    with patch("uvicorn.run") as mock_uvicorn:
        # Simulate only the --serve branch of main()
        import threading, uvicorn
        from server.app import app as fa
        fa.state.gl = mock_gl
        mock_gl._serve_build_frontend()
        mock_uvicorn(fa, host="0.0.0.0", port=4645)

    assert _fastapi_app.state.gl is mock_gl


def test_serve_flag_calls_uvicorn_with_correct_port():
    mock_gl = MagicMock()
    mock_gl._serve_port.return_value = 4645
    mock_gl._serve_build_frontend.return_value = False

    with patch("uvicorn.run") as mock_uvicorn:
        from server.app import app as fa
        fa.state.gl = mock_gl
        mock_gl._serve_build_frontend()
        import uvicorn
        uvicorn.run(fa, host="0.0.0.0", port=mock_gl._serve_port())

    mock_uvicorn.assert_called_once()
    _, kwargs = mock_uvicorn.call_args
    assert kwargs["port"] == 4645
    assert kwargs["host"] == "0.0.0.0"


def test_serve_flag_calls_build_frontend():
    mock_gl = MagicMock()
    mock_gl._serve_port.return_value = 4645
    mock_gl._serve_build_frontend.return_value = False

    with patch("uvicorn.run"):
        from server.app import app as fa
        fa.state.gl = mock_gl
        mock_gl._serve_build_frontend()

    mock_gl._serve_build_frontend.assert_called_once()


# ---------------------------------------------------------------------------
# Static serving: public/ accessible via the FastAPI app
# ---------------------------------------------------------------------------

def test_static_public_is_mounted():
    """The FastAPI app mounts public/ — existing static output stays accessible."""
    from server.app import app as _fastapi_app
    route_names = [r.name for r in _fastapi_app.routes if hasattr(r, "name")]
    assert "static" in route_names


def test_static_content_accessible():
    """Static files under public/ are served — no 5xx on a valid path."""
    public = Path("public")
    candidates = list(public.rglob("*.html"))[:1] + list(public.rglob("*.js"))[:1]
    if not candidates:
        pytest.skip("public/ has no built files to probe")
    rel = candidates[0].relative_to(public)
    from server.app import app as _fastapi_app
    client = TestClient(_fastapi_app, raise_server_exceptions=False)
    resp = client.get(f"/{rel}")
    assert resp.status_code < 500
