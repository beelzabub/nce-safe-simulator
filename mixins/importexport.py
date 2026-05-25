import csv
import json
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

VALID_DATE_FMT = "%Y-%m-%d"
VALID_STATES   = {"opened", "open", "closed"}


class ImportExportMixin:

    # ── Path / format helpers ─────────────────────────────────────────────────

    def _resolve_path(self, path_str):
        return Path(path_str).expanduser().resolve()

    def _detect_format(self, path):
        return "json" if path.suffix.lower() == ".json" else "csv"

    def _default_export_name(self, stem, fmt):
        return self._resolve_path(f"{self.sanitize_name(self.parent_group)}-{stem}.{fmt}")

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
        """Return {full_path: group_object} for root and all subgroups."""
        cache = {root_group.full_path: root_group}
        for sg in root_group.subgroups.list(all=True, include_subgroups=True):
            try:
                full = self.gl.groups.get(sg.id)
                cache[full.full_path] = full
            except Exception:
                pass
        return cache

    def _build_gid_path_map(self, root_group):
        """Return {group_id: full_path} for root and all subgroups."""
        m = {root_group.id: root_group.full_path}
        for sg in root_group.subgroups.list(all=True, include_subgroups=True):
            try:
                full = self.gl.groups.get(sg.id)
                m[full.id] = full.full_path
            except Exception:
                pass
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

    def _build_pid_path_map(self, root_group):
        """Return {project_id: path_with_namespace}."""
        return {
            p.id: p.path_with_namespace
            for p in root_group.projects.list(all=True, include_subgroups=True)
        }

    # ── Epic export ───────────────────────────────────────────────────────────

    def export_epics(self, output_path=None):
        group = self.get_group_by_name(self.parent_group)
        if not group:
            print(f"ERROR: group '{self.parent_group}' not found.")
            return

        fmt  = "csv"
        if output_path:
            path = self._resolve_path(output_path)
            fmt  = self._detect_format(path)
        else:
            path = self._default_export_name("epics-export", "csv")

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

    # ── Epic import ───────────────────────────────────────────────────────────

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

    def import_epics(self, input_path=None, dry_run=False):
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
        print("\n  Pre-flight validation...")
        cleaned, err_count = self._validate_epics(rows)
        if cleaned is None:
            return

        root_group   = self.get_group_by_name(self.parent_group)
        print("\n  Building group cache...")
        group_cache  = self._build_group_cache(root_group)
        print(f"  {len(group_cache)} group(s) available as targets")

        created = skipped = failed = 0

        for i, row in enumerate(cleaned, 1):
            title       = str(row.get("title", "")).strip()
            description = str(row.get("description", "")).strip()
            labels      = self._coerce_labels(row.get("labels"))
            start_date  = self._coerce_date(row.get("start_date"),                      "start_date",     i, [])
            due_date    = self._coerce_date(row.get("due_date") or row.get("end_date"),  "due_date",       i, [])
            parent_id   = self._coerce_int(row.get("parent_id"),    "parent_id",     i, [])
            weight      = self._coerce_int(row.get("planned_weight"), "planned_weight", i, [])
            state       = str(row.get("state", "")).strip().lower()
            gpath       = str(row.get("group_path", "")).strip() or root_group.full_path

            target = group_cache.get(gpath)
            if not target:
                print(f"  row {i}: WARN group_path '{gpath}' not found — using root group")
                target = root_group

            payload = {"title": title}
            if description:
                payload["description"] = description
            if labels:
                payload["labels"] = labels
            if start_date:
                payload["start_date"] = start_date
            if due_date:
                payload["end_date"] = due_date
            if parent_id:
                payload["parent_id"] = parent_id

            if dry_run:
                parts = [f"'{title}'", f"group={target.full_path}"]
                if labels:      parts.append(f"labels={labels}")
                if weight:      parts.append(f"weight={weight}")
                if parent_id:   parts.append(f"parent_id={parent_id}")
                if start_date:  parts.append(f"start={start_date}")
                if due_date:    parts.append(f"due={due_date}")
                print(f"  [dry] row {i}: {' | '.join(parts)}")
                created += 1
                continue

            try:
                epic = target.epics.create(payload)

                if weight is not None:
                    self._set_epic_weight(epic, weight)

                if state == "closed":
                    epic.state_event = "close"
                    epic.save()

                print(f"  row {i}: created #{epic.iid} '{title}' → {target.full_path}")
                created += 1
            except Exception as ex:
                print(f"  row {i}: FAILED '{title}' — {ex}")
                failed += 1

        print(f"\n  Done — {created} created  |  {skipped} skipped  |  {failed} failed"
              + ("  (dry run — no changes made)" if dry_run else ""))

    # ── Issue export ──────────────────────────────────────────────────────────

    def export_issues(self, output_path=None):
        group = self.get_group_by_name(self.parent_group)
        if not group:
            print(f"ERROR: group '{self.parent_group}' not found.")
            return

        fmt  = "csv"
        if output_path:
            path = self._resolve_path(output_path)
            fmt  = self._detect_format(path)
        else:
            path = self._default_export_name("issues-export", "csv")

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

    def import_issues(self, input_path=None, target_project_path=None, dry_run=False):
        if not input_path:
            print("ERROR: input_path is required.")
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

        root_group    = self.get_group_by_name(self.parent_group)
        print("\n  Building project cache...")
        project_cache = self._build_project_cache(root_group)
        print(f"  {len(project_cache)} project(s) available as targets")

        # Username → user ID cache (populated on demand)
        username_cache = {}

        created = skipped = failed = 0

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
            ppath       = target_project_path or str(row.get("project_path", "")).strip()

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

            # Milestone by title lookup
            if milestone:
                ms_list = project.milestones.list(search=milestone)
                if ms_list:
                    payload["milestone_id"] = ms_list[0].id
                else:
                    print(f"  row {i}: WARN milestone '{milestone}' not found — skipping")

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

            if dry_run:
                parts = [f"'{title}'", f"project={ppath}"]
                if labels:    parts.append(f"labels={labels}")
                if weight:    parts.append(f"weight={weight}")
                if epic_id:   parts.append(f"epic_id={epic_id}")
                if due_date:  parts.append(f"due={due_date}")
                if milestone: parts.append(f"milestone={milestone}")
                print(f"  [dry] row {i}: {' | '.join(parts)}")
                created += 1
                continue

            try:
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

        print(f"\n  Done — {created} created  |  {skipped} skipped  |  {failed} failed"
              + ("  (dry run — no changes made)" if dry_run else ""))
