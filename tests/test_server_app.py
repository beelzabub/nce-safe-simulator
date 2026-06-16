"""
REST API smoke tests for server/app.py.

Full WebSocket and job-streaming tests live in test_server_api.py (issue C).
These tests cover the three REST endpoints and the runner scaffolding.
"""
import threading

import pytest
from fastapi.testclient import TestClient

from mixins.reports import REPORTS
from mixins.tools import TOOLS
from server.app import app
from server.constraints import READONLY_TOOLS, _TOOL_GROUP
from server.runner import ThreadLocalWriter, install_writer, run_job


@pytest.fixture()
def client():
    app.state.gl = None
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/tools
# ---------------------------------------------------------------------------

def test_tools_returns_all_tools(client):
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == len(TOOLS)


def test_tools_keys_match_registry(client):
    resp = client.get("/api/tools")
    returned_keys = {t["key"] for t in resp.json()}
    expected_keys = {t["key"] for t in TOOLS}
    assert returned_keys == expected_keys


def test_tools_readonly_field(client):
    resp = client.get("/api/tools")
    for tool in resp.json():
        expected = tool["key"] in READONLY_TOOLS
        assert tool["readonly"] == expected, (
            f"tool '{tool['key']}': readonly={tool['readonly']}, expected {expected}"
        )


def test_tools_parallelism_group_field(client):
    resp = client.get("/api/tools")
    for tool in resp.json():
        expected_group = _TOOL_GROUP.get(tool["key"])
        assert tool["parallelism_group"] == expected_group


def test_tools_readonly_tools_have_null_group(client):
    resp = client.get("/api/tools")
    for tool in resp.json():
        if tool["readonly"]:
            assert tool["parallelism_group"] is None


# ---------------------------------------------------------------------------
# GET /api/reports
# ---------------------------------------------------------------------------

def test_reports_returns_all_reports(client):
    resp = client.get("/api/reports")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == len(REPORTS)


def test_reports_keys_match_registry(client):
    resp = client.get("/api/reports")
    returned_keys = {r["key"] for r in resp.json()}
    expected_keys = {r["key"] for r in REPORTS}
    assert returned_keys == expected_keys


def test_reports_all_readonly(client):
    resp = client.get("/api/reports")
    for report in resp.json():
        assert report["readonly"] is True
        assert report["parallelism_group"] is None


# ---------------------------------------------------------------------------
# POST /api/reports/fetch-data — no gl client wired
# ---------------------------------------------------------------------------

def test_fetch_data_503_when_no_gl(client):
    resp = client.post("/api/reports/fetch-data")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# ThreadLocalWriter
# ---------------------------------------------------------------------------

def test_thread_local_writer_routes_to_callback():
    captured = []
    writer = ThreadLocalWriter()

    def _run():
        import threading as _t
        _t.local  # access just to confirm threading available
        # Simulate what run_job does
        from server import runner as r
        r._thread_local.write_callback = captured.append
        writer.write("hello\n")
        r._thread_local.write_callback = None

    t = threading.Thread(target=_run)
    t.start()
    t.join()
    assert captured == ["hello"]


def test_thread_local_writer_main_thread_falls_back(capsys):
    import sys
    writer = ThreadLocalWriter(sys.__stdout__)
    # In the main thread there is no callback — should not raise
    writer.write("fallback")
    # No assertion on capsys here since __stdout__ bypasses capture;
    # the important thing is no exception is raised.


# ---------------------------------------------------------------------------
# run_job
# ---------------------------------------------------------------------------

def test_run_job_captures_output():
    captured = []

    def _job():
        print("line one")
        print("line two")

    install_writer()
    t = run_job(_job, captured.append)
    t.join(timeout=5)
    assert not t.is_alive()
    combined = "".join(captured)
    assert "line one" in combined
    assert "line two" in combined


def test_run_job_isolates_threads():
    results: dict[str, list] = {"a": [], "b": []}
    barrier = threading.Barrier(2)

    def _job_a():
        barrier.wait()
        print("from-a")

    def _job_b():
        barrier.wait()
        print("from-b")

    install_writer()
    ta = run_job(_job_a, results["a"].append)
    tb = run_job(_job_b, results["b"].append)
    ta.join(timeout=5)
    tb.join(timeout=5)

    assert any("from-a" in s for s in results["a"])
    assert any("from-b" in s for s in results["b"])
    assert not any("from-b" in s for s in results["a"])
    assert not any("from-a" in s for s in results["b"])
