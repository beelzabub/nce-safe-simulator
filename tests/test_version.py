"""Tests for application version resolution (issue #173)."""

import json
import subprocess

from fastapi.testclient import TestClient

from server import version as version_mod
from server.app import app
from server.version import resolve_version


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(path):
    _git(path, "init", "-q")
    _git(path, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "--allow-empty", "-q", "-m", "x")


def test_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NCE_VERSION", "9.9.9-rc1")
    (tmp_path / "version.json").write_text(json.dumps({"version": "baked"}))
    assert resolve_version() == "9.9.9-rc1"


def test_baked_version_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NCE_VERSION", raising=False)
    (tmp_path / "version.json").write_text(
        json.dumps({"version": "nce-abc1234", "commit": "abc1234"}))
    assert resolve_version() == "nce-abc1234"


def test_git_branch_build_uses_commit_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NCE_VERSION", raising=False)
    _init_repo(tmp_path)
    short = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=tmp_path,
        capture_output=True, text=True).stdout.strip()
    assert resolve_version() == f"nce-{short}"


def test_git_tagged_build_uses_tag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NCE_VERSION", raising=False)
    _init_repo(tmp_path)
    _git(tmp_path, "tag", "v1.2.3")
    assert resolve_version() == "v1.2.3"


def test_version_file_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # no .git, no version.json
    monkeypatch.delenv("NCE_VERSION", raising=False)
    (tmp_path / "VERSION").write_text("0.1.0-dev\n")
    assert resolve_version() == "0.1.0-dev"


def test_unknown_when_nothing_available(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NCE_VERSION", raising=False)
    assert resolve_version() == "nce-unknown"


def test_config_endpoint_carries_version(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NCE_VERSION", "test-7.7.7")
    monkeypatch.setattr(version_mod, "_cached", None)   # bust the memo
    body = TestClient(app).get("/api/config").json()
    assert body["version"] == "test-7.7.7"
