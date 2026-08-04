"""Tests for the self-hosted npm cache (issue #271).

The enclave contract: the frontend-builder Dockerfile stage installs npm
packages from the project's generic package registry — package ``npm-cache``,
a content-addressed cache captured by scripts/capture-npm-cache.sh — with
``npm ci --offline``, never from registry.npmjs.org.
"""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = (REPO / "Dockerfile").read_text()
CAPTURE = (REPO / "scripts" / "capture-npm-cache.sh").read_text()


def _stages():
    no_comments = "\n".join(
        l for l in DOCKERFILE.splitlines() if not l.lstrip().startswith("#")
    )
    parts = re.split(r"(?m)^FROM\s+\S+(?:\s+AS\s+(\S+))?\s*$", no_comments)
    return {name or "_final": body for name, body in zip(parts[1::2], parts[2::2])}


def test_ci_built_stages_npm_ci_is_offline_only():
    """`npm ci` in a CI-built stage must be --offline (cache-only); a bare
    `npm ci` reaches registry.npmjs.org — the egress #271 removes."""
    for name, body in _stages().items():
        if name == "ops":
            continue
        for line in body.splitlines():
            if re.search(r"\bnpm ci\b", line):
                assert "--offline" in line, (
                    f"stage {name} has an `npm ci` without --offline: "
                    f"{line.strip()!r} — must install from the npm-cache "
                    f"registry package (issue #271)"
                )


def test_ci_built_stages_have_no_npm_registry_host():
    for name, body in _stages().items():
        if name == "ops":
            continue
        assert "registry.npmjs.org" not in body, f"stage {name} references registry.npmjs.org"


def test_npm_cache_version_is_pinned():
    assert re.search(r"(?m)^ARG NPM_CACHE_VERSION=\d{4}\.\d{2}\.\d{2}$", DOCKERFILE), \
        "NPM_CACHE_VERSION must be pinned to a dated version at the top of the Dockerfile"


def test_dockerfile_fetch_matches_capture_package_path():
    """The Dockerfile must fetch the exact artifact the capture script uploads:
    npm-cache/<version>/npm-cache.tar.gz."""
    assert "packages/generic/npm-cache/" in DOCKERFILE
    assert "npm-cache.tar.gz" in DOCKERFILE
    assert "npm-cache.tar.gz" in CAPTURE


def test_frontend_builder_installs_offline_from_cache():
    fb = _stages()["frontend-builder"]
    assert "npm ci --offline --cache /tmp/npm-cache" in fb, \
        "frontend-builder must `npm ci --offline --cache /tmp/npm-cache`"


def test_capture_script_parses():
    subprocess.run(["bash", "-n", str(REPO / "scripts" / "capture-npm-cache.sh")], check=True)
