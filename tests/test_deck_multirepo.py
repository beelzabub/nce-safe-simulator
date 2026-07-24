"""Deck build multi-repo coverage (issue #268): companion-project issue rows,
work-state-sync exclusion, and the closed-in-window helper. Deck deps
(python-pptx) are optional in the test env, so the module import is guarded."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("pptx")
sys.path.insert(0, str(Path(__file__).parent.parent / "deck"))

import build_deck  # noqa: E402


def _raw(iid, title, labels=(), closed_at=None, state="closed"):
    return {"iid": iid, "title": title, "labels": list(labels),
            "closed_at": closed_at, "state": state, "assignee": None,
            "description": ""}


class _FakeRun:
    """Stands in for subprocess.run: routes glab api calls to canned per-project
    payloads; a project mapped to None fails (returncode 1, or CalledProcessError
    under check=True) — the shape of an unreachable companion project."""

    def __init__(self, payloads):
        self.payloads = payloads  # url fragment -> list-of-issues or None

    def __call__(self, cmd, **kw):
        url = cmd[2]
        for frag, issues in self.payloads.items():
            if frag in url:
                if issues is None:
                    if kw.get("check"):
                        raise subprocess.CalledProcessError(1, cmd)
                    return subprocess.CompletedProcess(cmd, 1, "", "glab: 404")
                return subprocess.CompletedProcess(cmd, 0, json.dumps(issues), "")
        raise AssertionError(f"unexpected glab url: {url}")


# ---------------------------------------------------------------------------
# _issue_row / _is_deck_issue / _closed_in_window
# ---------------------------------------------------------------------------

def test_issue_row_main_repo_ref_is_bare():
    row = build_deck._issue_row(_raw(42, "A thing", labels=["type::bug"]))
    assert row["ref"] == "#42" and row["repo"] == "" and row["type"] == "bug"


def test_issue_row_companion_ref_is_prefixed():
    row = build_deck._issue_row(_raw(7, "Restructure"), repo="nce-git-ops")
    assert row["ref"] == "nce-git-ops#7" and row["repo"] == "nce-git-ops"


def test_work_state_sync_rows_are_not_deck_issues():
    assert not build_deck._is_deck_issue(
        build_deck._issue_row(_raw(277, "Work state sync - 2026-07-23 21:48 UTC")))
    assert build_deck._is_deck_issue(build_deck._issue_row(_raw(1, "Real work")))


def test_closed_in_window_boundaries():
    since = datetime(2026, 7, 17, 21, 0, tzinfo=timezone.utc)
    assert build_deck._closed_in_window({"closed_at": "2026-07-20T00:00:00Z"}, since)
    assert not build_deck._closed_in_window({"closed_at": "2026-07-17T20:59:59Z"}, since)
    assert not build_deck._closed_in_window({"closed_at": None}, since)
    assert not build_deck._closed_in_window({"closed_at": "not-a-date"}, since)


# ---------------------------------------------------------------------------
# fetch_issues
# ---------------------------------------------------------------------------

def test_fetch_issues_merges_both_projects_and_drops_wss():
    fake = _FakeRun({
        "projects/:id/": [_raw(276, "Sim bug", ["type::bug"]),
                          _raw(277, "Work state sync - 2026-07-23")],
        "nce-git-ops": [_raw(7, "Restructure")],
    })
    with patch.object(build_deck.subprocess, "run", fake):
        rows = build_deck.fetch_issues()
    assert [r["ref"] for r in rows] == ["#276", "nce-git-ops#7"]


def test_fetch_issues_survives_unreachable_companion():
    fake = _FakeRun({"projects/:id/": [_raw(1, "Only sim")], "nce-git-ops": None})
    with patch.object(build_deck.subprocess, "run", fake):
        rows = build_deck.fetch_issues()
    assert [r["ref"] for r in rows] == ["#1"]


def test_fetch_issues_fails_hard_when_main_project_unreachable():
    fake = _FakeRun({"projects/:id/": None, "nce-git-ops": [_raw(7, "x")]})
    with patch.object(build_deck.subprocess, "run", fake):
        with pytest.raises(subprocess.CalledProcessError):
            build_deck.fetch_issues()


# ---------------------------------------------------------------------------
# fetch_slides_issues
# ---------------------------------------------------------------------------

def test_fetch_slides_issues_spans_projects_and_window():
    since = datetime(2026, 7, 17, 21, 0, tzinfo=timezone.utc)
    fake = _FakeRun({
        "projects/:id/": [_raw(276, "In window", closed_at="2026-07-23T21:00:00Z"),
                          _raw(200, "Old", closed_at="2026-06-01T00:00:00Z")],
        "nce-git-ops": [_raw(16, "AppSet", closed_at="2026-07-20T20:46:00Z")],
    })
    with patch.object(build_deck.subprocess, "run", fake):
        rows = build_deck.fetch_slides_issues(since)
    assert [r["ref"] for r in rows] == ["#276", "nce-git-ops#16"]
