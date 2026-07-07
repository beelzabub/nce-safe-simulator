"""Tests for transient-5xx retry on the shared REST session (issues #176, #207).

A single passing 502 from gitlab.com aborted a whole report run minutes into
the snapshot fetch (#176). The session adapter retries transient 5xx (matching
python-gitlab's retry_transient_errors set) for idempotent methods only —
mutation POSTs keep fail-fast semantics. The python-gitlab client itself must
follow the same policy: its own retry_transient_errors re-POSTs creates whose
response was lost, silently duplicating objects on the target (#207).
"""

import threading
import time
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
        if path == "/slow":
            time.sleep(1)
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


def test_retry_policy_excludes_mutation_methods():
    # The retry policy must never re-send a POST: a create whose response was
    # lost would be silently duplicated on the target (Refs #207).
    retry = _TimeoutAdapter(timeout=1).max_retries
    assert "POST" not in retry.allowed_methods
    assert "GET" in retry.allowed_methods


def test_429_retry_is_announced(flaky_server, capsys):
    # Retried responses never reach the requests hook layer, so the backoff
    # visibility (#201) must come from inside the retry machinery.
    base, handler = flaky_server
    handler.script["/f"] = [429, 200]
    assert _session().get(f"{base}/f").status_code == 200
    assert "rate limit hit (429)" in capsys.readouterr().out


def test_5xx_retries_are_announced(flaky_server, capsys):
    base, handler = flaky_server
    handler.script["/g"] = [502, 502, 200]
    assert _session().get(f"{base}/g").status_code == 200
    assert capsys.readouterr().out.count("transient error (502)") == 2


def test_post_429_reaches_the_visibility_hook(flaky_server, capsys):
    # urllib3 never retries POSTs, so a mutation's 429 surfaces at the
    # requests layer, where the hook announces the backoff that python-gitlab's
    # obey_rate_limit is about to sleep through silently (Refs #201, #207).
    from mixins.utils import UtilitiesMixin
    base, handler = flaky_server
    handler.script["/h"] = [429]
    sess = _session()
    sess.hooks.setdefault("response", []).append(UtilitiesMixin._rate_limit_hook)
    resp = sess.post(f"{base}/h")
    assert resp.status_code == 429
    assert handler.hits["/h"] == 1                      # no HTTP-layer re-POST
    assert "rate limit hit (429)" in capsys.readouterr().out


def test_default_timeout_is_enforced(flaky_server):
    # Session.request always passes timeout= explicitly (None when unset), so
    # the adapter must not rely on setdefault to apply its default.
    base, _ = flaky_server
    sess = requests.Session()
    adapter = _TimeoutAdapter(timeout=0.2)
    # read=False: surface the first timeout instead of retrying it away.
    adapter.max_retries = adapter.max_retries.new(read=False)
    sess.mount("http://", adapter)
    with pytest.raises(requests.exceptions.ReadTimeout):
        sess.get(f"{base}/slow")


def test_gitlab_client_does_not_retry_mutations():
    # python-gitlab's retry_transient_errors covers ALL methods including the
    # POST behind .create() — it must stay off; the mounted _TimeoutAdapter
    # provides idempotent-only retries instead, and the response hook keeps
    # obey_rate_limit's 429 backoff visible (Refs #207).
    import pathlib
    src = pathlib.Path("NceGitLab.py").read_text()
    assert "retry_transient_errors=False" in src
    assert "retry_transient_errors=True" not in src
    assert 'self.gl.session.mount("https://", adapter)' in src
    assert "self._rate_limit_hook" in src
