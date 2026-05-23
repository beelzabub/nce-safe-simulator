import random
import sys
from collections import defaultdict


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
        "key":         "generate-epic-blocks",
        "description": "Randomly create or remove blocking relationships between epics (negative count = remove)",
        "method":      "_tool_generate_epic_blocks",
        "params": [
            {"name": "count",   "prompt": "Relationships to create (positive) or remove (negative)", "type": int,  "default": 10},
            {"name": "dry_run", "prompt": "Dry run?",                                                 "type": bool, "default": False},
        ],
    },
    {
        "key":         "set-issue-weights",
        "description": "Assign Fibonacci story-point weights to issues that currently have none",
        "method":      "_tool_set_issue_weights",
        "params": [
            {"name": "fibonacci", "prompt": "Constrain to Fibonacci pool from config?", "type": bool, "default": True},
            {"name": "min_weight","prompt": "Minimum weight (blank = no min)",          "type": int,  "optional": True},
            {"name": "max_weight","prompt": "Maximum weight (blank = no max)",          "type": int,  "optional": True},
            {"name": "dry_run",   "prompt": "Dry run?",                                 "type": bool, "default": False},
        ],
    },
    {
        "key":         "audit-labels",
        "description": "Report every epic missing a type, PIID, or project label",
        "method":      "_tool_audit_labels",
        "params":      [],
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
        "key":         "generate-issues",
        "description": "Create issues in team backlog projects linked to Feature epics",
        "method":      "_tool_generate_issues",
        "params": [
            {"name": "count",   "prompt": "Issues to create per Feature (default 5)", "type": int,  "default": 5},
            {"name": "dry_run", "prompt": "Dry run?",                                  "type": bool, "default": False},
        ],
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
        "key":         "audit-hierarchy",
        "description": "Verify Features have Capability parents and Capabilities have Epic parents",
        "method":      "_tool_audit_hierarchy",
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
        "key":         "strip-labels",
        "description": "Remove a specific label from all epics (optionally filtered by type)",
        "method":      "_tool_strip_labels",
        "params": [
            {"name": "label",     "prompt": "Label to remove",                                       "type": str,  "optional": False},
            {"name": "epic_type", "prompt": "Limit to type (Epic/Capability/Feature, blank = all)",  "type": str,  "optional": True},
            {"name": "dry_run",   "prompt": "Dry run?",                                               "type": bool, "default": False},
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

    def _tool_close_percent(self, percent=30.0, seed=None, dry_run=False):
        """Randomly close N% of open epics and issues across the group hierarchy."""
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

    def _tool_generate_epic_blocks(self, count=10, dry_run=False):
        """Create (positive count) or remove (negative count) blocking relationships between epics."""
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

    def _tool_set_issue_weights(self, fibonacci=True, min_weight=None, max_weight=None, dry_run=False):
        """Assign weights to issues that currently have none."""
        group = self.get_group_by_name(self.parent_group)
        pool  = self.fibonacci_weights if fibonacci else list(range(1, 21))
        if min_weight is not None:
            pool = [w for w in pool if w >= min_weight]
        if max_weight is not None:
            pool = [w for w in pool if w <= max_weight]
        if not pool:
            print("No valid weights in pool — check min/max settings.")
            return

        print(f"Group : {group.full_path}")
        print(f"Pool  : {pool}")
        if dry_run:
            print("(dry-run — no changes will be saved)")

        updated = skipped = errors = 0
        for proj in group.projects.list(all=True, include_subgroups=True):
            try:
                full_p = self.gl.projects.get(proj.id)
                for issue in full_p.issues.list(all=True):
                    if issue.weight:
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

    def _tool_audit_labels(self):
        """Report every epic missing a type, PIID, or project label."""
        group     = self.get_group_by_name(self.parent_group)
        type_set  = set(self.EPIC_TYPE_LABELS)
        piid_set  = set(self.PIID_LABELS)
        proj_set  = set(self.PROJECT_LABELS)

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

    def _tool_simulate_pi_progress(self, piid=None, percent=50.0, dry_run=False):
        """Close X% of open issues linked to epics in a specific PI."""
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
        if piid not in self.PIID_LABELS:
            print(f"WARNING: '{piid}' is not in the configured PIID_LABELS: {self.PIID_LABELS}")

        group    = self.get_group_by_name(self.parent_group)
        piid_set = set(self.PIID_LABELS)
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
        if label not in self.PROJECT_LABELS:
            print(f"WARNING: '{label}' is not in the configured PROJECT_LABELS: {self.PROJECT_LABELS}")

        group    = self.get_group_by_name(self.parent_group)
        proj_set = set(self.PROJECT_LABELS)
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

    def _tool_generate_issues(self, count=5, dry_run=False):
        """Create issues in team backlog projects linked to Feature epics."""
        import lorem as _lorem  # optional dep — fall back to numbered titles if missing

        group = self.get_group_by_name(self.parent_group)
        print(f"Group : {group.full_path}  →  {count} issues per Feature")
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

    def _tool_weight_drift_check(self, threshold=20.0, epic_type=None):
        """Flag epics where planned weight vs sum of issue weights drifts beyond a threshold."""
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
