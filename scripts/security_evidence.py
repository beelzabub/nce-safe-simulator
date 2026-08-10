#!/usr/bin/env python3
"""Generate the in-repo security evidence (issue #304, Section 2).

Pulls the project's Vulnerability Report state via the GraphQL API and the scan
report artifacts from a pipeline, then writes a committable evidence pair:

  docs/security/evidence.json  — machine: per-scanner counts, dispositions,
                                 scanner versions, scanned SHA, pipeline, and
                                 SHA-256 of each full report artifact.
  docs/security/EVIDENCE.md    — human: the whole posture at a glance, incl.
                                 every dismissal grouped with its reason, so the
                                 security state is readable in the repo instead
                                 of clicking through Secure -> Vulnerability report.

The raw gl-*-report.json artifacts are NEVER committed (churny, path-noisy, and
the secret report can embed matched secrets) — only their hashes.

Usage:
  scripts/security_evidence.py --pipeline 2746483470 --sha 2dbd11f0 \
      [--generated-at 2026-08-10T09:00:00Z] [--out docs/security]
"""
import argparse, hashlib, json, os, subprocess, sys
from collections import defaultdict

PROJECT = "gl-demo-ultimate-lmwilliams/nce-safe-simulator"
BASE_URL = "https://gitlab.com/" + PROJECT

# Container OS-package groups for the readable dismissal table (mirrors the D4 review, #304).
CONTAINER_GROUPS = {
    "util-linux": ["bsdutils","libblkid1","liblastlog2-2","libmount1","libsmartcols1","libuuid1","login","mount","util-linux"],
    "systemd": ["libsystemd0","libudev1"], "ncurses": ["libncursesw6","libtinfo6","ncurses-base","ncurses-bin"],
    "shell-utils": ["tar","gzip","coreutils","bash","diffutils","sysvinit-utils"],
    "pam": ["libpam-modules","libpam-modules-bin","libpam-runtime","libpam0g"], "shadow": ["passwd","login.defs"],
    "misc-base": ["libattr1","libacl1","libbz2-1.0","zlib1g","apt","libapt-pkg7.0"], "glibc": ["libc6","libc-bin"],
    "glib": ["libglib2.0-0t64"], "sqlite": ["libsqlite3-0"], "expat": ["libexpat1"], "libpng": ["libpng16-16t64"],
    "perl": ["perl-base"],
}
PKG2GROUP = {p: g for g, pkgs in CONTAINER_GROUPS.items() for p in pkgs}
SCANNER_LABEL = {"CONTAINER_SCANNING": "Container Scanning", "DEPENDENCY_SCANNING": "Dependency Scanning",
                 "SAST": "SAST", "SECRET_DETECTION": "Secret Detection", "DAST": "DAST"}
REASON_LABEL = {"NOT_APPLICABLE": "Not applicable", "ACCEPTABLE_RISK": "Acceptable risk",
                "FALSE_POSITIVE": "False positive", "MITIGATING_CONTROL": "Mitigating control",
                "USED_IN_TESTS": "Used in tests", None: "—"}


