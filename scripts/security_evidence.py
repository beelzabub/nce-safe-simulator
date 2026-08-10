#!/usr/bin/env python3
"""Generate the in-repo security evidence / vulnerability disposition register
(issue #304, Section 2).

Pulls every finding from the project's Vulnerability Report (GraphQL) with its
identifier, severity, disposition and *written justification*, plus the scan
report metadata, and writes a committable, audit-grade record:

  docs/security/EVIDENCE.md    — human: provenance + summary + a per-finding
                                 risk-acceptance register (ID, CVE, severity,
                                 component, disposition, justification) so a
                                 security officer can present evidence of
                                 acceptability without opening the UI.
  docs/security/dispositions.csv — flat, one row per finding (importable to a
                                 POA&M / eMASS / spreadsheet).
  docs/security/evidence.json  — machine: counts, scanner versions, scanned SHA,
                                 report SHA-256, and the full findings array.

Raw gl-*-report.json artifacts are NEVER committed — only their SHA-256.

Usage:
  scripts/security_evidence.py --pipeline 2746483470 --sha 2dbd11f0 \
      --generated-at 2026-08-10T09:00:00Z [--out docs/security]
"""
import argparse, csv, hashlib, json, os, subprocess, sys
from collections import defaultdict

PROJECT = "gl-demo-ultimate-lmwilliams/nce-safe-simulator"
BASE_URL = "https://gitlab.com/" + PROJECT
AUTHORITY = ("Reviewed and approved under issue #304 — container OS-package "
             "dispositions per the D4 review (note 3650491306), approved 2026-08-10.")

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
                 "SAST": "SAST / IaC", "SECRET_DETECTION": "Secret Detection", "DAST": "DAST"}
REASON_LABEL = {"NOT_APPLICABLE": "Not applicable", "ACCEPTABLE_RISK": "Acceptable risk",
                "FALSE_POSITIVE": "False positive", "MITIGATING_CONTROL": "Mitigating control",
                "USED_IN_TESTS": "Used in tests", None: "—"}
SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4, "UNKNOWN": 5}


