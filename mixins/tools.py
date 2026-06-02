import random
import sys
from collections import defaultdict
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Tool registry
# Each entry describes one runnable tool: its display name, a short
# description, the ordered list of parameters to prompt for, and the method
# on NceGitLab that implements it.
#
# param schema:
#   name        – internal key
#   prompt      – text shown to the user
#   type        – float | int | bool | str
#   default     – value used when the user presses Enter (omit = required)
#   optional    – True means blank input → None (only meaningful for int/str)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "key":         "audit-hierarchy",
        "description": "Verify Features have Capability parents and Capabilities have Epic parents",
        "method":      "_tool_audit_hierarchy",
        "params":      [],
    },
    {
        "key":         "audit-labels",
        "description": "Report every epic missing a type, PIID, or project label",
        "method":      "_tool_audit_labels",
        "params":      [],
    },
    {
        "key":         "clean-wikis",
        "description": "Delete all wiki pages from: 'portfolio' (root), 'teams' (all team wikis), 'all' (every group), or an explicit group path",
        "method":      "_tool_clean_wikis",
        "params": [
            {"name": "scope",   "prompt": "Scope — portfolio / teams / all / <group-path>", "type": str,  "default": "portfolio"},
            {"name": "dry_run", "prompt": "Dry run?",                                        "type": bool, "default": False},
        ],
    },
    {
        "key":         "clean-roam-risks",
        "description": "Delete all ROAM risk issues (and their epic links) across the group",
        "method":      "_tool_clean_roam_risks",
        "params": [
            {"name": "dry_run", "prompt": "Dry run?", "type": bool, "default": False},
        ],
    },
    {
        "key":         "close-percent",
        "description": "Randomly close N% of open epics and issues (simulate PI progress)",
        "method":      "_tool_close_percent",
        "params": [
            {"name": "percent",  "prompt": "Percent to close",            "type": float, "default": 30.0},
            {"name": "seed",     "prompt": "Random seed (blank = none)",  "type": int,   "optional": True},
            {"name": "dry_run",  "prompt": "Dry run?",                    "type": bool,  "default": False},
        ],
    },
    {
        "key":         "export-epics",
        "description": "Export all epics from the group hierarchy to CSV or JSON",
        "method":      "export_epics",
        "params": [
            {"name": "output_path", "prompt": "Output file path (.csv or .json, blank = auto-named)", "type": str, "optional": True},
        ],
    },
    {
        "key":         "export-issues",
        "description": "Export all issues from the group hierarchy to CSV or JSON",
        "method":      "export_issues",
        "params": [
            {"name": "output_path", "prompt": "Output file path (.csv or .json, blank = auto-named)", "type": str, "optional": True},
        ],
    },
    {
        "key":         "generate-epic-blocks",
        "description": "Randomly create or remove blocking relationships between epics (negative count = remove)",
        "method":      "_tool_generate_epic_blocks",
        "params": [
            {"name": "count",   "prompt": "Relationships to create (positive) or remove (negative)", "type": int,  "default": 10},
            {"name": "dry_run", "prompt": "Dry run?",                                                 "type": bool, "default": False},
        ],
    },
    {
        "key":         "generate-issues",
        "description": "Create issues in team backlog projects linked to Feature epics",
        "method":      "_tool_generate_issues",
        "params": [
            {"name": "count",           "prompt": "Issues to create per Feature (default 5)",              "type": int,   "default": 5},
            {"name": "feature_percent", "prompt": "Percent of Features to target (100 = all, 50 = half)",  "type": float, "default": 100.0},
            {"name": "dry_run",         "prompt": "Dry run?",                                               "type": bool,  "default": False},
        ],
    },
    {
        "key":         "generate-risk-reasons",
        "description": "Create Behind Schedule / Past Due / Child Overdue / Blocked conditions on a random % of open epics",
        "method":      "_tool_generate_risk_reasons",
        "params": [
            {"name": "conditions",   "prompt": "Conditions to create (behind_schedule / past_due / child_overdue / blocked / all)", "type": str,   "default": "all"},
            {"name": "percent",      "prompt": "Percent of eligible epics to target (default 20)",                         "type": float, "default": 20.0},
            {"name": "days_overdue", "prompt": "Days past due to set on due dates (default 7)",                            "type": int,   "default": 7},
            {"name": "piid",         "prompt": "PI label for behind_schedule (blank = auto-detect active PI)",             "type": str,   "optional": True},
            {"name": "dry_run",      "prompt": "Dry run?",                                                                  "type": bool,  "default": False},
        ],
    },
    {
        "key":         "generate-roam-risks",
        "description": "Create ROAM risk issues, each related to a random number of epics",
        "method":      "_tool_generate_roam_risks",
        "params": [
            {"name": "count",         "prompt": "Number of ROAM risk issues to create",                       "type": int,  "default": 10},
            {"name": "relations_min", "prompt": "Min epics related per risk (blank = config default)",        "type": int,  "optional": True},
            {"name": "relations_max", "prompt": "Max epics related per risk (blank = config default)",        "type": int,  "optional": True},
            {"name": "piid",          "prompt": "Limit to PIID label (blank = all)",                          "type": str,  "optional": True},
            {"name": "seed",          "prompt": "Random seed (blank = none)",                                  "type": int,  "optional": True},
            {"name": "dry_run",       "prompt": "Dry run?",                                                    "type": bool, "default": False},
        ],
    },
    {
        "key":         "import-epics",
        "description": "Import epics from a CSV or JSON file with pre-flight validation",
        "method":      "import_epics",
        "params": [
            {"name": "input_path",         "prompt": "Input file path (.csv or .json)",                                        "type": str,  "optional": False},
            {"name": "unresolved_parent",  "prompt": "Unresolvable parent_id action (ask / label / skip)",                     "type": str,  "default": "label"},
            {"name": "dry_run",            "prompt": "Dry run? (validate and preview only)",                                    "type": bool, "default": False},
        ],
    },
    {
        "key":         "import-issues",
        "description": "Import issues from a CSV or JSON file with pre-flight validation",
        "method":      "import_issues",
        "params": [
            {"name": "input_path",          "prompt": "Input file path (.csv or .json)",                            "type": str,  "optional": False},
            {"name": "target_project_path", "prompt": "Target project path (blank = use project_path column)",      "type": str,  "optional": True},
            {"name": "dry_run",             "prompt": "Dry run? (validate and preview only)",                       "type": bool, "default": False},
        ],
    },
    {
        "key":         "list-wikis",
        "description": "List all wiki pages for: 'portfolio' (root), 'teams' (all team wikis), 'all' (every group), or an explicit group path",
        "method":      "_tool_list_wikis",
        "params": [
            {"name": "scope", "prompt": "Scope (portfolio / teams / all / <group-path>)", "type": str, "default": "portfolio"},
        ],
    },
    {
        "key":         "orphan-epics",
        "description": "Remove parent links from N or X% of epics (simulate orphaned data)",
        "method":      "_tool_orphan_epics",
        "params": [
            {"name": "count",   "prompt": "Number of epics to orphan (blank to use percent instead)", "type": int,   "optional": True},
            {"name": "percent", "prompt": "Percent of epics to orphan (used when count is blank)",    "type": float, "default": 10.0},
            {"name": "dry_run", "prompt": "Dry run?",                                                  "type": bool,  "default": False},
        ],
    },
    {
        "key":         "orphan-issues",
        "description": "Remove epic links from N or X% of issues (simulate orphaned data)",
        "method":      "_tool_orphan_issues",
        "params": [
            {"name": "count",   "prompt": "Number of issues to orphan (blank to use percent instead)", "type": int,   "optional": True},
            {"name": "percent", "prompt": "Percent of issues to orphan (used when count is blank)",    "type": float, "default": 10.0},
            {"name": "dry_run", "prompt": "Dry run?",                                                   "type": bool,  "default": False},
        ],
    },
    {
        "key":         "reset-pi-progress",
        "description": "Reopen all closed issues linked to epics in a specific PI",
        "method":      "_tool_reset_pi_progress",
        "params": [
            {"name": "piid",    "prompt": "PIID label (e.g. PIID::2026Q3)", "type": str,  "optional": False},
            {"name": "dry_run", "prompt": "Dry run?",                       "type": bool, "default": False},
        ],
    },
    {
        "key":         "scaffold",
        "description": "Create SAFe group/project structure (VS → ART → Team → Team Backlog) with no content",
        "method":      "create_safe_hierarchy",
        "params":      [],
    },
    {
        "key":         "set-epic-states",
        "description": "Open or close all epics matching an optional type and/or PI filter",
        "method":      "_tool_set_epic_states",
        "params": [
            {"name": "state",     "prompt": "State to set (open/close)",                             "type": str,  "default": "close"},
            {"name": "piid",      "prompt": "Limit to PIID label (e.g. PIID::2026Q3, blank = all)",  "type": str,  "optional": True},
            {"name": "epic_type", "prompt": "Limit to type (Epic/Capability/Feature, blank = all)",  "type": str,  "optional": True},
            {"name": "dry_run",   "prompt": "Dry run?",                                               "type": bool, "default": False},
        ],
    },
    {
        "key":         "set-issue-weights",
        "description": "Assign Fibonacci story-point weights to issues that have none (or all when reassign=True)",
        "method":      "_tool_set_issue_weights",
        "params": [
            {"name": "fibonacci",  "prompt": "Constrain to Fibonacci pool from config?",  "type": bool, "default": True},
            {"name": "min_weight", "prompt": "Minimum weight (blank = no min)",            "type": int,  "optional": True},
            {"name": "max_weight", "prompt": "Maximum weight (blank = no max)",            "type": int,  "optional": True},
            {"name": "reassign",   "prompt": "Replace existing weights too?",              "type": bool, "default": False},
            {"name": "dry_run",    "prompt": "Dry run?",                                   "type": bool, "default": False},
        ],
    },
    {
        "key":         "strip-issue-weights",
        "description": "Zero out all issue weights across every team project (clean slate for testing)",
        "method":      "_tool_strip_issue_weights",
        "params": [
            {"name": "dry_run", "prompt": "Dry run?", "type": bool, "default": False},
        ],
    },
    {
        "key":         "set-lifecycle-labels",
        "description": "Randomly assign lifecycle::funnel/analyzing/backlog/implementing/done labels to open epics (or all when reassign=True)",
        "method":      "_tool_set_lifecycle_labels",
        "params": [
            {"name": "percent",  "prompt": "Percent of open epics to label (default 20)", "type": float, "default": 20.0},
            {"name": "reassign", "prompt": "Replace existing lifecycle:: labels too?",     "type": bool,  "default": False},
            {"name": "dry_run",  "prompt": "Dry run?",                                     "type": bool,  "default": False},
        ],
    },
    {
        "key":         "strip-lifecycle-labels",
        "description": "Remove all lifecycle::* labels from every epic (clean slate for testing)",
        "method":      "_tool_strip_lifecycle_labels",
        "params": [
            {"name": "dry_run", "prompt": "Dry run?", "type": bool, "default": False},
        ],
    },
    {
        "key":         "set-piid-labels",
        "description": "Bulk-assign a PIID label to epics that are missing one",
        "method":      "_tool_set_piid_labels",
        "params": [
            {"name": "piid",      "prompt": "PIID label to assign (e.g. PIID::2026Q3)", "type": str,  "optional": False},
            {"name": "epic_type", "prompt": "Limit to type (Epic/Capability/Feature, blank = all)", "type": str, "optional": True},
            {"name": "dry_run",   "prompt": "Dry run?",                                  "type": bool, "default": False},
        ],
    },
    {
        "key":         "set-project-labels",
        "description": "Bulk-assign a project label to epics that are missing one",
        "method":      "_tool_set_project_labels",
        "params": [
            {"name": "label",     "prompt": "Project label to assign (e.g. project::DO)", "type": str,  "optional": False},
            {"name": "epic_type", "prompt": "Limit to type (Epic/Capability/Feature, blank = all)", "type": str, "optional": True},
            {"name": "dry_run",   "prompt": "Dry run?",                                    "type": bool, "default": False},
        ],
    },
    {
        "key":         "set-risk-labels",
        "description": "Randomly assign risk::high/medium/low labels to open epics that have none",
        "method":      "_tool_set_risk_labels",
        "params": [
            {"name": "percent",  "prompt": "Percent of open epics to label (default 15)", "type": float, "default": 15.0},
            {"name": "dry_run",  "prompt": "Dry run?",                                    "type": bool,  "default": False},
        ],
    },
    {
        "key":         "set-work-type-labels",
        "description": "Randomly assign type::feature/enabler/infrastructure/defect labels to open epics that have none (or all when reassign=True)",
        "method":      "_tool_set_work_type_labels",
        "params": [
            {"name": "percent",  "prompt": "Percent of open epics to label (default 20)", "type": float, "default": 20.0},
            {"name": "reassign", "prompt": "Replace existing type:: labels too?",          "type": bool,  "default": False},
            {"name": "dry_run",  "prompt": "Dry run?",                                     "type": bool,  "default": False},
        ],
    },
    {
        "key":         "strip-work-type-labels",
        "description": "Remove all type::* labels from every epic (clean slate for testing)",
        "method":      "_tool_strip_work_type_labels",
        "params": [
            {"name": "dry_run", "prompt": "Dry run?", "type": bool, "default": False},
        ],
    },
    {
        "key":         "set-wsjf-labels",
        "description": "Randomly assign wsjf-value/urgency/risk Fibonacci labels to open epics that have none (or all when reassign=True)",
        "method":      "_tool_set_wsjf_labels",
        "params": [
            {"name": "percent",  "prompt": "Percent of open epics to label (default 20)", "type": float, "default": 20.0},
            {"name": "reassign", "prompt": "Replace existing wsjf labels too?",           "type": bool,  "default": False},
            {"name": "dry_run",  "prompt": "Dry run?",                                    "type": bool,  "default": False},
        ],
    },
    {
        "key":         "strip-wsjf-labels",
        "description": "Remove all wsjf-value/urgency/risk labels from every epic (clean slate for testing)",
        "method":      "_tool_strip_wsjf_labels",
        "params": [
            {"name": "dry_run", "prompt": "Dry run?", "type": bool, "default": False},
        ],
    },
    {
        "key":         "simulate-pi-progress",
        "description": "Close X% of open issues linked to epics in a specific PI",
        "method":      "_tool_simulate_pi_progress",
        "params": [
            {"name": "piid",    "prompt": "PIID label (e.g. PIID::2026Q3)", "type": str,   "default": None, "optional": False},
            {"name": "percent", "prompt": "Percent of issues to close",     "type": float, "default": 50.0},
            {"name": "dry_run", "prompt": "Dry run?",                       "type": bool,  "default": False},
        ],
    },
    {
        "key":         "strip-labels",
        "description": "Remove a specific label from all epics (optionally filtered by type)",
        "method":      "_tool_strip_labels",
        "params": [
            {"name": "label",     "prompt": "Label to remove",                                       "type": str,  "optional": False},
            {"name": "epic_type", "prompt": "Limit to type (Epic/Capability/Feature, blank = all)",  "type": str,  "optional": True},
            {"name": "dry_run",   "prompt": "Dry run?",                                               "type": bool, "default": False},
        ],
    },
    {
        "key":         "update-weights",
        "description": "Assign planned weights to all epics based on SAFe type label",
        "method":      "_tool_update_epic_weights",
        "params": [
            {"name": "dry_run", "prompt": "Dry run?", "type": bool, "default": False},
        ],
    },
    {
        "key":         "validate-weights",
        "description": "Validate epic and issue weights against configured pools",
        "method":      "_tool_validate_weights",
        "params":      [],
    },
    {
        "key":         "weight-drift-check",
        "description": "Flag epics where planned weight vs sum of issue weights drifts beyond a threshold",
        "method":      "_tool_weight_drift_check",
        "params": [
            {"name": "threshold", "prompt": "Drift threshold % to flag (default 20)", "type": float, "default": 20.0},
            {"name": "epic_type", "prompt": "Limit to type (Epic/Capability/Feature, blank = all)", "type": str, "optional": True},
        ],
    },
]


