"""
Fetch live project metrics for the sprint-review deck (deck/build_deck.py): issue/MR
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


def fetch_commit_stats():
    total = int(_git(["log", "--oneline"]).count("\n"))
    first_date = _git(["log", "--reverse", "--format=%ad", "--date=short"]).splitlines()[0]
    last_date = _git(["log", "-1", "--format=%ad", "--date=short"]).strip()
    months = _git(["log", "--format=%ad", "--date=format:%Y-%m"]).splitlines()
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "metrics.json"))
    args = ap.parse_args()

    metrics = {}
    metrics.update(fetch_issue_mr_counts())
    metrics.update(fetch_commit_stats())
    metrics["sloc"] = fetch_sloc()

    with open(args.out, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Wrote {args.out}")
    print(json.dumps(metrics, indent=2)[:800])


if __name__ == "__main__":
    main()
