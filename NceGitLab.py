import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime
from importlib.metadata import version as pkg_version
from pathlib import Path

import gitlab

from mixins import (
    BootstrapMixin,
    EpicsMixin,
    GroupsMixin,
    ImportExportMixin,
    IssuesMixin,
    LabelsMixin,
    MilestonesMixin,
    ProjectsMixin,
    ReportsMixin,
    ServeMixin,
    ToolsMixin,
    UtilitiesMixin,
    WikiMixin,
)
from mixins.utils import _clear, _pause, _tee_to_log


class NceGitLab(
    UtilitiesMixin,
    WikiMixin,
    LabelsMixin,
    GroupsMixin,
    ProjectsMixin,
    EpicsMixin,
    IssuesMixin,
    MilestonesMixin,
    ReportsMixin,
    BootstrapMixin,
    ToolsMixin,
    ImportExportMixin,
    ServeMixin,
):
    def __init__(self, config_file="config.json", ssl_verify=None):
        self.config_file = Path(config_file)

        if not self.config_file.exists():
            print(f"Config file '{self.config_file}' not found!")
            print('''Please create config.json with the following format:
                    {
                        "url": "https://gitlab.com",
                        "private_token": "glpat-XXXXXXXXXXXXXXXXXXXX",
                        "parent_group": "AMW-120",
                        "gitlab_namespace": "gl-demo-ultimate-lmwilliams",
                        "project_labels": ["project::DO", "project::RTSO"],
                        "piid_labels": ["PIID::2026Q3", "PIID::2026Q4", "PIID::2027Q1"],
                        "epic_type_labels": ["Epic", "Capability", "Feature"],
                        "risk_labels": ["risk::high", "risk::medium", "risk::low"],
                        "work_type_labels": ["type::feature", "type::enabler", "type::infrastructure", "type::defect"],
                        "wsjf_labels": { "urgency": [...], "risk": [...] }
                    }
            ''')
            exit(1)

        self.EPIC_TYPE_ICONS = {
            "Epic":       "🏆",
            "Capability": "🧩",
            "Feature":    "🛠️",
        }

        self._ssl_verify_override = ssl_verify
        self.reload_config()

        # project_labels and piid_labels are optional — used only for simulation/bootstrap.
        # Reports and tools discover these dynamically from live epic labels.
        missing_fields = [
            field for field, val in [
                ("url",              self.url),
                ("parent_group",     self.parent_group),
                ("private_token",    self.private_token),
                ("fibonacci_weights", self.fibonacci_weights),
                ("epic_labels",      self.EPIC_TYPE_LABELS),
            ] if not val
        ]

        if missing_fields:
            print(f"ERROR: Missing required fields in config.json: {', '.join(missing_fields)}")
            exit(1)

        try:
            self.gl = gitlab.Gitlab(self.url, private_token=self.private_token, ssl_verify=self.ssl_verify)
            self.gl.auth()

            version, _ = self.gl.version()
            print(f"GitLab server : {self.gl.api_url}  (v{version})")
            print(f"python-gitlab : v{pkg_version('python-gitlab')}")
            print(f"Python        : {sys.version}")
        except gitlab.GitlabAuthenticationError:
            print("Authentication failed. Please check your private token.")
            exit(1)
        except gitlab.GitlabGetError as e:
            print(f"Failed to fetch group '{self.parent_group}': {e}")
            exit(1)

    def reload_config(self):
        """Re-read config.json and refresh all config-derived instance attributes.

        Safe to call at any time after __init__. Does NOT re-initialise the
        GitLab API connection — only config-file-derived state is updated.
        """
        def parse_label_env(env_var):
            env_val = os.getenv(env_var)
            return [item.strip() for item in env_val.split(",") if item.strip()] if env_val else None

        def parse_fibonacci_env(env_var):
            env_val = os.getenv(env_var)
            if env_val:
                try:
                    return [int(item.strip()) for item in env_val.split(",") if item.strip()]
                except ValueError:
                    return None
            return None

        with open(self.config_file, "r", encoding="utf-8") as f:
            config = json.load(f)

        self.url              = config.get("url", "")
        self.parent_group     = os.getenv("GROUP_NAME") or config.get("parent_group", "")
        self.gitlab_namespace = config.get("gitlab_namespace", "")

        # Token precedence: GITLAB_TOKEN env > config.json > ACCESS_TOKEN (deprecated).
        # Keeps the secret out of the tracked config.json — see issue #110. Locally,
        # export GITLAB_TOKEN; in CI set it as a masked variable; in the cloud the
        # seed step injects it into the SSM-stored config.
        gitlab_token_env = os.getenv("GITLAB_TOKEN")
        access_token_env = os.getenv("ACCESS_TOKEN")   # deprecated alias
        if gitlab_token_env:
            self.private_token = gitlab_token_env
        elif config.get("private_token"):
            self.private_token = config.get("private_token", "")
        elif access_token_env:
            print("WARNING: ACCESS_TOKEN is deprecated; set GITLAB_TOKEN instead.", file=sys.stderr)
            self.private_token = access_token_env
        else:
            self.private_token = ""

        self.api_timeout     = config.get("api_timeout",    300)
        self.delete_workers  = config.get("delete_workers",  5)
        self.report_workers  = config.get("report_workers",  4)

        _cfg_ssl_verify = config.get("ssl_verify", True)
        _env_ssl_verify = os.getenv("SSL_VERIFY")
        if _env_ssl_verify is not None:
            _env_ssl_verify = _env_ssl_verify.strip().lower() not in ("false", "0", "no")
        ssl_override = getattr(self, "_ssl_verify_override", None)
        self.ssl_verify = ssl_override if ssl_override is not None else (
                          _env_ssl_verify if _env_ssl_verify is not None else _cfg_ssl_verify)
        if not self.ssl_verify:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        fibonacci_weights_env = parse_fibonacci_env("FIBONACCI_WEIGHTS")
        self.fibonacci_weights = fibonacci_weights_env if fibonacci_weights_env else config.get("fibonacci_weights")

        _bvf = config.get("business_value_field", {})
        self.BUSINESS_VALUE_FIELD = {
            "name":           _bvf.get("name",        "Business Value"),
            "field_type":     _bvf.get("field_type",  "SINGLE_SELECT"),
            "select_options": [str(v) for v in _bvf.get("select_options", ["1","2","3","5","8","13","21"])],
        }

        project_labels_env = parse_label_env("PROJECT_LABELS")
        self.PROJECT_LABELS = project_labels_env if project_labels_env else config.get("project_labels", [])

        piid_labels_env = parse_label_env("PIID_LABELS")
        self.PIID_LABELS = piid_labels_env if piid_labels_env else config.get("piid_labels", [])

        epic_labels_env = parse_label_env("EPIC_TYPE_LABELS")
        self.EPIC_TYPE_LABELS = epic_labels_env if epic_labels_env else config.get("epic_type_labels", [])
        self.EPIC_TYPE_DISPLAY_NAMES = [
            t.split("::")[-1].capitalize() if "::" in t
            else t.split(":")[-1].capitalize() if ":" in t
            else t.capitalize()
            for t in self.EPIC_TYPE_LABELS
        ]

        risk_labels_env = parse_label_env("RISK_LABELS")
        self.RISK_LABELS = risk_labels_env if risk_labels_env else config.get("risk_labels", [])

        roam_labels_env = parse_label_env("ROAM_LABELS")
        self.ROAM_LABELS = roam_labels_env if roam_labels_env else config.get("roam_labels", [
            "roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved",
        ])

        _wsjf = config.get("wsjf_labels", {})
        self.WSJF_URGENCY_LABELS = _wsjf.get("urgency", [])
        self.WSJF_RISK_LABELS    = _wsjf.get("risk",    [])
        self.WSJF_LABELS         = self.WSJF_URGENCY_LABELS + self.WSJF_RISK_LABELS

        work_type_env = parse_label_env("WORK_TYPE_LABELS")
        self.WORK_TYPE_LABELS = work_type_env if work_type_env else config.get("work_type_labels", [])

        lifecycle_env = parse_label_env("LIFECYCLE_LABELS")
        self.LIFECYCLE_LABELS = lifecycle_env if lifecycle_env else config.get("lifecycle_labels", [])

        self.EPIC_TYPE_PLANNED_WEIGHTS = config.get("epic_type_planned_weights", {
            "Feature":    [3, 5, 8, 13],
            "Capability": [21, 34, 55, 89],
            "Epic":       [89, 144, 233, 377],
        })

        _bd = config.get("defaults", {}).get("bootstrap", {})
        self.default_num_value_streams    = _bd.get("num_value_streams",    2)
        self.default_num_arts             = _bd.get("num_arts",             2)
        self.default_num_teams            = _bd.get("num_teams",            2)
        self.default_portfolio_epics      = _bd.get("portfolio_epics",      5)
        self.default_vs_caps_per_vs       = _bd.get("vs_caps_per_vs",       3)
        self.default_art_caps_per_art     = _bd.get("art_caps_per_art",     4)
        self.default_features_per_team    = _bd.get("features_per_team",    4)
        self.default_direct_feature_ratio       = _bd.get("direct_feature_ratio",       0.70)
        self.default_history_close_rate_min     = _bd.get("history_close_rate_min",     0.70)
        self.default_history_close_rate_max     = _bd.get("history_close_rate_max",     0.95)
        self.default_current_pi_issue_close_pct = _bd.get("current_pi_issue_close_pct", 0.50)
        # Seed a realistic amount of blocking during lorem bootstrap. Toggle off via
        # config; percentages reflect a normal portfolio mid-PI (not block-heavy).
        self.default_seed_blocks          = _bd.get("seed_blocks",          True)
        self.default_epic_block_percent   = _bd.get("epic_block_percent",   12)
        self.default_issue_block_percent  = _bd.get("issue_block_percent",  8)

        _td = config.get("defaults", {}).get("tools", {})
        self.default_close_percent             = _td.get("close_percent",                30.0)
        self.default_generate_blocks_count     = _td.get("generate_epic_blocks_count",   10)
        self.default_generate_issue_blocks_count = _td.get("generate_issue_blocks_count", 10)
        self.default_simulate_pi_percent       = _td.get("simulate_pi_progress_percent", 50.0)
        self.default_generate_issues_count     = _td.get("generate_issues_count",        5)
        self.default_weight_drift_threshold    = _td.get("weight_drift_threshold",       20.0)
        self.default_set_risk_percent          = _td.get("set_risk_labels_percent",       15.0)
        self.default_set_wsjf_percent          = _td.get("set_wsjf_labels_percent",       20.0)
        _rr = _td.get("roam_risk_relations", {})
        self.default_roam_risk_relations_min   = _rr.get("min", 1)
        self.default_roam_risk_relations_max   = _rr.get("max", 3)

        _sd = config.get("defaults", {}).get("serve", {})
        self.serve_port = _sd.get("port", 80)

        self.grafana_url = os.getenv("GRAFANA_URL") or config.get("grafana_url", "")