def _prompt_param(param):
    """Prompt the user for a single parameter value and return the typed result."""
    ptype    = param["type"]
    optional = param.get("optional", False)
    default  = param.get("default")

    if ptype is bool:
        default_hint = "Y/n" if default else "y/N"
        raw = input(f"  {param['prompt']} [{default_hint}]: ").strip().lower()
        if not raw:
            return default if default is not None else False
        return raw in ("y", "yes")

    if ptype is int:
        while True:
            raw = input(f"  {param['prompt']}: ").strip()
            if not raw:
                if optional:
                    return None
                if default is not None:
                    return default
                print("  Required — please enter a value.")
                continue
            try:
                return int(raw)
            except ValueError:
                print("  Please enter a whole number.")

    if ptype is float:
        while True:
            hint = f" [{default}]" if default is not None else ""
            raw  = input(f"  {param['prompt']}{hint}: ").strip()
            if not raw and default is not None:
                return default
            try:
                val = float(raw)
                if not (0.0 <= val <= 100.0) and "percent" in param["name"]:
                    print("  Must be between 0 and 100.")
                    continue
                return val
            except ValueError:
                print("  Please enter a number.")

    # str
    while True:
        hint = f" [{default}]" if default is not None else ""
        raw  = input(f"  {param['prompt']}{hint}: ").strip()
        if not raw:
            if optional:
                return None
            if default is not None:
                return default
            print("  Required — please enter a value.")
            continue
        return raw


