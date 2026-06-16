"""
WebSocket integration tests for the /ws/run endpoint.

REST endpoint smoke tests live in test_server_app.py (issue B).
"""
import threading

import pytest
from fastapi.testclient import TestClient

from server.app import app, _running_jobs
from server.runner import install_writer


# ---------------------------------------------------------------------------
# Mock GitLab client
# ---------------------------------------------------------------------------

class MockGl:
    parent_group = "test-group"
    EPIC_TYPE_LABELS        = ["Epic", "Capability", "Feature"]
    EPIC_TYPE_DISPLAY_NAMES = ["Epic", "Capability", "Feature"]

    def _tool_audit_hierarchy(self):
        print("audit line 1")
        print("audit line 2")

    def _tool_audit_labels(self):
        print("labels ok")

    def _tool_set_lifecycle_labels(
        self, percent=20.0, reassign=False, open_only=False, dry_run=False
    ):
        self._lifecycle_started.set()
        self._lifecycle_gate.wait(timeout=10)
        print("lifecycle labels set")

    def _run_reports(self, reports, reuse_data=None, formats=None):
        for r in reports:
            print(f"report:{r['key']}")

    def reload_config(self):
        pass

    # Per-instance events wired in fixture
    _lifecycle_started: threading.Event
    _lifecycle_gate: threading.Event


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_state():
    """Clear running jobs and reinstall the thread-local writer before each test."""
    _running_jobs.clear()
    install_writer()
    yield
    _running_jobs.clear()


@pytest.fixture()
def gl():
    mock = MockGl()
    mock._lifecycle_started = threading.Event()
    mock._lifecycle_gate    = threading.Event()
    return mock


@pytest.fixture()
def client(gl):
    app.state.gl = gl
    return TestClient(app)


@pytest.fixture()
def client_no_gl():
    app.state.gl = None
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def collect(ws) -> list:
    """Collect WebSocket messages until a terminal one (done/error/conflict)."""
    msgs = []
    while True:
        msg = ws.receive_json()
        msgs.append(msg)
        if msg["type"] in ("done", "error", "conflict"):
            break
    return msgs


def log_text(msgs: list) -> str:
    return "".join(m["text"] for m in msgs if m["type"] == "log")


# ---------------------------------------------------------------------------
# Successful tool run
# ---------------------------------------------------------------------------

def test_tool_run_streams_log_lines(client):
    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"tool": "audit-hierarchy"})
        msgs = collect(ws)

    assert any(m["type"] == "done" for m in msgs)
    text = log_text(msgs)
    assert "audit line 1" in text
    assert "audit line 2" in text


def test_tool_run_final_message_is_done(client):
    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"tool": "audit-hierarchy"})
        msgs = collect(ws)

    assert msgs[-1]["type"] == "done"


# ---------------------------------------------------------------------------
# Successful report run
# ---------------------------------------------------------------------------

def test_report_run_streams_log_lines(client):
    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"report": "portfolio"})
        msgs = collect(ws)

    assert any(m["type"] == "done" for m in msgs)
    assert "portfolio" in log_text(msgs)


def test_report_run_final_message_is_done(client):
    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"report": "wsjf"})
        msgs = collect(ws)

    assert msgs[-1]["type"] == "done"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_unknown_tool_returns_error(client):
    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"tool": "does-not-exist"})
        msgs = collect(ws)

    assert any(m["type"] == "error" for m in msgs)


def test_unknown_report_returns_error(client):
    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"report": "does-not-exist"})
        msgs = collect(ws)

    assert any(m["type"] == "error" for m in msgs)


def test_empty_message_returns_error(client):
    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({})
        msgs = collect(ws)

    assert any(m["type"] == "error" for m in msgs)