def gql(q):
    out = subprocess.run(["glab", "api", "graphql", "-f", f"query={q}"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def api(path, dest=None):
    r = subprocess.run(["glab", "api", path], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def fetch_vulns():
    out, cursor = [], None
    while True:
        after = f', after: "{cursor}"' if cursor else ""
        d = gql(f'''query {{ project(fullPath: "{PROJECT}") {{
          vulnerabilities(first: 100{after}) {{
            nodes {{ state severity reportType dismissalReason title
              location {{ ... on VulnerabilityLocationContainerScanning {{ dependency {{ package {{ name }} }} }}
                          ... on VulnerabilityLocationDependencyScanning {{ dependency {{ package {{ name }} }} }} }} }}
            pageInfo {{ hasNextPage endCursor }} }} }} }}''')
        v = d["data"]["project"]["vulnerabilities"]
        out += v["nodes"]
        if not v["pageInfo"]["hasNextPage"]:
            break
        cursor = v["pageInfo"]["endCursor"]
    return out


def pkg_of(n):
    return ((n.get("location") or {}).get("dependency") or {}).get("package", {}).get("name")


def scanners_meta(project_id, pipeline):
    """SHA-256 + scanner version per report artifact from the scan pipeline."""
    jobs = json.loads(api(f"projects/{project_id}/pipelines/{pipeline}/jobs?per_page=60") or "[]")
    reports = {"container_scanning": "gl-container-scanning-report.json",
               "gemnasium-dependency_scanning": "gl-dependency-scanning-report.json",
               "semgrep-sast": "gl-sast-report.json", "secret_detection": "gl-secret-detection-report.json"}
    meta = []
    for job in jobs:
        rf = reports.get(job["name"])
        if not rf:
            continue
        raw = api(f"projects/{project_id}/jobs/{job['id']}/artifacts/{rf}")
        if not raw:
            continue
        sha = hashlib.sha256(raw.encode()).hexdigest()
        try:
            scan = json.loads(raw).get("scan", {})
            sc = scan.get("scanner", {})
            meta.append({"job": job["name"], "report": rf, "scanner": sc.get("name"),
                         "version": sc.get("version"), "type": scan.get("type"), "report_sha256": sha})
        except Exception:
            meta.append({"job": job["name"], "report": rf, "report_sha256": sha})
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", required=True)
    ap.add_argument("--sha", required=True)
    ap.add_argument("--generated-at", required=True, help="ISO8601, e.g. 2026-08-10T09:00:00Z")
    ap.add_argument("--project-id", default="81726491")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "security"))
    args = ap.parse_args()

    vulns = fetch_vulns()
    # counts[scanner][state] and severity per scanner
    counts = defaultdict(lambda: defaultdict(int))
    sev = defaultdict(lambda: defaultdict(int))
    # dismissed container grouped by package-group + reason; other scanners by reason
    cont_groups = defaultdict(lambda: {"count": 0, "reason": None})
    other_dismissed = defaultdict(list)   # scanner -> [(title, reason)]
    resolved = defaultdict(int)
    for n in vulns:
        rt, st = n["reportType"], n["state"]
        counts[rt][st] += 1
        if st == "DETECTED":
            sev[rt][n["severity"]] += 1
        if st == "DISMISSED":
            if rt == "CONTAINER_SCANNING":
                g = PKG2GROUP.get(pkg_of(n), "other")
                cont_groups[g]["count"] += 1
                cont_groups[g]["reason"] = n["dismissalReason"]
            else:
                other_dismissed[rt].append((n["title"], n["dismissalReason"]))
        if st == "RESOLVED":
            resolved[rt] += 1

    scanners = scanners_meta(args.project_id, args.pipeline)

    evidence = {
        "project": PROJECT, "scanned_sha": args.sha, "generated_at": args.generated_at,
        "scan_pipeline": {"id": int(args.pipeline), "url": f"{BASE_URL}/-/pipelines/{args.pipeline}"},
        "totals": {"detected": sum(c.get("DETECTED", 0) for c in counts.values()),
                   "dismissed": sum(c.get("DISMISSED", 0) for c in counts.values()),
                   "resolved": sum(c.get("RESOLVED", 0) for c in counts.values())},
        "by_scanner": {rt: {"detected": counts[rt].get("DETECTED", 0),
                            "dismissed": counts[rt].get("DISMISSED", 0),
                            "resolved": counts[rt].get("RESOLVED", 0),
                            "detected_by_severity": dict(sev[rt])} for rt in sorted(counts)},
        "scanners": scanners,
        "note": "Raw gl-*-report.json artifacts are intentionally not committed; only their SHA-256 hashes are recorded.",
    }
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "evidence.json"), "w") as f:
        json.dump(evidence, f, indent=2)

    # ---- EVIDENCE.md (the readable posture) ----
    L = []
    L.append("# Security posture — NCE Safe Simulator\n")
    L.append(f"> **Generated {args.generated_at}** from `develop @ {args.sha}`, scan pipeline "
             f"[#{args.pipeline}]({BASE_URL}/-/pipelines/{args.pipeline}). Regenerate with "
             f"`scripts/security_evidence.py` after a scan.\n")
    t = evidence["totals"]
    L.append(f"## {t['detected']} Detected · {t['dismissed']} Dismissed · {t['resolved']} Resolved\n")
    L.append("Every finding is either fixed (Resolved) or dispositioned with a written reason "
             "(Dismissed). This file is the source of truth so you don't have to page through "
             "*Secure → Vulnerability report*.\n")
    L.append("| Scanner | Detected | Dismissed | Resolved |")
    L.append("|---|---:|---:|---:|")
    for rt in sorted(counts):
        c = counts[rt]
        L.append(f"| {SCANNER_LABEL.get(rt, rt)} | {c.get('DETECTED',0)} | {c.get('DISMISSED',0)} | {c.get('RESOLVED',0)} |")
    L.append(f"| **Total** | **{t['detected']}** | **{t['dismissed']}** | **{t['resolved']}** |\n")

    if cont_groups:
        L.append("## Dismissed — Container Scanning (no fix available in Debian trixie)\n")
        L.append("| Package group | Findings | Reason |")
        L.append("|---|---:|---|")
        for g in sorted(cont_groups, key=lambda x: -cont_groups[x]["count"]):
            d = cont_groups[g]
            pkgs = ", ".join(CONTAINER_GROUPS.get(g, [g]))
            L.append(f"| `{g}` ({pkgs}) | {d['count']} | {REASON_LABEL.get(d['reason'], d['reason'])} |")
        L.append("\n_Full per-finding rationale is on each vulnerability (Secure → Vulnerability report → the finding), citing the D4 review (#304, note 3650491306)._\n")

    for rt in sorted(other_dismissed):
        L.append(f"## Dismissed — {SCANNER_LABEL.get(rt, rt)}\n")
        L.append("| Finding | Reason |")
        L.append("|---|---|")
        for title, reason in other_dismissed[rt]:
            L.append(f"| {title} | {REASON_LABEL.get(reason, reason)} |")
        L.append("")

    if scanners:
        L.append("## Scanners (this evidence)\n")
        L.append("| Job | Scanner | Version | Report SHA-256 |")
        L.append("|---|---|---|---|")
        for s in scanners:
            L.append(f"| {s.get('job')} | {s.get('scanner') or '—'} | {s.get('version') or '—'} | `{s['report_sha256'][:16]}…` |")
        L.append("")

    with open(os.path.join(args.out, "EVIDENCE.md"), "w") as f:
        f.write("\n".join(L) + "\n")

    print(f"wrote {args.out}/evidence.json and EVIDENCE.md")
    print(f"  totals: {t['detected']} detected, {t['dismissed']} dismissed, {t['resolved']} resolved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
