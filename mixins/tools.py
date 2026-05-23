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
