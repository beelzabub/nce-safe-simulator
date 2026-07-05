"""Tests for transient-5xx retry on the shared REST session (issue #176).

A single passing 502 from gitlab.com aborted a whole report run minutes into
the snapshot fetch. The session adapter now retries transient 5xx (matching
python-gitlab's retry_transient_errors set) for idempotent methods only —
mutation POSTs keep fail-fast semantics.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

from mixins.utils import _TimeoutAdapter


class _FlakyHandler(BaseHTTPRequestHandler):
    """Serves scripted status sequences per path, tracking hit counts."""

    hits = {}
    script = {}   # path -> [status, status, ...]; last repeats forever

    def _serve(self):
        path = self.path
        n = _FlakyHandler.hits.get(path, 0)
        _FlakyHandler.hits[path] = n + 1
        seq = _FlakyHandler.script.get(path, [200])
        status = seq[min(n, len(seq) - 1)]
        self.send_response(status)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    do_GET = _serve
    do_POST = _serve

    def log_message(self, *args):
        pass


@pytest.fixture()
def flaky_server():
    _FlakyHandler.hits = {}
    _FlakyHandler.script = {}
    server = HTTPServer(("127.0.0.1", 0), _FlakyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", _FlakyHandler
    server.shutdown()


def _session():
    sess = requests.Session()
    adapter = _TimeoutAdapter(timeout=10)
    # backoff_factor=0 keeps the test instant while preserving retry counts.
    adapter.max_retries = adapter.max_retries.new(backoff_factor=0)
    sess.mount("http://", adapter)
    return sess


def test_get_survives_transient_502(flaky_server):
    base, handler = flaky_server
    handler.script["/a"] = [502, 502, 200]
    resp = _session().get(f"{base}/a")
    assert resp.status_code == 200
    assert handler.hits["/a"] == 3


def test_get_survives_503_and_504(flaky_server):
    base, handler = flaky_server
    handler.script["/b"] = [503, 504, 200]
    assert _session().get(f"{base}/b").status_code == 200


def test_get_gives_up_after_retry_budget(flaky_server):
    base, handler = flaky_server
    handler.script["/c"] = [502]          # 502 forever
    resp = _session().get(f"{base}/c")
    assert resp.status_code == 502        # raise_on_status=False: returned, not raised
    assert handler.hits["/c"] == 6        # 1 try + 5 retries


def test_post_is_not_retried_on_502(flaky_server):
    # Mutations must keep fail-fast semantics — only idempotent methods retry.
    base, handler = flaky_server
    handler.script["/d"] = [502, 200]
    resp = _session().post(f"{base}/d")
    assert resp.status_code == 502
    assert handler.hits["/d"] == 1


def test_429_still_retries(flaky_server):
    base, handler = flaky_server
    handler.script["/e"] = [429, 200]
    resp = _session().get(f"{base}/e")
    assert resp.status_code == 200
    assert handler.hits["/e"] == 2


def test_gitlab_client_retries_transient_errors():
    # The python-gitlab path (which the observed 502 killed) must be
    # constructed with retry_transient_errors=True (Refs #176).
    import pathlib
    src = pathlib.Path("NceGitLab.py").read_text()
    assert "retry_transient_errors=True" in src
