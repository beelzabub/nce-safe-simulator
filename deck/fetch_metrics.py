"""
Fetch live project metrics for the status deck (deck/build_deck.py): issue/MR
counts, commit velocity, and SLOC breakdown. Writes deck/metrics.json.

Run this from within the repo (uses `glab api projects/:id/...`, which resolves the
project from the current git remote - no hardcoded project ID) and `git log` against
the current checkout.

Usage:
  python3 deck/fetch_metrics.py [--out deck/metrics.json]
"""
import argparse
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)

# directories (relative to repo root) to break SLOC out by, in the order they should
# be reported. Anything not listed falls under "other".
SLOC_BUCKETS = [
    ("mixins", ["mixins"], [".py"]),
    ("tests", ["tests"], [".py"]),
    ("marimo", ["marimo"], [".py"]),
    ("server", ["server"], [".py"]),
    ("cdk", ["cdk"], [".py"]),
    ("diagrams", ["diagrams"], [".py"]),
    ("cli-entry", ["."], [".py"]),  # NceGitLab.py etc at repo root, handled specially below
    ("frontend-vue", ["frontend/src"], [".vue"]),
    ("frontend-js", ["frontend/src"], [".js", ".ts"]),
]
EXCLUDE_DIRS = {".git", ".venv", "node_modules", "public", "dist", "__pycache__"}


def _decode_concatenated_json_arrays(text):
    """glab api --paginate concatenates one JSON array per page with no separator
    (e.g. "[...][...]"), so a plain json.loads() fails on anything past page 1."""
    decoder = json.JSONDecoder()
    items = []
    idx = 0
    text = text.strip()
    while idx < len(text):
        obj, end = decoder.raw_decode(text, idx)
        items.extend(obj)
        idx = end
    return items


