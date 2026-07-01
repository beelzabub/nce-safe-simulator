"""Age-based retention for the web UI's import/export temp files.

The web UI writes browser-uploaded import files to ``uploads/`` and generated
exports to ``public/exports/``. Left alone these grow unbounded on the server
(or EFS in the cloud). This prunes files older than a configurable TTL.

Only those two UI temp dirs are ever touched. Explicit CLI output paths live
elsewhere on disk and are never affected — so the CLI import/export contract is
unchanged.

TTL is controlled by ``TEMP_FILE_RETENTION_HOURS`` (default 24). A value of 0
(or negative) disables pruning entirely.
"""
import os
import time
from pathlib import Path

# UI temp dirs subject to retention. CLI explicit paths are never in here.
TEMP_DIRS = (Path("uploads"), Path("public/exports"))

_DEFAULT_RETENTION_HOURS = 24.0


def retention_seconds() -> float:
    """Configured TTL in seconds; <= 0 means pruning is disabled."""
    try:
        hours = float(os.environ.get("TEMP_FILE_RETENTION_HOURS", _DEFAULT_RETENTION_HOURS))
    except ValueError:
        hours = _DEFAULT_RETENTION_HOURS
    return hours * 3600.0


def prune_temp_files(dirs=TEMP_DIRS, max_age_seconds=None):
    """Delete files in ``dirs`` older than the TTL.

    Returns the list of removed ``Path``s. Missing dirs are skipped, and files
    that vanish or can't be removed mid-pass (e.g. a racing download) are left
    for the next pass rather than raising.
    """
    if max_age_seconds is None:
        max_age_seconds = retention_seconds()
    if max_age_seconds <= 0:
        return []  # pruning disabled

    cutoff = time.time() - max_age_seconds
    removed = []
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for entry in d.iterdir():
            if not entry.is_file():
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    removed.append(entry)
            except OSError:
                # File raced away or is locked — skip; caught next pass.
                continue
    return removed
