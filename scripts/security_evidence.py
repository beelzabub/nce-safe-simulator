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
  # regenerate the committed register (by hand; the commit is a review step)
  scripts/security_evidence.py --pipeline 2746483470 --sha 2dbd11f0 \
      --generated-at 2026-08-10T09:00:00Z [--out docs/security]

  # ask whether the committed register is still current, change nothing (#317)
  scripts/security_evidence.py --check [--out build/security-evidence]

Every argument now has a default: --sha, --generated-at and --pipeline resolve
themselves from the CI environment / the git checkout / the API when omitted,
which is what lets the security-evidence recipe call this with no arguments.

API access (#317): the two API helpers speak HTTP directly when a token is in
the environment (SECURITY_EVIDENCE_TOKEN, GITLAB_API_TOKEN or GITLAB_TOKEN),
and fall back to shelling out to `glab` when there isn't one. Both paths matter:
`glab` is what a workstation has configured, and HTTP is what CI can use — the
runtime image has `requests` baked in but no `glab`, and downloading one at job
time would break the air-gap property every recipe here relies on.
"""
import argparse, csv, difflib, hashlib, json, os, shutil, subprocess, sys, tempfile
from collections import defaultdict
from datetime import datetime, timezone

try:
    import requests
except ImportError:                                          # glab fallback only
    requests = None

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


TOKEN_VARS = ("SECURITY_EVIDENCE_TOKEN", "GITLAB_API_TOKEN", "GITLAB_TOKEN")


def api_v4():
    """API root — CI hands it to us; otherwise gitlab.com."""
    return (os.environ.get("CI_API_V4_URL") or "https://gitlab.com/api/v4").rstrip("/")


def token():
    """First non-empty token in the environment, or None to use glab instead."""
    for var in TOKEN_VARS:
        if os.environ.get(var):
            return os.environ[var]
    return None


def http():
    """The token to make direct HTTP calls with, or None if we must use glab."""
    return token() if requests is not None else None


def auth_error(status, where):
    """A rejected token is a configuration problem — say so, don't traceback."""
    var = next((v for v in TOKEN_VARS if os.environ.get(v)), None)
    print(f"error: GitLab rejected the token with HTTP {status} on {where}.\n"
          f"       The token came from ${var}. It is present but not accepted — "
          f"expired,\n       revoked, or without the read_api scope.\n"
          f"       In CI: check that variable holds a CURRENT token with read_api. "
          f"CI_JOB_TOKEN\n       cannot read project vulnerabilities, so it is not an "
          f"alternative here.\n"
          f"       Recognised variables, in order: {', '.join(TOKEN_VARS)}.",
          file=sys.stderr)
    sys.exit(1)


def gql(q):
    tok = http()
    if tok:
        # .../api/v4 → .../api/graphql
        url = api_v4().rsplit("/", 1)[0] + "/graphql"
        r = requests.post(url, headers={"PRIVATE-TOKEN": tok}, json={"query": q}, timeout=60)
        if r.status_code in (401, 403):
            auth_error(r.status_code, "the GraphQL endpoint")
        r.raise_for_status()
        return r.json()
    out = subprocess.run(["glab", "api", "graphql", "-f", f"query={q}"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def api(path):
    """GET an API v4 path; returns the raw body, or None if it wasn't a 200.

    Also used to pull job artifacts, so it must stay body-in-text, not JSON.
    """
    tok = http()
    if tok:
        r = requests.get(f"{api_v4()}/{path.lstrip('/')}",
                         headers={"PRIVATE-TOKEN": tok}, timeout=60)
        # A rejected token here would silently empty the scanner metadata rather
        # than fail — the one 4xx worth stopping on.
        if r.status_code in (401, 403):
            auth_error(r.status_code, f"/{path.lstrip('/').split('?')[0]}")
        return r.text if r.status_code == 200 else None
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


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_SECURITY = os.path.join(REPO_ROOT, "docs", "security")


# ── Provenance resolution (#317) ─────────────────────────────────────────────
# So the recipe can call this with no arguments at all.

def default_sha():
    """The commit being described: CI's, else the checkout's."""
    short = os.environ.get("CI_COMMIT_SHORT_SHA")
    if short:
        return short
    r = subprocess.run(["git", "-C", REPO_ROOT, "rev-parse", "--short=8", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def default_generated_at():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_ref():
    return os.environ.get("CI_DEFAULT_BRANCH") or "develop"


def resolve_scan_pipeline(ref=None, scan=20):
    """The most recent pipeline on `ref` that actually produced security reports.

    NOT the caller's own pipeline id: this recipe runs as a child pipeline with
    no scanners in it, and the register it reads was reconciled by the parent
    default-branch run that did carry them (#315). Citing our own id would name
    a pipeline that scanned nothing.

    Returns (pipeline_id, short_sha) as strings, or (None, None) if no recent
    run on that ref carried reports.
    """
    ref = ref or default_ref()
    d = gql(f'''query {{ project(fullPath: "{PROJECT}") {{
      pipelines(ref: "{ref}", first: {scan}) {{
        nodes {{ id sha securityReportSummary {{
          containerScanning {{ vulnerabilitiesCount }}
          dependencyScanning {{ vulnerabilitiesCount }}
          sast {{ vulnerabilitiesCount }}
          secretDetection {{ vulnerabilitiesCount }} }} }} }} }} }}''')
    nodes = (((d.get("data") or {}).get("project") or {}).get("pipelines") or {}).get("nodes") or []
    for n in nodes:
        summary = n.get("securityReportSummary") or {}
        if any(summary.get(k) for k in ("containerScanning", "dependencyScanning", "sast", "secretDetection")):
            return n["id"].split("/")[-1], (n.get("sha") or "")[:8] or None
    return None, None


def pipeline_sha(project_id, pipeline):
    """The commit a given pipeline ran on — the thing the register describes."""
    raw = api(f"projects/{project_id}/pipelines/{pipeline}")
    if not raw:
        return None
    try:
        return (json.loads(raw).get("sha") or "")[:8] or None
    except (ValueError, AttributeError):
        return None


# ── Drift check (#317) ───────────────────────────────────────────────────────
# Every regeneration re-stamps the scan sha, the timestamp, the pipeline and the
# per-report SHA-256, so a textual diff always "differs". Drift has to mean the
# findings moved — otherwise the job cries wolf on every run and the signal is
# worth nothing.

PROVENANCE_KEYS = ("scanned_sha", "generated_at", "scan_pipeline")
PROVENANCE_MD_PREFIXES = ("- **Scanned commit:**", "- **Scan:** pipeline")
FINDING_FIELDS = ("state", "disposition", "severity", "scanner", "component",
                  "cve", "title", "justification")


def normalize_evidence(ev):
    """evidence.json minus the fields that change on every run regardless."""
    out = {k: v for k, v in ev.items() if k not in PROVENANCE_KEYS}
    out["scanners"] = [{k: v for k, v in s.items() if k != "report_sha256"}
                       for s in ev.get("scanners") or []]
    return out


def normalize_md(text):
    """EVIDENCE.md minus its provenance bullets."""
    return [ln for ln in text.splitlines()
            if not ln.startswith(PROVENANCE_MD_PREFIXES)]


def findings_delta(old, new):
    """(added, gone, changed) between two findings arrays, keyed by vuln_id."""
    o = {r["vuln_id"]: r for r in old}
    n = {r["vuln_id"]: r for r in new}
    added = [n[k] for k in sorted(set(n) - set(o))]
    gone = [o[k] for k in sorted(set(o) - set(n))]
    changed = []
    for k in sorted(set(o) & set(n)):
        diffs = {f: (o[k].get(f), n[k].get(f)) for f in FINDING_FIELDS
                 if o[k].get(f) != n[k].get(f)}
        if diffs:
            changed.append((n[k], diffs))
    return added, gone, changed


def _describe(r):
    return f"{r['vuln_id']} [{r['severity']}] {r['scanner']} · {r['component']} — {r['cve'] or r['title']}"


def check(candidate_dir, committed_dir, show=25):
    """Report whether the committed register still describes reality. Never fails.

    Drift is information, not a defect: gating the pipeline on it would pressure
    people into rubber-stamping a register whose whole value is that a human
    read it. Always returns 0.
    """
    cand_json = os.path.join(candidate_dir, "evidence.json")
    comm_json = os.path.join(committed_dir, "evidence.json")
    if not os.path.exists(comm_json):
        print(f"DRIFT: no committed evidence at {comm_json} — this would be the first commit of it.")
        return 0

    with open(cand_json) as fh:
        cand = json.load(fh)
    with open(comm_json) as fh:
        comm = json.load(fh)

    print("=" * 72)
    print("Committed register:  "
          f"{comm.get('scanned_sha')} · {comm.get('generated_at')} · "
          f"pipeline {(comm.get('scan_pipeline') or {}).get('id')}")
    print("Regenerated now:     "
          f"{cand.get('scanned_sha')} · {cand.get('generated_at')} · "
          f"pipeline {(cand.get('scan_pipeline') or {}).get('id')}")
    print("=" * 72)

    added, gone, changed = findings_delta(comm.get("findings") or [], cand.get("findings") or [])
    ct, cc = comm.get("totals") or {}, cand.get("totals") or {}
    print(f"\nTotals   committed: {ct.get('detected',0)} detected, {ct.get('dismissed',0)} dismissed, {ct.get('resolved',0)} resolved")
    print(f"         now:       {cc.get('detected',0)} detected, {cc.get('dismissed',0)} dismissed, {cc.get('resolved',0)} resolved")

    if added:
        print(f"\n{len(added)} finding(s) NOT in the committed register:")
        for r in added[:show]:
            print(f"  + {_describe(r)}  [{r['state']}]")
        if len(added) > show:
            print(f"  … and {len(added) - show} more (see the dispositions.csv artifact)")
    if gone:
        print(f"\n{len(gone)} committed finding(s) no longer in the report:")
        for r in gone[:show]:
            print(f"  - {_describe(r)}  [{r['state']}]")
        if len(gone) > show:
            print(f"  … and {len(gone) - show} more")
    if changed:
        print(f"\n{len(changed)} finding(s) whose disposition or detail changed:")
        for r, diffs in changed[:show]:
            print(f"  ~ {_describe(r)}")
            for f, (was, now) in diffs.items():
                print(f"      {f}: {was!r} → {now!r}")
        if len(changed) > show:
            print(f"  … and {len(changed) - show} more")

    # Generator drift: the register's own shape can move without any finding
    # moving (a template edit that was never regenerated into the committed copy).
    rendered = []
    for name in ("EVIDENCE.md", "dispositions.csv"):
        c, m = os.path.join(candidate_dir, name), os.path.join(committed_dir, name)
        if not os.path.exists(m):
            rendered.append(name)
            continue
        a = normalize_md(open(m).read()) if name.endswith(".md") else open(m).read().splitlines()
        b = normalize_md(open(c).read()) if name.endswith(".md") else open(c).read().splitlines()
        if a != b:
            rendered.append(name)
            print(f"\n{name} differs (provenance lines excluded):")
            for line in list(difflib.unified_diff(a, b, "committed", "regenerated", lineterm=""))[:show]:
                print(f"  {line}")
    if normalize_evidence(comm) != normalize_evidence(cand) and not (added or gone or changed):
        rendered.append("evidence.json")
        print("\nevidence.json differs outside the findings array (scanner set or counts).")

    drift = bool(added or gone or changed or rendered)
    print("\n" + "=" * 72)
    if drift:
        print("RESULT: the committed evidence is STALE — regenerate and commit it.")
        print("  scripts/security_evidence.py            # writes docs/security in place")
        print("  git add docs/security && git commit     # the commit IS the review step")
    else:
        print("RESULT: the committed evidence is CURRENT — no action needed.")
    print("Drift is reported, never enforced: this job is green either way.")
    print("=" * 72)
    return 0


def generate(out, pipeline, sha, generated_at, project_id):
    recs = [record(n) for n in fetch_vulns()]
    dismissed = [r for r in recs if r["state"] == "DISMISSED"]
    resolved = [r for r in recs if r["state"] == "RESOLVED"]
    detected = [r for r in recs if r["state"] == "DETECTED"]

    # scanner metadata (versions + report hashes)
    jobs = json.loads(api(f"projects/{project_id}/pipelines/{pipeline}/jobs?per_page=60") or "[]")
    reports = {"container_scanning": "gl-container-scanning-report.json",
               "gemnasium-dependency_scanning": "gl-dependency-scanning-report.json",
               "semgrep-sast": "gl-sast-report.json", "secret_detection": "gl-secret-detection-report.json"}
    scanners = []
    for job in jobs:
        rf = reports.get(job["name"])
        if not rf:
            continue
        raw = api(f"projects/{project_id}/jobs/{job['id']}/artifacts/{rf}")
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

    os.makedirs(out, exist_ok=True)

    # ---- evidence.json ----
    with open(os.path.join(out, "evidence.json"), "w") as fh:
        json.dump({
            "project": PROJECT, "scanned_sha": sha, "generated_at": generated_at,
            "scan_pipeline": {"id": int(pipeline), "url": f"{BASE_URL}/-/pipelines/{pipeline}"},
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
    with open(os.path.join(out, "dispositions.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["vuln_id", "cve", "scanner", "component", "severity", "state",
                    "disposition", "title", "justification", "url"])
        for r in sorted(recs, key=lambda x: (x["state"], x["scanner"], SEV_ORDER.get(x["severity"], 9))):
            w.writerow([r["vuln_id"], r["cve"], r["scanner"], r["component"], r["severity"],
                        r["state"], r["disposition"], r["title"], r["justification"], r["url"]])

    # ---- EVIDENCE.md (audit-grade register) ----
    L = ["# Security posture & vulnerability disposition register — NCE Safe Simulator\n"]
    L.append("## Provenance\n")
    L.append(f"- **Scanned commit:** `develop @ {sha}`")
    L.append(f"- **Scan:** pipeline [#{pipeline}]({BASE_URL}/-/pipelines/{pipeline}), {generated_at[:10]}")
    if scanners:
        L.append("- **Scanners:** " + ", ".join(f"{s['scanner']} {s['version']}" for s in scanners if s.get('scanner')))
    L.append(f"- **Disposition authority:** {AUTHORITY}")
    L.append("- **Source:** GitLab Vulnerability Report; regenerate with `scripts/security_evidence.py`.")
    L.append("- **Full flat register:** [`dispositions.csv`](dispositions.csv) — one row per finding.\n")

    # Refresh procedure (#317). This lives in the GENERATOR, not in EVIDENCE.md:
    # the markdown is generated output, so anything hand-written into it is
    # deleted by the next regeneration.
    L.append("## Refreshing this register\n")
    L.append("**When.** After anything that moves the dependency or image surface — a "
             "requirements bump, a base-image refresh, a Dockerfile change — and after the "
             "scanners have reconciled the register on the default branch. Scans only "
             "reconcile from the default branch's **own** pipeline jobs (#315), so the "
             "sequence is: merge, run `RECIPE=security-all` on the default branch, let it "
             "finish, then refresh this file.\n")
    L.append("**Checking whether it is stale.** Run the recipe — "
             "`RECIPE=security-evidence` (see [`ci-recipes/README.md`](../../ci-recipes/README.md)) "
             "— or locally:\n")
    L.append("```bash\nscripts/security_evidence.py --check\n```\n")
    L.append("It regenerates the register somewhere harmless, prints what moved (findings "
             "added, no longer reported, or with a changed disposition), publishes the "
             "regenerated files as job artifacts, and **exits green whether or not there is "
             "drift**. It never writes to `docs/security` and never commits. Drift is "
             "information; a job that failed on it would only teach people to wave it "
             "through.\n")
    L.append("**Refreshing it for real.**\n")
    L.append("```bash\nscripts/security_evidence.py          # rewrites the three files in place\n"
             "git add docs/security && git commit   # a deliberate review step\n```\n")
    L.append("**The commit is the point.** This register carries a disposition authority — "
             "an assertion that a person reviewed these findings and accepted the risk. The "
             "justifications are human-written; regeneration only re-reads them from the "
             "Vulnerability Report. So nothing automated commits this file: a job that "
             "re-stamped the approval on every push would be asserting a review nobody "
             "performed, which makes the artifact worth less as evidence, not more.\n")

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

    with open(os.path.join(out, "EVIDENCE.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")

    print(f"wrote EVIDENCE.md, dispositions.csv, evidence.json to {out}")
    print(f"  {len(detected)} detected, {len(dismissed)} dismissed, {len(resolved)} resolved")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pipeline", help="scan pipeline to cite; default: newest on --ref with security reports")
    ap.add_argument("--sha", help="commit described; default: $CI_COMMIT_SHORT_SHA or the checkout's HEAD")
    ap.add_argument("--generated-at", help="ISO-8601 stamp; default: now (UTC)")
    ap.add_argument("--project-id", default="81726491")
    ap.add_argument("--ref", default=None, help="branch to resolve --pipeline from (default: $CI_DEFAULT_BRANCH)")
    ap.add_argument("--out", default=None,
                    help="where to write; default docs/security, or a temp dir under --check")
    ap.add_argument("--check", action="store_true",
                    help="regenerate elsewhere, report drift against the committed copy, exit 0")
    ap.add_argument("--committed", default=DOCS_SECURITY,
                    help="the committed register --check compares against")
    args = ap.parse_args()

    # Under --check the default output must NOT be the committed copy: this path
    # exists precisely to change nothing. Settle that before any API call, so a
    # usage error fails instantly instead of after a full report sweep.
    tmp = None
    if args.out:
        out = args.out
    elif args.check:
        tmp = out = tempfile.mkdtemp(prefix="security-evidence-")
    else:
        out = DOCS_SECURITY
    if args.check and os.path.abspath(out) == os.path.abspath(args.committed):
        shutil.rmtree(tmp, ignore_errors=True) if tmp else None
        print("error: --check would overwrite the committed register it is meant to compare "
              "against.\n       Point --out somewhere else, or drop it for a temp dir.", file=sys.stderr)
        return 1

    generated_at = args.generated_at or default_generated_at()

    # The SHA must be the one the CITED SCAN ran on, not this checkout's HEAD:
    # the recipe runs on a branch, in a child pipeline, and cites a default-branch
    # scan. Taking HEAD here would stamp the register with a commit nothing scanned.
    pipeline, pipe_sha = args.pipeline, None
    if not pipeline:
        pipeline, pipe_sha = resolve_scan_pipeline(args.ref)
    if pipeline and not args.sha and not pipe_sha:
        pipe_sha = pipeline_sha(args.project_id, pipeline)
    sha = args.sha or pipe_sha or default_sha()

    if not pipeline:
        ref = args.ref or default_ref()
        shutil.rmtree(tmp, ignore_errors=True) if tmp else None
        print(f"error: no pipeline on '{ref}' carried security reports, so there is nothing to cite.\n"
              f"       Run the scanners first (RECIPE=security-all on {ref} — they must be the\n"
              f"       parent pipeline's own jobs, see #315), or pass --pipeline explicitly.",
              file=sys.stderr)
        return 1

    try:
        generate(out, pipeline, sha, generated_at, args.project_id)
        return check(out, args.committed) if args.check else 0
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