def _glab_paginate(endpoint):
    out = subprocess.run(
        ["glab", "api", endpoint, "--paginate"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return _decode_concatenated_json_arrays(out)


def fetch_issue_mr_counts():
    issues = _glab_paginate("projects/:id/issues?state=all&per_page=100")
    mrs = _glab_paginate("projects/:id/merge_requests?state=all&per_page=100")
    return {
        "issues_total": len(issues),
        "issues_closed": sum(1 for i in issues if i["state"] == "closed"),
        "issues_open": sum(1 for i in issues if i["state"] == "opened"),
        "mrs_total": len(mrs),
        "mrs_merged": sum(1 for m in mrs if m["state"] == "merged"),
        "mrs_closed": sum(1 for m in mrs if m["state"] == "closed"),
        "mrs_open": sum(1 for m in mrs if m["state"] == "opened"),
    }


def _git(args):
    return subprocess.run(["git"] + args, cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def fetch_commit_stats(ref="HEAD", until=None):
    """Commit counts for ``ref``, optionally bounded at ``until``.

    Both arguments matter for a rebuild. Plain ``git log`` reads whatever the
    build clone happens to have checked out, so a rebuild run from a working
    branch reports that branch's commits as the project's — and an off-cadence
    rebuild counts commits made after the period the deck covers. Pass the ref
    the deck reports on and the period-end date, and the numbers match what a
    build on the day would have produced.
    """
    rng = [ref] + ([f"--until={until} 23:59:59"] if until else [])
    total = int(_git(["log", "--oneline"] + rng).count("\n"))
    first_date = _git(["log", "--reverse", "--format=%ad", "--date=short"] + rng).splitlines()[0]
    last_date = _git(["log", "-1", "--format=%ad", "--date=short"] + rng).strip()
    months = _git(["log", "--format=%ad", "--date=format:%Y-%m"] + rng).splitlines()
    monthly = Counter(months)
    return {
        "commits_total": total,
        "first_commit_date": first_date,
        "last_commit_date": last_date,
        "monthly_commit_trend": dict(sorted(monthly.items())),
    }


def _count_lines(path):
    try:
        with open(path, "r", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def fetch_sloc():
    buckets = Counter()
    file_counts = Counter()
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        rel_dir = os.path.relpath(dirpath, REPO_ROOT)
        for fname in filenames:
            ext = os.path.splitext(fname)[1]
            full = os.path.join(dirpath, fname)
            if rel_dir.startswith("mixins") and ext == ".py":
                key = "mixins"
            elif rel_dir.startswith("tests") and ext == ".py":
                key = "tests"
            elif rel_dir.startswith("marimo") and ext == ".py":
                key = "marimo"
            elif rel_dir.startswith("server") and ext == ".py":
                key = "server"
            elif rel_dir.startswith("cdk") and ext == ".py":
                key = "cdk"
            elif rel_dir.startswith("diagrams") and ext == ".py":
                key = "diagrams"
            elif rel_dir == "." and ext == ".py":
                key = "cli-entry"
            elif rel_dir.startswith(os.path.join("frontend", "src")) and ext == ".vue":
                key = "frontend-vue"
            elif rel_dir.startswith(os.path.join("frontend", "src")) and ext in (".js", ".ts"):
                key = "frontend-js"
            else:
                continue
            lines = _count_lines(full)
            buckets[key] += lines
            file_counts[key] += 1
    python_keys = ["mixins", "tests", "marimo", "server", "cdk", "diagrams", "cli-entry"]
    frontend_keys = ["frontend-vue", "frontend-js"]
    return {
        "by_bucket_lines": dict(buckets),
        "by_bucket_files": dict(file_counts),
        "python_total": sum(buckets[k] for k in python_keys),
        "frontend_total": sum(buckets[k] for k in frontend_keys),
        "grand_total": sum(buckets.values()),
    }


def _is_source(rel_path):
    """Match fetch_sloc's bucket rules for a git-tracked path: root-level .py
    (the CLI entry), .py under the tracked Python dirs, and frontend/src Vue/JS."""
    ext = os.path.splitext(rel_path)[1]
    if ext == ".py":
        if "/" not in rel_path:
            return True
        return rel_path.split("/", 1)[0] in ("mixins", "tests", "marimo", "server", "cdk", "diagrams")
    if rel_path.startswith("frontend/src/"):
        return ext in (".vue", ".js", ".ts")
    return False


def _sloc_at_commit(commit):
    """Total source lines at a commit, read straight from the object store
    (no checkout): list the tree's source blobs, then stream them through one
    `git cat-file --batch` and count lines (newlines, +1 for an unterminated
    final line — matching fetch_sloc's per-file line count)."""
    tree = _git(["ls-tree", "-r", commit])
    blobs = []
    for line in tree.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 3 and parts[1] == "blob" and _is_source(path):
            blobs.append(parts[2])
    if not blobs:
        return 0
    proc = subprocess.run(["git", "cat-file", "--batch"], cwd=REPO_ROOT,
                          input="".join(o + "\n" for o in blobs).encode(),
                          capture_output=True, check=True)
    out, total, i = proc.stdout, 0, 0
    while i < len(out):
        nl = out.index(b"\n", i)
        parts = out[i:nl].split()
        i = nl + 1
        if len(parts) != 3 or parts[1] != b"blob":
            continue  # 'missing' etc.
        size = int(parts[2])
        content = out[i:i + size]
        i += size + 1
        total += content.count(b"\n") + (1 if size and not content.endswith(b"\n") else 0)
    return total


def fetch_sloc_by_week():
    """SLOC at the tip of each week from first to last commit — the code-growth
    curve for the deck's 'SLOC by Week' chart."""
    commits = []
    for line in _git(["log", "--format=%H %cI"]).splitlines():
        h, iso = line.split(" ", 1)
        # git emits a trailing 'Z' for UTC, which datetime.fromisoformat rejects
        # before Python 3.11 — normalize it so the build runs on 3.9/3.10 too.
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        commits.append((h, datetime.fromisoformat(iso)))
    commits.sort(key=lambda c: c[1])
    if not commits:
        return {}
    first_dt, last_dt = commits[0][1], commits[-1][1]
    points, t = [], first_dt
    while t < last_dt:
        t += timedelta(weeks=1)
        points.append(min(t, last_dt))
    if not points or points[-1] != last_dt:
        points.append(last_dt)
    series, ci, latest = {}, 0, None
    for p in points:
        while ci < len(commits) and commits[ci][1] <= p:
            latest = commits[ci][0]
            ci += 1
        if latest is not None:
            series[p.strftime("%m/%d")] = _sloc_at_commit(latest)
    return series


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "metrics.json"))
    ap.add_argument("--ref", default="HEAD",
                    help="git ref the commit stats describe (default: whatever is checked "
                         "out). A rebuild should pass the ref the deck reports on, e.g. "
                         "origin/develop — see issue #309.")
    ap.add_argument("--until", metavar="YYYY-MM-DD",
                    help="ignore commits after this date, so an off-cadence rebuild "
                         "reproduces the numbers a build on the day would have produced. "
                         "Pass the deck's period end (the Friday).")
    args = ap.parse_args()

    metrics = {}
    metrics.update(fetch_issue_mr_counts())
    metrics.update(fetch_commit_stats(ref=args.ref, until=args.until))
    metrics["sloc"] = fetch_sloc()
    metrics["sloc_by_week"] = fetch_sloc_by_week()

    with open(args.out, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Wrote {args.out}")
    print(json.dumps(metrics, indent=2)[:800])


if __name__ == "__main__":
    main()
