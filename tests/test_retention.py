"""Tests for age-based retention of import/export temp files (Refs #127).

Covers:
  * files older than the TTL are pruned from uploads/ and public/exports/;
  * fresh files (and subdirectories) are left alone;
  * missing dirs are handled without error;
  * TTL of 0 disables pruning;
  * only the two named temp dirs are touched — an explicit CLI-style path
    elsewhere on disk is never affected (the #127 hard constraint).
"""
import os
import time
from pathlib import Path

import pytest

from server.retention import prune_temp_files, retention_seconds

pytestmark = pytest.mark.unit


def _touch(path: Path, age_seconds: float = 0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    if age_seconds:
        past = time.time() - age_seconds
        os.utime(path, (past, past))
    return path


def test_prunes_only_aged_files(tmp_path):
    uploads = tmp_path / "uploads"
    exports = tmp_path / "public" / "exports"

    old_upload = _touch(uploads / "old.csv", age_seconds=48 * 3600)
    new_upload = _touch(uploads / "new.csv", age_seconds=0)
    old_export = _touch(exports / "old-export.csv", age_seconds=48 * 3600)
    new_export = _touch(exports / "new-export.csv", age_seconds=0)

    removed = prune_temp_files(dirs=(uploads, exports), max_age_seconds=24 * 3600)

    assert set(removed) == {old_upload, old_export}
    assert not old_upload.exists()
    assert not old_export.exists()
    assert new_upload.exists()
    assert new_export.exists()


def test_missing_dirs_are_skipped(tmp_path):
    # Neither dir exists — must not raise, must remove nothing.
    removed = prune_temp_files(
        dirs=(tmp_path / "uploads", tmp_path / "public" / "exports"),
        max_age_seconds=1,
    )
    assert removed == []


def test_subdirectories_are_left_alone(tmp_path):
    exports = tmp_path / "exports"
    exports.mkdir()
    old_dir = exports / "nested"
    old_dir.mkdir()
    os.utime(old_dir, (0, 0))  # ancient dir

    removed = prune_temp_files(dirs=(exports,), max_age_seconds=1)

    assert removed == []
    assert old_dir.is_dir()


def test_zero_ttl_disables_pruning(tmp_path):
    exports = tmp_path / "exports"
    _touch(exports / "ancient.csv", age_seconds=10 ** 7)

    assert prune_temp_files(dirs=(exports,), max_age_seconds=0) == []
    assert (exports / "ancient.csv").exists()


def test_explicit_path_outside_temp_dirs_is_never_touched(tmp_path):
    """The #127 hard constraint: CLI explicit output paths are untouched."""
    exports = tmp_path / "public" / "exports"
    _touch(exports / "aged-ui-export.csv", age_seconds=48 * 3600)

    # An explicit CLI-style path living elsewhere, also aged out.
    cli_out = _touch(tmp_path / "some" / "cli" / "epics.csv", age_seconds=48 * 3600)

    prune_temp_files(dirs=(tmp_path / "uploads", exports), max_age_seconds=24 * 3600)

    assert cli_out.exists()  # never enumerated → never removed


def test_retention_seconds_env_override(monkeypatch):
    monkeypatch.setenv("TEMP_FILE_RETENTION_HOURS", "2")
    assert retention_seconds() == 2 * 3600.0
    monkeypatch.setenv("TEMP_FILE_RETENTION_HOURS", "bogus")
    assert retention_seconds() == 24 * 3600.0  # falls back to default
    monkeypatch.delenv("TEMP_FILE_RETENTION_HOURS", raising=False)
    assert retention_seconds() == 24 * 3600.0
