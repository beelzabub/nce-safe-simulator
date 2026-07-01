import csv
import json
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


# ── Field definitions ─────────────────────────────────────────────────────────

EPIC_EXPORT_FIELDS = [
    "group_path", "iid", "id", "title", "description", "state",
    "labels", "start_date", "due_date", "parent_id", "parent_iid",
    "planned_weight", "author", "web_url",
    "created_at", "updated_at", "closed_at",
]

ISSUE_EXPORT_FIELDS = [
    "project_path", "iid", "id", "title", "description", "state",
    "labels", "weight", "due_date", "milestone", "assignees",
    "epic_id", "epic_iid", "author", "web_url",
    "created_at", "updated_at", "closed_at",
]

# Fields the import will act on; anything else is noted and ignored
EPIC_IMPORT_KNOWN = {
    "title", "group_path", "description", "labels",
    "start_date", "due_date", "end_date", "parent_id",
    "planned_weight", "state",
    # read-only / reference columns carried from export — silently ignored
    "iid", "id", "author", "web_url", "created_at", "updated_at",
    "closed_at", "parent_iid", "work_item_id",
}
EPIC_IMPORT_REQUIRED = {"title"}

ISSUE_IMPORT_KNOWN = {
    "title", "project_path", "description", "labels", "weight",
    "due_date", "milestone", "assignees", "epic_id", "state",
    # read-only reference columns
    "iid", "id", "author", "web_url", "created_at", "updated_at",
    "closed_at", "epic_iid",
}
ISSUE_IMPORT_REQUIRED = {"title"}

# Columns unique to each import type (shared reference columns like iid/author
# cancel out). Their presence in the other importer is a strong signal that the
# wrong file was supplied — e.g. an issues export fed to the epics importer.
EPIC_ONLY_COLS  = EPIC_IMPORT_KNOWN  - ISSUE_IMPORT_KNOWN
ISSUE_ONLY_COLS = ISSUE_IMPORT_KNOWN - EPIC_IMPORT_KNOWN

VALID_DATE_FMT = "%Y-%m-%d"
VALID_STATES   = {"opened", "open", "closed"}

# Exports land here so FastAPI's static server can serve them for download.
_EXPORTS_DIR = Path("public/exports")


