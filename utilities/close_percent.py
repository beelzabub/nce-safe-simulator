"""
Randomly closes a given percentage of open epics and issues in the configured group.

Useful for simulating PI progress against lorem test data.

Usage:
    python close_percent.py [--config nce_gitlab_config.json] [--percent 30] [--seed 42] [--dry-run]
"""

import argparse
import json
import random
import sys
from pathlib import Path

import gitlab


def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"ERROR: config file '{path}' not found.")
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def collect_epics(gl, group):
    """Return all open epics across the group hierarchy (recursive)."""
    results = []

    def _walk(grp):
        for epic in grp.epics.list(all=True, state="opened"):
            results.append((grp, epic))
        for sg in grp.subgroups.list(all=True):
            _walk(gl.groups.get(sg.id))

    _walk(group)
    return results


def collect_issues(gl, group):
    """Return all open issues across every project in the group hierarchy."""
    results = []
    for proj in group.projects.list(all=True, include_subgroups=True):
        if "_deletion_scheduled" in proj.path:
            continue
        try:
            full_p = gl.projects.get(proj.id)
            for issue in full_p.issues.list(all=True, state="opened"):
                results.append((full_p, issue))
        except Exception as e:
            print(f"  WARNING: could not fetch issues for '{proj.path_with_namespace}': {e}")
    return results


def sample_percent(items, percent, rng):
    k = max(0, round(len(items) * percent / 100))
    return rng.sample(items, k)


def close_epics(to_close, dry_run):
    ok = 0
    for grp, epic in to_close:
        label = f"Epic #{epic.iid} '{epic.title[:50]}' in {grp.full_path}"
        if dry_run:
            print(f"  DRY   {label}")
            ok += 1
            continue
        try:
            epic.state_event = "close"
            epic.save()
            print(f"  CLOSED {label}")
            ok += 1
        except Exception as e:
            print(f"  ERROR  {label}: {e}")
    return ok


def close_issues(to_close, dry_run):
    ok = 0
    for proj, issue in to_close:
        label = f"Issue #{issue.iid} '{issue.title[:50]}' in {proj.path_with_namespace}"
        if dry_run:
            print(f"  DRY   {label}")
            ok += 1
            continue
        try:
            issue.state_event = "close"
            issue.save()
            print(f"  CLOSED {label}")
            ok += 1
        except Exception as e:
            print(f"  ERROR  {label}: {e}")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config",  default="nce_gitlab_config.json")
    parser.add_argument("--percent", type=float, default=30.0,
                        help="Percentage of open items to close (default: 30)")
    parser.add_argument("--seed",    type=int, default=None,
                        help="Random seed for reproducibility")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be closed without making changes")
    args = parser.parse_args()

    if not (0 <= args.percent <= 100):
        print("ERROR: --percent must be between 0 and 100.")
        sys.exit(1)

    cfg = load_config(args.config)
    rng = random.Random(args.seed)

    gl = gitlab.Gitlab(cfg["url"], private_token=cfg["private_token"])
    gl.auth()

    group_name = cfg["parent_group"]
    groups = [g for g in gl.groups.list(search=group_name, get_all=True)
              if g.name == group_name]
    if not groups:
        print(f"ERROR: group '{group_name}' not found.")
        sys.exit(1)
    group = gl.groups.get(groups[0].id)
    print(f"Group: {group.full_path}")
    print(f"Percent to close: {args.percent}%"
          + (f"  (seed={args.seed})" if args.seed is not None else ""))
    if args.dry_run:
        print("(dry-run — no changes will be saved)\n")

    print("\nCollecting open epics...")
    all_epics = collect_epics(gl, group)
    epic_sample = sample_percent(all_epics, args.percent, rng)
    print(f"  {len(all_epics)} open  →  closing {len(epic_sample)}")

    print("\nCollecting open issues...")
    all_issues = collect_issues(gl, group)
    issue_sample = sample_percent(all_issues, args.percent, rng)
    print(f"  {len(all_issues)} open  →  closing {len(issue_sample)}")

    print("\n--- Closing epics ---")
    epics_closed = close_epics(epic_sample, args.dry_run)

    print("\n--- Closing issues ---")
    issues_closed = close_issues(issue_sample, args.dry_run)

    print(f"\nDone.  Epics closed: {epics_closed}  Issues closed: {issues_closed}")
    if args.dry_run:
        print("(dry-run — no changes saved)")


if __name__ == "__main__":
    main()
