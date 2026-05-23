import argparse
import json
import os
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
    IssuesMixin,
    LabelsMixin,
    MilestonesMixin,
    ProjectsMixin,
    ReportsMixin,
    ToolsMixin,
    UtilitiesMixin,
    WikiMixin,
)


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
):
    def __init__(self, config_file="config.json"):
        self.config_file = Path(config_file)

        if not self.config_file.exists():
            print(f"Config file '{self.config_file}' not found!")
            print('''Please create config.json with the following format:
                    {
                        "url": "https://gitlab.com",
                        "private_token": "glpat-XXXXXXXXXXXXXXXXXXXX",
                        "parent_group": "AMW-120",
                        "gitlab_namespace": "gl-demo-ultimate-lmwilliams",
                        "project_labels": ["project::DO", "project::RTSO", "project::DCGS", "project::TestA", "project::TestB", "project::TestC"],
                        "piid_labels": ["PIID::2026Q3", "PIID::2026Q4", "PIID::2027Q1", "PIID::2027Q2", "PIID::2027Q3", "PIID::2027Q4"],
                        "epic_labels": ["Epic", "Capability", "Feature"]
                    }
            ''')
            exit(1)

        self.EPIC_TYPE_ICONS = {
            "Epic":       "🏆",
            "Capability": "🧩",
            "Feature":    "🛠️",
        }

        with open(self.config_file, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)

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

        self.url              = config.get("url", "")
        self.parent_group     = os.getenv("GROUP_NAME") or config.get("parent_group", "")
        self.gitlab_namespace = config.get("gitlab_namespace", "")

        access_token_env = os.getenv("ACCESS_TOKEN")
        if access_token_env:
            self.private_token = access_token_env
        else:
            self.private_token = config.get("private_token", "")

        fibonacci_weights_env = parse_fibonacci_env("FIBONACCI_WEIGHTS")
        self.fibonacci_weights = fibonacci_weights_env if fibonacci_weights_env else config.get("fibonacci_weights")

        project_labels_env = parse_label_env("PROJECT_LABELS")
        self.PROJECT_LABELS = project_labels_env if project_labels_env else config.get("project_labels", [])

        piid_labels_env = parse_label_env("PIID_LABELS")
        self.PIID_LABELS = piid_labels_env if piid_labels_env else config.get("piid_labels", [])

        epic_labels_env = parse_label_env("EPIC_TYPE_LABELS")
        self.EPIC_TYPE_LABELS = epic_labels_env if epic_labels_env else config.get("epic_type_labels", [])

        self.EPIC_TYPE_PLANNED_WEIGHTS = config.get("epic_type_planned_weights", {
            "Feature":    [3, 5, 8, 13],
            "Capability": [21, 34, 55, 89],
            "Epic":       [89, 144, 233, 377],
        })

        missing_fields = [
            field for field, val in [
                ("url",              self.url),
                ("parent_group",     self.parent_group),
                ("private_token",    self.private_token),
                ("fibonacci_weights", self.fibonacci_weights),
                ("project_labels",   self.PROJECT_LABELS),
                ("piid_labels",      self.PIID_LABELS),
                ("epic_labels",      self.EPIC_TYPE_LABELS),
            ] if not val
        ]

        if missing_fields:
            print(f"ERROR: Missing required fields in config.json: {', '.join(missing_fields)}")
            exit(1)

        try:
            self.gl = gitlab.Gitlab(self.url, private_token=self.private_token)
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


def main():
    parser = argparse.ArgumentParser(description="NCE GitLab SAFe tooling")
    parser.add_argument("--usage",     action="store_true", help="Show this help message and exit")
    parser.add_argument("--clean",     action="store_true", help="Delete all group data")
    parser.add_argument("--create",    action="store_true", help="Bootstrap lorem SAFe data")
    parser.add_argument("--report",    nargs="?", const="__menu__", metavar="REPORT",
                        help="Generate reports interactively (omit REPORT to show menu)")
    parser.add_argument("--all",       action="store_true", help="Run clean, create, and report in sequence")
    parser.add_argument("--utilities", nargs="?", const="__menu__", metavar="TOOL",
                        help="Run a utility tool interactively (omit TOOL to show menu)")
    args = parser.parse_args()

    if args.usage or not any(vars(args).values()):
        parser.print_help()
        print()
        return

    gl = NceGitLab()

    if args.utilities is not None:
        tool_key = None if args.utilities == "__menu__" else args.utilities
        gl.run_tools_menu(tool_key)
        return

    phases = []

    def _run_phase(label, fn):
        start = datetime.now()
        t0    = time.monotonic()
        fn()
        elapsed = time.monotonic() - t0
        end     = datetime.now()
        phases.append((label, start, end, elapsed))

    if args.all or args.clean:
        _run_phase("cleanup", gl.cleanup_group)
    if args.all or args.create:
        _run_phase("create",  gl.create_all_lorem_objects)

    if args.all:
        gl.generate_all_reports()
        if hasattr(gl, '_last_reports_phase'):
            phases.append(gl._last_reports_phase)
        if len(phases) > 1:
            gl._print_timing_table(phases, "Full Run Summary (--all)")
    elif args.report is not None:
        report_key = None if args.report == "__menu__" else args.report
        gl.run_reports_menu(report_key)

    # single-phase timing summary (--clean or --create alone)
    if not args.all and phases:
        gl._print_timing_table(phases)


if __name__ == "__main__":
    main()
