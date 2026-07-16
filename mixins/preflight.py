"""Preflight dependency gate + shared dependency-check engine.

The repo is lifted into air-gapped enclaves (git clone -> cp -R -> push) where
apt mirrors and PyPI may be unreachable, so system and pip package availability
differs per enclave. A missing dependency must surface as a clean, readable gap
report BEFORE the job starts -- never as a mid-job Python traceback.

This module is the single source of truth for "what does the app need, and is it
actually here right now". Two consumers:

  * diagnose  (mixins/tools.py:_tool_diagnose via reports.py:_check_environment)
    -- renders the WHOLE manifest, grouped, as an environment litmus test.
  * the preflight gate (PreflightMixin._preflight, called from NceGitLab.main())
    -- renders only the checks a specific job needs, and exits before any work
    if a required one is missing.

Checks are DATA (DEP_CHECKS) and jobs map to check-key sets (JOB_PROFILES), so a
`--formats markdown` run never demands WeasyPrint/quarto, and adding a dependency
is a one-line manifest edit.
"""

import json
import os
import shutil
import sys
from importlib import import_module
from pathlib import Path

# Exit code the preflight gate uses when a REQUIRED dependency is missing.
# Distinct from 1 (an unexpected crash) so CI / operators can tell an
# environment gap apart from "the code broke".
PREFLIGHT_EXIT = 2

_OFFLINE_NOTE = "air-gap: provision from your internal apt/PyPI mirror"

# Each entry is one atomic capability check.
#   key       short id (also the JOB_PROFILES token)
#   kind      "python" | "binary" | "render"
#   target    module name (python) or executable name (binary); ignored for render
#   label     human-readable name shown in reports
#   provides  what breaks without it
#   fix       remediation command (online)
#   removable how an operator / dev can avoid needing it (the send-back path)
DEP_CHECKS = [
    # --- python packages (import must succeed) ---
    dict(key="gitlab",   kind="python", target="gitlab",
         label="python: python-gitlab", provides="all GitLab API access",
         fix="pip install python-gitlab", removable="no"),
    dict(key="requests", kind="python", target="requests",
         label="python: requests", provides="HTTP / GraphQL calls",
         fix="pip install requests", removable="no"),
    dict(key="pandas",   kind="python", target="pandas",
         label="python: pandas", provides="all report data crunching",
         fix="pip install pandas", removable="no"),
    dict(key="dateutil", kind="python", target="dateutil",
         label="python: python-dateutil", provides="PI / date math in reports",
         fix="pip install python-dateutil", removable="no"),
    dict(key="markdown", kind="python", target="markdown",
         label="python: markdown", provides="wiki page rendering",
         fix="pip install markdown", removable="no"),
    dict(key="marimo",   kind="python", target="marimo",
         label="python: marimo", provides="interactive (WASM) report pages",
         fix="pip install marimo", removable="drop --formats interactive to skip"),
    dict(key="boto3",    kind="python", target="boto3",
         label="python: boto3", provides="AWS deploy (S3 / ECS / EKS / ECR)",
         fix="pip install boto3", removable="only needed for AWS deploy paths"),

    # --- render probe: pip-present is NOT enough. WeasyPrint wraps Pango (a
    #     system library) and needs fonts, so actually render one PDF to prove
    #     the native libs + a font load -- a version check can never see this. ---
    dict(key="weasyprint", kind="render", target="weasyprint",
         label="WeasyPrint render (Pango + fonts)",
         provides="epic-cards / PDF export",
         fix="pip install weasyprint && apt-get install libpango-1.0-0 "
             "libpangoft2-1.0-0 fonts-dejavu-core",
         removable="enclave-provisionable / flag for code rework to drop PDF"),

    # --- external binaries (must be on PATH) ---
    dict(key="quarto",  kind="binary", target="quarto",
         label="quarto -- static HTML report site", provides="--formats plotly",
         fix="install Quarto (see README)",
         removable="drop --formats plotly to skip"),
    dict(key="dot",     kind="binary", target="dot",
         label="graphviz (dot) -- architecture diagrams",
         provides="architecture diagrams in the static site",
         fix="apt-get install graphviz",
         removable="optional -- diagrams are skipped if absent"),
    dict(key="aws",     kind="binary", target="aws", label="aws -- AWS CLI",
         provides="all AWS deploy paths", fix="install the AWS CLI v2",
         removable="only needed for AWS deploy paths"),
    dict(key="cdk",     kind="binary", target="cdk", label="cdk -- AWS CDK",
         provides="ECS / EKS deploy", fix="npm install -g aws-cdk",
         removable="only needed for ECS / EKS deploy"),
    dict(key="node",    kind="binary", target="node", label="node -- Node.js",
         provides="CDK / frontend build", fix="install Node.js LTS",
         removable="only needed for CDK deploy / frontend build"),
    dict(key="kubectl", kind="binary", target="kubectl", label="kubectl",
         provides="EKS deploy", fix="install kubectl",
         removable="only needed for EKS deploy"),
    dict(key="helm",    kind="binary", target="helm", label="helm",
         provides="EKS chart install", fix="install Helm",
         removable="only needed for EKS deploy"),
    dict(key="make",    kind="binary", target="make", label="make",
         provides="deploy Makefile wrappers", fix="apt-get install make",
         removable="only needed for deploy paths"),
    dict(key="jq",      kind="binary", target="jq", label="jq",
         provides="deploy JSON parsing", fix="apt-get install jq",
         removable="only needed for deploy paths"),
    dict(key="docker",  kind="binary", target="docker", label="docker",
         provides="ECR image build / push", fix="install Docker",
         removable="only needed for --deploy-ecr publish"),

    # --- TEMPORARY preflight demo (issue #249): two deliberately-absent deps so
    #     a CI run of `-ut epic-cards` shows the gate reporting BOTH a missing
    #     python package and a missing system binary at once. Remove these two
    #     entries and the two "demo_*" keys from the `pdf` profile after the demo.
    dict(key="demo_pydep", kind="python", target="nce_preflight_demo_pkg_xyz",
         label="python: nce-preflight-demo (TEMP demo)",
         provides="preflight demo — not a real dependency",
         fix="pip install nce-preflight-demo   # (fake — delete this check)",
         removable="TEMPORARY demo dep — delete from DEP_CHECKS + the pdf profile"),
    dict(key="demo_bindep", kind="binary", target="nce-preflight-demo-tool",
         label="nce-preflight-demo-tool (TEMP demo)",
         provides="preflight demo — not a real binary",
         fix="install nce-preflight-demo-tool   # (fake — delete this check)",
         removable="TEMPORARY demo dep — delete from DEP_CHECKS + the pdf profile"),
]