def _confirm_create(gl):
    """Show a summary of what Create will do and ask for confirmation."""
    cfg = gl
    ns  = gl.gitlab_namespace
    grp = gl.parent_group
    full_path = f"{ns}/{grp}" if ns else grp

    print()
    print("  Create — Populate with lorem SAFe data")
    print("  " + "-" * 46)
    print(f"  Target group : {full_path}")
    print()
    print("  This will create inside that group:")
    print("    • All label sets (PIID, type, lifecycle, risk, WSJF, ROAM)")
    print("    • Value Stream → ART → Team subgroups + Team Backlog projects")
    print("    • Portfolio Epics, VS/ART Capabilities, and Team Features")
    print("      with lorem text, dates, planned weights, and PI labels")
    print("    • Issues linked to Features (story points via Fibonacci weights)")
    print("    • Business Value custom field set on every epic")
    print()
    print("  The group must exist first (use Scaffold if it does not).")
    print("  Existing content will not be removed — run Clean first for a fresh start.")
    print()
    confirm = input("  Proceed? [y/N]: ").strip().lower()
    if confirm in ("y", "yes"):
        now      = datetime.now()
        log_path = Path("logs") / now.strftime("%Y-%m-%d") / f"{now.strftime('%H-%M-%S')}_create.log"
        with _tee_to_log(log_path):
            print(f"  log → {log_path}\n")
            gl.create_all_lorem_objects()
    else:
        print("  Cancelled.")


