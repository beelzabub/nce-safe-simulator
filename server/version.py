"""Application version resolution (issue #173).

The displayed version is resolved once per process, in precedence order:

1. ``NCE_VERSION`` env var — explicit deploy-time override.
2. ``version.json`` — baked at image build (Dockerfile ARGs carry the git
   tag/commit into the container, where no .git exists).
3. Live git (local checkouts): an exact tag on HEAD is a release build and
   wins; otherwise a branch build shows ``nce-<short-hash>``.
4. The committed ``VERSION`` file — source-tarball fallback.
5. ``nce-unknown``.
"""

import json
import os
import subprocess
from pathlib import Path

_cached = None


def _git(*args):
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True, timeout=5)
    return out.stdout.strip() if out.returncode == 0 else None


def resolve_version() -> str:
    env = os.environ.get("NCE_VERSION", "").strip()
    if env:
        return env

    baked = Path("version.json")
    if baked.is_file():
        try:
            v = json.loads(baked.read_text()).get("version", "").strip()
            if v:
                return v
        except ValueError:
            pass

    try:
        tag = _git("describe", "--tags", "--exact-match")
        if tag:
            return tag
        commit = _git("rev-parse", "--short", "HEAD")
        if commit:
            return f"nce-{commit}"
    except (OSError, subprocess.TimeoutExpired):
        pass

    version_file = Path("VERSION")
    if version_file.is_file():
        v = version_file.read_text().strip()
        if v:
            return v

    return "nce-unknown"


def app_version() -> str:
    """resolve_version() memoized for the life of the process."""
    global _cached
    if _cached is None:
        _cached = resolve_version()
    return _cached
