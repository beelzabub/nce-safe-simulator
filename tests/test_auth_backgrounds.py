"""Tests for the login-page background endpoints (epic #135).

Covers server/auth_backgrounds.py plus the /api/auth/backgrounds routes and
the dod_banner_enabled field on /api/config.
"""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from server import auth_backgrounds
from server.app import app


AUTH_CFG = {
    "dod_banner_enabled": True,
    "background": {
        "rotation_seconds": 15,
        "max_images": 8,
        "source": "repo",
        "staging_s3": {"bucket": "", "prefix": "login-backgrounds/", "presign_ttl_seconds": 3600},
    },
}


def _gl(auth=AUTH_CFG):
    """Minimal stand-in for the NceGitLab instance — only .auth is consumed."""
    return SimpleNamespace(auth=auth)


@pytest.fixture()
def media_dir(tmp_path, monkeypatch):
    d = tmp_path / "login-backgrounds"
    d.mkdir()
    monkeypatch.setattr(auth_backgrounds, "MEDIA_DIR", d)
    return d


@pytest.fixture()
def client(media_dir):
    app.state.gl = _gl()
    return TestClient(app)


def _add_image(media_dir, name, data=b"\xff\xd8fake"):
    (media_dir / name).write_bytes(data)


# ---------------------------------------------------------------------------
# GET /api/auth/backgrounds
# ---------------------------------------------------------------------------

def test_backgrounds_fallback_when_empty(client):
    resp = client.get("/api/auth/backgrounds")
    assert resp.status_code == 200
    data = resp.json()
    assert data["fallback"] is True
    assert data["images"] == []
    assert data["rotation_seconds"] == 15


def test_backgrounds_fallback_when_dir_missing(client, media_dir, monkeypatch):
    monkeypatch.setattr(auth_backgrounds, "MEDIA_DIR", media_dir / "nope")
    resp = client.get("/api/auth/backgrounds")
    assert resp.status_code == 200
    assert resp.json()["fallback"] is True


def test_backgrounds_lists_images_with_credits(client, media_dir):
    _add_image(media_dir, "csg-01.jpg")
    _add_image(media_dir, "ddg-02.png")
    (media_dir / "credits.json").write_text(json.dumps({"csg-01.jpg": "U.S. Navy photo"}))
    (media_dir / "notes.txt").write_text("not an image")

    data = client.get("/api/auth/backgrounds").json()
    assert data["fallback"] is False
    by_name = {i["name"]: i for i in data["images"]}
    assert set(by_name) == {"csg-01.jpg", "ddg-02.png"}
    assert by_name["csg-01.jpg"]["url"] == "/api/auth/backgrounds/csg-01.jpg"
    assert by_name["csg-01.jpg"]["credit"] == "U.S. Navy photo"
    assert by_name["ddg-02.png"]["credit"] == ""


def test_backgrounds_capped_at_max_images(client, media_dir):
    for i in range(12):
        _add_image(media_dir, f"img-{i:02d}.jpg")
    data = client.get("/api/auth/backgrounds").json()
    assert len(data["images"]) == 8  # AUTH_CFG max_images


def test_backgrounds_limit_param_tightens_cap(client, media_dir):
    for i in range(6):
        _add_image(media_dir, f"img-{i}.jpg")
    data = client.get("/api/auth/backgrounds?limit=3").json()
    assert len(data["images"]) == 3


def test_backgrounds_config_overrides(client, media_dir):
    _add_image(media_dir, "a.jpg")
    app.state.gl = _gl({"background": {"rotation_seconds": 5, "max_images": 1}})
    data = client.get("/api/auth/backgrounds").json()
    assert data["rotation_seconds"] == 5
    assert len(data["images"]) == 1


def test_backgrounds_s3_test_without_bucket_falls_back(client, media_dir):
    _add_image(media_dir, "a.jpg")  # repo images must NOT leak into s3-test mode
    app.state.gl = _gl({"background": {"source": "s3-test", "staging_s3": {"bucket": ""}}})
    data = client.get("/api/auth/backgrounds").json()
    assert data["fallback"] is True
    assert data["images"] == []


def test_backgrounds_never_5xx_on_source_error(client, media_dir, monkeypatch):
    def boom(_cfg):
        raise RuntimeError("S3 exploded")
    monkeypatch.setattr(auth_backgrounds, "_staging_images", boom)
    app.state.gl = _gl({"background": {"source": "s3-test", "staging_s3": {"bucket": "x"}}})
    resp = client.get("/api/auth/backgrounds")
    assert resp.status_code == 200
    assert resp.json()["fallback"] is True


# ---------------------------------------------------------------------------
# GET /api/auth/backgrounds/{filename}
# ---------------------------------------------------------------------------

def test_serve_image_with_cache_header(client, media_dir):
    _add_image(media_dir, "csg-01.jpg")
    resp = client.get("/api/auth/backgrounds/csg-01.jpg")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["cache-control"] == "public, max-age=86400"


def test_serve_rejects_traversal(client, media_dir):
    _add_image(media_dir, "a.jpg")
    assert client.get("/api/auth/backgrounds/..%2Fa.jpg").status_code == 404


def test_serve_rejects_non_image_extension(client, media_dir):
    (media_dir / "credits.json").write_text("{}")
    assert client.get("/api/auth/backgrounds/credits.json").status_code == 404


def test_serve_missing_file_404(client):
    assert client.get("/api/auth/backgrounds/nope.jpg").status_code == 404


# ---------------------------------------------------------------------------
# dod_banner_enabled on GET /api/config
# ---------------------------------------------------------------------------

def test_config_banner_default_true_without_gl(client):
    app.state.gl = None
    data = client.get("/api/config").json()
    assert data["dod_banner_enabled"] is True


def test_config_banner_respects_config(client):
    app.state.gl = _gl({"dod_banner_enabled": False})
    data = client.get("/api/config").json()
    assert data["dod_banner_enabled"] is False