_BY_KEY = {c["key"]: c for c in DEP_CHECKS}

# A job profile is (required_keys, optional_keys). Optional keys are checked and
# shown (as warnings) but never block. `core` is the baseline every GitLab job
# needs; the deploy tuples mirror server/deploy_*.py _REQUIRED_TOOLS.
_CORE = ["gitlab", "requests", "pandas", "dateutil"]

JOB_PROFILES = {
    "core":               (_CORE, []),
    "report-markdown":    (_CORE + ["markdown"], []),
    "report-plotly":      (_CORE + ["markdown", "quarto"], ["dot"]),
    "report-interactive": (_CORE + ["markdown", "marimo"], []),
    "report-all":         (_CORE + ["markdown", "quarto", "marimo"], ["dot"]),
    # NOTE: "demo_pydep"/"demo_bindep" are TEMPORARY (issue #249 preflight demo)
    # — remove them from this profile and from DEP_CHECKS after the demo.
    "pdf":                (_CORE + ["weasyprint", "demo_pydep", "demo_bindep"], []),
    "create":             (_CORE, []),
    "scaffold":           (_CORE, []),
    "clean":              (_CORE, []),
    "deploy-s3":          (["aws", "make", "jq"], []),
    "deploy-ecr":         (["make", "jq", "aws"], ["docker"]),
    "deploy-ecs":         (["make", "jq", "cdk", "node", "aws"], []),
    "deploy-eks":         (["make", "jq", "cdk", "node", "aws", "kubectl", "helm"], []),
}

# What a standalone `diagnose` litmus treats as REQUIRED: a box that can't do
# these can't run the core app or render the epic-cards deck. Everything else in
# DEP_CHECKS is shown as optional/recommended. Deliberately contains NO binary so
# the whole deploy/report toolchain being absent never fails the litmus.
DIAGNOSE_REQUIRED = set(_CORE + ["markdown", "weasyprint"])


def profile_for_formats(formats):
    """Map a parsed --formats set to the matching report profile.

    Keys off the actual formats requested (not a documented default), so it is
    correct whether or not --formats was passed.
    """
    f = set(formats or [])
    has_plotly = "plotly" in f
    has_interactive = "interactive" in f
    if has_plotly and has_interactive:
        return "report-all"
    if has_plotly:
        return "report-plotly"
    if has_interactive:
        return "report-interactive"
    return "report-markdown"


# --- the check primitives ---------------------------------------------------