def gql(q):
    out = subprocess.run(["glab", "api", "graphql", "-f", f"query={q}"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def api(path):
    r = subprocess.run(["glab", "api", path], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def fetch_vulns():
    out, cursor = [], None
    while True:
        after = f', after: "{cursor}"' if cursor else ""
        d = gql(f'''query {{ project(fullPath: "{PROJECT}") {{
          vulnerabilities(first: 100{after}) {{
            nodes {{ id state severity reportType dismissalReason title stateComment
              identifiers {{ externalType externalId }}
              location {{
                ... on VulnerabilityLocationContainerScanning {{ dependency {{ package {{ name }} }} }}
                ... on VulnerabilityLocationDependencyScanning {{ file dependency {{ package {{ name }} }} }}
                ... on VulnerabilityLocationSast {{ file startLine }} }} }}
            pageInfo {{ hasNextPage endCursor }} }} }} }}''')
        v = d["data"]["project"]["vulnerabilities"]
        out += v["nodes"]
        if not v["pageInfo"]["hasNextPage"]:
            break
        cursor = v["pageInfo"]["endCursor"]
    return out


def record(n):
    loc = n.get("location") or {}
    pkg = ((loc.get("dependency") or {}).get("package") or {}).get("name")
    f = loc.get("file")
    component = pkg or (f"{f}:{loc.get('startLine')}" if f else None) or "—"
    cve = next((i["externalId"] for i in (n.get("identifiers") or [])
                if (i.get("externalType") or "").lower() == "cve"), None)
    vid = n["id"].split("/")[-1]
    return {
        "vuln_id": vid, "url": f"{BASE_URL}/-/security/vulnerabilities/{vid}",
        "cve": cve or "", "scanner": SCANNER_LABEL.get(n["reportType"], n["reportType"]),
        "component": component, "severity": n["severity"], "state": n["state"],
        "disposition": REASON_LABEL.get(n["dismissalReason"], "Resolved (fixed)" if n["state"] == "RESOLVED" else "—"),
        "title": n["title"], "justification": (n.get("stateComment") or "").strip().replace("\n", " "),
        "report_type": n["reportType"], "pkg_group": PKG2GROUP.get(pkg) if pkg else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", required=True)
    ap.add_argument("--sha", required=True)
    ap.add_argument("--generated-at", required=True)
    ap.add_argument("--project-id", default="81726491")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "security"))
    args = ap.parse_args()

    recs = [record(n) for n in fetch_vulns()]
    dismissed = [r for r in recs if r["state"] == "DISMISSED"]
    resolved = [r for r in recs if r["state"] == "RESOLVED"]
    detected = [r for r in recs if r["state"] == "DETECTED"]

    # scanner metadata (versions + report hashes)
    jobs = json.loads(api(f"projects/{args.project_id}/pipelines/{args.pipeline}/jobs?per_page=60") or "[]")
    reports = {"container_scanning": "gl-container-scanning-report.json",
               "gemnasium-dependency_scanning": "gl-dependency-scanning-report.json",
               "semgrep-sast": "gl-sast-report.json", "secret_detection": "gl-secret-detection-report.json"}
    scanners = []
    for job in jobs:
        rf = reports.get(job["name"])
        if not rf:
            continue
        raw = api(f"projects/{args.project_id}/jobs/{job['id']}/artifacts/{rf}")
        if not raw:
            continue
        sc = (json.loads(raw).get("scan") or {}).get("scanner", {}) if raw.strip().startswith("{") else {}
        scanners.append({"job": job["name"], "scanner": sc.get("name"), "version": sc.get("version"),
                         "report_sha256": hashlib.sha256(raw.encode()).hexdigest()})

    counts = defaultdict(lambda: defaultdict(int))          # keyed by scanner label (for the MD table)
    rt_counts = defaultdict(lambda: defaultdict(int))       # keyed by report type (for evidence.json / the deck)
    for r in recs:
        counts[r["scanner"]][r["state"]] += 1
        rt_counts[r["report_type"]][r["state"]] += 1

    os.makedirs(args.out, exist_ok=True)

    # ---- evidence.json ----
    with open(os.path.join(args.out, "evidence.json"), "w") as fh:
        json.dump({
            "project": PROJECT, "scanned_sha": args.sha, "generated_at": args.generated_at,
            "scan_pipeline": {"id": int(args.pipeline), "url": f"{BASE_URL}/-/pipelines/{args.pipeline}"},
            "disposition_authority": AUTHORITY,
            "totals": {"detected": len(detected), "dismissed": len(dismissed), "resolved": len(resolved)},
            "by_scanner": {rt: {"detected": rt_counts[rt].get("DETECTED", 0),
                                "dismissed": rt_counts[rt].get("DISMISSED", 0),
                                "resolved": rt_counts[rt].get("RESOLVED", 0),
                                "detected_by_severity": {}} for rt in sorted(rt_counts)},
            "scanners": scanners,
            "findings": recs,
            "note": "Raw gl-*-report.json artifacts are not committed; only their SHA-256 is recorded.",
        }, fh, indent=2)

    # ---- dispositions.csv (flat register) ----
    with open(os.path.join(args.out, "dispositions.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["vuln_id", "cve", "scanner", "component", "severity", "state",
                    "disposition", "title", "justification", "url"])
        for r in sorted(recs, key=lambda x: (x["state"], x["scanner"], SEV_ORDER.get(x["severity"], 9))):
            w.writerow([r["vuln_id"], r["cve"], r["scanner"], r["component"], r["severity"],
                        r["state"], r["disposition"], r["title"], r["justification"], r["url"]])

    # ---- EVIDENCE.md (audit-grade register) ----
    L = ["# Security posture & vulnerability disposition register — NCE Safe Simulator\n"]
    L.append("## Provenance\n")
    L.append(f"- **Scanned commit:** `develop @ {args.sha}`")
    L.append(f"- **Scan:** pipeline [#{args.pipeline}]({BASE_URL}/-/pipelines/{args.pipeline}), {args.generated_at[:10]}")
    if scanners:
        L.append("- **Scanners:** " + ", ".join(f"{s['scanner']} {s['version']}" for s in scanners if s.get('scanner')))
    L.append(f"- **Disposition authority:** {AUTHORITY}")
    L.append("- **Source:** GitLab Vulnerability Report; regenerate with `scripts/security_evidence.py`.")
    L.append("- **Full flat register:** [`dispositions.csv`](dispositions.csv) — one row per finding.\n")

    L.append(f"## {len(detected)} open · {len(dismissed)} accepted / N/A · {len(resolved)} remediated\n")
    L.append("| Scanner | Open (Detected) | Accepted / N/A (Dismissed) | Remediated (Resolved) |")
    L.append("|---|---:|---:|---:|")
    for s in sorted(counts):
        c = counts[s]
        L.append(f"| {s} | {c.get('DETECTED',0)} | {c.get('DISMISSED',0)} | {c.get('RESOLVED',0)} |")
    L.append(f"| **Total** | **{len(detected)}** | **{len(dismissed)}** | **{len(resolved)}** |\n")

    # Acceptance register: container grouped (shared justification + enumerated members), others per-finding.
    L.append("## Accepted-risk & not-applicable register (dismissed)\n")
    L.append("Every accepted finding, its identifier and severity, and the justification for acceptance.\n")

    cont = [r for r in dismissed if r["scanner"] == "Container Scanning"]
    by_group = defaultdict(list)
    for r in cont:
        by_group[r["pkg_group"] or "other"].append(r)
    for g in sorted(by_group, key=lambda x: -len(by_group[x])):
        members = sorted(by_group[g], key=lambda x: SEV_ORDER.get(x["severity"], 9))
        disp = members[0]["disposition"]
        # shared justification = the member justification with the leading "pkg: " stripped
        j = members[0]["justification"]
        j = j.split(": ", 1)[1] if ": " in j and j.split(":", 1)[0] in PKG2GROUP else j
        L.append(f"### Container · `{g}` — {len(members)} findings · **{disp}**")
        L.append(f"*Justification:* {j}")
        L.append("")
        L.append("| Vuln | CVE | Package | Severity |")
        L.append("|---|---|---|---|")
        for r in members:
            L.append(f"| [{r['vuln_id']}]({r['url']}) | {r['cve'] or '—'} | {r['component']} | {r['severity']} |")
        L.append("")

    for scanner in ["SAST / IaC", "Dependency Scanning", "Secret Detection"]:
        rows = [r for r in dismissed if r["scanner"] == scanner]
        if not rows:
            continue
        L.append(f"### {scanner} — {len(rows)} findings\n")
        L.append("| Vuln | Finding | Component | Severity | Disposition | Justification |")
        L.append("|---|---|---|---|---|---|")
        for r in sorted(rows, key=lambda x: SEV_ORDER.get(x["severity"], 9)):
            fid = r["cve"] or r["title"]
            L.append(f"| [{r['vuln_id']}]({r['url']}) | {fid} | {r['component']} | {r['severity']} | "
                     f"{r['disposition']} | {r['justification']} |")
        L.append("")

    # Remediation register (resolved) — concise per scanner.
    L.append("## Remediated (resolved) register\n")
    L.append(f"{len(resolved)} findings fixed in code and verified gone in the scan. Full list in "
             "[`dispositions.csv`](dispositions.csv). By scanner:\n")
    rc = defaultdict(int)
    for r in resolved:
        rc[r["scanner"]] += 1
    L.append("| Scanner | Remediated |")
    L.append("|---|---:|")
    for s in sorted(rc):
        L.append(f"| {s} | {rc[s]} |")
    L.append("")

    with open(os.path.join(args.out, "EVIDENCE.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")

    print(f"wrote EVIDENCE.md, dispositions.csv, evidence.json to {args.out}")
    print(f"  {len(detected)} detected, {len(dismissed)} dismissed, {len(resolved)} resolved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