class ImportExportMixin:

    # ── Path / format helpers ─────────────────────────────────────────────────

    def _resolve_path(self, path_str):
        return Path(path_str).expanduser().resolve()

    def _detect_format(self, path):
        return "json" if path.suffix.lower() == ".json" else "csv"

    def _default_export_name(self, stem, fmt):
        """Build a unique, timestamped filename for a UI (auto-named) export.

        UI exports land in public/exports and must not clobber one another, so a
        UTC timestamp is appended: ``<group>-<stem>-YYYYMMDD-HHMMSS.<ext>``. This
        path is used only when no explicit output path is supplied; explicit CLI
        output paths are honoured verbatim and never routed through here.
        """
        _EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts       = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        filename = f"{self.sanitize_name(self.parent_group)}-{stem}-{ts}.{fmt}"
        return (_EXPORTS_DIR / filename).resolve()

    def _export_url(self, path: Path):
        """Return a host-agnostic download URL for an auto-named export.

        Auto-named exports land in public/exports and are served as browser
        downloads by the web UI's GET /api/download/<filename> endpoint. The
        returned link is relative so it resolves against whatever host serves
        the UI (localhost, the live domain, etc.) instead of a hardcoded URL.

        Explicit CLI output paths live outside the exports dir, so this returns
        None and the CLI behaviour is unchanged.
        """
        try:
            path.resolve().relative_to(_EXPORTS_DIR.resolve())
            return f"/api/download/{path.name}"
        except ValueError:
            return None

    # ── Active-group override ──────────────────────────────────────────────────

    @contextmanager
    def _group_override(self, group):
        """Temporarily retarget parent_group / gitlab_namespace for one run.

        Accepts an override of the form ``namespace/group`` (URL-slug namespace
        plus group display-name, e.g. ``saic-study-group/My Portfolio``) or just
        ``group`` (display-name only — the configured namespace is kept). An
        empty / None value leaves the configured group untouched.

        The override is per-run only: the original instance state is always
        restored on exit, so config.json is never mutated and other tools are
        unaffected. CLI callers that pass no group keep the configured behaviour.
        """
        orig_ns  = getattr(self, "gitlab_namespace", None)
        orig_grp = self.parent_group
        if group and str(group).strip():
            parts = str(group).strip().rsplit("/", 1)
            if len(parts) == 2:
                self.gitlab_namespace, self.parent_group = parts[0], parts[1]
            else:
                self.parent_group = parts[0]
        try:
            yield
        finally:
            self.gitlab_namespace = orig_ns
            self.parent_group     = orig_grp

    def _resolve_import_target(self, create_missing, dry_run):
        """Resolve the import target (root) group, optionally creating it.

        Returns the group object, or None when import cannot proceed (caller
        should return). With ``create_missing`` False and the group absent, a
        clear, actionable error is printed. With ``create_missing`` True the
        group is created via BootstrapMixin._get_or_create_root_group — except
        under dry run, where the intent is reported but nothing is created.
        """
        group = self.get_group_by_name(self.parent_group)
        if group is not None:
            return group

        ns     = getattr(self, "gitlab_namespace", None)
        target = f"{ns}/{self.parent_group}" if ns else self.parent_group

        if not create_missing:
            print(f"ERROR: target group '{target}' does not exist. "
                  f"Re-run with 'Create target group if missing' enabled to create "
                  f"it, or choose an existing group.")
            return None

        if dry_run:
            print(f"  [dry run] target group '{target}' does not exist — it would be "
                  f"created before import. Uncheck 'Dry run' to create it and import.")
            return None

        print(f"  Target group '{target}' not found — creating it "
              f"(create-if-missing enabled)...")
        return self._get_or_create_root_group()

    # ── Validation primitives ─────────────────────────────────────────────────

    @staticmethod
    def _coerce_date(value, field, row_num, errors):
        raw = str(value).strip() if value is not None else ""
        if raw in ("", "None", "none"):
            return None
        try:
            datetime.strptime(raw, VALID_DATE_FMT)
            return raw
        except ValueError:
            errors.append(f"  row {row_num}: '{field}' value '{raw}' is not a valid date (expected YYYY-MM-DD)")
            return None

    @staticmethod
    def _coerce_int(value, field, row_num, errors):
        raw = str(value).strip() if value is not None else ""
        if raw in ("", "None", "none"):
            return None
        try:
            return int(float(raw))
        except (ValueError, TypeError):
            errors.append(f"  row {row_num}: '{field}' value '{raw}' is not a valid integer")
            return None

    @staticmethod
    def _coerce_labels(value):
        if not value or str(value).strip() in ("", "None", "none"):
            return []
        return [lbl.strip() for lbl in str(value).split(",") if lbl.strip()]

    @staticmethod
    def _coerce_usernames(value):
        if not value or str(value).strip() in ("", "None", "none"):
            return []
        return [u.strip().lstrip("@") for u in str(value).split(",") if u.strip()]

    # ── File I/O ──────────────────────────────────────────────────────────────

    def _load_file(self, path):
        """Load CSV or JSON into a list of dicts. Returns None and prints on error."""
        fmt = self._detect_format(path)
        try:
            if fmt == "json":
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    print(f"ERROR: JSON must be a top-level array, got {type(data).__name__}")
                    return None
                return data
            else:
                with open(path, encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
                return rows
        except json.JSONDecodeError as ex:
            print(f"ERROR: Invalid JSON — {ex}")
        except csv.Error as ex:
            print(f"ERROR: Invalid CSV — {ex}")
        except UnicodeDecodeError:
            print("ERROR: File is not valid UTF-8 text")
        return None

    def _write_file(self, path, fmt, rows, field_order):
        """Write rows to path as CSV or JSON."""
        if not rows:
            print("  No records to write.")
            return
        # Columns: defined order first, then any extras not in the definition
        ordered = list(field_order) + [k for k in rows[0] if k not in field_order]
        if fmt == "json":
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2, default=str)
        else:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=ordered, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)

    # ── Group / project caches ────────────────────────────────────────────────

    def _build_group_cache(self, root_group):
        """Return {full_path: group_object} for root and ALL descendant subgroups.

        Uses the recursive get_all_subgroups walk — the same discovery the web
        UI's /api/groups picker uses — so any destination the picker offered
        resolves here too. GitLab's `subgroups` endpoint only returns DIRECT
        children (it ignores include_subgroups), so a single shallow list misses
        deep subgroups and a valid deep destination would be wrongly rejected.
        """
        cache = {}
        for g in self.get_all_subgroups(root_group, include_self=True):
            full_path = getattr(g, "full_path", None)
            if full_path:
                cache[full_path] = g
        return cache

    def _build_gid_path_map(self, root_group):
        """Return {group_id: full_path} for root and ALL descendant subgroups.

        Matches _build_group_cache's depth (the GitLab `subgroups` endpoint only
        returns DIRECT children and ignores include_subgroups). Without the full
        walk, epics in deep groups export with a blank group_path and are dropped
        from fallback-parent selection. Uses the single descendant_groups call —
        each item already carries id/full_path, so no per-group N+1 fetch.
        """
        m = {root_group.id: root_group.full_path}
        for g in self.list_descendant_groups(root_group):
            gid = getattr(g, "id", None)
            full_path = getattr(g, "full_path", None)
            if gid is not None and full_path:
                m[gid] = full_path
        return m

    def _build_project_cache(self, root_group):
        """Return {path_with_namespace: project_object} for all projects under group."""
        cache = {}
        for proj in root_group.projects.list(all=True, include_subgroups=True):
            try:
                full = self.gl.projects.get(proj.id)
                cache[full.path_with_namespace] = full
            except Exception:
                pass
        return cache

    # ── Re-import handling (on_existing: create | skip | update) ───────────────

    def _find_issue_by_title(self, project, title):
        """First issue in `project` with an exact matching title, else None."""
        try:
            for iss in project.issues.list(search=title, all=True):
                if getattr(iss, "title", "") == title:
                    return iss
        except Exception:
            pass
        return None

    def _find_epic_by_title(self, group, title):
        """First epic in `group` with an exact matching title, else None."""
        try:
            for ep in group.epics.list(search=title, all=True):
                if getattr(ep, "title", "") == title:
                    return ep
        except Exception:
            pass
        return None

    def _update_issue(self, issue, payload, state, epic_id):
        """Apply an import payload to an existing issue (merge — omitted fields
        are left untouched; matched title is not rewritten)."""
        for k, v in payload.items():
            if k == "title":
                continue
            setattr(issue, k, v)
        if epic_id is not None:
            issue.epic_id = epic_id
        if state == "closed":
            issue.state_event = "close"
        issue.save()

    def _update_epic(self, epic, payload, weight, state):
        """Apply an import payload to an existing epic (merge semantics)."""
        for k, v in payload.items():
            if k == "title":
                continue
            setattr(epic, k, v)
        epic.save()
        if weight is not None:
            self._set_epic_weight(epic, weight)
        if state == "closed":
            epic.state_event = "close"
            epic.save()

    def _build_pid_path_map(self, root_group):
        """Return {project_id: path_with_namespace}."""
        return {
            p.id: p.path_with_namespace
            for p in root_group.projects.list(all=True, include_subgroups=True)
        }

    # ── Epic export ───────────────────────────────────────────────────────────

    def export_epics(self, output_path=None, group=None, fmt="csv"):
        with self._group_override(group):
            return self._export_epics(output_path, fmt)

    def _export_epics(self, output_path=None, fmt="csv"):
        group = self.get_group_by_name(self.parent_group)
        if not group:
            print(f"ERROR: group '{self.parent_group}' not found.")
            return

        # Explicit output path (CLI): the extension drives the format, exactly as
        # before. Auto-named (UI): the fmt selector drives extension + format.
        if output_path:
            path = self._resolve_path(output_path)
            fmt  = self._detect_format(path)
        else:
            fmt  = "json" if str(fmt).lower() == "json" else "csv"
            path = self._default_export_name("epics-export", fmt)

        print(f"\nExporting epics from '{group.full_path}' (all subgroups included)...")

        all_epics = group.epics.list(all=True)
        print(f"  {len(all_epics)} epic(s) found")

        print("  Resolving group paths...")
        gid_map = self._build_gid_path_map(group)

        print("  Fetching planned weights via GraphQL...")
        weights = self._fetch_epic_weights(all_epics)

        rows = []
        for epic in all_epics:
            rows.append({
                "group_path":     gid_map.get(getattr(epic, "group_id", None), ""),
                "iid":            epic.iid,
                "id":             epic.id,
                "title":          epic.title or "",
                "description":    epic.description or "",
                "state":          epic.state or "",
                "labels":         ", ".join(epic.labels or []),
                "start_date":     getattr(epic, "start_date", "") or "",
                "due_date":       getattr(epic, "due_date",   "") or "",
                "parent_id":      getattr(epic, "parent_id",  "") or "",
                "parent_iid":     getattr(epic, "parent_iid", "") or "",
                "planned_weight": weights.get(epic.web_url, ""),
                "author":         (epic.author or {}).get("name", ""),
                "web_url":        epic.web_url or "",
                "created_at":     getattr(epic, "created_at", "") or "",
                "updated_at":     getattr(epic, "updated_at", "") or "",
                "closed_at":      getattr(epic, "closed_at",  "") or "",
            })

        self._write_file(path, fmt, rows, EPIC_EXPORT_FIELDS)
        print(f"  Exported {len(rows)} epic(s) → {path}")
        url = self._export_url(path)
        if url:
            print(f"  Download: {url}")

    # ── Epic import ───────────────────────────────────────────────────────────

    def _warn_type_unconfirmed(self, kind, other_kind, other_tool, example_cols):
        """Stand-out pre-flight notice: the file has only columns common to both
        epics and issues, so it was ACCEPTED but its type can't be confirmed."""
        bar = "  " + "═" * 64
        print("\n" + bar)
        print(f"  ⚠  ACCEPTED — but this file's type could NOT be confirmed.")
        print(f"     It has only columns common to both epics and issues (no")
        print(f"     {kind}-specific columns such as {example_cols}).")
        print(f"     If these rows were meant as {other_kind}, cancel now and use")
        print(f"     the {other_tool} tool instead.")
        print(bar)

    def _validate_epics(self, rows):
        """
        Pre-flight validation pass.
        Returns (cleaned_rows, error_count).
        cleaned_rows is None if there are blocking structural errors.
        """
        errors   = []
        warnings = []
        columns  = set(rows[0].keys()) if rows else set()

        # Required columns
        missing = EPIC_IMPORT_REQUIRED - columns
        if missing:
            print(f"\n  INVALID: missing required column(s): {', '.join(sorted(missing))}")
            print(f"  Required: {', '.join(sorted(EPIC_IMPORT_REQUIRED))}")
            print(f"  Optional: title, group_path, description, labels, start_date, due_date,")
            print(f"            parent_id, planned_weight, state")
            return None, 1

        # Wrong-file guard: issue-only columns mean this is almost certainly an
        # issues export, not epics. title alone would otherwise pass and create
        # epics from issue rows.
        issue_markers = columns & ISSUE_ONLY_COLS
        if issue_markers:
            print(f"\n  INVALID: this looks like an ISSUES export, not epics — it has "
                  f"issue-only column(s): {', '.join(sorted(issue_markers))}.")
            print("  Use the Import Issues tool for this file.")
            return None, 1

        # No epic-specific columns either → only shared columns → can't confirm type.
        if not (columns & EPIC_ONLY_COLS):
            self._warn_type_unconfirmed("epics", "issues", "Import Issues",
                                        "group_path or planned_weight")

        unknown = columns - EPIC_IMPORT_KNOWN
        if unknown:
            warnings.append(f"  WARN: unknown column(s) will be ignored: {', '.join(sorted(unknown))}")

        for i, row in enumerate(rows, 1):
            title = str(row.get("title", "")).strip()
            if not title:
                errors.append(f"  row {i}: 'title' is blank (required)")

            self._coerce_date(row.get("start_date"),                   "start_date",     i, errors)
            self._coerce_date(row.get("due_date") or row.get("end_date"), "due_date",    i, errors)
            self._coerce_int(row.get("parent_id"),    "parent_id",     i, errors)
            self._coerce_int(row.get("planned_weight"), "planned_weight", i, errors)

            state = str(row.get("state", "")).strip().lower()
            if state and state not in VALID_STATES:
                errors.append(f"  row {i}: 'state' = '{state}' invalid — use 'opened' or 'closed'")

        for w in warnings:
            print(w)
        for e in errors:
            print(e)

        if errors:
            print(f"\n  Validation FAILED — {len(errors)} error(s). Nothing was imported.")
            return None, len(errors)

        print(f"  Validation passed — {len(rows)} row(s) ready")
        return rows, 0

    # ── Unresolvable parent helpers ───────────────────────────────────────────

    def _build_valid_epic_ids(self, root_group):
        """Return the set of all epic IDs that exist in the target group hierarchy."""
        return {e.id for e in root_group.epics.list(all=True)}

    def _pick_fallback_parent(self, root_group):
        """
        Display the live epic hierarchy grouped by containing group and prompt
        the user to pick a fallback parent.  Returns (epic_id, epic_title) or
        (None, None) if the user chooses the label approach instead.
        """
        print("\n  Fetching epic hierarchy for fallback parent selection...")
        all_epics = root_group.epics.list(all=True)
        gid_map   = self._build_gid_path_map(root_group)

        # Group epics by containing group path
        by_group = {}
        for epic in all_epics:
            gpath = gid_map.get(getattr(epic, "group_id", None), root_group.full_path)
            by_group.setdefault(gpath, []).append(epic)

        choices = []  # ordered list of (epic_id, epic_title) matching display numbers
        print()
        for gpath in sorted(by_group):
            print(f"  {gpath}")
            for epic in by_group[gpath]:
                etype = self._epic_type_display(epic.labels or [])
                choices.append((epic.id, epic.title))
                idx = len(choices)
                print(f"    [{idx:>3}] [{etype:<11}] {epic.title[:55]}  (#{epic.iid})")
            print()

        print(f"    [  0] Apply 'import::needs-parent' label instead — no parent set")
        print(f"    [  q] Quit — abort the import entirely")
        print()

        while True:
            raw = input(f"  Select fallback parent [0–{len(choices)}, q to abort]: ").strip()
            if raw.lower() in ("q", "quit"):
                print("  Import aborted.")
                sys.exit(0)
            try:
                n = int(raw)
                if n == 0:
                    return None, None
                if 1 <= n <= len(choices):
                    eid, etitle = choices[n - 1]
                    print(f"  Fallback parent set to: '{etitle}' (id={eid})")
                    return eid, etitle
            except ValueError:
                pass
            print(f"  Please enter a number between 0 and {len(choices)}.")

    def _resolve_parent_ids(self, rows, valid_epic_ids, root_group, unresolved_parent):
        """
        Pre-flight parent_id resolution pass — runs before any creation.

        Scans every row for a parent_id that is not present in valid_epic_ids.
        If any are found, reports them all, then asks the user once how to
        proceed (unless unresolved_parent is already 'label' or 'skip').

        Returns a dict {row_index: resolved_parent_id_or_None} and a set of
        row indices that are marked as orphans (needs-parent label).
        Rows keyed to None get no parent set.  Returns (None, None) if the
        caller should abort.
        """
        unresolvable = []   # (row_index_1based, title, raw_parent_id)
        for i, row in enumerate(rows, 1):
            pid = self._coerce_int(row.get("parent_id"), "parent_id", i, [])
            if pid is not None and pid not in valid_epic_ids:
                unresolvable.append((i, str(row.get("title", "")).strip(), pid))

        if not unresolvable:
            return {}, set()

        print(f"\n  ── {len(unresolvable)} unresolvable parent_id(s) detected ──")
        print(f"  {'Row':<5} {'parent_id':<12} Title")
        print(f"  {'─'*5} {'─'*12} {'─'*40}")
        for row_num, title, pid in unresolvable:
            print(f"  {row_num:<5} {pid:<12} {title[:50]}")

        fallback_id    = None
        fallback_title = None

        if unresolved_parent == "skip":
            print(f"\n  Action: skip — {len(unresolvable)} row(s) will be skipped.")
            skip_rows = {r for r, _, _ in unresolvable}
            return {r: None for r in skip_rows}, set()

        if unresolved_parent == "label" or (unresolved_parent == "ask" and not sys.stdin.isatty()):
            if unresolved_parent == "ask":
                # 'ask' is interactive (it prompts on the live hierarchy); in a
                # non-interactive run (e.g. a web job) there is no stdin, so fall
                # back to 'label' instead of blocking/crashing on input().
                print(f"\n  Action: ask requested but this run is non-interactive — "
                      f"applying 'label' instead.")
            print(f"\n  Action: label — 'import::needs-parent' will be added to these epics.")
        else:
            # "ask" — let user pick a fallback parent from the hierarchy
            print(f"\n  Action: ask — select a fallback parent for all {len(unresolvable)} affected row(s).")
            fallback_id, fallback_title = self._pick_fallback_parent(root_group)
            if fallback_id:
                print(f"  Fallback: '{fallback_title}' (id={fallback_id}) — applies to all {len(unresolvable)} row(s).")
            else:
                print(f"  No fallback chosen — 'import::needs-parent' label will be applied instead.")

        parent_map = {}   # row_index → resolved parent_id (or None)
        orphan_rows = set()
        for row_num, _, _ in unresolvable:
            if fallback_id:
                parent_map[row_num] = fallback_id
            else:
                parent_map[row_num] = None
                orphan_rows.add(row_num)

        return parent_map, orphan_rows

    def import_epics(self, input_path=None, unresolved_parent="label", dry_run=False,
                     group=None, create_missing=False, dest_group=None, on_existing="skip"):
        with self._group_override(group):
            return self._import_epics(input_path, unresolved_parent, dry_run, create_missing,
                                      dest_group, on_existing)

    def _import_epics(self, input_path=None, unresolved_parent="label", dry_run=False,
                      create_missing=False, dest_group=None, on_existing="skip"):
        """
        Import epics from a CSV or JSON file.

        unresolved_parent controls what happens when a parent_id from the file
        does not match any epic in the target hierarchy.  The check runs in the
        pre-flight pass — before any epic is created — so the user decides once
        and the import runs without interruption:

          'ask'   – show the live hierarchy grouped by group, let the user pick
                    a single fallback parent for all affected rows; choosing 0
                    falls back to the label approach
          'label' – create without a parent and add 'import::needs-parent'
          'skip'  – skip the affected rows entirely
        """
        if unresolved_parent not in ("ask", "label", "skip"):
            print(f"ERROR: unresolved_parent must be 'ask', 'label', or 'skip' (got '{unresolved_parent}')")
            return
        if on_existing not in ("create", "skip", "update"):
            print(f"ERROR: on_existing must be 'create', 'skip', or 'update' (got '{on_existing}')")
            return
        if not input_path:
            print("ERROR: input_path is required.")
            return

        path = self._resolve_path(input_path)
        if not path.exists():
            print(f"ERROR: file not found: '{path}'")
            if str(path) != input_path:
                print(f"       (resolved from '{input_path}')")
            return

        print(f"\nImporting epics from '{path}'" + ("  [DRY RUN]" if dry_run else ""))

        rows = self._load_file(path)
        if rows is None:
            return
        if not rows:
            print("  File is empty — nothing to import.")
            return

        print(f"  {len(rows)} record(s) in file")

        # ── Pre-flight: structure + data types ───────────────────────────────
        print("\n  Pre-flight validation...")
        cleaned, err_count = self._validate_epics(rows)
        if cleaned is None:
            return

        root_group = self._resolve_import_target(create_missing, dry_run)
        if root_group is None:
            return
        print("\n  Building group cache...")
        group_cache = self._build_group_cache(root_group)
        print(f"  {len(group_cache)} group(s) available as targets")

        # Placement destination (#138): validate up front and fail loudly — a
        # bad destination must never silently dump every epic at the root.
        if dest_group and dest_group not in group_cache:
            print(f"\n  ERROR: destination group '{dest_group}' not found under "
                  f"target root '{root_group.full_path}'. Nothing was imported.")
            return

        # ── Pre-flight: parent_id resolution ────────────────────────────────
        print("\n  Checking parent_ids against target hierarchy...")
        valid_epic_ids = self._build_valid_epic_ids(root_group)
        print(f"  {len(valid_epic_ids)} epic(s) in target hierarchy")

        parent_map, orphan_rows = self._resolve_parent_ids(
            cleaned, valid_epic_ids, root_group, unresolved_parent
        )

        skip_rows = {r for r, resolved in parent_map.items() if resolved is None and r not in orphan_rows}

        print(f"\n  Ready — beginning import of {len(cleaned)} row(s)...")
        if skip_rows:
            print(f"  ({len(skip_rows)} row(s) will be skipped due to unresolvable parents)")
        if orphan_rows:
            print(f"  ({len(orphan_rows)} row(s) will receive 'import::needs-parent' label)")

        created = skipped = updated = failed = 0
        orphan_summary = []   # (row_num, title, group_path, original_parent_id)

        for i, row in enumerate(cleaned, 1):
            if i in skip_rows:
                skipped += 1
                continue

            title       = str(row.get("title", "")).strip()
            description = str(row.get("description", "")).strip()
            labels      = self._coerce_labels(row.get("labels"))
            start_date  = self._coerce_date(row.get("start_date"),                      "start_date", i, [])
            due_date    = self._coerce_date(row.get("due_date") or row.get("end_date"),  "due_date",   i, [])
            orig_pid    = self._coerce_int(row.get("parent_id"),     "parent_id",     i, [])
            weight      = self._coerce_int(row.get("planned_weight"), "planned_weight", i, [])
            state       = str(row.get("state", "")).strip().lower()
            # Placement (#138): per-row fallback. Honor the row's own
            # group_path when it resolves under the target root; otherwise place
            # the row in the user-picked dest_group (validated above). With
            # neither, land at the target root — the root is a valid epic
            # container (unlike issues, where a missing project has no root
            # fallback and the row is skipped).
            own = str(row.get("group_path", "")).strip()
            if own and own in group_cache:
                gpath = own
            elif dest_group:
                gpath = dest_group
            else:
                gpath = own or root_group.full_path

            target = group_cache.get(gpath)
            if not target:
                print(f"  row {i}: WARN group_path '{gpath}' not found — using root group")
                target = root_group

            is_orphan = i in orphan_rows
            if is_orphan and "import::needs-parent" not in labels:
                labels = labels + ["import::needs-parent"]

            # Determine resolved parent_id
            if orig_pid is not None and orig_pid in valid_epic_ids:
                resolved_pid = orig_pid
            else:
                resolved_pid = parent_map.get(i)  # fallback or None

            payload = {"title": title}
            if description:       payload["description"] = description
            if labels:            payload["labels"]      = labels
            if start_date:        payload["start_date"]  = start_date
            if due_date:          payload["end_date"]    = due_date
            if resolved_pid:      payload["parent_id"]   = resolved_pid

            # Re-import handling: match an existing epic by title in the target.
            existing = self._find_epic_by_title(target, title) if on_existing != "create" else None
            if existing and on_existing == "skip":
                print(f"  row {i}: {'[dry] ' if dry_run else ''}SKIP — epic '{title}' "
                      f"already exists (#{existing.iid})")
                skipped += 1
                continue

            if dry_run:
                action = "update" if (existing and on_existing == "update") else "create"
                parts = [f"'{title}'", f"group={target.full_path}", f"action={action}"]
                if existing:      parts.append(f"#{existing.iid}")
                if labels:        parts.append(f"labels={labels}")
                if weight:        parts.append(f"weight={weight}")
                if resolved_pid:  parts.append(f"parent_id={resolved_pid}")
                if is_orphan:     parts.append("⚑ needs-parent")
                if start_date:    parts.append(f"start={start_date}")
                if due_date:      parts.append(f"due={due_date}")
                print(f"  [dry] row {i}: {' | '.join(parts)}")
                if is_orphan:
                    orphan_summary.append((i, title, target.full_path, orig_pid))
                if action == "update":  updated += 1
                else:                   created += 1
                continue

            try:
                if existing and on_existing == "update":
                    self._update_epic(existing, payload, weight, state)
                    print(f"  row {i}: updated #{existing.iid} '{title}' → {target.full_path}")
                    updated += 1
                else:
                    epic = target.epics.create(payload)
                    if weight is not None:
                        self._set_epic_weight(epic, weight)
                    if state == "closed":
                        epic.state_event = "close"
                        epic.save()
                    print(f"  row {i}: created #{epic.iid} '{title}' → {target.full_path}")
                    created += 1
                if is_orphan:
                    orphan_summary.append((i, title, target.full_path, orig_pid))

            except Exception as ex:
                print(f"  row {i}: FAILED '{title}' — {ex}")
                failed += 1

        print(f"\n  Done — {created} created  |  {updated} updated  |  {skipped} skipped  |  {failed} failed"
              + ("  (dry run — no changes made)" if dry_run else ""))

        if orphan_summary:
            print(f"\n  ── Orphan summary ({len(orphan_summary)} epic(s) created without intended parent) ──")
            print(f"  {'Row':<5} {'Original parent_id':<20} {'Group':<35} Title")
            print(f"  {'─'*5} {'─'*20} {'─'*35} {'─'*30}")
            for row_num, etitle, gpath, orig_pid in orphan_summary:
                print(f"  {row_num:<5} {str(orig_pid):<20} {gpath[:35]:<35} {etitle[:50]}")
            print(f"\n  Filter by label 'import::needs-parent' in GitLab to find and re-parent these epics.")

    # ── Issue export ──────────────────────────────────────────────────────────

    def export_issues(self, output_path=None, group=None, fmt="csv"):
        with self._group_override(group):
            return self._export_issues(output_path, fmt)

    def _export_issues(self, output_path=None, fmt="csv"):
        group = self.get_group_by_name(self.parent_group)
        if not group:
            print(f"ERROR: group '{self.parent_group}' not found.")
            return

        # Explicit output path (CLI): the extension drives the format, exactly as
        # before. Auto-named (UI): the fmt selector drives extension + format.
        if output_path:
            path = self._resolve_path(output_path)
            fmt  = self._detect_format(path)
        else:
            fmt  = "json" if str(fmt).lower() == "json" else "csv"
            path = self._default_export_name("issues-export", fmt)

        print(f"\nExporting issues from '{group.full_path}' (all subgroups included)...")

        print("  Building project map...")
        pid_map = self._build_pid_path_map(group)

        all_issues = group.issues.list(all=True)
        print(f"  {len(all_issues)} issue(s) found")

        rows = []
        for issue in all_issues:
            epic_attr = getattr(issue, "epic", None) or {}
            rows.append({
                "project_path": pid_map.get(getattr(issue, "project_id", None), ""),
                "iid":          issue.iid,
                "id":           issue.id,
                "title":        issue.title or "",
                "description":  issue.description or "",
                "state":        issue.state or "",
                "labels":       ", ".join(issue.labels or []),
                "weight":       issue.weight if issue.weight is not None else "",
                "due_date":     issue.due_date or "",
                "milestone":    (issue.milestone or {}).get("title", ""),
                "assignees":    ", ".join(
                                    a.get("username", "") for a in (issue.assignees or [])
                                ),
                "epic_id":      epic_attr.get("id",  ""),
                "epic_iid":     epic_attr.get("iid", ""),
                "author":       (issue.author or {}).get("name", ""),
                "web_url":      issue.web_url or "",
                "created_at":   getattr(issue, "created_at", "") or "",
                "updated_at":   getattr(issue, "updated_at", "") or "",
                "closed_at":    getattr(issue, "closed_at",  "") or "",
            })

        self._write_file(path, fmt, rows, ISSUE_EXPORT_FIELDS)
        print(f"  Exported {len(rows)} issue(s) → {path}")
        url = self._export_url(path)
        if url:
            print(f"  Download: {url}")

    # ── Issue import ──────────────────────────────────────────────────────────

    def _validate_issues(self, rows, override_project):
        errors   = []
        warnings = []
        columns  = set(rows[0].keys()) if rows else set()

        missing = ISSUE_IMPORT_REQUIRED - columns
        if missing:
            print(f"\n  INVALID: missing required column(s): {', '.join(sorted(missing))}")
            print(f"  Required: {', '.join(sorted(ISSUE_IMPORT_REQUIRED))}")
            print(f"  Optional: project_path, description, labels, weight, due_date,")
            print(f"            milestone, assignees, epic_id, state")
            return None, 1

        # Wrong-file guard: epic-only columns mean this is almost certainly an
        # epics export, not issues.
        epic_markers = columns & EPIC_ONLY_COLS
        if epic_markers:
            print(f"\n  INVALID: this looks like an EPICS export, not issues — it has "
                  f"epic-only column(s): {', '.join(sorted(epic_markers))}.")
            print("  Use the Import Epics tool for this file.")
            return None, 1

        # No issue-specific columns either → only shared columns → can't confirm type.
        if not (columns & ISSUE_ONLY_COLS):
            self._warn_type_unconfirmed("issues", "epics", "Import Epics",
                                        "project_path or epic_id")

        if not override_project and "project_path" not in columns:
            print("\n  INVALID: 'project_path' column is required when no target project is specified")
            print("  Either add a project_path column to the file or provide a project path at the prompt.")
            return None, 1

        unknown = columns - ISSUE_IMPORT_KNOWN
        if unknown:
            warnings.append(f"  WARN: unknown column(s) will be ignored: {', '.join(sorted(unknown))}")

        for i, row in enumerate(rows, 1):
            title = str(row.get("title", "")).strip()
            if not title:
                errors.append(f"  row {i}: 'title' is blank (required)")

            if not override_project:
                ppath = str(row.get("project_path", "")).strip()
                if not ppath:
                    errors.append(f"  row {i}: 'project_path' is blank")

            self._coerce_date(row.get("due_date"),  "due_date", i, errors)
            self._coerce_int(row.get("weight"),     "weight",   i, errors)
            self._coerce_int(row.get("epic_id"),    "epic_id",  i, errors)

            state = str(row.get("state", "")).strip().lower()
            if state and state not in VALID_STATES:
                errors.append(f"  row {i}: 'state' = '{state}' invalid — use 'opened' or 'closed'")

        for w in warnings:
            print(w)
        for e in errors:
            print(e)

        if errors:
            print(f"\n  Validation FAILED — {len(errors)} error(s). Nothing was imported.")
            return None, len(errors)

        print(f"  Validation passed — {len(rows)} row(s) ready")
        return rows, 0

    def import_issues(self, input_path=None, target_project_path=None, dry_run=False,
                      group=None, create_missing=False, on_existing="skip"):
        with self._group_override(group):
            return self._import_issues(input_path, target_project_path, dry_run,
                                       create_missing, on_existing)

    def _import_issues(self, input_path=None, target_project_path=None, dry_run=False,
                       create_missing=False, on_existing="skip"):
        if not input_path:
            print("ERROR: input_path is required.")
            return
        if on_existing not in ("create", "skip", "update"):
            print(f"ERROR: on_existing must be 'create', 'skip', or 'update' (got '{on_existing}')")
            return

        path = self._resolve_path(input_path)
        if not path.exists():
            print(f"ERROR: file not found: '{path}'")
            if str(path) != input_path:
                print(f"       (resolved from '{input_path}')")
            return

        print(f"\nImporting issues from '{path}'" + ("  [DRY RUN]" if dry_run else ""))

        rows = self._load_file(path)
        if rows is None:
            return
        if not rows:
            print("  File is empty — nothing to import.")
            return

        print(f"  {len(rows)} record(s) in file")
        print("\n  Pre-flight validation...")
        cleaned, err_count = self._validate_issues(rows, target_project_path)
        if cleaned is None:
            return

        root_group = self._resolve_import_target(create_missing, dry_run)
        if root_group is None:
            return
        print("\n  Building project cache...")
        project_cache = self._build_project_cache(root_group)
        print(f"  {len(project_cache)} project(s) available as targets")

        # Placement destination (#138): validate up front and fail loudly — a
        # bad target project must never silently skip every row.
        if target_project_path and target_project_path not in project_cache:
            print(f"\n  ERROR: target project '{target_project_path}' not found under "
                  f"target root '{root_group.full_path}'. Nothing was imported.")
            return

        # Username → user ID cache (populated on demand)
        username_cache = {}

        created = skipped = updated = failed = 0

        for i, row in enumerate(cleaned, 1):
            title       = str(row.get("title", "")).strip()
            description = str(row.get("description", "")).strip()
            labels      = self._coerce_labels(row.get("labels"))
            weight      = self._coerce_int(row.get("weight"),   "weight",  i, [])
            due_date    = self._coerce_date(row.get("due_date"), "due_date", i, [])
            milestone   = str(row.get("milestone", "")).strip()
            assignees   = self._coerce_usernames(row.get("assignees"))
            epic_id     = self._coerce_int(row.get("epic_id"),  "epic_id", i, [])
            state       = str(row.get("state", "")).strip().lower()
            # Placement (#138): per-row fallback. Honor the row's own
            # project_path when it resolves under the target root; otherwise
            # place the row in the user-picked target_project_path (validated
            # above). Issues have no root fallback, so an unresolvable row with
            # no destination is skipped.
            own = str(row.get("project_path", "")).strip()
            if own and own in project_cache:
                ppath = own
            elif target_project_path:
                ppath = target_project_path
            else:
                ppath = own

            if not ppath:
                print(f"  row {i}: SKIP — no project path")
                skipped += 1
                continue

            project = project_cache.get(ppath)
            if not project:
                print(f"  row {i}: SKIP — project '{ppath}' not found")
                skipped += 1
                continue

            payload = {"title": title}
            if description:
                payload["description"] = description
            if labels:
                payload["labels"] = labels
            if weight is not None:
                payload["weight"] = weight
            if due_date:
                payload["due_date"] = due_date

            # Milestone by title lookup. include_ancestors pulls in group-level
            # milestones inherited from the parent groups (PI milestones live at
            # the ART/portfolio level, not on the project) — GitLab lets a group
            # milestone be assigned to an issue in a project under that group.
            if milestone:
                try:
                    ms_list = project.milestones.list(
                        search=milestone, include_ancestors=True, all=True)
                except Exception:
                    ms_list = project.milestones.list(search=milestone)
                # search is a substring match and may return several (e.g. a
                # project and a group milestone of the same name) — prefer an
                # exact title match.
                exact = [m for m in ms_list if getattr(m, "title", "") == milestone]
                chosen = exact[0] if exact else (ms_list[0] if ms_list else None)
                if chosen:
                    payload["milestone_id"] = chosen.id
                else:
                    print(f"  row {i}: WARN milestone '{milestone}' not found "
                          f"(searched project + ancestor groups) — skipping")

            # Assignee username → id lookup
            if assignees:
                ids = []
                for username in assignees:
                    if username in username_cache:
                        ids.append(username_cache[username])
                    else:
                        try:
                            users = self.gl.users.list(username=username)
                            if users:
                                uid = users[0].id
                                username_cache[username] = uid
                                ids.append(uid)
                            else:
                                print(f"  row {i}: WARN assignee '{username}' not found — skipping")
                        except Exception:
                            print(f"  row {i}: WARN could not look up user '{username}'")
                if ids:
                    payload["assignee_ids"] = ids

            # Re-import handling: match an existing issue by title in the target.
            existing = self._find_issue_by_title(project, title) if on_existing != "create" else None
            if existing and on_existing == "skip":
                print(f"  row {i}: {'[dry] ' if dry_run else ''}SKIP — issue '{title}' "
                      f"already exists (#{existing.iid})")
                skipped += 1
                continue

            if dry_run:
                action = "update" if (existing and on_existing == "update") else "create"
                parts = [f"'{title}'", f"project={ppath}", f"action={action}"]
                if existing:  parts.append(f"#{existing.iid}")
                if labels:    parts.append(f"labels={labels}")
                if weight:    parts.append(f"weight={weight}")
                if epic_id:   parts.append(f"epic_id={epic_id}")
                if due_date:  parts.append(f"due={due_date}")
                if milestone: parts.append(f"milestone={milestone}")
                print(f"  [dry] row {i}: {' | '.join(parts)}")
                if action == "update":  updated += 1
                else:                   created += 1
                continue

            try:
                if existing and on_existing == "update":
                    self._update_issue(existing, payload, state, epic_id)
                    print(f"  row {i}: updated #{existing.iid} '{title}' → {ppath}")
                    updated += 1
                    continue

                issue = project.issues.create(payload)

                if epic_id is not None:
                    try:
                        issue.epic_id = epic_id
                        issue.save()
                    except Exception as ex:
                        print(f"  row {i}: WARN epic assignment failed — {ex}")

                if state == "closed":
                    issue.state_event = "close"
                    issue.save()

                print(f"  row {i}: created #{issue.iid} '{title}' → {ppath}")
                created += 1
            except Exception as ex:
                print(f"  row {i}: FAILED '{title}' — {ex}")
                failed += 1

        print(f"\n  Done — {created} created  |  {updated} updated  |  {skipped} skipped  |  {failed} failed"
              + ("  (dry run — no changes made)" if dry_run else ""))
