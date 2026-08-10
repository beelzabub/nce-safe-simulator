#!/usr/bin/env python3
"""Pre-capture checks for the weekly deck (issue #258, Gaps B2 + C).

Two checks against the live app's /api/tools, so a tool moving, being renamed,
or being added can't silently produce a broken or incomplete deck:

  preflight — every shots.yaml `select` still names a real tool
              (catches a renamed/removed tool BEFORE the long capture run, not
              as one failed shot mid-run).
  coverage  — every tool has a screenshot OR is listed in `excluded_tools`
              (catches a NEW tool nobody wrote a shot for — the #258 item-3
              "5 of 8 Import/Export tools missing" case).

The picker's *section* labels (shots.yaml `expand:`) are grouped in the
frontend and are NOT exposed by /api/tools, so they aren't validated here; a
section move degrades to one skipped shot via capture_screenshots.py's fault
tolerance (commit 54aae1a) rather than a dead run.

Usage:
  python3 deck/deck_checks.py            # report; always exit 0 (cron warn-only)
  python3 deck/deck_checks.py --strict   # exit 1 on any problem (manual / CI)
"""
import argparse
import json
import os
import re
import sys
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


def _norm(name):
    """A tool display name ('Generate Issues') to its key ('generate-issues')."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _api_base(app_url):
    # app_url is "https://host/app/"; the API is its sibling "https://host/api/tools".
    return app_url.rsplit("/app", 1)[0].rstrip("/")


def load_tools(app_url, timeout=15):
    url = _api_base(app_url) + "/api/tools"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def run_checks(shots_path):
    shots = yaml.safe_load(open(shots_path))
    tools = load_tools(shots["app_url"])
    keys = {t["key"] for t in tools}
    excluded = set(shots.get("excluded_tools") or [])

    selects, covered = [], set()
    for grp in ("ui_shots", "live_run_shots"):
        for shot in shots.get(grp) or []:
            if shot.get("select"):
                key = _norm(shot["select"])
                selects.append((grp, shot["select"], key))
                covered.add(key)

    return {
        "tool_count": len(keys),
        "covered": len(covered & keys),
        "excluded": len(excluded),
        # preflight: a select that no longer names a real tool
        "missing_selects": [(g, n, k) for g, n, k in selects if k not in keys],
        # coverage: a real tool with no shot and not deliberately excluded
        "uncovered": sorted(k for k in keys if k not in covered and k not in excluded),
        # hygiene: an exclusion for a tool that no longer exists
        "stale_exclusions": sorted(k for k in excluded if k not in keys),
    }


def main():
    ap = argparse.ArgumentParser(description="Pre-capture /api/tools checks (#258).")
    ap.add_argument("--shots", default=os.path.join(HERE, "shots.yaml"))
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any problem is found (manual/CI). Without it, "
                         "problems are reported but exit is 0 — the cron warns, never blocks.")
    args = ap.parse_args()

    try:
        r = run_checks(args.shots)
    except Exception as exc:
        print(f"deck_checks: could not reach the app or read shots "
              f"({type(exc).__name__}: {exc})", file=sys.stderr)
        return 2 if args.strict else 0

    print(f"deck_checks: {r['tool_count']} tools — {r['covered']} shot, "
          f"{r['excluded']} excluded")
    problems = 0
    for grp, name, key in r["missing_selects"]:
        print(f"  PREFLIGHT: {grp} select {name!r} -> no tool {key!r} in /api/tools "
              f"(renamed or removed?)")
        problems += 1
    for key in r["uncovered"]:
        print(f"  COVERAGE: tool {key!r} has no screenshot and is not excluded "
              f"(new tool — add a shot to shots.yaml or list it in excluded_tools)")
        problems += 1
    for key in r["stale_exclusions"]:
        print(f"  HYGIENE: excluded_tools lists {key!r}, which is no longer a tool "
              f"(drop it)")  # informational, not a blocking problem

    if not problems:
        print("deck_checks: OK — every shot maps to a tool, every tool is shot or excluded")
    return 1 if (problems and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
