"""Durable background job engine (issue #214).

The engine tests drive a JobManager against a tmp directory using trivial
Python subprocesses, so they exercise the real process/manifest/log machinery
without any GitLab or network dependency. The endpoint tests drive the FastAPI
surface with a JobManager and argv resolver redirected to harmless commands.
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
    """argv running an inline python program (unbuffered so log tails are prompt)."""
    return [sys.executable, "-u", "-c", "\n".join(code_lines)]


def _wait_for(predicate, timeout=10.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture()
def mgr(tmp_path):
    return JobManager(jobs_dir=tmp_path / "jobs")


# ---------------------------------------------------------------------------
# Lifecycle + manifest
# ---------------------------------------------------------------------------

def test_launch_writes_manifest_and_runs(mgr):
    m = mgr.launch(_py("print('hello world')"), kind="test", label="greeter")
    assert m["state"] == "running"
    assert m["kind"] == "test"
    assert m["label"] == "greeter"
    assert m["pid"] and m["pgid"]
    assert m["finished"] is None and m["exit_code"] is None

    assert _wait_for(lambda: mgr._read_manifest(m["id"])["state"] == "done")
    done = mgr._read_manifest(m["id"])
    assert done["exit_code"] == 0
    assert done["finished"] is not None


def test_nonzero_exit_marks_error(mgr):
    m = mgr.launch(_py("import sys; sys.exit(3)"), kind="test")
    assert _wait_for(lambda: mgr._read_manifest(m["id"])["state"] in TERMINAL_STATES)
    done = mgr._read_manifest(m["id"])
    assert done["state"] == "error"
    assert done["exit_code"] == 3


def test_failed_to_start_is_error(mgr):
    m = mgr.launch(["/no/such/program/at/all"], kind="test")
    assert m["state"] == "error"
    assert m["pid"] is None


def test_log_captures_stdout_and_stderr(mgr):
    m = mgr.launch(
        _py("import sys",
            "print('to stdout')",
            "print('to stderr', file=sys.stderr)"),
        kind="test",
    )
    assert _wait_for(lambda: mgr._read_manifest(m["id"])["state"] == "done")
    job = mgr.get_job(m["id"])
    assert "to stdout" in job["log"]
    assert "to stderr" in job["log"]


# ---------------------------------------------------------------------------
# Log tail by byte offset (the reattach primitive)
# ---------------------------------------------------------------------------

def test_get_job_tails_from_offset(mgr):
    m = mgr.launch(
        _py("import time",
            "print('line-one', flush=True)",
            "time.sleep(0.4)",
            "print('line-two', flush=True)",
            "time.sleep(0.4)"),
        kind="test",
    )
    # First read grabs line-one and returns a non-zero offset.
    assert _wait_for(lambda: "line-one" in mgr.get_job(m["id"])["log"])
    first = mgr.get_job(m["id"], offset=0)
    off = first["offset"]
    assert off > 0
    assert "line-one" in first["log"]

    # A read from that offset must not repeat line-one, and eventually sees line-two.
    assert _wait_for(lambda: "line-two" in mgr.get_job(m["id"], offset=off)["log"])
    second = mgr.get_job(m["id"], offset=off)
    assert "line-one" not in second["log"]
    assert "line-two" in second["log"]

    assert _wait_for(lambda: mgr._read_manifest(m["id"])["state"] == "done")


def test_get_job_unknown_returns_none(mgr):
    assert mgr.get_job("nope-does-not-exist") is None


def test_offset_past_eof_returns_empty(mgr):
    m = mgr.launch(_py("print('x')"), kind="test")
    assert _wait_for(lambda: mgr._read_manifest(m["id"])["state"] == "done")
    size = mgr.get_job(m["id"])["offset"]
    tail = mgr.get_job(m["id"], offset=size)
    assert tail["log"] == ""
    assert tail["offset"] == size


# ---------------------------------------------------------------------------
# Cancel — explicit, via process-group signal
# ---------------------------------------------------------------------------

def test_cancel_running_job(mgr):
    m = mgr.launch(_py("import time", "time.sleep(30)"), kind="test")
    assert _wait_for(lambda: mgr._pid_alive(m["pid"]))
    returned = mgr.cancel(m["id"])
    assert returned is not None
    assert _wait_for(lambda: mgr._read_manifest(m["id"])["state"] == "cancelled", timeout=15)
    assert not mgr._pid_alive(m["pid"])


def test_cancel_signals_whole_group(mgr):
    # Parent spawns a child that ignores SIGTERM's default only via sleep; both
    # share the session/group, so killpg reaches the child too.
    m = mgr.launch(
        _py("import subprocess, sys, time",
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])",
            "time.sleep(30)"),
        kind="test",
    )
    assert _wait_for(lambda: mgr._pid_alive(m["pid"]))
    mgr.cancel(m["id"])
    assert _wait_for(lambda: mgr._read_manifest(m["id"])["state"] == "cancelled", timeout=15)
    assert not mgr._pid_alive(m["pid"])


def test_cancel_unknown_job_returns_none(mgr):
    assert mgr.cancel("does-not-exist") is None


def test_cancel_finished_job_is_noop(mgr):
    m = mgr.launch(_py("print('done')"), kind="test")
    assert _wait_for(lambda: mgr._read_manifest(m["id"])["state"] == "done")
    result = mgr.cancel(m["id"])
    assert result["state"] == "done"  # unchanged


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

def test_list_jobs_newest_first(mgr):
    a = mgr.launch(_py("print('a')"), kind="test", label="a")
    time.sleep(0.05)
    b = mgr.launch(_py("print('b')"), kind="test", label="b")
    assert _wait_for(lambda: all(
        mgr._read_manifest(x["id"])["state"] == "done" for x in (a, b)
    ))
    ids = [j["id"] for j in mgr.list_jobs()]
    assert ids.index(b["id"]) < ids.index(a["id"])


# ---------------------------------------------------------------------------
# Startup reconciliation
# ---------------------------------------------------------------------------

def test_reconcile_marks_dead_running_job_unknown(mgr):
    # Simulate a manifest a prior server left "running" for a pid that's gone.
    mgr._write_manifest({
        "id": "ghost", "kind": "test", "label": "ghost", "params": {},
        "argv": [], "pid": 999999, "pgid": 999999, "state": "running",
        "started": "2000-01-01T00:00:00+00:00", "finished": None, "exit_code": None,
    })
    changed = mgr.reconcile()
    assert "ghost" in changed
    assert mgr._read_manifest("ghost")["state"] == "unknown"


def test_reconcile_leaves_terminal_jobs_untouched(mgr):
    mgr._write_manifest({
        "id": "old", "kind": "test", "label": "old", "params": {},
        "argv": [], "pid": 999999, "pgid": 999999, "state": "done",
        "started": "2000-01-01T00:00:00+00:00",
        "finished": "2000-01-01T00:00:01+00:00", "exit_code": 0,
    })
    assert mgr.reconcile() == []
    assert mgr._read_manifest("old")["state"] == "done"


def test_reconcile_readopts_live_job(mgr, tmp_path):
    # A job still alive across a "restart": a fresh manager (empty _procs) must
    # re-adopt it and record a terminal state when it exits.
    running = mgr.launch(_py("import time", "time.sleep(1.0)"), kind="test")
    assert _wait_for(lambda: mgr._pid_alive(running["pid"]))

    fresh = JobManager(jobs_dir=tmp_path / "jobs")   # same dir, no _procs
    changed = fresh.reconcile()
    assert running["id"] not in changed   # still alive → not marked yet
    # When the process exits, the re-adoption watcher records a terminal state.
    assert _wait_for(
        lambda: fresh._read_manifest(running["id"])["state"] in TERMINAL_STATES,
        timeout=15,
    )


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def test_prune_removes_old_terminal_jobs_only(mgr):
    import os

    m = mgr.launch(_py("print('x')"), kind="test")
    assert _wait_for(lambda: mgr._read_manifest(m["id"])["state"] == "done")

    # 0 disables pruning; a huge TTL keeps everything fresh.
    assert mgr.prune(0) == []
    assert mgr.prune(10_000) == []

    # Backdate the manifest well past a 1s TTL, then it should be pruned.
    old = time.time() - 3600
    os.utime(mgr._manifest_path(m["id"]), (old, old))
    assert m["id"] in mgr.prune(1)
    assert mgr._read_manifest(m["id"]) is None


def test_prune_keeps_running_jobs(mgr):
    import os

    m = mgr.launch(_py("import time", "time.sleep(30)"), kind="test")
    assert _wait_for(lambda: mgr._pid_alive(m["pid"]))
    old = time.time() - 3600
    os.utime(mgr._manifest_path(m["id"]), (old, old))
    assert mgr.prune(1) == []          # never prune a live job
    assert mgr._read_manifest(m["id"])["state"] == "running"
    mgr.cancel(m["id"])


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    """TestClient with the module job_manager and argv resolver redirected to a
    harmless echo command, so POST /api/jobs spawns nothing that touches GitLab."""
    import server.app as appmod

    test_mgr = JobManager(jobs_dir=tmp_path / "jobs")
    monkeypatch.setattr(appmod, "job_manager", test_mgr)

    def _fake_argv(data):
        if data.get("tool") == "boom":
            raise ValueError("Unknown tool: 'boom'")
        return "test", "noop", _py("print('job ran')")

    monkeypatch.setattr(appmod, "_job_argv", _fake_argv)

    class _Gl:
        pass
    appmod.app.state.gl = _Gl()
    return TestClient(appmod.app), test_mgr


def test_post_launches_and_get_reattaches(app_client):
    client, mgr = app_client
    r = client.post("/api/jobs", json={"tool": "anything"})
    assert r.status_code == 201
    job_id = r.json()["id"]
    assert r.json()["state"] == "running"

    # A completely fresh reader (as after a refresh) can find the job and tail it.
    assert _wait_for(lambda: client.get(f"/api/jobs/{job_id}").json()["state"] == "done")
    tail = client.get(f"/api/jobs/{job_id}", params={"offset": 0}).json()
    assert "job ran" in tail["log"]
    assert tail["offset"] > 0


def test_list_endpoint_returns_job(app_client):
    client, _ = app_client
    job_id = client.post("/api/jobs", json={"tool": "x"}).json()["id"]
    ids = [j["id"] for j in client.get("/api/jobs").json()]
    assert job_id in ids


def test_post_invalid_kind_is_400(app_client):
    client, _ = app_client
    r = client.post("/api/jobs", json={"tool": "boom"})
    assert r.status_code == 400


def test_get_unknown_job_is_404(app_client):
    client, _ = app_client
    assert client.get("/api/jobs/nope").status_code == 404


def test_cancel_unknown_job_is_404(app_client):
    client, _ = app_client
    assert client.post("/api/jobs/nope/cancel").status_code == 404


def test_post_requires_gl(monkeypatch, tmp_path):
    import server.app as appmod
    monkeypatch.setattr(appmod, "job_manager", JobManager(jobs_dir=tmp_path / "jobs"))
    appmod.app.state.gl = None
    client = TestClient(appmod.app)
    assert client.post("/api/jobs", json={"tool": "x"}).status_code == 503


# ---------------------------------------------------------------------------
# argv resolver (whitelisted kinds → command line)
# ---------------------------------------------------------------------------

def test_job_argv_report():
    import server.app as appmod
    kind, label, argv = appmod._job_argv(
        {"report": "portfolio", "formats": ["markdown"], "reuse_data": "last"}
    )
    assert kind == "report" and label == "portfolio"
    assert argv[:2] == [sys.executable, "NceGitLab.py"]
    assert "-r" in argv and "portfolio" in argv
    assert "--formats" in argv and "markdown" in argv
    assert "--last" in argv


def test_job_argv_tool():
    import server.app as appmod
    kind, label, argv = appmod._job_argv({"tool": "audit-hierarchy"})
    assert kind == "tool" and label == "audit-hierarchy"
    assert "-ut" in argv and "audit-hierarchy" in argv


def test_job_argv_unknown_raises():
    import server.app as appmod
    with pytest.raises(ValueError):
        appmod._job_argv({"report": "does-not-exist"})
    with pytest.raises(ValueError):
        appmod._job_argv({"tool": "does-not-exist"})
    with pytest.raises(ValueError):
        appmod._job_argv({})


def test_tool_argv_tokens_types():
    import server.app as appmod
    tool = {"params": [
        {"name": "percent",  "type": float},
        {"name": "flag_on",  "type": bool, "default": False},
        {"name": "flag_off", "type": bool, "default": True},
        {"name": "neg",      "type": str},
        {"name": "skip",     "type": str},
        {"name": "hidden",   "type": str, "cli_only": True},
    ]}
    params = {"percent": 0.85, "flag_on": True, "flag_off": False,
              "neg": "-5", "skip": "", "hidden": "x"}
    toks = appmod._tool_argv_tokens(tool, params)
    assert "--percent" in toks and "0.85" in toks
    assert "--flag_on" in toks                     # default False, turned on → bare flag
    assert "--flag_off=false" in toks              # default True, turned off → explicit
    assert "--neg=-5" in toks                      # dash-leading value → attached form
    assert not any("skip" in t for t in toks)      # empty string skipped
    assert not any("hidden" in t for t in toks)    # cli_only hidden from argv
