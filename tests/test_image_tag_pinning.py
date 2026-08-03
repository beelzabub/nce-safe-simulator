"""Tests for immutable image-tag pinning on the EKS deploy path (issue #290).

Covers the two pieces that carry the guarantee:

- ``cdk/scripts/resolve-image-tag.sh`` — resolves the immutable tag of the
  image currently tagged :latest in ECR (stubbed ``aws`` on PATH).
- The Helm chart — refuses to render without an explicit ``image.tag`` and
  renders the pinned tag verbatim when given one (skipped when ``helm`` is
  not installed).
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOLVE = REPO_ROOT / "cdk" / "scripts" / "resolve-image-tag.sh"
CHART = REPO_ROOT / "helm" / "nce-safe-simulator"


def _stub_aws(tmp_path, body):
    """Drop a fake ``aws`` executable on PATH and return the env to use."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    aws = bindir / "aws"
    aws.write_text("#!/bin/sh\n" + body + "\n")
    aws.chmod(aws.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    return env


def _resolve(env):
    return subprocess.run(
        [str(RESOLVE), "nce-safe-simulator", "us-east-1"],
        capture_output=True, text=True, env=env,
    )


def test_resolver_prints_the_immutable_tag(tmp_path):
    env = _stub_aws(tmp_path, 'printf "0.1.0-dev-abc1234\\tlatest\\n"')
    r = _resolve(env)
    assert r.returncode == 0
    assert r.stdout.strip() == "0.1.0-dev-abc1234"


def test_resolver_ignores_tag_order(tmp_path):
    env = _stub_aws(tmp_path, 'printf "latest\\t0.1.0-dev-abc1234\\n"')
    r = _resolve(env)
    assert r.returncode == 0
    assert r.stdout.strip() == "0.1.0-dev-abc1234"


def test_resolver_fails_when_only_latest_exists(tmp_path):
    env = _stub_aws(tmp_path, 'printf "latest\\n"')
    r = _resolve(env)
    assert r.returncode != 0
    assert r.stdout == ""
    assert "no immutable tag" in r.stderr
    assert "ecr-push" in r.stderr


def test_resolver_fails_when_latest_is_missing(tmp_path):
    env = _stub_aws(tmp_path, "exit 254")
    r = _resolve(env)
    assert r.returncode != 0
    assert "ecr-push" in r.stderr


needs_helm = pytest.mark.skipif(shutil.which("helm") is None,
                                reason="helm not installed")


def _template(*sets):
    cmd = ["helm", "template", "test", str(CHART)]
    for s in sets:
        cmd += ["--set", s]
    return subprocess.run(cmd, capture_output=True, text=True)


@needs_helm
def test_chart_renders_the_pinned_tag():
    r = _template("image.repository=example/repo", "image.tag=0.1.0-dev-abc1234")
    assert r.returncode == 0
    assert 'image: "example/repo:0.1.0-dev-abc1234"' in r.stdout


@needs_helm
def test_chart_refuses_to_render_without_a_tag():
    r = _template("image.repository=example/repo")
    assert r.returncode != 0
    assert "image.tag is required" in r.stderr


def test_values_default_tag_is_empty_not_latest():
    # Guard against the default regressing to :latest — the KICS "Invalid
    # Image Tag" finding this issue fixes.
    values = (CHART / "values.yaml").read_text()
    image_block = values.split("image:")[1].split("\n\n")[0]
    assert "tag: latest" not in image_block
    assert 'tag: ""' in image_block