def test_no_gl_returns_error(client_no_gl):
    with client_no_gl.websocket_connect("/ws/run") as ws:
        ws.send_json({"tool": "audit-hierarchy"})
        msgs = collect(ws)

    assert any(m["type"] == "error" for m in msgs)


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def test_conflicting_job_returns_conflict_response(client):
    _running_jobs.add("set-lifecycle-labels")

    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"tool": "strip-lifecycle-labels"})
        msgs = collect(ws)

    conflict = next((m for m in msgs if m["type"] == "conflict"), None)
    assert conflict is not None
    assert "set-lifecycle-labels" in conflict["blocking"]


def test_conflict_names_all_blocking_jobs(client):
    _running_jobs.add("set-lifecycle-labels")
    _running_jobs.add("set-piid-labels")

    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"tool": "strip-labels"})
        msgs = collect(ws)

    conflict = next(m for m in msgs if m["type"] == "conflict")
    assert "set-lifecycle-labels" in conflict["blocking"]
    assert "set-piid-labels" in conflict["blocking"]


def test_readonly_tool_runs_alongside_writer(client):
    _running_jobs.add("set-lifecycle-labels")

    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"tool": "audit-hierarchy"})
        msgs = collect(ws)

    assert not any(m["type"] == "conflict" for m in msgs)
    assert any(m["type"] == "done" for m in msgs)


def test_report_runs_alongside_writer(client):
    _running_jobs.add("set-lifecycle-labels")

    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"report": "portfolio"})
        msgs = collect(ws)

    assert not any(m["type"] == "conflict" for m in msgs)
    assert any(m["type"] == "done" for m in msgs)


def test_two_reports_no_conflict(client):
    _running_jobs.add("portfolio")   # simulate another report running

    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"report": "wsjf"})
        msgs = collect(ws)

    assert not any(m["type"] == "conflict" for m in msgs)
    assert any(m["type"] == "done" for m in msgs)


# ---------------------------------------------------------------------------
# Running-jobs registry lifecycle
# ---------------------------------------------------------------------------

def test_job_key_added_while_running_and_removed_on_done(client, gl):
    """Job key is in _running_jobs during execution and removed afterward."""
    observed_during: list = []
    original_fn = gl._tool_audit_hierarchy

    def _spy():
        observed_during.append("audit-hierarchy" in _running_jobs)
        original_fn()

    gl._tool_audit_hierarchy = _spy

    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"tool": "audit-hierarchy"})
        collect(ws)

    assert any(observed_during), "job key was never in _running_jobs during execution"
    assert "audit-hierarchy" not in _running_jobs


def test_job_key_removed_after_error(client):
    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"tool": "does-not-exist"})
        collect(ws)

    assert "does-not-exist" not in _running_jobs


# ---------------------------------------------------------------------------
# Concurrent isolation — two jobs do not interleave output
# ---------------------------------------------------------------------------

def test_concurrent_readonly_jobs_do_not_interleave(client, gl):
    """Two read-only tools run simultaneously; each WebSocket gets only its own output."""
    results: dict = {"a": [], "b": []}
    barrier = threading.Barrier(2)

    original_audit = gl._tool_audit_hierarchy
    original_labels = gl._tool_audit_labels

    def _slow_audit():
        barrier.wait()
        print("output-from-audit-hierarchy")

    def _slow_labels():
        barrier.wait()
        print("output-from-audit-labels")

    gl._tool_audit_hierarchy = _slow_audit
    gl._tool_audit_labels    = _slow_labels

    def _run_a():
        with client.websocket_connect("/ws/run") as ws:
            ws.send_json({"tool": "audit-hierarchy"})
            results["a"] = collect(ws)

    def _run_b():
        with client.websocket_connect("/ws/run") as ws:
            ws.send_json({"tool": "audit-labels"})
            results["b"] = collect(ws)

    ta = threading.Thread(target=_run_a)
    tb = threading.Thread(target=_run_b)
    ta.start()
    tb.start()
    ta.join(timeout=10)
    tb.join(timeout=10)

    text_a = log_text(results["a"])
    text_b = log_text(results["b"])

    assert "output-from-audit-hierarchy" in text_a
    assert "output-from-audit-labels"    in text_b
    assert "output-from-audit-labels"    not in text_a
    assert "output-from-audit-hierarchy" not in text_b