class ToolsMixin:

    def run_tools_menu(self, tool_key=None):
        """Show the utilities menu or run a specific tool by key."""
        if tool_key:
            tool = next((t for t in TOOLS if t["key"] == tool_key), None)
            if tool is None:
                print(f"Unknown tool '{tool_key}'. Available tools:")
                for t in TOOLS:
                    print(f"  {t['key']}")
                sys.exit(1)
            self._run_tool(tool)
            return

        print()
        print("Available Utilities")
        print("=" * 50)
        for i, tool in enumerate(TOOLS, 1):
            print(f"  [{i}] {tool['key']:<22} {tool['description']}")
        print(f"  [q] quit")
        print()

        while True:
            raw = input(f"Select [1-{len(TOOLS)}] or q to quit: ").strip().lower()
            if raw in ("q", "quit", "exit"):
                return
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(TOOLS):
                    self._run_tool(TOOLS[idx])
                    return
            except ValueError:
                pass
            print(f"  Please enter a number between 1 and {len(TOOLS)}.")

    def _run_tool(self, tool):
        print()
        print(f"  {tool['key']} — {tool['description']}")
        print()

        kwargs = {}
        for param in tool["params"]:
            kwargs[param["name"]] = _prompt_param(param)

        print()
        getattr(self, tool["method"])(**kwargs)

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _tool_clean_wikis(self, scope="portfolio", dry_run=False):
        """Delete all wiki pages from target groups.

        scope:
          'portfolio'  — root group wiki only
          'teams'      — every team-level group wiki
          'all'        — root + every group in the hierarchy
          <group-path> — a specific group by path (relative to root or absolute)
        """
        root = self.get_group_by_name(self.parent_group)

        # ── Collect target groups ─────────────────────────────────────── #
        def _all_groups(grp):
            """Recursively yield grp and every subgroup."""
            yield grp
            for sg in grp.subgroups.list(all=True):
                yield from _all_groups(self.gl.groups.get(sg.id))

        def _team_groups(grp, depth=0):
            """Yield leaf groups (no subgroups) — these are the team groups."""
            sgs = grp.subgroups.list(all=True)
            if not sgs:
                yield grp
            else:
                for sg in sgs:
                    yield from _team_groups(self.gl.groups.get(sg.id), depth + 1)

        scope_lc = scope.strip().lower()
        if scope_lc == "portfolio":
            targets = [root]
        elif scope_lc == "teams":
            targets = list(_team_groups(root))
        elif scope_lc == "all":
            targets = list(_all_groups(root))
        else:
            # Treat as an explicit group path: try relative to parent_group, then absolute
            candidates = [
                f"{root.full_path}/{scope.strip('/')}",
                scope.strip("/"),
            ]
            resolved = None
            for path in candidates:
                try:
                    resolved = self.gl.groups.get(path)
                    break
                except Exception:
                    continue
            if resolved is None:
                print(f"Group not found for scope '{scope}'. "
                      f"Use 'portfolio', 'teams', 'all', or a valid group path.")
                return
            targets = [resolved]

        # ── Inventory ─────────────────────────────────────────────────── #
        print(f"\nScope : {scope}")
        if dry_run:
            print("Mode  : DRY RUN — no pages will be deleted")
        print()

        total_groups = total_pages = 0
        for grp in targets:
            try:
                pages = grp.wikis.list(all=True)
            except Exception as e:
                print(f"  {grp.full_path}: could not list wiki pages — {e}")
                continue
            if not pages:
                continue
            total_groups += 1
            total_pages  += len(pages)
            print(f"  {grp.full_path}  ({len(pages)} page(s))")
            for page in pages:
                print(f"    • {page.slug}")
                if not dry_run:
                    try:
                        page.delete()
                    except Exception as e:
                        print(f"      ERROR deleting '{page.slug}': {e}")

        print()
        if dry_run:
            print(f"Dry run complete — {total_pages} page(s) across {total_groups} group(s) would be deleted.")
        else:
            print(f"Done — deleted {total_pages} page(s) across {total_groups} group(s).")

    def _tool_list_wikis(self, scope="portfolio"):
        """List all wiki pages in target groups.

        scope:
          'portfolio'  — root group wiki only
          'teams'      — every team-level group wiki
          'all'        — root + every group in the hierarchy
          <group-path> — a specific group by path (relative to root or absolute)
        """
        root = self.get_group_by_name(self.parent_group)

        def _all_groups(grp):
            yield grp
            for sg in grp.subgroups.list(all=True):
                yield from _all_groups(self.gl.groups.get(sg.id))

        def _team_groups(grp):
            sgs = grp.subgroups.list(all=True)
            if not sgs:
                yield grp
            else:
                for sg in sgs:
                    yield from _team_groups(self.gl.groups.get(sg.id))

        scope_lc = scope.strip().lower()
        if scope_lc == "portfolio":
            targets = [root]
        elif scope_lc == "teams":
            targets = list(_team_groups(root))
        elif scope_lc == "all":
            targets = list(_all_groups(root))
        else:
            candidates = [
                f"{root.full_path}/{scope.strip('/')}",
                scope.strip("/"),
            ]
            resolved = None
            for path in candidates:
                try:
                    resolved = self.gl.groups.get(path)
                    break
                except Exception:
                    continue
            if resolved is None:
                print(f"Group not found for scope '{scope}'. "
                      f"Use 'portfolio', 'teams', 'all', or a valid group path.")
                return
            targets = [resolved]

        print(f"\nScope : {scope}")
        print()

        total_groups = total_pages = 0
        for grp in targets:
            try:
                pages = grp.wikis.list(all=True)
            except Exception as e:
                print(f"  {grp.full_path}: could not list wiki pages — {e}")
                continue
            if not pages:
                continue
            total_groups += 1
            total_pages  += len(pages)
            print(f"  {grp.full_path}  ({len(pages)} page(s))")
            slug_w  = max((len(p.slug)  for p in pages), default=4)
            title_w = max((len(p.title) for p in pages), default=5)
            print(f"    {'SLUG':<{slug_w}}  {'TITLE':<{title_w}}")
            print(f"    {'-' * slug_w}  {'-' * title_w}")
            for page in sorted(pages, key=lambda p: p.slug):
                print(f"    {page.slug:<{slug_w}}  {page.title}")
            print()

        print(f"Total: {total_pages} page(s) across {total_groups} group(s).")

    def _tool_close_percent(self, percent=None, seed=None, dry_run=False):
        """Randomly close N% of open epics and issues across the group hierarchy."""
        if percent is None:
            percent = self.default_close_percent
        group = self.get_group_by_name(self.parent_group)
        rng   = random.Random(seed)

        print(f"Group: {group.full_path}")
        print(f"Percent to close: {percent}%"
              + (f"  (seed={seed})" if seed is not None else ""))
        if dry_run:
            print("(dry-run — no changes will be saved)")

        # Collect open epics
        print("\nCollecting open epics...")
        open_epics = []

        def _walk_epics(grp):
            for epic in grp.epics.list(all=True, state="opened"):
                open_epics.append((grp, epic))
            for sg in grp.subgroups.list(all=True):
                _walk_epics(self.gl.groups.get(sg.id))

        _walk_epics(group)

        k_epics      = max(0, round(len(open_epics) * percent / 100))
        epic_sample  = rng.sample(open_epics, k_epics)
        print(f"  {len(open_epics)} open  →  closing {len(epic_sample)}")

        # Collect open issues
        print("\nCollecting open issues...")
        open_issues = []
        for proj in group.projects.list(all=True, include_subgroups=True):
            if "_deletion_scheduled" in proj.path:
                continue
            try:
                full_p = self.gl.projects.get(proj.id)
                for issue in full_p.issues.list(all=True, state="opened"):
                    open_issues.append((full_p, issue))
            except Exception as e:
                print(f"  WARNING: could not fetch issues for '{proj.path_with_namespace}': {e}")

        k_issues      = max(0, round(len(open_issues) * percent / 100))
        issue_sample  = rng.sample(open_issues, k_issues)
        print(f"  {len(open_issues)} open  →  closing {len(issue_sample)}")

        # Close epics
        print("\n--- Closing epics ---")
        epics_closed = 0
        for grp, epic in epic_sample:
            label = f"Epic #{epic.iid} '{epic.title[:50]}' in {grp.full_path}"
            if dry_run:
                print(f"  DRY   {label}")
                epics_closed += 1
            else:
                try:
                    epic.state_event = "close"
                    epic.save()
                    print(f"  CLOSED {label}")
                    epics_closed += 1
                except Exception as e:
                    print(f"  ERROR  {label}: {e}")

        # Close issues
        print("\n--- Closing issues ---")
        issues_closed = 0
        for proj, issue in issue_sample:
            label = f"Issue #{issue.iid} '{issue.title[:50]}' in {proj.path_with_namespace}"
            if dry_run:
                print(f"  DRY   {label}")
                issues_closed += 1
            else:
                try:
                    issue.state_event = "close"
                    issue.save()
                    print(f"  CLOSED {label}")
                    issues_closed += 1
                except Exception as e:
                    print(f"  ERROR  {label}: {e}")

        print(f"\nDone.  Epics closed: {epics_closed}  Issues closed: {issues_closed}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_update_epic_weights(self, dry_run=False):
        """Assign random planned weights to all epics based on their SAFe type label."""
        group        = self.get_group_by_name(self.parent_group)
        weight_pools = self.EPIC_TYPE_PLANNED_WEIGHTS
        safe_types   = ["Epic", "Capability", "Feature"]

        print(f"Group: {group.full_path}")

        epics = group.epics.list(get_all=True, include_descendant_groups=True)
        print(f"Fetched {len(epics)} epics\n")

        counts  = {t: 0 for t in safe_types}
        skipped = 0

        for epic in epics:
            etype = next((t for t in safe_types if t in epic.labels), None)
            if etype is None:
                print(f"  SKIP  [{epic.iid}] '{epic.title[:60]}' — no SAFe type label")
                skipped += 1
                continue

            pool = weight_pools.get(etype, [])
            if not pool:
                print(f"  SKIP  [{epic.iid}] '{epic.title[:60]}' — no weight pool for {etype}")
                skipped += 1
                continue

            weight = random.choice(pool)

            if dry_run:
                print(f"  DRY   [{epic.iid}] {etype:<12} weight={weight:>5}  '{epic.title[:50]}'")
            else:
                self._set_epic_weight(epic, weight)
                print(f"  SET   [{epic.iid}] {etype:<12} weight={weight:>5}  '{epic.title[:50]}'")

            counts[etype] += 1

        print("\nDone.  Updated: " +
              ", ".join(f"{t}={counts[t]}" for t in safe_types) +
              f"  Skipped: {skipped}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_validate_weights(self):
        """Validate that every epic and issue has a weight from the correct pool."""
        group        = self.get_group_by_name(self.parent_group)
        weight_pools = self.EPIC_TYPE_PLANNED_WEIGHTS
        fib_weights  = self.fibonacci_weights
        safe_types   = ["Epic", "Capability", "Feature"]

        print(f"Validating weights in: {group.full_path}\n")

        # --- Epics ---
        print("Checking epic weights...")
        results = {t: {"ok": 0, "bad": []} for t in safe_types}
        no_type = []

        def _walk(grp):
            for epic in grp.epics.list(all=True):
                etype = next((t for t in safe_types if t in epic.labels), None)
                w     = getattr(epic, "weight", None)
                if etype is None:
                    no_type.append(epic)
                    continue
                pool = weight_pools.get(etype, [])
                if w in pool:
                    results[etype]["ok"] += 1
                else:
                    results[etype]["bad"].append((epic, w, pool))
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        _walk(group)

        print(f"\n{'Type':<15} {'Expected pool':<45} {'OK':>5} {'FAIL':>5}")
        print("-" * 74)
        all_pass = True
        for t in safe_types:
            pool      = weight_pools.get(t, [])
            ok_count  = results[t]["ok"]
            bad_count = len(results[t]["bad"])
            status    = "PASS" if bad_count == 0 else "FAIL"
            if bad_count:
                all_pass = False
            print(f"{t:<15} {str(pool):<45} {ok_count:>5} {bad_count:>5}  [{status}]")
            for epic, w, pool in results[t]["bad"]:
                print(f"  !! Epic #{epic.iid} '{epic.title[:50]}' weight={w}, expected one of {pool}")

        if no_type:
            all_pass = False
            print(f"\n{len(no_type)} epic(s) have no recognised type label:")
            for e in no_type:
                print(f"  Epic #{e.iid} '{e.title[:50]}' labels={e.labels}")

        # --- Issues ---
        print(f"\nChecking issue weights (expected: {fib_weights})...")
        issue_ok  = 0
        issue_bad = []
        for proj in group.projects.list(all=True, include_subgroups=True):
            try:
                full_p = self.gl.projects.get(proj.id)
                for issue in full_p.issues.list(all=True):
                    w = getattr(issue, "weight", None)
                    if w in fib_weights:
                        issue_ok += 1
                    else:
                        issue_bad.append((issue, proj.path_with_namespace, w))
            except Exception as e:
                print(f"  WARNING: could not fetch issues for '{proj.path_with_namespace}': {e}")

        status = "PASS" if not issue_bad else "FAIL"
        print(f"  Issues: {issue_ok} OK, {len(issue_bad)} FAIL  [{status}]")
        for issue, pns, w in issue_bad:
            all_pass = False
            print(f"  !! Issue #{issue.iid} in '{pns}' weight={w}, expected one of {fib_weights}")

        print(f"\nOverall: {'PASS ✓' if all_pass else 'FAIL ✗'}")
        return all_pass

    def _tool_generate_epic_blocks(self, count=None, dry_run=False):
        """Create (positive count) or remove (negative count) blocking relationships between epics."""
        if count is None:
            count = self.default_generate_blocks_count
        import requests as _requests

        group   = self.get_group_by_name(self.parent_group)
        session = _requests.Session()
        session.headers.update({"PRIVATE-TOKEN": self.private_token})

        print(f"Group: {group.full_path}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        # Collect all epics with their owning group info
        print("\nCollecting epics...")
        all_epics = []  # list of (group_obj, epic_obj)

        def _walk(grp):
            for epic in grp.epics.list(all=True):
                all_epics.append((grp, epic))
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        _walk(group)
        print(f"  Found {len(all_epics)} epics")

        if count < 0:
            self._remove_epic_blocks(session, all_epics, abs(count), dry_run)
        else:
            self._create_epic_blocks(session, all_epics, count, dry_run)

    def _create_epic_blocks(self, session, all_epics, count, dry_run):
        if len(all_epics) < 2:
            print("Not enough epics to create blocking relationships (need at least 2).")
            return

        link_types   = ["blocks", "is_blocked_by"]
        created      = 0
        skipped      = 0
        errors       = 0
        linked_pairs = set()
        attempts     = 0
        max_attempts = count * 10

        while created < count and attempts < max_attempts:
            attempts += 1

            source_grp, source_epic = random.choice(all_epics)
            target_grp, target_epic = random.choice(all_epics)

            if source_epic.id == target_epic.id:
                continue
            pair = tuple(sorted([source_epic.id, target_epic.id]))
            if pair in linked_pairs:
                skipped += 1
                continue

            linked_pairs.add(pair)
            link_type = random.choice(link_types)
            label = (
                f"Epic #{source_epic.iid} '{source_epic.title[:40]}' ({source_grp.full_path})"
                f"  --[{link_type}]-->  "
                f"Epic #{target_epic.iid} '{target_epic.title[:40]}' ({target_grp.full_path})"
            )

            if dry_run:
                print(f"  DRY   {label}")
                created += 1
                continue

            url  = f"{self.url}/api/v4/groups/{source_grp.id}/epics/{source_epic.iid}/related_epics"
            resp = session.post(url, json={
                "target_group_id": target_grp.id,
                "target_epic_iid": target_epic.iid,
                "link_type":       link_type,
            })

            if resp.status_code in (200, 201):
                print(f"  LINKED {label}")
                created += 1
            elif resp.status_code == 409:
                skipped += 1
            else:
                print(f"  ERROR  [{resp.status_code}] {label}: {resp.text[:120]}")
                errors += 1

        print(f"\nDone.  Created: {created}  Skipped (duplicate): {skipped}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _remove_epic_blocks(self, session, all_epics, count, dry_run):
        # Collect all existing blocking links across the hierarchy.
        # Each link appears on both sides (blocks / is_blocked_by); deduplicate by link_id.
        # GitLab GET /related_epics response fields:
        #   id                    — related epic's global ID  (NOT the link's ID)
        #   iid                   — related epic's IID within its group
        #   link_type             — "blocks" | "is_blocked_by" | "relates_to"
        #   related_epic_link_id  — the EpicLink record's own ID  ← use this for DELETE
        print(f"\nCollecting existing blocking relationships (to remove {count})...")
        seen_link_ids = set()
        existing      = []  # list of (group_id, epic_iid, link_id, label)

        for grp, epic in all_epics:
            url  = f"{self.url}/api/v4/groups/{grp.id}/epics/{epic.iid}/related_epics"
            resp = session.get(url)
            if not resp.ok:
                continue
            for rel in resp.json():
                link_type = rel.get("link_type", "")
                if link_type not in ("blocks", "is_blocked_by"):
                    continue
                link_id = rel.get("related_epic_link_id")
                if not link_id:
                    continue
                if link_id in seen_link_ids:
                    continue
                seen_link_ids.add(link_id)
                label = (
                    f"Epic #{epic.iid} '{epic.title[:40]}' ({grp.full_path})"
                    f"  --[{link_type}]-->  "
                    f"#{rel.get('iid', '?')} '{rel.get('title', '')[:40]}'"
                )
                existing.append((grp.id, epic.iid, link_id, label))

        print(f"  Found {len(existing)} blocking relationship(s)")

        if not existing:
            print("Nothing to remove.")
            return

        sample  = random.sample(existing, min(count, len(existing)))
        removed = 0
        errors  = 0

        for grp_id, epic_iid, link_id, label in sample:
            if dry_run:
                print(f"  DRY   REMOVE {label}")
                removed += 1
                continue

            url  = f"{self.url}/api/v4/groups/{grp_id}/epics/{epic_iid}/related_epics/{link_id}"
            resp = session.delete(url)
            if resp.status_code in (200, 204):
                print(f"  REMOVED {label}")
                removed += 1
            else:
                print(f"  ERROR  [{resp.status_code}] {label}: {resp.text[:120]}")
                errors += 1

        print(f"\nDone.  Removed: {removed}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    # ------------------------------------------------------------------
    # Priority 1 — Model Validity
    # ------------------------------------------------------------------

    def _tool_set_issue_weights(self, fibonacci=True, min_weight=None, max_weight=None,
                                reassign=False, dry_run=False):
        """Assign weights to issues.

        By default skips issues that already have a weight.
        Pass reassign=True to overwrite existing weights too.
        """
        group = self.get_group_by_name(self.parent_group)
        pool  = self.fibonacci_weights if fibonacci else list(range(1, 21))
        if min_weight is not None:
            pool = [w for w in pool if w >= min_weight]
        if max_weight is not None:
            pool = [w for w in pool if w <= max_weight]
        if not pool:
            print("No valid weights in pool — check min/max settings.")
            return

        print(f"Group    : {group.full_path}")
        print(f"Pool     : {pool}")
        print(f"Reassign : {reassign}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        updated = skipped = errors = 0
        for proj in group.projects.list(all=True, include_subgroups=True):
            try:
                full_p = self.gl.projects.get(proj.id)
                for issue in full_p.issues.list(all=True):
                    if issue.weight and not reassign:
                        skipped += 1
                        continue
                    w = random.choice(pool)
                    if dry_run:
                        print(f"  DRY  #{issue.iid} '{issue.title[:50]}' → {w} pt")
                        updated += 1
                    else:
                        issue.weight = w
                        issue.save()
                        print(f"  SET  #{issue.iid} '{issue.title[:50]}' → {w} pt")
                        updated += 1
            except Exception as e:
                print(f"  ERROR  project '{proj.path}': {e}")
                errors += 1

        print(f"\nDone.  Updated: {updated}  Already set (skipped): {skipped}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_strip_issue_weights(self, dry_run=False):
        """Zero out all issue weights across every team project."""
        group = self.get_group_by_name(self.parent_group)

        print(f"Group : {group.full_path}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        cleared = skipped = errors = 0
        for proj in group.projects.list(all=True, include_subgroups=True):
            try:
                full_p = self.gl.projects.get(proj.id)
                for issue in full_p.issues.list(all=True):
                    if not issue.weight:
                        skipped += 1
                        continue
                    if dry_run:
                        print(f"  DRY  #{issue.iid} '{issue.title[:50]}' ({issue.weight} pt → 0)")
                        cleared += 1
                    else:
                        issue.weight = 0
                        issue.save()
                        print(f"  CLEAR  #{issue.iid} '{issue.title[:50]}'")
                        cleared += 1
            except Exception as e:
                print(f"  ERROR  project '{proj.path}': {e}")
                errors += 1

        print(f"\nDone.  Cleared: {cleared}  Already zero (skipped): {skipped}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_audit_labels(self):
        """Report every epic missing a type, PIID, or project label."""
        group    = self.get_group_by_name(self.parent_group)
        all_grp_labels = {l.name for l in group.labels.list(all=True)}
        type_set = all_grp_labels & {"Epic", "Capability", "Feature"}
        piid_set = {l for l in all_grp_labels if l.startswith("PIID::")}
        proj_set = {l for l in all_grp_labels if l.startswith("project::")}

        print(f"Auditing labels in: {group.full_path}\n")

        missing = defaultdict(list)   # "type" | "piid" | "project" → [epic]
        total   = 0

        def _walk(grp):
            nonlocal total
            for epic in grp.epics.list(all=True):
                total += 1
                labels = set(epic.labels)
                if not labels & type_set:
                    missing["type"].append(epic)
                if not labels & piid_set:
                    missing["piid"].append(epic)
                if not labels & proj_set:
                    missing["project"].append(epic)
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        _walk(group)

        print(f"Total epics scanned: {total}\n")
        all_ok = True
        for kind, label_name in [("type", "Type (Epic/Capability/Feature)"),
                                  ("piid", "PIID"),
                                  ("project", "Project")]:
            epics = missing[kind]
            if not epics:
                print(f"  ✓  {label_name} — all epics have a label")
            else:
                all_ok = False
                print(f"  ✗  {label_name} — {len(epics)} epic(s) missing:")
                for e in epics:
                    print(f"       #{e.iid}  '{e.title[:60]}'  {e.web_url}")
        print(f"\nOverall: {'PASS ✓' if all_ok else 'FAIL ✗'}")

    def _tool_simulate_pi_progress(self, piid=None, percent=None, dry_run=False):
        """Close X% of open issues linked to epics in a specific PI."""
        if percent is None:
            percent = self.default_simulate_pi_percent
        if not piid:
            print("ERROR: a PIID label is required.")
            return

        group = self.get_group_by_name(self.parent_group)
        print(f"Group : {group.full_path}")
        print(f"PI    : {piid}  →  closing {percent}% of open issues")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        print("\nCollecting epics for this PI...")
        pi_epic_ids = set()

        def _walk_epics(grp):
            for epic in grp.epics.list(all=True):
                if piid in epic.labels:
                    pi_epic_ids.add(epic.id)
            for sg in grp.subgroups.list(all=True):
                _walk_epics(self.gl.groups.get(sg.id))

        _walk_epics(group)
        print(f"  Found {len(pi_epic_ids)} epics labelled {piid}")

        if not pi_epic_ids:
            print(f"No epics found with label '{piid}' — nothing to do.")
            return

        print("\nCollecting open issues linked to those epics...")
        candidates = []
        for proj in group.projects.list(all=True, include_subgroups=True):
            try:
                full_p = self.gl.projects.get(proj.id)
                for issue in full_p.issues.list(all=True, state="opened"):
                    epic = getattr(issue, "epic", None)
                    if epic and epic.get("id") in pi_epic_ids:
                        candidates.append((full_p, issue))
            except Exception as e:
                print(f"  WARNING: could not fetch issues for '{proj.path}': {e}")

        k      = max(0, round(len(candidates) * percent / 100))
        sample = random.sample(candidates, k)
        print(f"  {len(candidates)} open issues  →  closing {k} ({percent}%)")

        closed = errors = 0
        for proj, issue in sample:
            if dry_run:
                print(f"  DRY   #{issue.iid} '{issue.title[:55]}'")
                closed += 1
            else:
                try:
                    issue.state_event = "close"
                    issue.save()
                    print(f"  CLOSED #{issue.iid} '{issue.title[:55]}'")
                    closed += 1
                except Exception as e:
                    print(f"  ERROR  #{issue.iid}: {e}")
                    errors += 1

        print(f"\nDone.  Closed: {closed}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    # ------------------------------------------------------------------
    # Priority 2 — Data Seeding
    # ------------------------------------------------------------------

    def _tool_set_piid_labels(self, piid=None, epic_type=None, dry_run=False):
        """Assign a PIID label to epics that are missing one."""
        if not piid:
            print("ERROR: a PIID label is required.")
            return
        group    = self.get_group_by_name(self.parent_group)
        piid_set = set(self._discover_labels(group, "PIID::"))
        if piid_set and piid not in piid_set:
            print(f"WARNING: '{piid}' not found in group labels. Known PIID labels: {sorted(piid_set)}")
        print(f"Group : {group.full_path}  →  assigning {piid}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        updated = skipped = errors = 0

        def _walk(grp):
            nonlocal updated, skipped, errors
            for epic in grp.epics.list(all=True):
                if set(epic.labels) & piid_set:
                    skipped += 1
                    continue
                if epic_type and epic_type not in epic.labels:
                    skipped += 1
                    continue
                if dry_run:
                    print(f"  DRY  #{epic.iid} '{epic.title[:55]}' → +{piid}")
                    updated += 1
                else:
                    try:
                        epic.labels = list(epic.labels) + [piid]
                        epic.save()
                        print(f"  SET  #{epic.iid} '{epic.title[:55]}' → +{piid}")
                        updated += 1
                    except Exception as e:
                        print(f"  ERROR #{epic.iid}: {e}")
                        errors += 1
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        _walk(group)
        print(f"\nDone.  Updated: {updated}  Skipped (already set or filtered): {skipped}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_set_project_labels(self, label=None, epic_type=None, dry_run=False):
        """Assign a project label to epics that are missing one."""
        if not label:
            print("ERROR: a project label is required.")
            return
        group    = self.get_group_by_name(self.parent_group)
        proj_set = set(self._discover_labels(group, "project::"))
        if proj_set and label not in proj_set:
            print(f"WARNING: '{label}' not found in group labels. Known project labels: {sorted(proj_set)}")
        print(f"Group : {group.full_path}  →  assigning {label}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        updated = skipped = errors = 0

        def _walk(grp):
            nonlocal updated, skipped, errors
            for epic in grp.epics.list(all=True):
                if set(epic.labels) & proj_set:
                    skipped += 1
                    continue
                if epic_type and epic_type not in epic.labels:
                    skipped += 1
                    continue
                if dry_run:
                    print(f"  DRY  #{epic.iid} '{epic.title[:55]}' → +{label}")
                    updated += 1
                else:
                    try:
                        epic.labels = list(epic.labels) + [label]
                        epic.save()
                        print(f"  SET  #{epic.iid} '{epic.title[:55]}' → +{label}")
                        updated += 1
                    except Exception as e:
                        print(f"  ERROR #{epic.iid}: {e}")
                        errors += 1
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        _walk(group)
        print(f"\nDone.  Updated: {updated}  Skipped (already set or filtered): {skipped}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_generate_issues(self, count=None, feature_percent=100.0, dry_run=False):
        """Create issues in team backlog projects linked to Feature epics."""
        if count is None:
            count = self.default_generate_issues_count
        if feature_percent is None:
            feature_percent = 100.0
        import lorem as _lorem  # optional dep — fall back to numbered titles if missing

        group = self.get_group_by_name(self.parent_group)
        pct_label = f"{feature_percent:.0f}% of" if feature_percent < 100.0 else "all"
        print(f"Group : {group.full_path}  →  {count} issues per Feature  ({pct_label} Features)")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        fib = self.fibonacci_weights

        def _title(i):
            try:
                return _lorem.sentence()[:80]
            except Exception:
                return f"Generated issue {i}"

        created = errors = 0
        for proj_stub in group.projects.list(all=True, include_subgroups=True):
            if not proj_stub.path.endswith("-backlog"):
                continue
            try:
                proj = self.gl.projects.get(proj_stub.id)
            except Exception as e:
                print(f"  ERROR fetching project '{proj_stub.path}': {e}")
                continue

            # Find the parent team group to get its Feature epics
            try:
                team_group = self.gl.groups.get(proj.namespace["id"])
                features   = [e for e in team_group.epics.list(all=True) if "Feature" in e.labels]
            except Exception as e:
                print(f"  ERROR fetching features for '{proj_stub.path}': {e}")
                continue

            if not features:
                print(f"  SKIP  {proj.path_with_namespace} — no Feature epics found")
                continue

            if feature_percent < 100.0:
                k        = max(1, round(len(features) * feature_percent / 100))
                features = random.sample(features, min(k, len(features)))

            for feat in features:
                for i in range(1, count + 1):
                    title = _title(i)
                    w     = random.choice(fib)
                    if dry_run:
                        print(f"  DRY  [{feat.title[:40]}] issue {i}: '{title[:50]}' ({w} pt)")
                        created += 1
                    else:
                        try:
                            issue = proj.issues.create({
                                "title":    title,
                                "weight":   w,
                                "epic_id":  feat.id,
                            })
                            print(f"  CREATED #{issue.iid} '{title[:50]}' → Feature '{feat.title[:40]}' ({w} pt)")
                            created += 1
                        except Exception as e:
                            print(f"  ERROR  Feature '{feat.title[:40]}' issue {i}: {e}")
                            errors += 1

        print(f"\nDone.  Created: {created}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    # ------------------------------------------------------------------
    # Priority 3 — State Simulation
    # ------------------------------------------------------------------

    def _tool_set_epic_states(self, state="close", piid=None, epic_type=None, dry_run=False):
        """Open or close epics matching optional type and/or PI filters."""
        if state not in ("open", "close"):
            print("ERROR: state must be 'open' or 'close'.")
            return

        group      = self.get_group_by_name(self.parent_group)
        state_event = state  # python-gitlab uses "close" / "reopen"
        if state == "open":
            state_event = "reopen"

        print(f"Group  : {group.full_path}")
        print(f"Action : {state}  piid={piid or 'all'}  type={epic_type or 'all'}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        updated = skipped = errors = 0

        def _walk(grp):
            nonlocal updated, skipped, errors
            for epic in grp.epics.list(all=True):
                if piid and piid not in epic.labels:
                    skipped += 1
                    continue
                if epic_type and epic_type not in epic.labels:
                    skipped += 1
                    continue
                current = epic.state.lower()
                if (state == "close" and current == "closed") or (state == "open" and current == "opened"):
                    skipped += 1
                    continue
                if dry_run:
                    print(f"  DRY  #{epic.iid} '{epic.title[:55]}' → {state}")
                    updated += 1
                else:
                    try:
                        epic.state_event = state_event
                        epic.save()
                        print(f"  {state.upper()}D  #{epic.iid} '{epic.title[:55]}'")
                        updated += 1
                    except Exception as e:
                        print(f"  ERROR #{epic.iid}: {e}")
                        errors += 1
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        _walk(group)
        print(f"\nDone.  Updated: {updated}  Skipped: {skipped}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    # ------------------------------------------------------------------
    # Priority 4 — Validation
    # ------------------------------------------------------------------

    def _tool_audit_hierarchy(self):
        """Verify Features have Capability parents and Capabilities have Epic parents."""
        group = self.get_group_by_name(self.parent_group)
        print(f"Auditing SAFe hierarchy in: {group.full_path}\n")

        all_epics  = {}   # id → epic
        parent_map = {}   # epic_id → parent_id

        def _walk(grp):
            for epic in grp.epics.list(all=True):
                all_epics[epic.id] = epic
                pid = getattr(epic, "parent_id", None)
                if pid:
                    parent_map[epic.id] = pid
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        _walk(group)
        print(f"Total epics: {len(all_epics)}\n")

        violations = []
        for eid, epic in all_epics.items():
            labels = set(epic.labels)
            pid    = parent_map.get(eid)

            if "Feature" in labels:
                parent = all_epics.get(pid)
                if parent is None:
                    violations.append((epic, "Feature has no parent (expected Capability or Epic)"))
                elif "Capability" not in parent.labels and "Epic" not in parent.labels:
                    ptype = next((t for t in ("Epic", "Capability", "Feature") if t in parent.labels), "unknown")
                    violations.append((epic, f"Feature parent is {ptype}, expected Capability or Epic"))

            elif "Capability" in labels:
                parent = all_epics.get(pid)
                if parent is None:
                    violations.append((epic, "Capability has no parent (expected Epic)"))
                elif "Epic" not in parent.labels:
                    ptype = next((t for t in ("Epic", "Capability", "Feature") if t in parent.labels), "unknown")
                    violations.append((epic, f"Capability parent is {ptype}, expected Epic"))

        if not violations:
            print("  ✓  All hierarchy relationships are valid.")
        else:
            print(f"  ✗  {len(violations)} violation(s) found:\n")
            for epic, reason in violations:
                print(f"  [{epic.iid}] '{epic.title[:60]}'")
                print(f"       {reason}  —  {epic.web_url}")

        print(f"\nOverall: {'PASS ✓' if not violations else 'FAIL ✗'}")

    def _tool_weight_drift_check(self, threshold=None, epic_type=None):
        """Flag epics where planned weight vs sum of issue weights drifts beyond a threshold."""
        if threshold is None:
            threshold = self.default_weight_drift_threshold
        group   = self.get_group_by_name(self.parent_group)
        metrics = self.calculate_portfolio_metrics(self.parent_group)

        tiers = ["Epic", "Capability", "Feature"] if not epic_type else [epic_type]
        epics = [e for t in tiers if t in metrics for e in metrics[t]]

        print(f"Group    : {group.full_path}")
        print(f"Threshold: {threshold}%")
        print(f"Checking : {len(epics)} epic(s)\n")

        flagged  = 0
        no_plan  = 0
        ok_count = 0

        for e in sorted(epics, key=lambda x: x.get("title", "")):
            planned = e.get("planned_weight", 0)
            actual  = e.get("actual_weight",  0)

            if not planned:
                no_plan += 1
                continue

            drift_pct = abs(actual - planned) / planned * 100

            if drift_pct > threshold:
                flagged += 1
                direction = "▲ over" if actual > planned else "▼ under"
                etype = next((t for t in ("Epic", "Capability", "Feature") if t in e.get("labels", [])), "?")
                icon  = self.EPIC_TYPE_ICONS.get(etype, "🏆")
                print(
                    f"  !! {icon} [{e['iid']}] '{e['title'][:55]}'  "
                    f"planned={planned}pt  actual={actual}pt  "
                    f"drift={drift_pct:.0f}% {direction}"
                )
            else:
                ok_count += 1

        print(f"\nDone.  Flagged: {flagged}  OK: {ok_count}  No planned weight: {no_plan}")

    # ------------------------------------------------------------------
    # Orphan simulators
    # ------------------------------------------------------------------

    def _tool_orphan_epics(self, count=None, percent=None, dry_run=False):
        """Remove the parent link from N or X% of epics that currently have a parent."""
        import requests as _requests

        group = self.get_group_by_name(self.parent_group)

        if count is None and percent is None:
            print("ERROR: provide either count or percent.")
            return

        print(f"Group  : {group.full_path}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        # Walk all epics once: build id→(group_id, iid) index and collect candidates
        epic_index   = {}  # epic_id → (group_id, iid)
        candidates   = []  # (child_id, child_iid, child_title, parent_id)

        def _walk(grp):
            for epic in grp.epics.list(all=True):
                epic_index[epic.id] = (grp.id, epic.iid)
                if getattr(epic, 'parent_id', None):
                    candidates.append((epic.id, epic.iid, epic.title, epic.parent_id))
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        print("\nCollecting epics with parents...")
        _walk(group)
        print(f"  {len(candidates)} epics have a parent")

        if count is not None:
            k = min(int(count), len(candidates))
        else:
            k = max(0, round(len(candidates) * float(percent) / 100))

        if k == 0:
            print("Nothing to orphan.")
            return

        sample = random.sample(candidates, k)
        print(f"  Orphaning {k}\n")

        session = _requests.Session()
        session.headers.update({"PRIVATE-TOKEN": self.private_token})

        updated = errors = 0
        for child_id, child_iid, title, parent_id in sample:
            if dry_run:
                print(f"  DRY  #{child_iid} '{title[:55]}'")
                updated += 1
                continue
            parent_info = epic_index.get(parent_id)
            if not parent_info:
                print(f"  SKIP #{child_iid} — parent {parent_id} not in index")
                errors += 1
                continue
            parent_gid, parent_iid = parent_info
            url  = f"{self.url}/api/v4/groups/{parent_gid}/epics/{parent_iid}/epics/{child_id}"
            resp = session.delete(url)
            if resp.status_code in (200, 204):
                print(f"  ORPHANED  #{child_iid} '{title[:55]}'")
                updated += 1
            else:
                print(f"  ERROR #{child_iid}: {resp.status_code} {resp.text[:80]}")
                errors += 1

        print(f"\nDone.  Orphaned: {updated}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_orphan_issues(self, count=None, percent=None, dry_run=False):
        """Remove the epic link from N or X% of issues currently linked to an epic."""
        import requests as _requests

        group = self.get_group_by_name(self.parent_group)

        if count is None and percent is None:
            print("ERROR: provide either count or percent.")
            return

        print(f"Group  : {group.full_path}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        session = _requests.Session()
        session.headers.update({"PRIVATE-TOKEN": self.private_token})

        # Collect via epic issues endpoint — gives us the epic_issue_id needed for DELETE
        candidates = []  # (group_id, epic_iid, epic_issue_id, issue_iid, title)

        print("\nCollecting issues linked to epics...")
        for epic in group.epics.list(all=True):
            grp_id = getattr(epic, 'group_id', None)
            if not grp_id:
                continue
            url  = f"{self.url}/api/v4/groups/{grp_id}/epics/{epic.iid}/issues"
            resp = session.get(url)
            if not resp.ok:
                continue
            for item in resp.json():
                candidates.append((
                    grp_id, epic.iid,
                    item['epic_issue_id'],
                    item['iid'],
                    item.get('title', ''),
                ))

        print(f"  {len(candidates)} issues are linked to epics")

        if count is not None:
            k = min(int(count), len(candidates))
        else:
            k = max(0, round(len(candidates) * float(percent) / 100))

        if k == 0:
            print("Nothing to orphan.")
            return

        sample = random.sample(candidates, k)
        print(f"  Orphaning {k}\n")

        updated = errors = 0
        for grp_id, epic_iid, epic_issue_id, issue_iid, title in sample:
            if dry_run:
                print(f"  DRY  #{issue_iid} '{title[:55]}'")
                updated += 1
            else:
                url  = f"{self.url}/api/v4/groups/{grp_id}/epics/{epic_iid}/issues/{epic_issue_id}"
                resp = session.delete(url)
                if resp.status_code in (200, 204):
                    print(f"  ORPHANED  #{issue_iid} '{title[:55]}'")
                    updated += 1
                else:
                    print(f"  ERROR #{issue_iid}: {resp.status_code} {resp.text[:80]}")
                    errors += 1

        print(f"\nDone.  Orphaned: {updated}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    # ------------------------------------------------------------------
    # Priority 5 — Reset / Cleanup
    # ------------------------------------------------------------------

    def _tool_reset_pi_progress(self, piid=None, dry_run=False):
        """Reopen all closed issues linked to epics in a specific PI."""
        if not piid:
            print("ERROR: a PIID label is required.")
            return

        group = self.get_group_by_name(self.parent_group)
        print(f"Group : {group.full_path}  →  reopening closed issues for {piid}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        print("\nCollecting epics for this PI...")
        pi_epic_ids = set()

        def _walk_epics(grp):
            for epic in grp.epics.list(all=True):
                if piid in epic.labels:
                    pi_epic_ids.add(epic.id)
            for sg in grp.subgroups.list(all=True):
                _walk_epics(self.gl.groups.get(sg.id))

        _walk_epics(group)
        print(f"  Found {len(pi_epic_ids)} epics in {piid}")

        if not pi_epic_ids:
            print(f"No epics found with label '{piid}' — nothing to do.")
            return

        print("\nCollecting closed issues linked to those epics...")
        reopened = errors = 0
        for proj in group.projects.list(all=True, include_subgroups=True):
            try:
                full_p = self.gl.projects.get(proj.id)
                for issue in full_p.issues.list(all=True, state="closed"):
                    epic = getattr(issue, "epic", None)
                    if not (epic and epic.get("id") in pi_epic_ids):
                        continue
                    if dry_run:
                        print(f"  DRY   #{issue.iid} '{issue.title[:55]}'")
                        reopened += 1
                    else:
                        try:
                            issue.state_event = "reopen"
                            issue.save()
                            print(f"  REOPENED #{issue.iid} '{issue.title[:55]}'")
                            reopened += 1
                        except Exception as e:
                            print(f"  ERROR  #{issue.iid}: {e}")
                            errors += 1
            except Exception as e:
                print(f"  WARNING: could not fetch issues for '{proj.path}': {e}")

        print(f"\nDone.  Reopened: {reopened}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_strip_labels(self, label=None, epic_type=None, dry_run=False):
        """Remove a specific label from all epics matching an optional type filter."""
        if not label:
            print("ERROR: a label to remove is required.")
            return

        group = self.get_group_by_name(self.parent_group)
        print(f"Group  : {group.full_path}  →  removing label '{label}'")
        if epic_type:
            print(f"Filter : type = {epic_type}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        updated = skipped = errors = 0

        def _walk(grp):
            nonlocal updated, skipped, errors
            for epic in grp.epics.list(all=True):
                if epic_type and epic_type not in epic.labels:
                    skipped += 1
                    continue
                if label not in epic.labels:
                    skipped += 1
                    continue
                new_labels = [l for l in epic.labels if l != label]
                if dry_run:
                    print(f"  DRY  #{epic.iid} '{epic.title[:55]}' — remove '{label}'")
                    updated += 1
                else:
                    try:
                        epic.labels = new_labels
                        epic.save()
                        print(f"  REMOVED  #{epic.iid} '{epic.title[:55]}' — '{label}' stripped")
                        updated += 1
                    except Exception as e:
                        print(f"  ERROR #{epic.iid}: {e}")
                        errors += 1
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        _walk(group)
        print(f"\nDone.  Updated: {updated}  Skipped: {skipped}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_set_risk_labels(self, percent=None, dry_run=False):
        """Randomly assign risk::high/medium/low labels to open epics that have none."""
        if percent is None:
            percent = self.default_set_risk_percent

        group      = self.get_group_by_name(self.parent_group)
        risk_labels = self._discover_labels(group, "risk::")
        if not risk_labels:
            print("No risk::* labels found on group. Create them via bootstrap first.")
            return

        high_labels = [l for l in risk_labels if "high"   in l]
        med_labels  = [l for l in risk_labels if "medium" in l]
        low_labels  = [l for l in risk_labels if "low"    in l]

        # Weighted pool: ~20% high, ~35% medium, ~45% low
        pool     = high_labels * 2 + med_labels * 3 + low_labels * 4
        risk_set = set(risk_labels)

        print(f"Group  : {group.full_path}")
        print(f"Labels : {risk_labels}")
        print(f"Target : {percent}% of open epics with no existing risk label")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        candidates = []

        def _walk(grp):
            for epic in grp.epics.list(all=True, state="opened"):
                if not set(epic.labels) & risk_set:
                    candidates.append((grp, epic))
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        print("\nCollecting open epics...")
        _walk(group)
        print(f"  {len(candidates)} open epics without a risk label")

        k      = max(0, round(len(candidates) * percent / 100))
        sample = random.sample(candidates, min(k, len(candidates)))
        print(f"  Labelling {len(sample)} ({percent}%)\n")

        updated = errors = 0
        for grp, epic in sample:
            label = random.choice(pool)
            if dry_run:
                print(f"  DRY  [{label}]  #{epic.iid} '{epic.title[:55]}'")
                updated += 1
            else:
                try:
                    epic.labels = list(epic.labels) + [label]
                    epic.save()
                    print(f"  SET  [{label}]  #{epic.iid} '{epic.title[:55]}'")
                    updated += 1
                except Exception as e:
                    print(f"  ERROR #{epic.iid}: {e}")
                    errors += 1

        print(f"\nDone.  Labelled: {updated}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_set_wsjf_labels(self, percent=None, reassign=False, dry_run=False):
        """Randomly assign wsjf-value/urgency/risk Fibonacci labels to open epics.

        By default skips epics that already have any wsjf label.
        Pass reassign=True to replace existing wsjf labels too.
        """
        if percent is None:
            percent = self.default_set_wsjf_percent

        group = self.get_group_by_name(self.parent_group)

        value_labels   = self._discover_labels(group, "wsjf-value::")
        urgency_labels = self._discover_labels(group, "wsjf-urgency::")
        risk_labels    = self._discover_labels(group, "wsjf-risk::")

        if not value_labels and not urgency_labels and not risk_labels:
            print("No wsjf-* labels found on group. Create them via bootstrap first.")
            return

        all_wsjf = set(value_labels + urgency_labels + risk_labels)

        print(f"Group          : {group.full_path}")
        print(f"Value labels   : {value_labels}")
        print(f"Urgency labels : {urgency_labels}")
        print(f"Risk labels    : {risk_labels}")
        mode = "ALL open epics (reassign mode)" if reassign else "open epics with no existing wsjf label"
        print(f"Target         : {percent}% of {mode}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        candidates = []

        def _walk(grp):
            for epic in grp.epics.list(all=True, state="opened"):
                if reassign or not (set(epic.labels) & all_wsjf):
                    candidates.append((grp, epic))
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        print("\nCollecting open epics...")
        _walk(group)
        label_state = "total" if reassign else "without wsjf labels"
        print(f"  {len(candidates)} open epics {label_state}")

        k      = max(0, round(len(candidates) * percent / 100))
        sample = random.sample(candidates, min(k, len(candidates)))
        print(f"  Labelling {len(sample)} ({percent}%)\n")

        updated = errors = 0
        for grp, epic in sample:
            # Strip any existing wsjf labels before assigning new ones
            new_labels = [l for l in epic.labels if l not in all_wsjf]
            chosen = []
            if value_labels:
                v = random.choice(value_labels)
                new_labels.append(v)
                chosen.append(v)
            if urgency_labels:
                u = random.choice(urgency_labels)
                new_labels.append(u)
                chosen.append(u)
            if risk_labels:
                r = random.choice(risk_labels)
                new_labels.append(r)
                chosen.append(r)

            tag = " ".join(f"[{c}]" for c in chosen)
            if dry_run:
                print(f"  DRY  {tag}  #{epic.iid} '{epic.title[:45]}'")
                updated += 1
            else:
                try:
                    epic.labels = new_labels
                    epic.save()
                    print(f"  SET  {tag}  #{epic.iid} '{epic.title[:45]}'")
                    updated += 1
                except Exception as e:
                    print(f"  ERROR #{epic.iid}: {e}")
                    errors += 1

        print(f"\nDone.  Labelled: {updated}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_strip_wsjf_labels(self, dry_run=False):
        """Remove all wsjf-value::*, wsjf-urgency::*, and wsjf-risk::* labels from every open epic."""
        group = self.get_group_by_name(self.parent_group)

        value_labels   = self._discover_labels(group, "wsjf-value::")
        urgency_labels = self._discover_labels(group, "wsjf-urgency::")
        risk_labels    = self._discover_labels(group, "wsjf-risk::")
        all_wsjf = set(value_labels + urgency_labels + risk_labels)

        if not all_wsjf:
            print("No wsjf-* labels found on group — nothing to strip.")
            return

        print(f"Group     : {group.full_path}")
        print(f"Stripping : {sorted(all_wsjf)}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        stripped = skipped = errors = 0

        def _walk(grp):
            nonlocal stripped, skipped, errors
            for epic in grp.epics.list(all=True, state="opened"):
                existing = set(epic.labels) & all_wsjf
                if not existing:
                    skipped += 1
                    continue
                new_labels = [l for l in epic.labels if l not in all_wsjf]
                if dry_run:
                    print(f"  DRY  remove {sorted(existing)}  #{epic.iid} '{epic.title[:45]}'")
                    stripped += 1
                else:
                    try:
                        epic.labels = new_labels
                        epic.save()
                        print(f"  STRIP  {sorted(existing)}  #{epic.iid} '{epic.title[:45]}'")
                        stripped += 1
                    except Exception as e:
                        print(f"  ERROR #{epic.iid}: {e}")
                        errors += 1
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        print("\nWalking epics...")
        _walk(group)
        print(f"\nDone.  Stripped: {stripped}  Skipped (no wsjf): {skipped}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_set_work_type_labels(self, percent=None, reassign=False, dry_run=False):
        """Randomly assign type::feature/enabler/infrastructure/defect labels to open epics."""
        if percent is None:
            percent = 20.0

        group       = self.get_group_by_name(self.parent_group)
        work_labels = self._discover_labels(group, "type::")
        if not work_labels:
            print("No type::* labels found on group. Create them via bootstrap first.")
            return

        all_work = set(work_labels)

        # Weighted pool matching SAFe targets: ~50% feature, ~30% enabler, ~20% infra, defect rare
        feat_l  = [l for l in work_labels if "feature"        in l]
        en_l    = [l for l in work_labels if "enabler"        in l]
        infra_l = [l for l in work_labels if "infrastructure" in l]
        def_l   = [l for l in work_labels if "defect"         in l]
        pool    = feat_l * 5 + en_l * 3 + infra_l * 2 + def_l * 1

        if not pool:
            pool = work_labels  # fallback: uniform

        print(f"Group   : {group.full_path}")
        print(f"Labels  : {work_labels}")
        mode = "ALL open epics (reassign mode)" if reassign else "open epics without type:: label"
        print(f"Target  : {percent}% of {mode}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        candidates = []

        def _walk(grp):
            for epic in grp.epics.list(all=True, state="opened"):
                if reassign or not (set(epic.labels) & all_work):
                    candidates.append((grp, epic))
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        print("\nCollecting open epics...")
        _walk(group)
        label_state = "total" if reassign else "without type:: label"
        print(f"  {len(candidates)} open epics {label_state}")

        k      = max(0, round(len(candidates) * percent / 100))
        sample = random.sample(candidates, min(k, len(candidates)))
        print(f"  Labelling {len(sample)} ({percent}%)\n")

        updated = errors = 0
        for grp, epic in sample:
            new_labels = [l for l in epic.labels if l not in all_work]
            label      = random.choice(pool)
            new_labels.append(label)
            if dry_run:
                print(f"  DRY  [{label}]  #{epic.iid} '{epic.title[:50]}'")
                updated += 1
            else:
                try:
                    epic.labels = new_labels
                    epic.save()
                    print(f"  SET  [{label}]  #{epic.iid} '{epic.title[:50]}'")
                    updated += 1
                except Exception as e:
                    print(f"  ERROR #{epic.iid}: {e}")
                    errors += 1

        print(f"\nDone.  Labelled: {updated}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_strip_work_type_labels(self, dry_run=False):
        """Remove all type::* labels from every open epic."""
        group       = self.get_group_by_name(self.parent_group)
        work_labels = self._discover_labels(group, "type::")
        all_work    = set(work_labels)

        if not all_work:
            print("No type::* labels found on group — nothing to strip.")
            return

        print(f"Group     : {group.full_path}")
        print(f"Stripping : {sorted(all_work)}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        stripped = skipped = errors = 0

        def _walk(grp):
            nonlocal stripped, skipped, errors
            for epic in grp.epics.list(all=True, state="opened"):
                existing = set(epic.labels) & all_work
                if not existing:
                    skipped += 1
                    continue
                new_labels = [l for l in epic.labels if l not in all_work]
                if dry_run:
                    print(f"  DRY  remove {sorted(existing)}  #{epic.iid} '{epic.title[:50]}'")
                    stripped += 1
                else:
                    try:
                        epic.labels = new_labels
                        epic.save()
                        print(f"  STRIP  {sorted(existing)}  #{epic.iid} '{epic.title[:50]}'")
                        stripped += 1
                    except Exception as e:
                        print(f"  ERROR #{epic.iid}: {e}")
                        errors += 1
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        print("\nWalking epics...")
        _walk(group)
        print(f"\nDone.  Stripped: {stripped}  Skipped (no type::): {skipped}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_set_lifecycle_labels(self, percent=None, reassign=False, dry_run=False):
        """Randomly assign lifecycle::* labels to open epics using SAFe Kanban state distribution."""
        if percent is None:
            percent = 20.0

        group          = self.get_group_by_name(self.parent_group)
        lifecycle_lbls = self._discover_labels(group, "lifecycle::")
        if not lifecycle_lbls:
            print("No lifecycle::* labels found on group. Create them via bootstrap first.")
            return

        all_lc = set(lifecycle_lbls)

        # Weighted pool: funnel/analyzing/backlog heavier than implementing/done (realistic portfolio)
        funnel_l  = [l for l in lifecycle_lbls if "funnel"       in l]
        anlyz_l   = [l for l in lifecycle_lbls if "analyzing"    in l]
        backlog_l = [l for l in lifecycle_lbls if "backlog"      in l]
        impl_l    = [l for l in lifecycle_lbls if "implementing" in l]
        done_l    = [l for l in lifecycle_lbls if "done"         in l]
        pool      = funnel_l * 3 + anlyz_l * 2 + backlog_l * 3 + impl_l * 3 + done_l * 1

        if not pool:
            pool = lifecycle_lbls  # fallback: uniform

        print(f"Group   : {group.full_path}")
        print(f"Labels  : {lifecycle_lbls}")
        mode = "ALL open epics (reassign mode)" if reassign else "open epics without lifecycle:: label"
        print(f"Target  : {percent}% of {mode}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        candidates = []

        def _walk(grp):
            for epic in grp.epics.list(all=True, state="opened"):
                if reassign or not (set(epic.labels) & all_lc):
                    candidates.append((grp, epic))
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        print("\nCollecting open epics...")
        _walk(group)
        label_state = "total" if reassign else "without lifecycle:: label"
        print(f"  {len(candidates)} open epics {label_state}")

        k      = max(0, round(len(candidates) * percent / 100))
        sample = random.sample(candidates, min(k, len(candidates)))
        print(f"  Labelling {len(sample)} ({percent}%)\n")

        updated = errors = 0
        for grp, epic in sample:
            new_labels = [l for l in epic.labels if l not in all_lc]
            label      = random.choice(pool)
            new_labels.append(label)
            if dry_run:
                print(f"  DRY  [{label}]  #{epic.iid} '{epic.title[:50]}'")
                updated += 1
            else:
                try:
                    epic.labels = new_labels
                    epic.save()
                    print(f"  SET  [{label}]  #{epic.iid} '{epic.title[:50]}'")
                    updated += 1
                except Exception as e:
                    print(f"  ERROR #{epic.iid}: {e}")
                    errors += 1

        print(f"\nDone.  Labelled: {updated}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_strip_lifecycle_labels(self, dry_run=False):
        """Remove all lifecycle::* labels from every open epic."""
        group          = self.get_group_by_name(self.parent_group)
        lifecycle_lbls = self._discover_labels(group, "lifecycle::")
        all_lc         = set(lifecycle_lbls)

        if not all_lc:
            print("No lifecycle::* labels found on group — nothing to strip.")
            return

        print(f"Group     : {group.full_path}")
        print(f"Stripping : {sorted(all_lc)}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        stripped = skipped = errors = 0

        def _walk(grp):
            nonlocal stripped, skipped, errors
            for epic in grp.epics.list(all=True, state="opened"):
                existing = set(epic.labels) & all_lc
                if not existing:
                    skipped += 1
                    continue
                new_labels = [l for l in epic.labels if l not in all_lc]
                if dry_run:
                    print(f"  DRY  remove {sorted(existing)}  #{epic.iid} '{epic.title[:50]}'")
                    stripped += 1
                else:
                    try:
                        epic.labels = new_labels
                        epic.save()
                        print(f"  STRIP  {sorted(existing)}  #{epic.iid} '{epic.title[:50]}'")
                        stripped += 1
                    except Exception as e:
                        print(f"  ERROR #{epic.iid}: {e}")
                        errors += 1
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        print("\nWalking epics...")
        _walk(group)
        print(f"\nDone.  Stripped: {stripped}  Skipped (no lifecycle::): {skipped}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    # ------------------------------------------------------------------
    # ROAM risk issue management
    # ------------------------------------------------------------------

    def _tool_clean_roam_risks(self, dry_run=False):
        """Delete all ROAM risk issues across the group."""
        group       = self.get_group_by_name(self.parent_group)
        roam_labels = getattr(self, 'ROAM_LABELS', [
            "roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved",
        ])
        print(f"Group: {group.full_path}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        # Collect issues per label (REST group.issues aggregates sub-group projects)
        print("\nFetching ROAM risk issues...")
        seen    = {}
        for label in roam_labels:
            for issue in group.issues.list(labels=[label], get_all=True):
                if issue.id not in seen:
                    seen[issue.id] = issue
        issues = list(seen.values())
        print(f"  Found {len(issues)} issue(s).")

        if not issues:
            print("Nothing to clean up.")
            return

        deleted = errors = 0
        for issue in issues:
            label = f"#{issue.iid} '{issue.title[:55]}'"
            if dry_run:
                print(f"  DRY   {label}")
                deleted += 1
                continue
            try:
                self.gl.projects.get(issue.project_id).issues.delete(issue.iid)
                print(f"  DELETED {label}")
                deleted += 1
            except Exception as e:
                print(f"  ERROR   {label}: {e}")
                errors += 1

        print(f"\nDone.  Deleted: {deleted}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_generate_roam_risks(self, count=10, relations_min=None, relations_max=None,
                                   piid=None, seed=None, dry_run=False):
        """Create ROAM risk issues and relate each to a random number of epics."""
        import lorem

        group       = self.get_group_by_name(self.parent_group)
        roam_labels = getattr(self, 'ROAM_LABELS', [
            "roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved",
        ])
        if not roam_labels:
            print("ERROR: ROAM_LABELS not configured.")
            return

        rel_min = relations_min if relations_min is not None \
            else getattr(self, 'default_roam_risk_relations_min', 1)
        rel_max = relations_max if relations_max is not None \
            else getattr(self, 'default_roam_risk_relations_max', 3)
        rel_min = max(1, rel_min)
        rel_max = max(rel_min, rel_max)

        rng = random.Random(seed)
        print(f"Group: {group.full_path}  count={count}  relations={rel_min}-{rel_max}"
              + (f"  piid={piid}" if piid else "")
              + (f"  seed={seed}" if seed is not None else ""))
        if dry_run:
            print("(dry-run — no changes will be saved)")

        # Collect all epics (any type: Epic, Capability, Feature)
        print("\nCollecting epics...")
        epics = []

        def _walk(grp):
            for epic in grp.epics.list(all=True):
                if getattr(epic, "group_id", grp.id) != grp.id:
                    continue
                if not any(t in epic.labels for t in ["Epic", "Capability", "Feature"]):
                    continue
                if piid and piid not in epic.labels:
                    continue
                epics.append((grp, epic))
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        _walk(group)
        print(f"  Found {len(epics)} epic(s)")

        if not epics:
            print("Nothing to do.")
            return

        # Project cache: group_id → project object
        proj_cache: dict = {}

        def _project_for(grp):
            if grp.id in proj_cache:
                return proj_cache[grp.id]
            projects = grp.projects.list(all=True)
            proj = (
                next((p for p in projects if "backlog" in p.path.lower()), None)
                or (projects[0] if projects else None)
            )
            if proj:
                proj = self.gl.projects.get(proj.id)
            else:
                for sg in grp.subgroups.list(all=True):
                    proj = _project_for(self.gl.groups.get(sg.id))
                    if proj:
                        break
            proj_cache[grp.id] = proj
            return proj

        _LINK = """
        mutation($riskGid: WorkItemID!, $epicGids: [WorkItemID!]!) {
          workItemAddLinkedItems(input: {
            id: $riskGid  workItemsIds: $epicGids  linkType: RELATED
          }) {
            workItem { id }
            errors
          }
        }
        """

        created = errors = 0

        print(f"\n--- Generating {count} risk issue(s) ---")
        for _ in range(count):
            k         = rng.randint(rel_min, min(rel_max, len(epics)))
            selection = rng.sample(epics, k)
            labels_str = ", ".join(
                f"{next((t for t in ['Epic','Capability','Feature'] if t in e.labels), 'epic')} "
                f"#{e.iid}" for _, e in selection
            )

            if dry_run:
                roam_label = rng.choice(roam_labels)
                print(f"  DRY   [{roam_label}] → [{labels_str}]")
                created += 1
                continue

            grp, _ = selection[0]
            project = _project_for(grp)
            if not project:
                print(f"  SKIP  no project found for group {grp.full_path}")
                errors += 1
                continue

            roam_label = rng.choice(roam_labels)
            try:
                risk = project.issues.create({
                    "title":       f"Risk: {lorem.sentence().rstrip('.')}",
                    "description": lorem.paragraph(),
                    "labels":      [roam_label],
                })
                risk_gid  = f"gid://gitlab/WorkItem/{risk.id}"
                epic_gids = [
                    f"gid://gitlab/WorkItem/{epic.work_item_id}"
                    for _, epic in selection
                    if epic.work_item_id
                ]
                if epic_gids:
                    link_result = self.graphql_query(_LINK, variables={
                        "riskGid": risk_gid, "epicGids": epic_gids,
                    })
                    link_errors = (link_result or {}).get("workItemAddLinkedItems", {}).get("errors", [])
                    if link_errors:
                        print(f"  WARN  #{risk.iid} link errors: {link_errors}")

                print(f"  CREATED #{risk.iid} [{roam_label}] → [{labels_str}]")
                created += 1
            except Exception as e:
                print(f"  ERROR  [{labels_str}]: {e}")
                errors += 1

        print(f"\nDone.  Created: {created}  Errors: {errors}")
        if dry_run:
            print("(dry-run — no changes saved)")

    def _tool_generate_risk_reasons(self, conditions="all", percent=20.0,
                                     days_overdue=7, piid=None, dry_run=False):
        """Create Behind Schedule / Past Due / Child Overdue / Blocked conditions on a random % of open epics."""
        conds_all = {"behind_schedule", "past_due", "child_overdue", "blocked"}
        if conditions.strip().lower() == "all":
            conds = conds_all
        else:
            conds = {c.strip().lower() for c in conditions.replace(",", " ").split() if c.strip()}
            unknown = conds - conds_all
            if unknown:
                print(f"ERROR: unknown condition(s): {', '.join(sorted(unknown))}")
                print(f"Valid: {', '.join(sorted(conds_all))} or 'all'")
                return

        today     = date.today()
        past_date = (today - timedelta(days=days_overdue)).isoformat()
        group     = self.get_group_by_name(self.parent_group)

        print(f"Group     : {group.full_path}")
        print(f"Conditions: {', '.join(sorted(conds))}")
        print(f"Target    : {percent}% of eligible epics")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        # ── Collect all open epics (deduplicated by global epic id) ──── #
        print("\nCollecting open epics...")
        all_open: list = []
        _seen_ids: set = set()

        def _walk(grp):
            for epic in grp.epics.list(all=True, state="opened"):
                if epic.id not in _seen_ids:
                    _seen_ids.add(epic.id)
                    all_open.append((grp, epic))
            for sg in grp.subgroups.list(all=True):
                _walk(self.gl.groups.get(sg.id))

        _walk(group)
        print(f"  Found {len(all_open)} open epics")

        # ── Past Due ─────────────────────────────────────────────────── #
        if "past_due" in conds:
            print("\n── Past Due ──")
            eligible = [
                (g, e) for g, e in all_open
                if "Feature" not in e.labels
                and (not e.due_date or e.due_date >= today.isoformat())
            ]
            k      = max(0, round(len(eligible) * percent / 100))
            sample = random.sample(eligible, min(k, len(eligible)))
            print(f"  Eligible (non-Feature, no existing past due_date): {len(eligible)}")
            print(f"  Targeting {len(sample)}\n")
            updated = errors = 0
            for g, epic in sample:
                if dry_run:
                    print(f"  DRY  due={past_date}  #{epic.iid} '{epic.title[:55]}'")
                    updated += 1
                else:
                    try:
                        epic.due_date = past_date
                        epic.save()
                        print(f"  SET  due={past_date}  #{epic.iid} '{epic.title[:55]}'")
                        updated += 1
                    except Exception as exc:
                        print(f"  ERROR #{epic.iid}: {exc}")
                        errors += 1
            print(f"\n  Updated: {updated}  Errors: {errors}")

        # ── Child Overdue ─────────────────────────────────────────────── #
        if "child_overdue" in conds:
            print("\n── Child Overdue ──")
            eligible = [
                (g, e) for g, e in all_open
                if "Feature" in e.labels
                and getattr(e, "parent_id", None) is not None
                and (not e.due_date or e.due_date >= today.isoformat())
            ]
            k      = max(0, round(len(eligible) * percent / 100))
            sample = random.sample(eligible, min(k, len(eligible)))
            print(f"  Eligible (Feature with parent, no existing past due_date): {len(eligible)}")
            print(f"  Targeting {len(sample)}\n")
            updated = errors = 0
            for g, epic in sample:
                if dry_run:
                    print(f"  DRY  due={past_date}  #{epic.iid} '{epic.title[:55]}'")
                    updated += 1
                else:
                    try:
                        epic.due_date = past_date
                        epic.save()
                        print(f"  SET  due={past_date}  #{epic.iid} '{epic.title[:55]}'")
                        updated += 1
                    except Exception as exc:
                        print(f"  ERROR #{epic.iid}: {exc}")
                        errors += 1
            print(f"\n  Updated: {updated}  Errors: {errors}")

        # ── Behind Schedule ───────────────────────────────────────────── #
        if "behind_schedule" in conds:
            print("\n── Behind Schedule ──")

            # Resolve the target PI (auto-detect current active PI if not supplied)
            target_piid = None
            if piid:
                target_piid = piid if piid.startswith("PIID::") else f"PIID::{piid}"
            else:
                for _, epic in all_open:
                    for lbl in epic.labels:
                        if lbl.startswith("PIID::") and 0 < (self._pct_through_pi(lbl) or 0) < 100:
                            target_piid = lbl
                            break
                    if target_piid:
                        break

            if not target_piid:
                print("  No active PI found (0 < elapsed < 100%). Pass piid= to specify one.")
            else:
                pct_pi = self._pct_through_pi(target_piid)
                print(f"  Active PI : {target_piid}  ({pct_pi}% elapsed)")

                # Collect closed weighted issues whose epic is in this PI
                print("\n  Collecting closed weighted issues on PI epics...")
                pi_epic_ids = {e.id for _, e in all_open if target_piid in e.labels}
                print(f"  Open epics in {target_piid}: {len(pi_epic_ids)}")

                candidates: list = []
                for proj in group.projects.list(all=True, include_subgroups=True):
                    try:
                        full_p = self.gl.projects.get(proj.id)
                        for issue in full_p.issues.list(all=True, state="closed"):
                            epic_ref = getattr(issue, "epic", None)
                            if epic_ref and epic_ref.get("id") in pi_epic_ids:
                                if (issue.weight or 0) > 0:
                                    candidates.append((full_p, issue))
                    except Exception as exc:
                        print(f"  WARNING: {proj.path}: {exc}")

                k      = max(0, round(len(candidates) * percent / 100))
                sample = random.sample(candidates, min(k, len(candidates)))
                print(f"  Closed weighted issues in PI: {len(candidates)}")
                print(f"  Reopening {len(sample)} ({percent}%)\n")

                updated = errors = 0
                for full_p, issue in sample:
                    if dry_run:
                        print(f"  DRY  reopen #{issue.iid} '{issue.title[:55]}'")
                        updated += 1
                    else:
                        try:
                            issue.state_event = "reopen"
                            issue.save()
                            print(f"  REOPEN #{issue.iid} '{issue.title[:55]}'")
                            updated += 1
                        except Exception as exc:
                            print(f"  ERROR #{issue.iid}: {exc}")
                            errors += 1
                print(f"\n  Reopened: {updated}  Errors: {errors}")

        # ── Blocked ───────────────────────────────────────────────────── #
        # Target Feature epics with a parent so the block propagates up to the
        # Capability ancestor (⬆️ Risk propagation) and the portfolio Epic (⚠️ Portfolio risk flag).
        if "blocked" in conds:
            print("\n── Blocked ──")
            import requests as _requests

            session = _requests.Session()
            session.headers.update({"PRIVATE-TOKEN": self.private_token})

            # Blocked targets: Features that have a parent (guarantees ancestor propagation)
            targets = [
                (g, e) for g, e in all_open
                if "Feature" in e.labels
                and getattr(e, "parent_id", None) is not None
            ]
            # Blocker pool: non-Feature epics (Capabilities/Epics act as blockers)
            blocker_pool = [(g, e) for g, e in all_open if "Feature" not in e.labels]
            if not blocker_pool:
                blocker_pool = all_open

            k      = max(0, round(len(targets) * percent / 100))
            sample = random.sample(targets, min(k, len(targets)))
            print(f"  Eligible (Feature with parent): {len(targets)}")
            print(f"  Targeting {len(sample)}\n")

            updated = errors = 0
            for g, epic in sample:
                valid_blockers = [(bg, be) for bg, be in blocker_pool if be.id != epic.id]
                if not valid_blockers:
                    print(f"  SKIP  #{epic.iid} (no valid blocker available)")
                    continue

                blocker_grp, blocker_epic = random.choice(valid_blockers)
                label = (
                    f"#{epic.iid} '{epic.title[:45]}'"
                    f"  <--[blocked by]--  "
                    f"#{blocker_epic.iid} '{blocker_epic.title[:45]}'"
                )

                if dry_run:
                    print(f"  DRY  {label}")
                    updated += 1
                else:
                    url  = f"{self.url}/api/v4/groups/{g.id}/epics/{epic.iid}/related_epics"
                    resp = session.post(url, json={
                        "target_group_id": blocker_grp.id,
                        "target_epic_iid": blocker_epic.iid,
                        "link_type":       "is_blocked_by",
                    })
                    if resp.status_code in (200, 201):
                        print(f"  BLOCKED  {label}")
                        updated += 1
                    elif resp.status_code == 409:
                        print(f"  SKIP (already linked)  #{epic.iid}")
                    else:
                        print(f"  ERROR [{resp.status_code}] #{epic.iid}: {resp.text[:120]}")
                        errors += 1

            print(f"\n  Blocked: {updated}  Errors: {errors}")

        print("\nDone.")
        if dry_run:
            print("(dry-run — no changes saved)")
