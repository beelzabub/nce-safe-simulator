"""Tests for the self-hosted npm cache (issue #271).

The enclave contract: the frontend-builder Dockerfile stage installs npm
packages from the project's generic package registry — package ``npm-cache``,
a content-addressed cache captured by scripts/capture-npm-cache.sh — with
``npm ci --offline``, never from registry.npmjs.org.

OFFLINE=0 is the connected-dev escape hatch: an `npm ci` without --offline is
legal only as the fallback branch of the ``OFFLINE`` conditional (still
lock-pinned — `npm ci` installs package-lock.json exactly). The OFFLINE=1
default and CI-never-sets-it contracts are enforced in test_pip_wheels.py.
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


def _run_blocks(body):
    """Each RUN command (backslash continuations joined) as one string."""
    blocks, cur = [], None
    for line in body.splitlines():
        if cur is None:
            if line.lstrip().startswith("RUN"):
                cur = [line]
        else:
            cur.append(line)
        if cur is not None and not line.rstrip().endswith("\\"):
            blocks.append("\n".join(cur))
            cur = None
    if cur:
        blocks.append("\n".join(cur))
    return blocks


OFFLINE_GUARD = 'if [ "$OFFLINE" = "1" ]'


def test_online_npm_ci_only_behind_the_offline_flag():
    """In CI-built stages, an `npm ci` without --offline (which would reach
    registry.npmjs.org — the egress #271 removes) is legal only as the
    OFFLINE=0 fallback: inside a RUN guarded by the OFFLINE conditional whose
    offline branch installs --offline from the vendored cache."""
    for name, body in _stages().items():
        if name == "ops":
            continue
        for block in _run_blocks(body):
            bare = [
                l.strip() for l in block.splitlines()
                if re.search(r"\bnpm ci\b", l) and "--offline" not in l
            ]
            if not bare:
                continue
            assert OFFLINE_GUARD in block and re.search(
                r"npm ci[^\n]*--offline", block
            ), (
                f"stage {name} has an `npm ci` without --offline outside the "
                f"OFFLINE guard: {bare!r} — the default build must install "
                f"from the npm-cache registry package (issue #271)"
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
