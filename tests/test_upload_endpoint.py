"""
Tests for issue #125: web UI import file-upload endpoint.

Covers POST /api/upload — the endpoint the import-epics / import-issues file
picker posts to before running. It must:
  - round-trip a CSV/JSON file and return its server path + metadata
  - return a path the import path-resolution would accept (absolute, existing)
  - reject unsupported extensions
  - strip path-traversal components from the supplied filename
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import app
from mixins.importexport import ImportExportMixin


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Endpoint writes to Path("uploads") relative to cwd — isolate it in tmp_path.
    monkeypatch.chdir(tmp_path)
    return TestClient(app)


def test_upload_csv_roundtrip(client):
    content = b"title,group_path\nMy Epic,portfolio\n"
    r = client.post("/api/upload", files={"file": ("epics.csv", content, "text/csv")})
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "epics.csv"
    assert body["size"] == len(content)
    saved = Path(body["path"])
    assert saved.is_absolute()
    assert saved.exists()
    assert saved.read_bytes() == content


def test_upload_json_roundtrip(client):
    content = json.dumps([{"title": "Epic A"}]).encode()
    r = client.post("/api/upload", files={"file": ("issues.json", content, "application/json")})
    assert r.status_code == 200
    saved = Path(r.json()["path"])
    assert saved.exists()
    assert json.loads(saved.read_text()) == [{"title": "Epic A"}]


def test_uploaded_path_resolves_for_import(client):
    """The returned path passes the same checks import_epics runs before reading."""
    r = client.post("/api/upload", files={"file": ("e.csv", b"title\nFoo\n", "text/csv")})
    server_path = r.json()["path"]
    # import_epics does: path = self._resolve_path(input_path); path.exists()
    resolved = ImportExportMixin._resolve_path(None, server_path)
    assert resolved.exists()


def test_upload_rejects_bad_extension(client):
    r = client.post("/api/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400
    assert ".csv" in r.json()["detail"]


def test_upload_rejects_no_extension(client):
    r = client.post("/api/upload", files={"file": ("noext", b"hello", "application/octet-stream")})
    assert r.status_code == 400


def test_upload_strips_path_traversal(client, tmp_path):
    content = b"title\nx\n"
    r = client.post("/api/upload", files={"file": ("../../evil.csv", content, "text/csv")})
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "evil.csv"
    saved = Path(body["path"])
    assert saved.exists()
    # Must remain inside the uploads dir, not escape upward.
    uploads = (tmp_path / "uploads").resolve()
    assert str(saved).startswith(str(uploads))