def _confirm_clean(gl):
    """Show exactly what Clean will destroy and require the group name as confirmation."""
    ns        = gl.gitlab_namespace
    grp       = gl.parent_group
    full_path = f"{ns}/{grp}" if ns else grp

    print()
    print("  ⚠️   DESTRUCTIVE — this cannot be undone.")
    print("  " + "-" * 46)
    print(f"  Target group : {full_path}")
    print()
    print("  Everything inside that group will be permanently deleted:")
    print("    • All wiki pages")
    print("    • All epics, capabilities, and features")
    print("    • All milestones")
    print("    • All issues")
    print("    • All labels")
    print("    • All team backlog projects")
    print("    • All subgroups (ARTs, Value Streams)")
    print("    • The root group itself")
    print()
    print(f"  To confirm, type the group name exactly: {grp}")
    print()
    typed = input("  Group name: ").strip()
    if typed == grp:
        now      = datetime.now()
        log_path = Path("logs") / now.strftime("%Y-%m-%d") / f"{now.strftime('%H-%M-%S')}_clean.log"
        with _tee_to_log(log_path):
            print(f"  log → {log_path}\n")
            gl.cleanup_group()
    else:
        print(f"  '{typed}' does not match '{grp}' — cancelled.")


def _last_report_stamp():
    """Return 'YYYY-MM-DD HH:MM' of the most recent report run, or None."""
    root = Path("reports")
    if not root.exists():
        return None
    for date_dir in sorted(root.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for time_dir in sorted(date_dir.iterdir(), reverse=True):
            if not time_dir.is_dir():
                continue
            try:
                t = datetime.strptime(
                    f"{date_dir.name}{time_dir.name}", "%Y%m%d%H%M%S"
                )
                return t.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue
    return None


def _last_tool_stamp():
    """Return (key, 'YYYY-MM-DD HH:MM') of the most recent tool log, or None."""
    root = Path("logs")
    if not root.exists():
        return None
    for date_dir in sorted(root.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for log_file in sorted(date_dir.iterdir(), reverse=True):
            if log_file.suffix != ".log":
                continue
            parts = log_file.stem.split("_", 1)
            if len(parts) != 2:
                continue
            time_str, key = parts
            try:
                t = datetime.strptime(
                    f"{date_dir.name}_{time_str}", "%Y-%m-%d_%H-%M-%S"
                )
                return key, t.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue
    return None


def _run_main_menu(gl):
    """Top-level interactive menu. Loops until the user quits."""
    while True:
        _clear()
        print("NCE GitLab SAFe Tooling")
        print("=" * 38)
        print(f"  Group : {gl.parent_group}")
        last_report = _last_report_stamp()
        last_tool   = _last_tool_stamp()
        if last_report or last_tool:
            if last_report:
                print(f"  Last report : {last_report}")
            if last_tool:
                key, ts = last_tool
                print(f"  Last tool   : {key}  ({ts})")
        srv_running, _ = gl._serve_status()
        srv_port       = gl._serve_port()
        srv_label      = f"RUNNING  (port {srv_port})" if srv_running else "stopped"
        print(f"  Server      : {srv_label}")
        print()
        print("  [1] Reports      Generate wiki reports")
        print("  [2] Utilities    Data management tools")
        print("  [3] Scaffold     Create SAFe group/project structure")
        print("  [4] Create       Populate group with lorem SAFe data")
        print("  [5] Clean        Delete all group data")
        print("  [6] Site         Build, clean, and serve the report site")
        print("  [q] quit")
        print()

        raw = input("Select [1-6] or q: ").strip().lower()

        if raw in ("q", "quit", "exit"):
            return
        if raw == "1":
            if gl.run_reports_menu():
                _pause()
        elif raw == "2":
            gl.run_tools_menu()
        elif raw == "3":
            gl.create_safe_hierarchy()
            _pause()
        elif raw == "4":
            _confirm_create(gl)
            _pause()
        elif raw == "5":
            _confirm_clean(gl)
            _pause()
        elif raw == "6":
            gl.run_site_menu()
        else:
            print("  Please enter a number between 1 and 6.")


def _last_data_dir():
    """Return the most recent reports/.../data directory that contains a valid snapshot."""
    root = Path("reports")
    if not root.exists():
        return None
    for d in sorted(root.glob("*/*/data"), reverse=True):
        if (d / "epics.json").exists():
            return d
    return None


def _parse_tool_args(extra):
    """Convert leftover CLI tokens into a tool-param prefills dict.

    Handles --flag (bool True) and --param value (string, coerced later).
    Normalises --dry-run style hyphens to underscores.
    """
    result = {}
    i = 0
    while i < len(extra):
        tok = extra[i]
        if tok.startswith("--"):
            name = tok[2:].replace("-", "_")
            if i + 1 < len(extra) and not extra[i + 1].startswith("-"):
                result[name] = extra[i + 1]
                i += 2
            else:
                result[name] = True
                i += 1
        else:
            i += 1
    return result


def _parse_formats(raw_list):
    """Resolve --formats tokens (space and/or comma-separated) to a set of format names."""
    _valid = {"all", "markdown", "plotly", "interactive"}
    _all   = {"markdown", "plotly", "interactive"}
    tokens = set()
    for tok in (raw_list or []):
        for part in tok.split(","):
            p = part.strip().lower()
            if p:
                tokens.add(p)
    invalid = tokens - _valid
    if invalid:
        print(f"Unknown --formats value(s): {', '.join(sorted(invalid))}")
        print(f"Valid formats: {', '.join(sorted(_valid))}")
        sys.exit(1)
    if "all" in tokens:
        return set(_all)
    if not tokens:
        return set(_all)
    return tokens


def main():
    sys.stdout.reconfigure(line_buffering=True)
    # ------------------------------------------------------------------ #
    # Signal handler — installed before NceGitLab() so it covers init too #
    # ------------------------------------------------------------------ #
    _phase = ["starting"]   # mutable so the closure can see updates
    _gl    = [None]

    def _sigint_handler(sig, frame):
        phase  = _phase[0]
        gl_ref = _gl[0]
        detail = getattr(gl_ref, '_current_op', None) if gl_ref else None
        msg    = f"Interrupted: {phase}"
        if detail:
            msg += f" — {detail}"
        print(f"\n{msg}")
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint_handler)

    parser = argparse.ArgumentParser(description="NCE GitLab SAFe tooling")
    parser.add_argument("--usage",                  action="store_true", help="Show this help message and exit")
    parser.add_argument("-c", "--clean",             action="store_true", help="Delete all group data")
    parser.add_argument("-C", "--create",            action="store_true", help="Bootstrap lorem SAFe data")
    parser.add_argument("-r", "--report",            nargs="?", const="__menu__", metavar="REPORT",
                        help="Generate reports interactively (omit REPORT to show menu)")
    parser.add_argument("--reuse-data",              metavar="DATA_DIR",
                        help="Skip API fetch; load JSON snapshot from this directory instead")
    parser.add_argument("--last",                    action="store_true",
                        help="Reuse the most recently pulled data snapshot (no API fetch)")
    parser.add_argument("-a", "--all",               action="store_true", help="Run clean, create, and report in sequence")
    parser.add_argument("--formats",                 nargs="+", metavar="FORMAT",
                        help="Output formats: all markdown plotly interactive "
                             "(space or comma-separated, default: markdown)")
    parser.add_argument("--no-ssl-verify",           action="store_true",
                        help="Disable SSL certificate verification (Aisle 5 / corporate network)")
    parser.add_argument("-ut", "--utilities",        nargs="?", const="__menu__", metavar="TOOL",
                        help="Run a utility tool interactively (omit TOOL to show menu)")
    parser.add_argument("-D", "--diagnose",          action="store_true",
                        help="Print environment, software versions, API capabilities, and label validation to stdout")
    parser.add_argument("-s", "--scaffold",          nargs="?", const="__prompt__", metavar="GROUP",
                        help="Create SAFe group/project structure only (omit GROUP to be prompted)")
    parser.add_argument("-w", "--serve",             action="store_true",
                        help="Start the uvicorn server and open the browser")
    args, extra = parser.parse_known_args()

    if args.usage:
        parser.print_help()
        print()
        return

    formats   = _parse_formats(args.formats)
    _phase[0] = "connecting to GitLab"
    gl = NceGitLab(ssl_verify=False if args.no_ssl_verify else None)
    _gl[0] = gl

    if not any(vars(args).values()):
        _run_main_menu(gl)
        return

    if args.utilities is not None:
        _phase[0] = "utilities menu"
        tool_key = None if args.utilities == "__menu__" else args.utilities
        prefills = _parse_tool_args(extra)
        if args.all:
            prefills.setdefault("all", True)
        gl.run_tools_menu(tool_key, prefills=prefills)
        return

    if args.diagnose:
        _phase[0] = "diagnose"
        gl._tool_diagnose()
        return

    if args.scaffold is not None:
        _phase[0] = "scaffold"
        target = None if args.scaffold == "__prompt__" else args.scaffold
        gl.create_safe_hierarchy(target)
        return

    if args.serve:
        import uvicorn
        from server.app import app as _fastapi_app

        _phase[0] = "serve"
        port = gl._serve_port()
        _fastapi_app.state.gl = gl
        gl._serve_build_frontend()

        uvicorn.run(_fastapi_app, host="0.0.0.0", port=port)
        return

    phases = []

    def _run_phase(label, fn, log_stem=None):
        _phase[0] = label
        now      = datetime.now()
        log_path = (
            Path("logs")
            / now.strftime("%Y-%m-%d")
            / f"{now.strftime('%H-%M-%S')}_{log_stem or label}.log"
        ) if log_stem is not None else None
        start = now
        t0    = time.monotonic()
        if log_path:
            with _tee_to_log(log_path):
                print(f"  log → {log_path}\n")
                fn()
        else:
            fn()
        elapsed = time.monotonic() - t0
        end     = datetime.now()
        phases.append((label, start, end, elapsed))

    if args.all or args.clean:
        _run_phase("cleanup", gl.cleanup_group, log_stem="clean")
    if args.all or args.create:
        _run_phase("create",  gl.create_all_lorem_objects, log_stem="create")

    if args.all:
        _phase[0] = "reports"
        gl.generate_all_reports(formats=formats)
        if hasattr(gl, '_last_reports_phase'):
            phases.append(gl._last_reports_phase)
        if len(phases) > 1:
            gl._print_timing_table(phases, "Full Run Summary (--all)")
    elif args.report is not None:
        _phase[0] = "reports"
        report_key = None if args.report == "__menu__" else args.report
        reuse = args.reuse_data
        if args.last:
            last = _last_data_dir()
            if last:
                print(f"  --last: reusing snapshot from {last}\n")
                reuse = str(last)
            else:
                print("  --last: no previous snapshot found — fetching live data.\n")
        gl.run_reports_menu(report_key, reuse_data=reuse, formats=formats)

    # single-phase timing summary (--clean or --create alone)
    if not args.all and phases:
        gl._print_timing_table(phases)


if __name__ == "__main__":
    main()
