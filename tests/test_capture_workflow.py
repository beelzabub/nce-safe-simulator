"""Tests for the vendored-dependency refresh workflow (issue #296).

The contract: `make capture-deps` (engine: scripts/capture-deps.sh) is the
one documented way to refresh the vendored closures. pip/npm versions are
content-addressed — the capture scripts default their registry version to
the same sha256-derivation the Dockerfile install sites run at build time —
so capture is idempotent (an already-published hash skips) and drift is
structural (an uncaptured lock 404s the next image build). apt keeps a
dated version plus the Dockerfile capture-input stamp (test_apt_debs.py).
"""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ORCH = (REPO / "scripts" / "capture-deps.sh").read_text()
PIP_CAPTURE = (REPO / "scripts" / "capture-pip-wheels.sh").read_text()
NPM_CAPTURE = (REPO / "scripts" / "capture-npm-cache.sh").read_text()
MAKEFILE = (REPO / "Makefile").read_text()


def test_orchestrator_parses():
    subprocess.run(["bash", "-n", str(REPO / "scripts" / "capture-deps.sh")], check=True)


def test_make_targets_exist_and_route_to_orchestrator():
    for target, mode in (("capture-deps", "all"), ("capture-pip", "pip"),
                         ("capture-npm", "npm"), ("capture-apt", "apt")):
        assert re.search(rf"(?m)^{target}:.*##", MAKEFILE), f"missing make target {target}"
        assert f"capture-deps.sh {mode}" in MAKEFILE, f"{target} must run capture-deps.sh {mode}"


def test_orchestrator_preflights_every_requirement():
    """Gaps must be reported up front with the fix, not die mid-capture."""
    assert "command -v docker" in ORCH
    assert "GITLAB_TOKEN" in ORCH
    assert "binfmt_misc" in ORCH and "tonistiigi/binfmt" in ORCH


def test_orchestrator_recompiles_lock_with_pinned_pip_tools():
    """The lock recompile must be reproducible: pinned pip-tools, the
    Dockerfile's own base image, adopt-on-change (an untouched
    requirements.txt reproduces the lock byte-for-byte, so nothing
    recaptures)."""
    assert re.search(r"PIP_TOOLS_PIN='pip-tools==[\d.]+'", ORCH)
    assert "python:3.11-slim" in ORCH
    assert "pip-compile" in ORCH and "--no-header" in ORCH
    assert "cmp -s" in ORCH


def test_capture_scripts_skip_already_published_versions():
    """version == content hash, so an existing version is guaranteed
    identical — capture must no-op (idempotence), with --force as the
    explicit override."""
    for name, text in (("pip", PIP_CAPTURE), ("npm", NPM_CAPTURE)):
        assert "--force" in text, name
        assert "already published" in text, name
        assert re.search(r"curl -fsSo /dev/null .*--head|--head.*curl", text, re.S), \
            f"{name}: existence probe must be a HEAD request"


def test_capture_scripts_publish_capture_info():
    """The registry UI shows only the opaque hash version — every publish
    must carry a capture-info.txt naming the source file, its full sha256,
    and the capture date."""
    for name, text, source in (("pip", PIP_CAPTURE, "requirements.lock"),
                               ("npm", NPM_CAPTURE, "frontend/package-lock.json")):
        assert "capture-info.txt" in text, name
        assert f"source: {source}" in text, name
        assert "captured:" in text, name


def test_capture_before_push_is_documented():
    """The ordering rule IS the drift guard (an unpublished capture 404s the
    MR pipeline) — the tooling must say it where developers look."""
    assert "BEFORE" in ORCH
    for text in (MAKEFILE, ORCH):
        assert "404" in text