def _first_line(err, fallback):
    s = str(err).strip()
    return s.splitlines()[0][:80] if s else fallback


def _check_python(mod):
    try:
        import_module(mod)
        return True, ""
    except Exception as e:                       # noqa: BLE001 -- report any failure
        return False, _first_line(e, "import failed")


def _check_binary(name):
    path = shutil.which(name)
    return bool(path), (path or "not on PATH")


def _check_render(_target):
    # pip-present is NOT enough: WeasyPrint wraps Pango (system lib) + needs
    # fonts. Render one PDF to prove the native libs load.
    try:
        from weasyprint import HTML
        HTML(string="<p>x</p>").write_pdf()
        return True, ""
    except Exception as e:                       # noqa: BLE001
        return False, _first_line(e, "render failed")


_RUNNERS = {"python": _check_python, "binary": _check_binary, "render": _check_render}


def run_checks(keys, *, required_keys=None):
    """Run the named checks in DEP_CHECKS order.

    `required_keys` (a set) marks which results are required for the current job;
    anything not in it is optional (never blocks). When None, every requested
    check is treated as required. Unknown keys are ignored. Never raises.
    """
    keyset = list(dict.fromkeys(keys))           # de-dup, keep order
    req = set(required_keys) if required_keys is not None else set(keyset)
    results = []
    for c in DEP_CHECKS:
        if c["key"] not in keyset:
            continue
        ok, detail = _RUNNERS[c["kind"]](c["target"])
        results.append({
            "key": c["key"], "label": c["label"], "ok": ok, "detail": detail,
            "required": c["key"] in req, "fix": c["fix"],
            "removable": c["removable"], "provides": c["provides"],
        })
    return results


# --- reporting --------------------------------------------------------------

def _icon(ok, required):
    if ok:
        return "✅"                          # white check
    return "❌" if required else "⚠️"   # cross / warning


def render_report(results, *, job_label=None, mode="preflight"):
    """Format check results as clean lines. No tracebacks, ever.

    mode="diagnose"  -- full grouped litmus (all requested checks shown).
    mode="preflight" -- gate framing: missing-first, present summary, guidance.
    """
    W = 66
    missing_req = [r for r in results if r["required"] and not r["ok"]]
    missing_opt = [r for r in results if not r["required"] and not r["ok"]]
    present     = [r for r in results if r["ok"]]

    if mode == "diagnose":
        out = ["", "\U0001fa7a  Environment Dependencies (no GitLab connection needed)",
               "═" * W, ""]
        nw = max((len(r["label"]) for r in results), default=0)
        for r in results:
            tag = "" if r["required"] else "  (optional)"
            out.append(f"  {_icon(r['ok'], r['required'])}  {r['label']:<{nw}}{tag}")
            if not r["ok"]:
                if r["detail"]:
                    out.append(f"        ↳ {r['detail']}")
                out.append(f"        ↳ fix: {r['fix']}")
        out.append("")
        if missing_req:
            out.append(f"❌ {len(missing_req)} required dependency(ies) missing "
                       f"-- the deck / reports will fail until fixed (see 'fix:' lines).")
        else:
            out.append("✅ All required dependencies present.")
        out += ["═" * W, ""]
        return out

    # --- preflight gate framing ---
    if not missing_req:
        n = len(results)
        tail = f" for {job_label}" if job_label else ""
        return [f"  ✓ preflight OK -- {n} dependency(ies) present{tail}"]

    title = "⛔  Preflight -- cannot start"
    if job_label:
        title += f" “{job_label}”"
    out = ["", title, "═" * W, "",
           f"Missing {len(missing_req)} required dependency(ies) for this job:", ""]
    for r in missing_req:
        out.append(f"  ❌  {r['label']}")
        out.append(f"        needs:     {r['provides']}")
        if r["detail"]:
            out.append(f"        detail:    {r['detail']}")
        out.append(f"        fix:       {r['fix']}")
        out.append(f"        {_OFFLINE_NOTE}")
        out.append(f"        removable: {r['removable']}")
        out.append("")
    if missing_opt:
        out.append("  ⚠️  Optional (the job will run without these):")
        for r in missing_opt:
            out.append(f"        {r['label']} -- {r['fix']}")
        out.append("")
    if present:
        shown = ", ".join(r["label"].replace("python: ", "") for r in present)
        out.append(f"  ✅  Present: {shown}")
        out.append("")
    out += [
        "Resolve the items above -- a few at a time is fine -- then re-run the",
        "same command. Full environment report:  python3 NceGitLab.py --diagnose",
        "═" * W, "",
    ]
    return out


