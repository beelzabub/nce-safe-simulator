"""
REST API smoke tests for server/app.py.

Durable report/tool run integration tests live in test_server_api.py; the
durable job engine itself is covered in test_jobs.py. These tests cover the
REST endpoints and the request→argv resolution helpers.
"""
import pytest
from fastapi.testclient import TestClient

from mixins.reports import REPORTS
from mixins.tools import TOOLS
from server.app import app
from server.constraints import READONLY_TOOLS, _TOOL_GROUP


@pytest.fixture()
def client():
    app.state.gl = None
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/tools
# ---------------------------------------------------------------------------

def test_tools_returns_all_visible_tools(client):
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == len([t for t in TOOLS if not t.get("ui_hidden")])


def test_tools_keys_match_registry(client):
    resp = client.get("/api/tools")
    returned_keys = {t["key"] for t in resp.json()}
    expected_keys = {t["key"] for t in TOOLS if not t.get("ui_hidden")}
    assert returned_keys == expected_keys


def test_ui_hidden_tools_stay_out_of_web_picker(client):
    # `query` is CLI-only: its web home is the Search view, so the raw tool
    # must not also appear in the job picker.
    hidden = {t["key"] for t in TOOLS if t.get("ui_hidden")}
    assert "query" in hidden                     # the flag is actually set
    returned_keys = {t["key"] for t in client.get("/api/tools").json()}
    assert not (hidden & returned_keys)


def test_import_export_run_menu_order(client):
    """The Tools run menu groups by parallelism_group and preserves the
    /api/tools order within a group, so the import-export tools must appear
    in the sequence #211 specifies: each export paired with its import,
    bundle first, then epics, issues, links."""
    resp = client.get("/api/tools")
    order = [t["key"] for t in resp.json()
             if _TOOL_GROUP.get(t["key"]) == "import-export"]
    assert order == [
        "export-bundle", "import-bundle",
        "export-epics", "import-epics",
        "export-issues", "import-issues",
        "export-links", "import-links",
    ]


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


def test_export_tools_ui_payload_hides_output_path(client):
    """The server-side output_path field is a CLI-only param and must not be
    surfaced to the web UI for export-epics / export-issues (issue #130)."""
    resp = client.get("/api/tools")
    by_key = {t["key"]: t for t in resp.json()}
    for key in ("export-epics", "export-issues"):
        param_names = {p["name"] for p in by_key[key]["params"]}
        assert "output_path" not in param_names, (
            f"tool '{key}' still exposes output_path in the UI payload"
        )
        # the format selector and group picker must still be present
        assert "fmt" in param_names
        assert "group" in param_names


def test_cli_only_params_never_reach_ui_payload(client):
    """No param flagged cli_only in the raw registry should appear in any UI
    tool payload."""
    resp = client.get("/api/tools")
    ui_params = {
        t["key"]: {p["name"] for p in t["params"]} for t in resp.json()
    }
    for tool in TOOLS:
        for p in tool.get("params", []):
            if p.get("cli_only"):
                assert p["name"] not in ui_params.get(tool["key"], set()), (
                    f"cli_only param '{p['name']}' leaked into UI payload for "
                    f"'{tool['key']}'"
                )


def test_cli_registry_still_exposes_output_path(client):
    """HARD CONSTRAINT: the CLI reads the raw TOOLS registry, which must keep
    output_path (flagged cli_only) for export-epics / export-issues."""
    by_key = {t["key"]: t for t in TOOLS}
    for key in ("export-epics", "export-issues"):
        output = [p for p in by_key[key]["params"] if p["name"] == "output_path"]
        assert len(output) == 1, f"tool '{key}' lost its output_path param"
        p = output[0]
        assert p["cli_only"] is True
        assert p["optional"] is True
        assert p["type"] is str


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


def test_reload_config_drops_jql_caches(tmp_path, monkeypatch):
    # A config save may repoint parent_group (or swap tokens): run_jql's
    # cached group path / current user must not outlive the reload, or the
    # search keeps querying the previous group until the process restarts.
    import json as _json
    from NceGitLab import NceGitLab

    monkeypatch.delenv("GROUP_NAME", raising=False)
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(_json.dumps(
        {**SAMPLE_CONFIG, "parent_group": "repointed-group"}), encoding="utf-8")

    class _Shell:                    # bare instance: reload_config only needs
        pass                         # config_file (+ optional overrides)

    shell = _Shell()
    shell.config_file = cfg_file
    shell._jql_group_path_cache = "old/group/path"
    shell._jql_current_user_cache = "old-user"
    NceGitLab.reload_config(shell)
    assert shell.parent_group == "repointed-group"
    assert shell._jql_group_path_cache is None
    assert shell._jql_current_user_cache is None


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
