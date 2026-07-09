"""
Integration tests for report/tool runs on the durable job engine (issue #219).

Report and tool runs launched from the UI are durable subprocess jobs:
``POST /api/jobs`` starts them, ``GET /api/jobs/{id}?offset=N`` tails/reattaches
the log, and ``POST /api/jobs/{id}/cancel`` is the only cancel path — a
disconnect never cancels anything. The retired ``/ws/run`` WebSocket and its
disconnect-kills-job behavior are gone; these tests exercise the surface that
replaced it.

To keep the suite hermetic, ``_job_argv`` is redirected to a harmless inline
Python command while still running through the *real* resolver first, so the
whitelist (unknown tool/report → 400) and the job label (which drives the
parallelism guard) are the production ones — only the process that finally runs
is a stand-in that never touches GitLab.
"""
import sys
import time

import pytest
from fastapi.testclient import TestClient

from server.jobs import JobManager, TERMINAL_STATES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _py(*code_lines) -> list:
    return [sys.executable, "-u", "-c", "\n".join(code_lines)]


def _wait_for(predicate, timeout=10.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _seed_running(mgr, label):
    """Write a manifest a job manager will treat as a live job of *label*, so
    the conflict guard sees it as running without spawning a real process."""
    mgr._write_manifest({
        "id": f"seed-{label}", "kind": "tool", "label": label, "params": {},
        "argv": [], "pid": 999999, "pgid": 999999, "state": "running",
        "started": "2000-01-01T00:00:00+00:00", "finished": None, "exit_code": None,
    })


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    """TestClient with the module job manager pointed at a tmp dir and the argv
    resolver redirected to a harmless command that prints and briefly lingers."""
    import server.app as appmod

    test_mgr = JobManager(jobs_dir=tmp_path / "jobs")
    monkeypatch.setattr(appmod, "job_manager", test_mgr)

    real_job_argv = appmod._job_argv

    def harmless_argv(data):
        # Real resolution: keeps production whitelisting + label, so unknown
        # keys still 400 and the conflict guard uses the true job key.
        kind, label, _argv = real_job_argv(data)
        return kind, label, _py(
            "import time",
            "print('ran the job', flush=True)",
            "time.sleep(0.3)",
        )

    monkeypatch.setattr(appmod, "_job_argv", harmless_argv)

    class _Gl:
        pass
    appmod.app.state.gl = _Gl()
    return TestClient(appmod.app), test_mgr


@pytest.fixture()
def app_client_no_gl(monkeypatch, tmp_path):
    import server.app as appmod
    monkeypatch.setattr(appmod, "job_manager", JobManager(jobs_dir=tmp_path / "jobs"))
    appmod.app.state.gl = None
    return TestClient(appmod.app)


# ---------------------------------------------------------------------------
# Launch + reattach (the core migration)
# ---------------------------------------------------------------------------

def test_tool_run_launches_and_tails(app_client):
    client, _ = app_client
    r = client.post("/api/jobs", json={"tool": "audit-hierarchy"})
    assert r.status_code == 201
    job = r.json()
    assert job["state"] == "running"
    assert job["kind"] == "tool" and job["label"] == "audit-hierarchy"

    assert _wait_for(lambda: client.get(f"/api/jobs/{job['id']}").json()["state"] == "done")
    tail = client.get(f"/api/jobs/{job['id']}", params={"offset": 0}).json()
    assert "ran the job" in tail["log"]


def test_report_run_launches_and_tails(app_client):
    client, _ = app_client
    job = client.post("/api/jobs", json={"report": "portfolio"}).json()
    assert job["kind"] == "report" and job["label"] == "portfolio"
    assert _wait_for(lambda: client.get(f"/api/jobs/{job['id']}").json()["state"] == "done")
    assert "ran the job" in client.get(f"/api/jobs/{job['id']}").json()["log"]


def test_multi_report_run_labels_by_count(app_client):
    client, _ = app_client
    job = client.post("/api/jobs", json={"reports": ["portfolio", "wsjf"]}).json()
    assert job["kind"] == "report"
    assert job["label"] == "reports (2)"


def test_launch_echoes_cli_command_as_first_log_lines(app_client):
    """The run record carries the exact reproducing command (issue #140),
    written to the log before the process starts."""
    client, _ = app_client
    job = client.post("/api/jobs", json={"report": "wsjf", "formats": ["markdown"]}).json()
    assert _wait_for(lambda: client.get(f"/api/jobs/{job['id']}").json()["state"] in TERMINAL_STATES)
    log = client.get(f"/api/jobs/{job['id']}").json()["log"]
    assert "$ python3 NceGitLab.py -r wsjf --formats markdown" in log


def test_reattach_from_a_fresh_client(app_client):
    """A completely fresh reader (as after a refresh or re-login) finds a live
    job in the list and tails its output — no socket, nothing lost."""
    client, _ = app_client
    job = client.post("/api/jobs", json={"tool": "audit-hierarchy"}).json()

    fresh = TestClient(client.app)
    ids = [j["id"] for j in fresh.get("/api/jobs").json()]
    assert job["id"] in ids
    assert _wait_for(lambda: "ran the job" in fresh.get(f"/api/jobs/{job['id']}").json()["log"])


# ---------------------------------------------------------------------------
# Error / validation
# ---------------------------------------------------------------------------

def test_unknown_tool_is_400(app_client):
    client, _ = app_client
    assert client.post("/api/jobs", json={"tool": "does-not-exist"}).status_code == 400


def test_unknown_report_is_400(app_client):
    client, _ = app_client
    assert client.post("/api/jobs", json={"report": "does-not-exist"}).status_code == 400


def test_empty_request_is_400(app_client):
    client, _ = app_client
    assert client.post("/api/jobs", json={}).status_code == 400


def test_no_gl_is_503(app_client_no_gl):
    assert app_client_no_gl.post("/api/jobs", json={"tool": "audit-hierarchy"}).status_code == 503


# ---------------------------------------------------------------------------
# Parallelism guard (the /ws/run conflict check, moved onto POST /api/jobs)
# ---------------------------------------------------------------------------

def test_conflicting_write_tool_is_409(app_client):
    client, mgr = app_client
    _seed_running(mgr, "set-lifecycle-labels")
    r = client.post("/api/jobs", json={"tool": "strip-lifecycle-labels"})
    assert r.status_code == 409
    assert "set-lifecycle-labels" in r.json()["detail"]["blocking"]


def test_conflict_names_all_blocking_jobs(app_client):
    client, mgr = app_client
    _seed_running(mgr, "set-lifecycle-labels")
    _seed_running(mgr, "set-piid-labels")
    r = client.post("/api/jobs", json={"tool": "strip-labels"})
    assert r.status_code == 409
    blocking = r.json()["detail"]["blocking"]
    assert "set-lifecycle-labels" in blocking
    assert "set-piid-labels" in blocking


def test_readonly_tool_not_blocked_by_writer(app_client):
    client, mgr = app_client
    _seed_running(mgr, "set-lifecycle-labels")
    assert client.post("/api/jobs", json={"tool": "audit-hierarchy"}).status_code == 201


def test_report_not_blocked_by_writer(app_client):
    client, mgr = app_client
    _seed_running(mgr, "set-lifecycle-labels")
    assert client.post("/api/jobs", json={"report": "portfolio"}).status_code == 201


# ---------------------------------------------------------------------------
# /api/running now reflects the durable engine
# ---------------------------------------------------------------------------

def test_running_endpoint_reflects_durable_jobs(app_client):
    client, mgr = app_client
    _seed_running(mgr, "set-lifecycle-labels")
    running = client.get("/api/running").json()
    keys = [r["key"] for r in running]
    assert "set-lifecycle-labels" in keys
    for r in running:
        assert "elapsed_seconds" in r


def test_running_endpoint_excludes_finished(app_client):
    client, _ = app_client
    job = client.post("/api/jobs", json={"tool": "audit-hierarchy"}).json()
    assert _wait_for(lambda: client.get(f"/api/jobs/{job['id']}").json()["state"] == "done")
    keys = [r["key"] for r in client.get("/api/running").json()]
    assert "audit-hierarchy" not in keys


# ---------------------------------------------------------------------------
# Explicit cancel is the only cancel path
# ---------------------------------------------------------------------------

def test_cancel_running_job(app_client, monkeypatch):
    client, _ = app_client
    import server.app as appmod
    real = appmod._job_argv   # the fixture's harmless resolver

    def slow(data):
        kind, label, _argv = real(data)
        return kind, label, _py("import time", "time.sleep(30)")   # something to cancel

    monkeypatch.setattr(appmod, "_job_argv", slow)
    job = client.post("/api/jobs", json={"tool": "audit-hierarchy"}).json()

    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
    assert _wait_for(
        lambda: client.get(f"/api/jobs/{job['id']}").json()["state"] == "cancelled",
        timeout=15,
    )


def test_cancel_unknown_job_is_404(app_client):
    client, _ = app_client
    assert client.post("/api/jobs/nope/cancel").status_code == 404