def write_gap_manifest(results, path):
    """Write the missing dependencies to a JSON artifact for enclave ops /
    send-back-for-rework. Returns the Path written, or None on any failure
    (writing the artifact must never itself block the gate). Never raises.
    """
    missing = [
        {"key": r["key"], "label": r["label"], "required": r["required"],
         "provides": r["provides"], "detail": r["detail"], "fix": r["fix"],
         "offline": _OFFLINE_NOTE, "removable": r["removable"]}
        for r in results if not r["ok"]
    ]
    payload = {
        "missing_required": len([m for m in missing if m["required"]]),
        "missing": missing,
    }
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
        return p
    except Exception:                            # noqa: BLE001 -- never block on this
        return None


def config_preflight_skip(config_file="config.json"):
    """Read defaults.preflight.skip straight from a config file, for the gate
    that runs BEFORE the GitLab client (and its config load) exists. Returns
    False on any error — a config problem must neither silently disable the gate
    nor crash it. Never raises."""
    try:
        with open(config_file) as f:
            cfg = json.load(f)
        return bool(cfg.get("defaults", {}).get("preflight", {}).get("skip", False))
    except Exception:                            # noqa: BLE001
        return False


def _skip_decided(skip_override, config_file):
    """Three-tier precedence: flag (skip_override) > PREFLIGHT_SKIP env > config."""
    if skip_override is not None:
        return bool(skip_override)
    env = os.getenv("PREFLIGHT_SKIP")
    if env is not None:
        return env.strip().lower() not in ("false", "0", "no", "")
    return config_preflight_skip(config_file)


def run_preflight(profile, *, phase_label=None, decided_skip=None,
                  skip_override=None, config_file="config.json"):
    """Gate a job on `profile`'s dependencies. Runs the WHOLE profile in one pass
    and reports every gap at once — it never stops at the first missing item.

    On a missing REQUIRED dep: print the report, write the gap manifest, and
    sys.exit(PREFLIGHT_EXIT) before any work starts. Returns True to proceed.

    Skip: pass `decided_skip` (a bool) when the caller already resolved its own
    precedence; otherwise it is `skip_override` > PREFLIGHT_SKIP env > config file.
    Designed to be callable with no GitLab client — so it can run before auth.
    """
    skipped = decided_skip if decided_skip is not None \
        else _skip_decided(skip_override, config_file)
    if skipped:
        print("  ⚠️  preflight skipped (--skip-preflight / PREFLIGHT_SKIP / config)")
        return True
    required, optional = JOB_PROFILES.get(profile, JOB_PROFILES["core"])
    keys = list(required) + list(optional)
    results = run_checks(keys, required_keys=set(required))
    missing = [r for r in results if r["required"] and not r["ok"]]
    if not missing:
        return True
    gap_path = write_gap_manifest(results, Path("logs") / "preflight-gaps.json")
    print("\n".join(render_report(results, job_label=phase_label or profile,
                                  mode="preflight")))
    if gap_path is not None:
        print(f"  Gap manifest written: {gap_path}  "
              f"(share with enclave ops / send back for rework)\n")
    sys.exit(PREFLIGHT_EXIT)


class PreflightMixin:
    """Preflight dependency gate. Runs before a job to confirm the tools/libs
    that job needs are present, printing a clean gap report instead of letting a
    missing dependency crash mid-run.
    """

    def _dependency_check(self, keys, *, required_keys=None):
        """Run checks for `keys`; return (results, missing_required_labels)."""
        results = run_checks(keys, required_keys=required_keys)
        missing = [r["label"] for r in results if r["required"] and not r["ok"]]
        return results, missing

    def _preflight_skipped(self):
        """Three-tier precedence: --skip-preflight flag > PREFLIGHT_SKIP env >
        config default (defaults.preflight.skip). Mirrors the SSL-verify idiom.
        """
        override = getattr(self, "_preflight_skip_override", None)
        if override is not None:
            return bool(override)
        env = os.getenv("PREFLIGHT_SKIP")
        if env is not None:
            return env.strip().lower() not in ("false", "0", "no", "")
        return bool(getattr(self, "preflight_skip", False))

    def _preflight(self, profile, *, phase_label=None):
        """Instance entry to the gate — resolves the three-tier skip from this
        client's own state, then delegates to run_preflight (the same engine the
        pre-client gate in main() uses). Returns True when the job may proceed;
        otherwise prints the gap report and sys.exit(PREFLIGHT_EXIT).
        """
        return run_preflight(profile, phase_label=phase_label,
                             decided_skip=self._preflight_skipped())
