"""Tests for scripts/sync_login_backgrounds.py (epic #135 curation tooling)."""
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sync_login_backgrounds.py"
_spec = importlib.util.spec_from_file_location("sync_login_backgrounds", _SCRIPT)
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _make_image(path, size=(2400, 1350), color=(10, 40, 80)):
    Image.new("RGB", size, color).save(path)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def test_slugify():
    assert sync.slugify("USS Nimitz (CVN 68)!") == "uss-nimitz-cvn-68"
    assert sync.slugify("___") == "image"


def test_optimize_resizes_to_target_width(tmp_path):
    src = tmp_path / "big.png"
    _make_image(src, size=(3000, 2000))
    data, (w, h) = sync.optimize(src)
    assert (w, h) == (1920, 1280)
    assert data[:2] == b"\xff\xd8"  # JPEG magic


def test_optimize_keeps_small_images(tmp_path):
    src = tmp_path / "small.jpg"
    _make_image(src, size=(1200, 800))
    _, (w, h) = sync.optimize(src)
    assert (w, h) == (1200, 800)


def test_staging_defaults_without_config(monkeypatch, tmp_path):
    monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)
    assert sync.staging_defaults() == (sync.DEFAULT_BUCKET, sync.DEFAULT_PREFIX)


def test_staging_defaults_from_config(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(
        {"auth": {"background": {"staging_s3": {"bucket": "my-bucket", "prefix": "bg/"}}}}
    ))
    monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)
    assert sync.staging_defaults() == ("my-bucket", "bg/")


# ---------------------------------------------------------------------------
# stage
# ---------------------------------------------------------------------------

def test_stage_dry_run_uploads_nothing(tmp_path, capsys, monkeypatch):
    src = tmp_path / "candidates"
    src.mkdir()
    _make_image(src / "USS Test.png")
    monkeypatch.setattr(sync, "s3_client", lambda: pytest.fail("dry-run must not build a client"))

    args = SimpleNamespace(source_dir=str(src), dry_run=True)
    sync.cmd_stage(args, "bucket", "pre/")
    out = capsys.readouterr().out
    assert "DRY-RUN stage USS Test.png -> s3://bucket/pre/uss-test.jpg" in out


def test_stage_uploads_with_credit_metadata(tmp_path, monkeypatch):
    src = tmp_path / "candidates"
    src.mkdir()
    _make_image(src / "ship.png")
    (src / "credits.json").write_text(json.dumps({"ship.png": "U.S. Navy photo by MC2 Test"}))

    puts = []
    client = SimpleNamespace(put_object=lambda **kw: puts.append(kw))
    monkeypatch.setattr(sync, "s3_client", lambda: client)

    sync.cmd_stage(SimpleNamespace(source_dir=str(src), dry_run=False), "bucket", "pre/")
    assert len(puts) == 1
    assert puts[0]["Key"] == "pre/ship.jpg"
    assert puts[0]["ContentType"] == "image/jpeg"
    assert puts[0]["Metadata"] == {"credit": "U.S. Navy photo by MC2 Test"}


def test_stage_exits_when_no_images(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SystemExit):
        sync.cmd_stage(SimpleNamespace(source_dir=str(empty), dry_run=True), "b", "p/")


# ---------------------------------------------------------------------------
# promote
# ---------------------------------------------------------------------------

class _FakeS3:
    """list/head/download stub over an in-memory {key: (bytes, credit)} store."""

    def __init__(self, objects):
        self.objects = objects

    def get_paginator(self, _op):
        contents = [{"Key": k} for k in sorted(self.objects)]
        return SimpleNamespace(paginate=lambda **kw: [{"Contents": contents}])

    def head_object(self, Bucket, Key):
        data, credit = self.objects[Key]
        return {"ContentLength": len(data), "Metadata": {"credit": credit} if credit else {}}

    def download_file(self, bucket, key, dest):
        Path(dest).write_bytes(self.objects[key][0])


def test_promote_writes_images_and_merges_credits(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    (media / "credits.json").write_text(json.dumps({"existing.jpg": "kept"}))
    monkeypatch.setattr(sync, "MEDIA_DIR", media)
    fake = _FakeS3({"pre/csg.jpg": (b"jpegbytes", "U.S. Navy photo by MC1 A")})
    monkeypatch.setattr(sync, "s3_client", lambda: fake)

    sync.cmd_promote(SimpleNamespace(names=[], dry_run=False), "bucket", "pre/")

    assert (media / "csg.jpg").read_bytes() == b"jpegbytes"
    credits = json.loads((media / "credits.json").read_text())
    assert credits == {"existing.jpg": "kept", "csg.jpg": "U.S. Navy photo by MC1 A"}


def test_promote_named_subset_and_missing(tmp_path, monkeypatch):
    media = tmp_path / "media"
    monkeypatch.setattr(sync, "MEDIA_DIR", media)
    fake = _FakeS3({"pre/a.jpg": (b"a", ""), "pre/b.jpg": (b"b", "")})
    monkeypatch.setattr(sync, "s3_client", lambda: fake)

    sync.cmd_promote(SimpleNamespace(names=["a.jpg"], dry_run=False), "bucket", "pre/")
    assert (media / "a.jpg").is_file() and not (media / "b.jpg").exists()

    with pytest.raises(SystemExit):
        sync.cmd_promote(SimpleNamespace(names=["nope.jpg"], dry_run=False), "bucket", "pre/")


def test_promote_dry_run_touches_nothing(tmp_path, monkeypatch):
    media = tmp_path / "media"
    monkeypatch.setattr(sync, "MEDIA_DIR", media)
    fake = _FakeS3({"pre/a.jpg": (b"a", "c")})
    monkeypatch.setattr(sync, "s3_client", lambda: fake)

    sync.cmd_promote(SimpleNamespace(names=[], dry_run=True), "bucket", "pre/")
    assert not media.exists()
