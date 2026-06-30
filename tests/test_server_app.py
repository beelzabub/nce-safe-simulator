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


# ---------------------------------------------------------------------------
# GET /api/config/full  and  PUT /api/config/full
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "url": "https://gitlab.example.com",
    "private_token": "glpat-test",
    "parent_group": "test-group",
    "gitlab_namespace": "test-ns",
    "project_labels": ["project::A"],
}


@pytest.fixture()
def config_client(tmp_path, monkeypatch):
    """Client with a temporary config.json in a temp directory."""
    import json as _json
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(_json.dumps(SAMPLE_CONFIG), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    app.state.gl = None
    return TestClient(app), tmp_path


def test_get_config_full_returns_config(config_client):
    client, _ = config_client
    resp = client.get("/api/config/full")
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == SAMPLE_CONFIG["url"]
    assert data["parent_group"] == SAMPLE_CONFIG["parent_group"]
    assert data["private_token"] == SAMPLE_CONFIG["private_token"]


def test_get_config_full_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app.state.gl = None
    client = TestClient(app)
    resp = client.get("/api/config/full")
    assert resp.status_code == 404


def test_put_config_full_saves_to_disk(config_client):
    import json as _json
    client, tmp_path = config_client
    new_cfg = {**SAMPLE_CONFIG, "parent_group": "updated-group"}
    resp = client.put("/api/config/full", json=new_cfg)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    saved = _json.loads((tmp_path / "config.json").read_text())
    assert saved["parent_group"] == "updated-group"


def test_put_config_full_reloads_gl(config_client):
    client, _ = config_client
    reload_calls = []

    class _MockGl:
        def reload_config(self):
            reload_calls.append(True)

    app.state.gl = _MockGl()
    try:
        client.put("/api/config/full", json=SAMPLE_CONFIG)
    finally:
        app.state.gl = None
    assert reload_calls, "reload_config was not called"


def test_put_config_full_non_dict_returns_400(config_client):
    client, _ = config_client
    resp = client.put(
        "/api/config/full",
        content=b"[1, 2, 3]",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/download/{filename} — export browser download
# ---------------------------------------------------------------------------


@pytest.fixture()
def download_client(tmp_path, monkeypatch):
    """Client with a populated public/exports directory in a temp cwd."""
    exports = tmp_path / "public" / "exports"
    exports.mkdir(parents=True)
    (exports / "demo-epics-export.csv").write_text("title\nHello\n", encoding="utf-8")
    (exports / "demo-issues-export.json").write_text('[{"title": "Hi"}]', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    app.state.gl = None
    return TestClient(app)


def test_download_csv_sets_attachment_header(download_client):
    resp = download_client.get("/api/download/demo-epics-export.csv")
    assert resp.status_code == 200
    disp = resp.headers["content-disposition"]
    assert "attachment" in disp
    assert "demo-epics-export.csv" in disp
    assert resp.headers["content-type"].startswith("text/csv")
    assert "Hello" in resp.text


def test_download_json_media_type(download_client):
    resp = download_client.get("/api/download/demo-issues-export.json")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["content-type"].startswith("application/json")


def test_download_missing_file_returns_404(download_client):
    resp = download_client.get("/api/download/nope.csv")
    assert resp.status_code == 404


def test_download_rejects_path_traversal(download_client):
    # A leaked secret one level up from public/exports must not be reachable.
    from pathlib import Path
    Path("secret.txt").write_text("top secret", encoding="utf-8")
    resp = download_client.get("/api/download/..%2F..%2Fsecret.txt")
    assert resp.status_code == 404
    assert "top secret" not in resp.text


# ---------------------------------------------------------------------------
# _resolve_reuse_data — sentinel file guards
# ---------------------------------------------------------------------------

from server.app import _resolve_reuse_data


def _make_data_dir(base, date="20260101", time="120000", complete=True):
    """Create a reports/date/time/data/ directory, optionally with sentinel."""
    d = base / "reports" / date / time / "data"
    d.mkdir(parents=True)
    if complete:
        (d / "snapshot.complete").touch()
    return d


def test_resolve_reuse_data_none_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _resolve_reuse_data(None) is None


def test_resolve_reuse_data_empty_string_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _resolve_reuse_data("") is None


def test_resolve_reuse_data_last_picks_complete_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = _make_data_dir(tmp_path, complete=True)
    result = _resolve_reuse_data("last")
    assert result is not None and result.resolve() == d


def test_resolve_reuse_data_last_skips_incomplete_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_data_dir(tmp_path, complete=False)
    result = _resolve_reuse_data("last")
    assert result is None


def test_resolve_reuse_data_last_logs_when_no_complete_snapshot(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _make_data_dir(tmp_path, complete=False)
    _resolve_reuse_data("last")
    assert "No complete snapshot found" in capsys.readouterr().out


def test_resolve_reuse_data_last_picks_newest_complete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_data_dir(tmp_path, date="20260101", time="090000", complete=True)
    newer = _make_data_dir(tmp_path, date="20260101", time="120000", complete=True)
    result = _resolve_reuse_data("last")
    assert result is not None and result.resolve() == newer


def test_resolve_reuse_data_last_skips_incomplete_prefers_older_complete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    older = _make_data_dir(tmp_path, date="20260101", time="090000", complete=True)
    _make_data_dir(tmp_path, date="20260101", time="120000", complete=False)
    result = _resolve_reuse_data("last")
    assert result is not None and result.resolve() == older


def test_resolve_reuse_data_explicit_path_returned_as_is(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _resolve_reuse_data("reports/20260101/090000/data")
    from pathlib import Path
    assert result == Path("reports/20260101/090000/data")
