import csv
import json
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


# ── Field definitions ─────────────────────────────────────────────────────────

EPIC_EXPORT_FIELDS = [
    "group_path", "source_root", "iid", "id", "title", "description", "state",
    "labels", "start_date", "due_date", "parent_id", "parent_iid",
    "planned_weight", "business_value", "author", "web_url",
    "created_at", "updated_at", "closed_at",
]

ISSUE_EXPORT_FIELDS = [
    "project_path", "source_root", "iid", "id", "title", "description", "state",
    "labels", "weight", "due_date", "milestone", "assignees",
    "epic_id", "epic_iid", "epic_title", "author", "web_url",
    "created_at", "updated_at", "closed_at",
]

# Fields the import will act on; anything else is noted and ignored
EPIC_IMPORT_KNOWN = {
    "title", "group_path", "description", "labels",
    "start_date", "due_date", "end_date", "parent_id",
    "planned_weight", "business_value", "state",
    # read-only / reference columns carried from export — silently ignored
    "iid", "id", "author", "web_url", "created_at", "updated_at",
    "closed_at", "parent_iid", "work_item_id",
    # source root stamp (#139) — carried across enclaves, consumed for
    # relative-path reconciliation, not written to the created epic
    "source_root",
}
EPIC_IMPORT_REQUIRED = {"title"}

ISSUE_IMPORT_KNOWN = {
    "title", "project_path", "description", "labels", "weight",
    "due_date", "milestone", "assignees", "epic_id", "state",
    # epic link resolution across systems (#197) — title beats raw id
    "epic_title",
    # read-only reference columns
    "iid", "id", "author", "web_url", "created_at", "updated_at",
    "closed_at", "epic_iid",
    # source root stamp (#139) — see EPIC_IMPORT_KNOWN
    "source_root",
}
ISSUE_IMPORT_REQUIRED = {"title"}

# Columns unique to each import type (shared reference columns like iid/author
# cancel out). Their presence in the other importer is a strong signal that the
# wrong file was supplied — e.g. an issues export fed to the epics importer.
EPIC_ONLY_COLS  = EPIC_IMPORT_KNOWN  - ISSUE_IMPORT_KNOWN
ISSUE_ONLY_COLS = ISSUE_IMPORT_KNOWN - EPIC_IMPORT_KNOWN

VALID_DATE_FMT = "%Y-%m-%d"
VALID_STATES   = {"opened", "open", "closed"}

LINK_EXPORT_FIELDS = [
    "link_type", "source_type", "source_id", "source_iid", "source_title",
    "source_container", "target_type", "target_id", "target_iid",
    "target_title", "target_container", "source_root",
]

# Exports land here so FastAPI's static server can serve them for download.
_EXPORTS_DIR = Path("public/exports")

# Default epic-cards spec (filter + taxonomy) shipped at the repo root. Operators
# edit this file to match the labels of their target system; --card_spec overrides
# it for one-offs. Anchored to the repo root (this file lives in mixins/) so the
# default resolves the same whatever the current working directory is.
_CARD_SPEC_DEFAULT = Path(__file__).resolve().parents[1] / "epic-cards-spec.json"


def _gid_int(gid):
    """'gid://gitlab/WorkItem/123' -> 123 (or None); plain ints pass through."""
    try:
        return int(str(gid).rsplit("/", 1)[-1])
    except (ValueError, AttributeError):
        return None


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

        Accepts an override of the form ``namespace/group`` or just ``group``
        (the configured namespace is kept). The group part is always a display
        name. The namespace part may be a display name (``TWA-122 -
        PlatformEngineering/JamieGroup``) or a full URL-slug path (``a/b/c``) —
        lookups resolve display names first and fall back to the path (#202).
        An empty / None value leaves the configured group untouched.

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

    def _find_issue_by_title(self, project, title, cache=None):
        """First issue in `project` with an exact matching title, else None.

        With ``cache`` (a per-run dict), the project's issues are listed ONCE
        and looked up locally — O(containers) API calls instead of one search
        per row, which is what rate-limited large re-imports (#201). Without
        it, the original per-call search is used.

        WARNs when several issues share the title — title is the de-facto
        identity key for re-import matching, so ambiguity is worth surfacing
        rather than silently picking one (#194).
        """
        try:
            if cache is not None:
                key = getattr(project, "id", None)
                titles = cache.get(key)
                if titles is None:
                    titles = {}
                    for iss in project.issues.list(all=True):
                        titles.setdefault(getattr(iss, "title", ""), []).append(iss)
                    cache[key] = titles
                matches = titles.get(title, [])
            else:
                matches = [iss for iss in project.issues.list(search=title, all=True)
                           if getattr(iss, "title", "") == title]
            if len(matches) > 1:
                print(f"  WARN: {len(matches)} issues titled '{title}' in "
                      f"'{getattr(project, 'path_with_namespace', '?')}' — using #{matches[0].iid}")
            return matches[0] if matches else None
        except Exception:
            return None

    def _find_epic_by_title(self, group, title, cache=None):
        """First epic in `group` ITSELF with an exact matching title, else None.

        With ``cache`` (a per-run dict) the container's own epics are listed
        once and looked up locally — see _find_issue_by_title (#201).

        The group-epics endpoint includes descendant groups' epics by
        default, which made same-titled epics in *different* containers
        collide on re-import — a row targeting the root skipped because its
        twin lived in a subgroup (#199). on_existing semantics are
        per-container, so matches filter to this exact group; whole-tree
        searches (e.g. import-links endpoint resolution) intentionally use
        _target_epic_titles instead.

        WARNs on multiple exact matches — see _find_issue_by_title (#194).
        """
        try:
            gid = getattr(group, "id", None)
            if cache is not None:
                titles = cache.get(gid)
                if titles is None:
                    titles = {}
                    for ep in group.epics.list(all=True):
                        if gid is None or getattr(ep, "group_id", gid) == gid:
                            titles.setdefault(getattr(ep, "title", ""), []).append(ep)
                    cache[gid] = titles
                matches = titles.get(title, [])
            else:
                matches = [
                    ep for ep in group.epics.list(search=title, all=True)
                    if getattr(ep, "title", "") == title
                    and (gid is None or getattr(ep, "group_id", gid) == gid)
                ]
            if len(matches) > 1:
                print(f"  WARN: {len(matches)} epics titled '{title}' in "
                      f"'{getattr(group, 'full_path', '?')}' — using #{matches[0].iid}")
            return matches[0] if matches else None
        except Exception:
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

    # ── Relative-path reconciliation across roots (#139) ───────────────────────

    @staticmethod
    def _strip_source_root(path, source_root):
        """Return `path` made relative to `source_root`, or None if it isn't under it.

        Paths are matched on whole segments (so a source root of ``ns-a/port``
        never partially strips ``ns-a/portfolio``). ``path == source_root`` maps
        to the root itself and returns ``""``.
        """
        path = (path or "").strip().strip("/")
        root = (source_root or "").strip().strip("/")
        if not path or not root:
            return None
        if path == root:
            return ""
        prefix = root + "/"
        if path.startswith(prefix):
            return path[len(prefix):]
        return None

    def _infer_source_root(self, rows, path_key, override=None):
        """Determine the source root to strip from each row's structural path.

        Precedence (Decision 1 in #139):
          1. an explicit ``override`` (import param) — trusted verbatim
          2. the ``source_root`` stamp carried in the export (Companion A) —
             deterministic; the exact root the export was taken from
          3. longest-common path-prefix of the rows' paths — best-effort fallback
             for un-stamped (older) files; a guess that can over-strip when every
             row shares a deeper subtree, which is exactly why the stamp exists.

        Returns ``(source_root, trusted)``: the root string (or None if nothing
        usable) and whether it came from an authoritative source (override/stamp)
        vs. the LCP guess. ``trusted`` gates the degenerate reconcile-to-root case
        so an over-stripping guess can't silently land rows at the bare root.
        """
        if override and str(override).strip():
            return str(override).strip().strip("/"), True

        stamped = {
            str(r.get("source_root", "")).strip().strip("/")
            for r in rows
            if str(r.get("source_root", "")).strip()
        }
        if len(stamped) == 1:
            return next(iter(stamped)), True

        # Longest-common-prefix fallback (segment-wise) over the rows' own paths.
        segs = [
            str(r.get(path_key, "")).strip().strip("/").split("/")
            for r in rows
            if str(r.get(path_key, "")).strip()
        ]
        if not segs:
            return None, False
        common = segs[0]
        for other in segs[1:]:
            i = 0
            while i < len(common) and i < len(other) and common[i] == other[i]:
                i += 1
            common = common[:i]
            if not common:
                return None, False
        return ("/".join(common) or None), False

    # ── Group/project display names across systems (#200) ─────────────────────

    def _write_group_names_sidecar(self, group, export_path):
        """Write <export>-group-names.json next to an export (#200).

        Maps each descendant group's and project's RELATIVE path to its
        display name, so create_missing_groups / create_missing_projects can
        name recreated containers like the source instead of using slugs.
        A convenience artifact: failure WARNs and never breaks the export.
        """
        try:
            root = group.full_path

            def _rel(p):
                # Import-side lookups are always root-relative; anything not
                # under the root would be a dead key, so it is skipped.
                return p[len(root) + 1:] if p.startswith(root + "/") else None

            # NOTE: this re-walks descendants/projects even though the export
            # body built path maps moments earlier — those maps are path-only
            # (no names), and fetching here keeps the sidecar fully inside
            # this try/except so it can never break an export. Typical
            # hierarchies are tens of containers; the extra listing is cheap.
            groups = {}
            for g in self.list_descendant_groups(group):
                rel = _rel(getattr(g, "full_path", ""))
                nm = getattr(g, "name", "")
                if rel and nm:
                    groups[rel] = nm
            projects = {}
            for pr in group.projects.list(all=True, include_subgroups=True):
                rel = _rel(getattr(pr, "path_with_namespace", ""))
                nm = getattr(pr, "name", "")
                if rel and nm:
                    projects[rel] = nm
            if not groups and not projects:
                return None
            sidecar = export_path.with_name(export_path.stem + "-group-names.json")
            sidecar.write_text(
                json.dumps({"groups": groups, "projects": projects}, indent=2),
                encoding="utf-8")
            print(f"  Group names sidecar: {sidecar}")
            url = self._export_url(sidecar)
            if url:
                print(f"  Download: {url}   — pass to imports as 'Group names file'")
            return sidecar
        except Exception as ex:
            print(f"  WARN: could not write the group-names sidecar — {ex}")
            return None

    def _load_group_names(self, path_str):
        """Load a group-names sidecar; tolerant — {} mappings on any problem."""
        empty = {"groups": {}, "projects": {}}
        if not path_str:
            return empty
        try:
            data = json.loads(self._resolve_path(path_str).read_text(encoding="utf-8"))
            return {"groups":   dict(data.get("groups")   or {}),
                    "projects": dict(data.get("projects") or {})}
        except Exception as ex:
            print(f"  WARN: group-names file '{path_str}' could not be loaded "
                  f"({ex}) — created containers will use path segments as names.")
            return empty

    def _ensure_group_chain(self, root_group, rel, group_cache, dry_run, planned,
                            names=None):
        """Create (or, under dry run, plan) the subgroup chain for ``rel``.

        Walks ``rel`` segment by segment under ``root_group``, creating each
        missing subgroup (mkdir -p style) and adding it to ``group_cache`` so
        later rows land in it without re-creating. Segments come from a real
        exported full_path, so they are already valid URL slugs; the display
        name is the slug (the export doesn't carry display names). Under dry
        run nothing is created — planned paths are reported once each and a
        lightweight stub keeps the preview showing the intended placement.

        Returns the (created/stubbed/existing) group for the full chain.
        """
        class _Planned:
            def __init__(self, full_path):
                self.full_path = full_path

        names = names or {}
        parent = root_group
        cur = root_group.full_path
        rel_prefix = []
        for seg in rel.strip("/").split("/"):
            rel_prefix.append(seg)
            cur = f"{cur}/{seg}"
            g = group_cache.get(cur)
            if g is None:
                # Display name from the sidecar (#200); slug fallback.
                display = names.get("/".join(rel_prefix), seg)
                note = f" (name '{display}')" if display != seg else ""
                if dry_run:
                    if cur not in planned:
                        planned.add(cur)
                        print(f"  [dry] would create group '{cur}'{note}")
                    g = _Planned(cur)
                else:
                    g = self.gl.groups.create({
                        "name": display, "path": seg, "parent_id": parent.id,
                    })
                    planned.add(cur)
                    print(f"  created group '{cur}'{note}")
                group_cache[cur] = g
            parent = g
        return parent

    def _reconcile_path(self, own, source_root, target_root_path, cache, allow_root=True):
        """Resolve `own` (a source-rooted path) under `target_root_path`.

        Strips `source_root` from `own` to get the structural remainder, then
        looks for ``target_root_path/<remainder>`` in `cache`. Returns the matched
        cache key (a full target path) or None when it doesn't resolve. Because it
        matches the whole relative path — not a bare leaf name — it maps to exactly
        one target container or none, so it can never silently misplace an item.

        ``allow_root`` guards the empty-remainder case (``own == source_root`` →
        the target root itself): meaningful for a trusted stamp/override, but with
        a guessed (LCP) root it just means the guess over-stripped, so callers pass
        ``allow_root=False`` and let the normal root/skip fallback handle the row.
        """
        rel = self._strip_source_root(own, source_root)
        if rel is None:
            return None
        if rel == "" and not allow_root:
            return None
        candidate = f"{target_root_path}/{rel}" if rel else target_root_path
        return candidate if candidate in cache else None

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

        # Business Value custom field (#196) — prioritization signal; without
        # it a transferred portfolio loses WSJF scores and BV-at-risk metrics.
        bv_values = self._fetch_epic_business_values(all_epics, root_namespace=group)

        rows = []
        for epic in all_epics:
            rows.append({
                "group_path":     gid_map.get(getattr(epic, "group_id", None), ""),
                "source_root":    group.full_path,
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
                "business_value": bv_values.get(epic.id, ""),
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
        self._write_group_names_sidecar(group, path)

    # ── Epic cards (printable PDF, #249) ──────────────────────────────────────

    def export_epic_cards(self, output_path=None, group=None, per_page="1",
                          label_filter=None, card_spec=None):
        with self._group_override(group):
            return self._export_epic_cards(output_path, per_page, label_filter, card_spec)

    def _export_epic_cards(self, output_path=None, per_page="1",
                           label_filter=None, card_spec=None):
        from .epic_cards import render_cards   # lazy — WeasyPrint only needed for this tool

        group = self.get_group_by_name(self.parent_group)
        if not group:
            print(f"ERROR: group '{self.parent_group}' not found.")
            return

        try:
            per = int(per_page)
        except (TypeError, ValueError):
            per = 1
        if per not in (1, 2, 3, 4):
            per = 1

        if output_path:
            path = self._resolve_path(output_path)
            if path.suffix.lower() != ".pdf":
                path = path.with_suffix(".pdf")
        else:
            path = self._default_export_name("epic-cards", "pdf")

        # The card spec (filter + taxonomy) is the self-contained definition of a
        # card set; operators edit epic-cards-spec.json to match their system. An
        # explicit label_filter still overrides its filter for a one-off; the
        # taxonomy always comes from the spec.
        spec = self._load_card_spec(card_spec)
        taxonomy = self._normalize_taxonomy(spec.get("taxonomy", {}))

        print(f"\nBuilding epic cards from '{group.full_path}' (all subgroups included)...")
        all_epics = group.epics.list(all=True)

        # Optional filter: comma-separated labels; an epic must carry ALL of them.
        # A trailing '*' makes a token a scope wildcard — e.g. `mission-thread::*`
        # matches an epic carrying any `mission-thread::…` label. The capability
        # card set is `epic::capability,mission-thread::*`. An explicit label_filter
        # overrides the spec's "filter"; otherwise the spec supplies it.
        wanted = self._filter_tokens(label_filter) or self._filter_tokens(spec.get("filter"))
        if wanted:
            print(f"  Filter: {', '.join(wanted)}")
            all_epics = [e for e in all_epics
                         if self._epic_label_match(e.labels or [], wanted)]
        print(f"  {len(all_epics)} epic(s) after filter")
        if not all_epics:
            print("  Nothing to render — no epics matched the filter.")
            return

        weights = self._fetch_epic_weights(all_epics)
        label_colors = self._fetch_label_colors(group)
        cards   = [self._epic_to_card(e, weights, taxonomy, label_colors) for e in all_epics]
        render_cards(cards, path, per_page=per)
        print(f"  Rendered {len(cards)} card(s), {per}-up → {path}")
        url = self._export_url(path)
        if url:
            print(f"  Download: {url}")

    def _load_card_spec(self, card_spec_path):
        """Load the epic-cards spec — one JSON carrying both the label ``filter``
        and the label ``taxonomy`` for a card set. Falls back to the shipped
        ``epic-cards-spec.json`` at the repo root when no path is given; returns
        {} when the file is missing or unreadable (the tool still runs, just with
        no filter/taxonomy). Operators edit the spec to match their system."""
        path = Path(card_spec_path).expanduser() if card_spec_path else _CARD_SPEC_DEFAULT
        if not path.exists():
            if card_spec_path:
                print(f"  WARN: card spec not found: {path}")
            return {}
        try:
            return json.loads(path.read_text()) or {}
        except (OSError, ValueError) as e:
            print(f"  WARN: could not read card spec {path}: {e}")
            return {}

    @staticmethod
    def _filter_tokens(value):
        """Normalize a filter spec to a list of label tokens. Accepts a
        comma-separated string (``"epic::capability,mission-thread::*"``) or a
        list of tokens; blanks are dropped. Returns [] for None/empty."""
        if not value:
            return []
        parts = value if isinstance(value, (list, tuple)) else str(value).split(",")
        return [t.strip() for t in parts if t and str(t).strip()]

    @staticmethod
    def _normalize_taxonomy(raw):
        """Turn a taxonomy dict (family -> names, or family -> {names:[...]}) into
        ``{family: set(names)}`` so unscoped labels can be split into buckets vs
        project/system codes. Returns {} for a falsy/empty taxonomy — scoped
        fields still resolve; unscoped ones are left empty."""
        fams = {}
        for fam, spec in (raw or {}).items():
            names = spec.get("names", spec) if isinstance(spec, dict) else spec
            fams[fam] = set(names or [])
        return fams

    @staticmethod
    def _epic_label_match(labels, wanted):
        """True when ``labels`` satisfies every token in ``wanted`` (AND). A token
        ending in '*' is a scope wildcard: `mission-thread::*` matches any
        `mission-thread::…` label. The capability card set is
        `epic::capability,mission-thread::*`."""
        labs = set(labels or [])
        for w in wanted:
            if w.endswith("*"):
                if not any(l.startswith(w[:-1]) for l in labs):
                    return False
            elif w not in labs:
                return False
        return True

    @staticmethod
    def _scoped_value(labels, prefix):
        """Value of a scoped label ``prefix::X`` -> 'X' (first match), else None."""
        for l in labels:
            if l.startswith(prefix + "::"):
                return l.split("::", 1)[1]
        return None

    @staticmethod
    def _program_color(system):
        """Deterministic placeholder color per program until Program's palette
        (issue #222) lands — stable so a program is always the same hue."""
        if not system:
            return "#3b6ea5"
        palette = ["#2f6f4f", "#8a3b3b", "#2f5c8a", "#6b4e8a", "#8a6a2f",
                   "#3b7d7d", "#7d3b6b", "#556b2f"]
        return palette[sum(ord(c) for c in system) % len(palette)]

    def _fetch_label_colors(self, group):
        """Map label name -> #rrggbb from the group's live GitLab labels so the
        card chips can honor the colors set in GitLab. Best-effort — an empty map
        just falls back to the renderer's default chip colors."""
        try:
            return {l.name: getattr(l, "color", None)
                    for l in group.labels.list(all=True, iterator=True)}
        except Exception as e:
            print(f"  WARN: could not fetch label colors: {e}")
            return {}

    def _epic_to_card(self, epic, weights, taxonomy, label_colors=None):
        """Map a live epic + the #238 taxonomy to a card dict (see epic_cards.py)."""
        labels   = list(epic.labels or [])
        unscoped = [l for l in labels if "::" not in l]
        main_system   = self._scoped_value(labels, "project")
        bucket_vocab  = taxonomy.get("bucket", set())
        project_vocab = taxonomy.get("project", set())
        buckets = [l for l in unscoped if l in bucket_vocab] if bucket_vocab else []
        related = [l for l in unscoped
                   if l in project_vocab and l != main_system] if project_vocab else []
        colors = label_colors or {}
        return {
            "title":           epic.title or "",
            "weight":          weights.get(epic.web_url) if weights else None,
            "description":     getattr(epic, "description", "") or "",
            "mission_thread":  self._scoped_value(labels, "mission-thread"),
            "buckets":         buckets,
            "bucket_colors":   {b: colors.get(b) for b in buckets},
            "main_system":     main_system,
            "related_systems": related,
            "due_date":        getattr(epic, "due_date", None) or getattr(epic, "end_date", None),
            "color":           self._program_color(main_system),
        }

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
            self._coerce_int(row.get("id"),           "id",            i, errors)
            self._coerce_int(row.get("parent_id"),    "parent_id",     i, errors)
            self._coerce_int(row.get("planned_weight"), "planned_weight", i, errors)
            self._coerce_int(row.get("business_value"), "business_value", i, errors)

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

    # ── Within-file parent mapping (#194) ─────────────────────────────────────

    def _map_file_ids(self, rows):
        """Return {source_id: 1-based row index} from the rows' own 'id' column.

        The export stamps each epic's source-system id; together with
        parent_id this makes the file self-describing — the hierarchy can be
        rebuilt on any target without the source ids existing there. First
        occurrence wins on duplicates (WARNed once).
        """
        row_of_id, dups = {}, 0
        for i, r in enumerate(rows, 1):
            rid = self._coerce_int(r.get("id"), "id", i, [])
            if rid is None:
                continue
            if rid in row_of_id:
                dups += 1
            else:
                row_of_id[rid] = i
        if dups:
            print(f"  WARN: {dups} duplicate 'id' value(s) in file — first "
                  f"occurrence wins for parent mapping")
        return row_of_id

    def _order_rows_for_import(self, rows, row_of_id):
        """Return (ordered 1-based row indices, cycle_rows) — parents first.

        When a row's parent_id references another row in the file, that parent
        must be created first so the child can link to its NEW id (#194).
        Order is otherwise stable (file order); each in-file parent's subtree
        is emitted depth-first in file order. cycle_rows are rows whose
        in-file ancestor chain never reaches a root (a parent_id cycle in the
        file data); they are appended in file order, which breaks each cycle
        at its first row (created parentless + labeled) while later members
        still link to the cycle members created before them — minimal
        structure loss rather than orphaning the whole cycle.
        """
        parent_row = {}
        for i, r in enumerate(rows, 1):
            pid = self._coerce_int(r.get("parent_id"), "parent_id", i, [])
            p = row_of_id.get(pid)
            if p is not None and p != i:
                parent_row[i] = p

        children = {}
        for c, p in parent_row.items():
            children.setdefault(p, []).append(c)
        for kids in children.values():
            kids.sort()

        ordered, placed = [], set()

        def _emit(root):
            stack = [root]
            while stack:
                cur = stack.pop()
                if cur in placed:
                    continue
                placed.add(cur)
                ordered.append(cur)
                stack.extend(reversed(children.get(cur, [])))

        for i in range(1, len(rows) + 1):
            if i not in parent_row:
                _emit(i)    # a root; its subtree follows depth-first

        # Anything unplaced hangs off a parent_id cycle. Break each cycle at
        # its lowest-index member, then emit that subtree normally so every
        # descendant (and the other cycle members) still follows its parent.
        cycle_breaks = set()
        while len(placed) < len(rows):
            start = min(i for i in range(1, len(rows) + 1) if i not in placed)
            chain, cur = [], start
            while cur is not None and cur not in placed and cur not in chain:
                chain.append(cur)
                cur = parent_row.get(cur)
            members = chain[chain.index(cur):] if cur in chain else [start]
            breaker = min(members)
            cycle_breaks.add(breaker)
            _emit(breaker)

        if cycle_breaks:
            print(f"  WARN: parent_id cycle(s) in the file — broken at row(s) "
                  f"{', '.join(str(r) for r in sorted(cycle_breaks))} "
                  f"('import::needs-parent'); all other rows keep their parent link")
        return ordered, cycle_breaks

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

    # ── Business Value on import (#196) ────────────────────────────────────────

    def _resolve_import_bv_field(self, rows, root, on_missing="create",
                                 dry_run=False):
        """Resolve the target's Business Value field once, iff any row needs it.

        root is the target root group object or its full path as a string —
        the path form lets the check run before the root group is (or would
        be) created, so 'fail' can abort with zero mutations.

        on_missing (#204) decides what to do when rows carry BV but the field
        doesn't exist on the target:
          'create' – create it from the configured definition at the target
                     root's top-level namespace; a failed create (no Ultimate
                     license, no Owner) degrades to 'ignore' with a WARN
          'ignore' – WARN once; the import continues and drops the values
                     (the caller counts them into the run summary)
          'fail'   – abort before anything is touched

        An existing field is never modified — values outside its option set
        keep their per-row WARN. Dry runs only read: 'create' previews the
        field it would create instead of creating it.

        Returns {"field_gid", "options": {int value: option gid}} when the
        field is available, {} when values will be dropped, "abort" under
        'fail', or None when no row carries a business_value (no GraphQL
        spent).
        """
        needs_bv = any(
            str(r.get("business_value", "")).strip() not in ("", "None", "none")
            for r in rows
        )
        if not needs_bv:
            return None
        bv_field = self._find_bv_field(group=root)
        if not bv_field:
            name = self.BUSINESS_VALUE_FIELD["name"]
            if on_missing == "fail":
                print(f"\n  ERROR: Business Value custom field ('{name}') not "
                      f"found on the target and on_missing_bv_field=fail — "
                      f"nothing was imported.\n"
                      f"         Create it (setup-bv-field tool) or re-run "
                      f"with on_missing_bv_field=create.")
                return "abort"
            if on_missing == "create":
                bv_field = self._import_create_bv_field(root, dry_run)
                if bv_field == "dry":
                    return {}
            if not bv_field:
                tail = ("." if dry_run
                        else " (counted in the run summary).")
                print(f"  WARN: Business Value custom field ('{name}') not "
                      f"available on the target — business_value values will "
                      f"be dropped{tail}")
                return {}
        options = {}
        for opt in bv_field.get("selectOptions") or []:
            try:
                options[int(opt["value"])] = opt["id"]
            except (KeyError, ValueError, TypeError):
                pass
        return {"field_gid": bv_field["id"], "options": options}

    def _import_create_bv_field(self, root, dry_run=False):
        """Create the Business Value field for a target that lacks it (#204).

        root is the target root group object or its full path as a string.
        Custom fields live at the top-level group and apply only within it, so
        the field is created at the target root's top-level ancestor — NOT the
        configured gitlab_namespace, which can be a different tree on a
        cross-instance import. The configured definition is used (options
        outside it keep their per-row WARN; #196).

        Returns the created field dict (re-fetched so selectOptions carry
        their option gids), "dry" under dry run (announce only), or None when
        creation isn't possible — creating custom fields needs GitLab Ultimate
        and Owner on the top-level group; the caller degrades to warn-and-drop.
        """
        cfg = self.BUSINESS_VALUE_FIELD
        full_path = root if isinstance(root, str) else (getattr(root, "full_path", "") or "")
        ns = full_path.split("/")[0]
        if not ns:
            return None
        label = (f"custom field '{cfg['name']}' ({cfg['field_type']}, options "
                 f"{', '.join(cfg['select_options'])}) at top-level group '{ns}'")
        if dry_run:
            print(f"  [dry] would create {label}")
            return "dry"
        try:
            type_id = self._get_epic_work_item_type_id(ns)
            if not type_id:
                print(f"  WARN: could not resolve the Epic work item type on "
                      f"'{ns}' — cannot create the Business Value field.")
                return None
            self._custom_field_create(ns, cfg["name"], cfg["field_type"],
                                      cfg["select_options"], [type_id])
            # Re-fetch: the create mutation doesn't return option gids, which
            # _import_set_bv needs to map values onto.
            fields = self._fetch_custom_fields(ns)
            field = next((f for f in fields if f["name"] == cfg["name"]), None)
            if field:
                print(f"  Created {label}")
            return field
        except Exception as ex:
            print(f"  WARN: could not create {label} — {ex}")
            print(f"         (creating custom fields requires GitLab Ultimate "
                  f"and Owner on '{ns}')")
            return None

    def _import_set_bv(self, epic, bv, bv_ctx, row_num):
        """Set the BV custom field on a created/updated epic; WARN, never raise.

        Returns True when the value was set, False on any miss — the caller
        tallies misses so the run summary reflects them (#202: a transient
        GraphQL failure used to lose the value with no trace in the summary).
        """
        opt_gid = bv_ctx["options"].get(bv)
        if opt_gid is None:
            print(f"  row {row_num}: WARN business_value {bv} is not an option "
                  f"of the target field ({sorted(bv_ctx['options'])}) — not set")
            return False
        wid = getattr(epic, "work_item_id", None)
        if not wid:
            print(f"  row {row_num}: WARN epic has no work_item_id — "
                  f"business_value not set")
            return False
        try:
            if self._set_work_item_business_value(wid, bv_ctx["field_gid"], opt_gid):
                return True
            print(f"  row {row_num}: WARN business_value {bv} not set on "
                  f"'{getattr(epic, 'title', '?')}' — GraphQL mutation failed "
                  f"after retries")
            return False
        except Exception as ex:
            print(f"  row {row_num}: WARN business_value set failed — {ex}")
            return False

    def _resolve_parent_ids(self, rows, valid_epic_ids, root_group, unresolved_parent,
                            file_ids=frozenset(), cross_root=False):
        """
        Pre-flight parent_id resolution pass — runs before any creation.

        Scans every row for a parent_id that resolves neither within the file
        (file_ids — those link through the source_id→new_id map, #194) nor
        against the live target (valid_epic_ids). With cross_root True the
        live-target match is NOT accepted: the file comes from a different
        root, so a raw id equal to some target epic's id is coincidence, not
        a link — silently attaching to it would corrupt the tree.

        If any are found, reports them all, then asks the user once how to
        proceed (unless unresolved_parent is already 'label' or 'skip').

        Returns a dict {row_index: resolved_parent_id_or_None} and a set of
        row indices that are marked as orphans (needs-parent label).
        Rows keyed to None get no parent set.  Returns (None, None) if the
        caller should abort.
        """
        unresolvable = []   # (row_index_1based, title, raw_parent_id)
        distrusted   = 0
        for i, row in enumerate(rows, 1):
            pid = self._coerce_int(row.get("parent_id"), "parent_id", i, [])
            if pid is None or pid in file_ids:
                continue
            if pid in valid_epic_ids:
                if not cross_root:
                    continue
                distrusted += 1
            unresolvable.append((i, str(row.get("title", "")).strip(), pid))

        if distrusted:
            print(f"\n  NOTE: {distrusted} parent_id(s) match a live epic id on the "
                  f"target, but the file comes from a different root — raw ids "
                  f"are not trusted cross-root (they would attach to unrelated epics).")

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
                     group=None, create_missing=False, dest_group=None, on_existing="skip",
                     source_root=None, create_missing_groups=False, group_names=None,
                     on_missing_bv_field="create"):
        with self._group_override(group):
            return self._import_epics(input_path, unresolved_parent, dry_run, create_missing,
                                      dest_group, on_existing, source_root,
                                      create_missing_groups, group_names,
                                      on_missing_bv_field)

    def _import_epics(self, input_path=None, unresolved_parent="label", dry_run=False,
                      create_missing=False, dest_group=None, on_existing="skip",
                      source_root=None, create_missing_groups=False, group_names=None,
                      on_missing_bv_field="create"):
        """
        Import epics from a CSV or JSON file.

        Hierarchy: a parent_id that references another row in the file (by
        that row's own 'id' column) is resolved through the source_id→new_id
        map — parents are created first, so the exported tree is rebuilt on
        the target regardless of what ids exist there (#194). Cross-root
        imports never trust raw target-id matches.

        unresolved_parent controls what happens when a parent_id resolves
        neither within the file nor against the target hierarchy.  The check
        runs in the pre-flight pass — before any epic is created — so the
        user decides once and the import runs without interruption:

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
        if on_missing_bv_field not in ("create", "ignore", "fail"):
            print(f"ERROR: on_missing_bv_field must be 'create', 'ignore', or 'fail' "
                  f"(got '{on_missing_bv_field}')")
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

        # Business Value field (#196/#204) — resolved BEFORE the target root
        # can be created, so on_missing_bv_field=fail aborts with zero
        # mutations ('nothing was imported' must stay literally true, even
        # with create_missing on). The intended root path stands in for the
        # group object: custom fields live at the top-level group, which must
        # already exist. Under 'create' the field can therefore be minted
        # even when a later pre-flight check aborts the import — harmless, it
        # is exactly the field the retry needs. Dry runs only ever read.
        ns = getattr(self, "gitlab_namespace", None)
        intended_root = f"{ns}/{self.parent_group}" if ns else self.parent_group
        bv_ctx = self._resolve_import_bv_field(cleaned, intended_root,
                                               on_missing=on_missing_bv_field,
                                               dry_run=dry_run)
        if bv_ctx == "abort":
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

        # Cross-root reconciliation (#139): when a row's own group_path carries a
        # different (source) root, strip that root and re-resolve the structural
        # remainder under this target root. src_root comes from the source_root
        # override, else the export's stamp, else an LCP guess.
        src_root, src_trusted = self._infer_source_root(cleaned, "group_path", source_root)
        if src_root and src_root != root_group.full_path:
            print(f"  Reconciling source root '{src_root}' → '{root_group.full_path}' "
                  f"for unresolved paths")

        # ── Pre-flight: parent_id resolution ────────────────────────────────
        print("\n  Checking parent_ids against target hierarchy...")
        valid_epic_ids = self._build_valid_epic_ids(root_group)
        print(f"  {len(valid_epic_ids)} epic(s) in target hierarchy")

        # Within-file hierarchy (#194): the rows' own id column + parent_id
        # make the file self-describing. Parents in the file are created
        # first and children link through the source_id → new_id map, so the
        # exported tree is rebuilt even though none of the source ids exist
        # on the target. Cross-root, raw target-id matches are distrusted —
        # equal ids on different systems are coincidence, not links.
        row_of_file_id = self._map_file_ids(cleaned)
        # Distrust raw target-id parent matches ONLY when we positively know
        # the file came from a disjoint root: a trusted source root (explicit
        # override or export stamp) that neither equals, contains, nor sits
        # under the target root. An LCP-guessed root is exactly that — a
        # guess — and a same-system subtree export must keep resolving its
        # live parent ids (the guess would otherwise orphan them); overlapping
        # roots mean the same group tree, hence the same id space.
        tgt = root_group.full_path
        overlap = (
            src_root == tgt
            or (src_root or "").startswith(tgt + "/")
            or tgt.startswith((src_root or "") + "/")
        )
        cross_root = bool(src_root) and src_trusted and not overlap
        in_file_parents = sum(
            1 for i, r in enumerate(cleaned, 1)
            if row_of_file_id.get(
                self._coerce_int(r.get("parent_id"), "parent_id", i, []), i) != i
        )
        if in_file_parents:
            print(f"  {in_file_parents} row(s) reference parents within the file — "
                  f"importing parents first and remapping to their new ids")

        parent_map, orphan_rows = self._resolve_parent_ids(
            cleaned, valid_epic_ids, root_group, unresolved_parent,
            file_ids=frozenset(row_of_file_id), cross_root=cross_root,
        )

        ordered, _cycle_breaks = self._order_rows_for_import(cleaned, row_of_file_id)

        skip_rows = {r for r, resolved in parent_map.items() if resolved is None and r not in orphan_rows}

        print(f"\n  Ready — beginning import of {len(cleaned)} row(s)...")
        if skip_rows:
            print(f"  ({len(skip_rows)} row(s) will be skipped due to unresolvable parents)")
        if orphan_rows:
            print(f"  ({len(orphan_rows)} row(s) will receive 'import::needs-parent' label)")

        created = skipped = updated = failed = bv_missed = bv_dropped = 0
        orphan_summary = []   # (row_num, title, group_path, original_parent_id)
        id_map = {}           # source id → new/matched target id (#194)
        existing_cache = {}   # container id → {title: [epics]} — one list per container (#201)
        groups_created = set()   # full paths created (or planned, dry run) (#195)
        # Display names (#200) — only relevant when groups can be created.
        names_ctx = (self._load_group_names(group_names) if create_missing_groups
                     else {"groups": {}, "projects": {}})

        for i in ordered:
            row = cleaned[i - 1]
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
            bv          = self._coerce_int(row.get("business_value"), "business_value", i, [])
            state       = str(row.get("state", "")).strip().lower()
            # Placement precedence: (1) the row's own group_path when it resolves
            # directly under the target root (same-root import); (2) #139 relative
            # reconcile — strip the source root and re-resolve the structural path
            # under this target root (cross-enclave); (2b) #195 create the missing
            # subgroup chain for that structural path, when enabled and the source
            # root is TRUSTED (stamp/override — never the LCP guess, which could
            # mint a wrong tree); (3) #138 picked dest_group as the fallback when
            # structure can't be honored; (4) the target root — a valid epic
            # container (unlike issues, where a missing project has no root
            # fallback and the row is skipped).
            own = str(row.get("group_path", "")).strip()
            reconciled = (
                self._reconcile_path(own, src_root, root_group.full_path, group_cache,
                                     allow_root=src_trusted)
                if own and own not in group_cache else None
            )
            if own and own in group_cache:
                gpath = own
            elif reconciled:
                gpath = reconciled
            else:
                chain_rel = (
                    self._strip_source_root(own, src_root)
                    if create_missing_groups and own and src_trusted else None
                )
                if chain_rel:
                    grp = self._ensure_group_chain(
                        root_group, chain_rel, group_cache, dry_run, groups_created,
                        names=names_ctx["groups"])
                    gpath = grp.full_path
                elif dest_group:
                    gpath = dest_group
                else:
                    gpath = own or root_group.full_path

            target = group_cache.get(gpath)
            if not target:
                print(f"  row {i}: WARN group_path '{gpath}' not found — using root group")
                target = root_group

            # Resolved parent precedence (#194): ① another row in the file →
            # the id map (its NEW id — recorded on create, update, or
            # skip-as-existing); ② a live target id, same-root imports only;
            # ③ the pre-flight fallback/label decision. An in-file parent
            # that never materialized (failed create, cycle) degrades to the
            # needs-parent label at runtime rather than silently mis-linking.
            parent_row = row_of_file_id.get(orig_pid)
            runtime_orphan = False
            if parent_row is not None and parent_row != i:
                resolved_pid = id_map.get(orig_pid)
                if resolved_pid is None:
                    runtime_orphan = True
            elif orig_pid is not None and orig_pid in valid_epic_ids and not cross_root:
                resolved_pid = orig_pid
            else:
                resolved_pid = parent_map.get(i)  # fallback or None

            if runtime_orphan and unresolved_parent == "skip":
                # Honor the user's choice for parents that fell through at
                # runtime too (failed create, cycle break, skipped chain).
                print(f"  row {i}: {'[dry] ' if dry_run else ''}SKIP — in-file parent "
                      f"(id {orig_pid}) was not created")
                skipped += 1
                continue

            is_orphan = i in orphan_rows or runtime_orphan
            if is_orphan and "import::needs-parent" not in labels:
                labels = labels + ["import::needs-parent"]

            # This row's own source id — recorded into the id map once the
            # row materializes, so in-file children can link to it (#194).
            src_id = self._coerce_int(row.get("id"), "id", i, [])
            if src_id is not None and row_of_file_id.get(src_id) != i:
                src_id = None   # duplicate id — first occurrence owns the map slot

            # In a dry run, in-file parents resolve to a ("dry", row) sentinel
            # instead of a real id; it never reaches the API.
            symbolic = isinstance(resolved_pid, tuple)

            payload = {"title": title}
            if description:       payload["description"] = description
            if labels:            payload["labels"]      = labels
            if start_date:        payload["start_date"]  = start_date
            if due_date:          payload["end_date"]    = due_date
            if resolved_pid and not symbolic:
                payload["parent_id"] = resolved_pid

            # Re-import handling: match an existing epic by title in the target.
            existing = (self._find_epic_by_title(target, title, cache=existing_cache)
                        if on_existing != "create" else None)
            if existing and on_existing == "skip":
                print(f"  row {i}: {'[dry] ' if dry_run else ''}SKIP — epic '{title}' "
                      f"already exists (#{existing.iid} in {target.full_path})")
                if src_id is not None:
                    # existing.id is a real target id even under dry run, so
                    # children preview their concrete parent_id.
                    id_map[src_id] = existing.id
                skipped += 1
                continue

            if dry_run:
                action = "update" if (existing and on_existing == "update") else "create"
                parts = [f"'{title}'", f"group={target.full_path}", f"action={action}"]
                if existing:      parts.append(f"#{existing.iid}")
                if labels:        parts.append(f"labels={labels}")
                if weight:        parts.append(f"weight={weight}")
                if bv is not None: parts.append(f"bv={bv}")
                if symbolic:      parts.append(f"parent=(epic from row {resolved_pid[1]})")
                elif resolved_pid: parts.append(f"parent_id={resolved_pid}")
                if is_orphan:     parts.append("⚑ needs-parent")
                if start_date:    parts.append(f"start={start_date}")
                if due_date:      parts.append(f"due={due_date}")
                print(f"  [dry] row {i}: {' | '.join(parts)}")
                if src_id is not None:
                    id_map[src_id] = ("dry", i)
                if is_orphan:
                    orphan_summary.append((i, title, target.full_path, orig_pid))
                if action == "update":  updated += 1
                else:                   created += 1
                continue

            try:
                if existing and on_existing == "update":
                    self._update_epic(existing, payload, weight, state)
                    if bv is not None:
                        if bv_ctx:
                            if not self._import_set_bv(existing, bv, bv_ctx, i):
                                bv_missed += 1
                        else:
                            bv_dropped += 1
                    print(f"  row {i}: updated #{existing.iid} '{title}' → {target.full_path}")
                    if src_id is not None:
                        id_map[src_id] = existing.id
                    updated += 1
                else:
                    epic = target.epics.create(payload)
                    if weight is not None:
                        self._set_epic_weight(epic, weight)
                    if bv is not None:
                        if bv_ctx:
                            if not self._import_set_bv(epic, bv, bv_ctx, i):
                                bv_missed += 1
                        else:
                            bv_dropped += 1
                    if state == "closed":
                        epic.state_event = "close"
                        epic.save()
                    print(f"  row {i}: created #{epic.iid} '{title}' → {target.full_path}")
                    # Keep the existence cache truthful for intra-run
                    # duplicates: a later same-title row in this container
                    # must still see this epic (#201).
                    _tgt_titles = existing_cache.get(getattr(target, "id", None))
                    if _tgt_titles is not None:
                        _tgt_titles.setdefault(title, []).append(epic)
                    if src_id is not None:
                        id_map[src_id] = epic.id
                    created += 1
                if is_orphan:
                    orphan_summary.append((i, title, target.full_path, orig_pid))

            except Exception as ex:
                print(f"  row {i}: FAILED '{title}' — {ex}")
                failed += 1

        print(f"\n  Done — {created} created  |  {updated} updated  |  {skipped} skipped  |  {failed} failed"
              + ("  (dry run — no changes made)" if dry_run else ""))
        if bv_missed:
            print(f"  WARN: {bv_missed} business_value value(s) could not be set "
                  f"(see row WARNs above) — transient GraphQL failures can be "
                  f"retried by re-importing the affected rows with on_existing=update")
        if bv_dropped:
            print(f"  WARN: {bv_dropped} business_value value(s) dropped — the "
                  f"Business Value field is missing on the target (see WARN "
                  f"above). Create it (setup-bv-field, or on_missing_bv_field="
                  f"create), then re-import with on_existing=update to backfill.")
        if groups_created:
            verb = "would be created" if dry_run else "created"
            print(f"  {len(groups_created)} missing subgroup(s) {verb} along "
                  f"reconciled paths (create-missing-groups)")

        # Paired import (#197): persist the source_id → new id map so a
        # following issues import can resolve its epic_id references to the
        # epics just created here. Real ids only — dry sentinels excluded.
        real_map = {str(k): v for k, v in id_map.items() if isinstance(v, int)}
        if real_map and not dry_run:
            try:
                map_path = self._default_export_name("epic-id-map", "json")
                map_path.write_text(json.dumps(real_map, indent=2), encoding="utf-8")
                print(f"  Epic id map (source id → new id): {map_path}")
                url = self._export_url(map_path)
                if url:
                    print(f"  Download: {url}   — pass to import-issues as 'Epic id map file'")
            except Exception as ex:
                # The map is a convenience artifact — its failure must never
                # taint an import that already succeeded.
                print(f"  WARN: could not write the epic id map — {ex}")

        if orphan_summary:
            print(f"\n  ── Orphan summary ({len(orphan_summary)} epic(s) created without intended parent) ──")
            print(f"  {'Row':<5} {'Original parent_id':<20} {'Group':<35} Title")
            print(f"  {'─'*5} {'─'*20} {'─'*35} {'─'*30}")
            for row_num, etitle, gpath, orig_pid in orphan_summary:
                print(f"  {row_num:<5} {str(orig_pid):<20} {gpath[:35]:<35} {etitle[:50]}")
            print(f"\n  Filter by label 'import::needs-parent' in GitLab to find and re-parent these epics.")

        # The id map is also the success signal (#206): every abort path above
        # returns None, so a dict — possibly empty under dry run — means the
        # import ran. import_bundle threads it straight into the issues/links
        # phases without a file round-trip.
        return real_map

    # ── Issue → epic link resolution (#197) ───────────────────────────────────

    def _load_epic_id_map(self, path_str):
        """Load a paired-import id map ({source epic id: new target id}).

        Produced by a preceding epics import. Also accepts the map itself as a
        dict (#206: import_bundle threads the in-memory map returned by
        _import_epics). Returns {} on any problem, with a WARN — a bad map
        degrades to title/raw-id resolution, never aborts.
        """
        if not path_str:
            return {}
        if isinstance(path_str, dict):
            try:
                return {str(k): int(v) for k, v in path_str.items()}
            except (TypeError, ValueError) as ex:
                print(f"  WARN: in-memory epic id map is malformed ({ex}) — "
                      f"falling back to title/raw-id resolution.")
                return {}
        path = self._resolve_path(path_str)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {str(k): int(v) for k, v in data.items()}
        except Exception as ex:
            print(f"  WARN: epic id map '{path}' could not be loaded ({ex}) — "
                  f"falling back to title/raw-id resolution.")
            return {}

    def _target_epic_titles(self, root_group):
        """Return {title: [epic ids]} for every epic under the target root."""
        titles = {}
        try:
            for ep in root_group.epics.list(all=True):
                titles.setdefault(getattr(ep, "title", ""), []).append(ep.id)
        except Exception as ex:
            print(f"  WARN: could not list target epics for title resolution — {ex}")
        return titles

    def _resolve_issue_epic(self, epic_id, epic_title, id_map, epic_titles,
                            same_root, row_num):
        """Resolve a row's epic reference to a TARGET epic id, or None.

        Precedence: ① the paired-import id map (source id → new id);
        ② exact epic_title match among the target's epics (first wins,
        ambiguity WARNs); ③ the raw id — same-root imports only, since an
        equal id on a different system is coincidence and linking to it
        would attach the issue to an unrelated epic. An unresolvable
        reference WARNs and the link is dropped (the issue still imports).
        """
        if epic_id is not None and str(epic_id) in id_map:
            return id_map[str(epic_id)]
        if epic_title and epic_titles is not None:
            hits = epic_titles.get(epic_title, [])
            if len(hits) > 1:
                print(f"  row {row_num}: WARN {len(hits)} target epics titled "
                      f"'{epic_title}' — using the first")
            if hits:
                return hits[0]
        if epic_id is not None and same_root:
            return epic_id
        if epic_id is not None or epic_title:
            print(f"  row {row_num}: WARN epic link dropped — "
                  f"'{epic_title or epic_id}' matches no target epic "
                  f"(cross-root raw ids are not trusted)")
        return None

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
                "source_root":  group.full_path,
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
                "epic_title":   epic_attr.get("title", ""),
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
        self._write_group_names_sidecar(group, path)

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

    def _ensure_project(self, root_group, rel, group_cache, project_cache,
                        dry_run, planned, names=None):
        """Create (or, under dry run, plan) the project for ``rel`` (#198).

        ``rel`` is a source-relative project path: the last segment is the
        project slug, everything before it the subgroup chain — created via
        _ensure_group_chain under the same trusted-root guardrail. Returns
        the (created/stubbed) project, cached so later rows reuse it.
        """
        class _Planned:
            def __init__(self, pwn):
                self.path_with_namespace = pwn
                self.id = None

        names = names or {}
        rel = rel.strip("/")
        group_rel, _, proj_slug = rel.rpartition("/")
        parent = (self._ensure_group_chain(root_group, group_rel, group_cache,
                                           dry_run, planned,
                                           names=names.get("groups"))
                  if group_rel else root_group)
        pwn = f"{root_group.full_path}/{rel}"
        display = (names.get("projects") or {}).get(rel, proj_slug)
        note = f" (name '{display}')" if display != proj_slug else ""
        if dry_run:
            if pwn not in planned:
                planned.add(pwn)
                print(f"  [dry] would create project '{pwn}'{note}")
            proj = _Planned(pwn)
        else:
            proj = self.gl.projects.create({
                "name": display, "path": proj_slug, "namespace_id": parent.id,
            })
            planned.add(pwn)
            print(f"  created project '{pwn}'{note}")
        project_cache[pwn] = proj
        return proj

    def import_issues(self, input_path=None, target_project_path=None, dry_run=False,
                      group=None, create_missing=False, on_existing="skip",
                      source_root=None, epic_id_map=None, create_missing_projects=False,
                      group_names=None):
        with self._group_override(group):
            return self._import_issues(input_path, target_project_path, dry_run,
                                       create_missing, on_existing, source_root,
                                       epic_id_map, create_missing_projects, group_names)

    def _import_issues(self, input_path=None, target_project_path=None, dry_run=False,
                       create_missing=False, on_existing="skip", source_root=None,
                       epic_id_map=None, create_missing_projects=False, group_names=None):
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

        # Cross-root reconciliation (#139): strip the source root from each row's
        # own project_path and re-resolve the structural remainder under this
        # target root's projects. src_root: override, else stamp, else LCP guess.
        src_root, src_trusted = self._infer_source_root(cleaned, "project_path", source_root)
        if src_root and src_root != root_group.full_path:
            print(f"  Reconciling source root '{src_root}' → '{root_group.full_path}' "
                  f"for unresolved paths")

        # Epic link resolution context (#197). same_root mirrors the epics
        # importer's cross-root rule: raw epic ids are only trusted when the
        # file does NOT positively come from a disjoint root (trusted stamp/
        # override naming a non-overlapping tree).
        tgt = root_group.full_path
        overlap = (
            src_root == tgt
            or (src_root or "").startswith(tgt + "/")
            or tgt.startswith((src_root or "") + "/")
        )
        same_root = not (bool(src_root) and src_trusted and not overlap)
        id_map = self._load_epic_id_map(epic_id_map)
        # Target epic titles: one listing, only when some row needs title or
        # cross-root resolution (i.e. the id map alone can't settle it).
        _needs_titles = any(
            str(r.get("epic_title", "")).strip()
            or (not same_root and str(r.get("epic_id", "")).strip() not in ("", "None", "none"))
            for r in cleaned
        )
        epic_titles = self._target_epic_titles(root_group) if _needs_titles else {}

        # Username → user ID cache (populated on demand)
        username_cache = {}
        existing_cache = {}   # project id → {title: [issues]} — one list per project (#201)

        created = skipped = updated = failed = 0
        projects_created = set()   # paths created (or planned, dry run) (#198)
        group_cache = None         # built lazily, only when creating projects
        # Display names (#200) — only relevant when containers can be created.
        names_ctx = (self._load_group_names(group_names) if create_missing_projects
                     else {"groups": {}, "projects": {}})

        for i, row in enumerate(cleaned, 1):
            title       = str(row.get("title", "")).strip()
            description = str(row.get("description", "")).strip()
            labels      = self._coerce_labels(row.get("labels"))
            weight      = self._coerce_int(row.get("weight"),   "weight",  i, [])
            due_date    = self._coerce_date(row.get("due_date"), "due_date", i, [])
            milestone   = str(row.get("milestone", "")).strip()
            assignees   = self._coerce_usernames(row.get("assignees"))
            src_epic_id = self._coerce_int(row.get("epic_id"),  "epic_id", i, [])
            epic_title  = str(row.get("epic_title", "")).strip()
            epic_id     = self._resolve_issue_epic(
                src_epic_id, epic_title, id_map, epic_titles, same_root, i)
            state       = str(row.get("state", "")).strip().lower()
            # Placement precedence: (1) own project_path when it resolves directly
            # (same-root); (2) #139 relative reconcile under this target root
            # (cross-enclave); (3) #138 picked target_project_path as the fallback;
            # (4) skip — issues have no root fallback, so an unresolvable row with
            # no destination is dropped. (3b, #198): with create_missing_projects
            # and a TRUSTED source root, the missing group chain + project are
            # created along the reconciled path instead of falling back.
            own = str(row.get("project_path", "")).strip()
            reconciled = (
                self._reconcile_path(own, src_root, root_group.full_path, project_cache,
                                     allow_root=src_trusted)
                if own and own not in project_cache else None
            )
            if own and own in project_cache:
                ppath = own
            elif reconciled:
                ppath = reconciled
            else:
                proj_rel = (
                    self._strip_source_root(own, src_root)
                    if create_missing_projects and own and src_trusted else None
                )
                if proj_rel:
                    if group_cache is None:
                        group_cache = self._build_group_cache(root_group)
                    try:
                        proj = self._ensure_project(
                            root_group, proj_rel, group_cache, project_cache,
                            dry_run, projects_created, names=names_ctx)
                        ppath = proj.path_with_namespace
                    except Exception as ex:
                        print(f"  row {i}: FAILED — could not create container "
                              f"for '{own}' — {ex}")
                        failed += 1
                        continue
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
            if milestone and not hasattr(project, "milestones"):
                # A planned (dry-run) project stub — the milestone can only
                # resolve once the project exists.
                print(f"  row {i}: [dry] milestone '{milestone}' will resolve "
                      f"after the project is created")
            elif milestone:
                try:
                    ms_list = project.milestones.list(
                        search=milestone, include_ancestors=True, all=True)
                except Exception:
                    try:
                        ms_list = project.milestones.list(search=milestone)
                    except Exception:
                        ms_list = []
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
            existing = (self._find_issue_by_title(project, title, cache=existing_cache)
                        if on_existing != "create" else None)
            if existing and on_existing == "skip":
                print(f"  row {i}: {'[dry] ' if dry_run else ''}SKIP — issue '{title}' "
                      f"already exists (#{existing.iid} in {ppath})")
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
                _prj_titles = existing_cache.get(getattr(project, "id", None))
                if _prj_titles is not None:
                    _prj_titles.setdefault(title, []).append(issue)
                created += 1
            except Exception as ex:
                print(f"  row {i}: FAILED '{title}' — {ex}")
                failed += 1

        print(f"\n  Done — {created} created  |  {updated} updated  |  {skipped} skipped  |  {failed} failed"
              + ("  (dry run — no changes made)" if dry_run else ""))
        if projects_created:
            verb = "would be created" if dry_run else "created"
            print(f"  {len(projects_created)} missing container(s) {verb} along "
                  f"reconciled paths (create-missing-projects)")

    # ── Blocking-link export / import (#198) ───────────────────────────────────

    _LINK_EPIC_ISSUE_BLOCKERS_QUERY = """
    query($path: ID!, $cursor: String) {
      group(fullPath: $path) {
        workItems(types: [EPIC], includeDescendants: true, first: 100, after: $cursor) {
          pageInfo { hasNextPage endCursor }
          nodes {
            id iid title
            namespace { fullPath }
            widgets {
              ... on WorkItemWidgetLinkedItems {
                linkedItems(first: 100) {
                  pageInfo { hasNextPage }
                  nodes {
                    linkType
                    workItem {
                      id iid title
                      namespace { fullPath }
                      workItemType { name }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }"""

    _LINK_ISSUE_FLAG_QUERY = """
    query($path: ID!, $cursor: String) {
      group(fullPath: $path) {
        issues(includeSubgroups: true, first: 100, after: $cursor) {
          pageInfo { hasNextPage endCursor }
          nodes { iid title blocked blockedByCount projectId }
        }
      }
    }"""

    def export_links(self, output_path=None, group=None, fmt="csv"):
        with self._group_override(group):
            return self._export_links(output_path, fmt)

    def _export_links(self, output_path=None, fmt="csv"):
        """Export every is_blocked_by relationship under the group (#198).

        Three kinds, one row each (source is_blocked_by target):
        epic ← epic (REST related_epics), issue ← issue (bulk GraphQL flag +
        REST links for flagged issues only), and epic ← Issue (the cross-type
        work-items links invisible to both REST graphs, #177). Containers are
        exported as full paths so import can reconcile them structurally.
        """
        group = self.get_group_by_name(self.parent_group)
        if not group:
            print(f"ERROR: group '{self.parent_group}' not found.")
            return

        if output_path:
            path = self._resolve_path(output_path)
            fmt  = self._detect_format(path)
        else:
            fmt  = "json" if str(fmt).lower() == "json" else "csv"
            path = self._default_export_name("links-export", fmt)

        print(f"\nExporting blocking links from '{group.full_path}'...")
        session = self._make_session()
        gid_map = self._build_gid_path_map(group)
        rows    = []

        def _row(src_t, src, src_container, tgt_t, tgt, tgt_container):
            rows.append({
                "link_type":        "is_blocked_by",
                "source_type":      src_t,
                "source_id":        src.get("id", ""),
                "source_iid":       src.get("iid", ""),
                "source_title":     src.get("title", ""),
                "source_container": src_container,
                "target_type":      tgt_t,
                "target_id":        tgt.get("id", ""),
                "target_iid":       tgt.get("iid", ""),
                "target_title":     tgt.get("title", ""),
                "target_container": tgt_container,
                "source_root":      group.full_path,
            })

        # ── epic ← epic (REST) ────────────────────────────────────────────
        print("  Collecting epic blocking links...")
        # (container path, iid) → legacy REST epic id, so cross-type rows can
        # carry the SAME id space the paired-import id map is keyed on.
        legacy_epic_id = {}
        for epic in group.epics.list(all=True):
            grp_id = getattr(epic, "group_id", None)
            legacy_epic_id[(gid_map.get(grp_id, ""), epic.iid)] = epic.id
            url = f"{self.url}/api/v4/groups/{grp_id}/epics/{epic.iid}/related_epics"
            try:
                resp = session.get(url)
                if not resp.ok:
                    continue
                for rel in resp.json():
                    if rel.get("link_type") != "is_blocked_by":
                        continue
                    _row("Epic",
                         {"id": epic.id, "iid": epic.iid, "title": epic.title},
                         gid_map.get(grp_id, ""),
                         "Epic",
                         {"id": rel.get("id"), "iid": rel.get("iid"),
                          "title": rel.get("title")},
                         gid_map.get(rel.get("group_id"), ""))
            except Exception as ex:
                print(f"  WARN: related_epics fetch failed for #{epic.iid} — {ex}")
        n_epic = len(rows)
        print(f"    {n_epic} epic←epic link(s)")

        # ── epic ← Issue (work-items GraphQL, #177) ───────────────────────
        print("  Collecting cross-type (epic←issue) blocking links...")
        cursor = None
        try:
            while True:
                data = self.graphql_query(
                    self._LINK_EPIC_ISSUE_BLOCKERS_QUERY,
                    variables={"path": group.full_path, "cursor": cursor}, retries=1)
                conn = ((data or {}).get("group") or {}).get("workItems") or {}
                for node in conn.get("nodes", []):
                    for widget in node.get("widgets", []):
                        _li_conn = (widget or {}).get("linkedItems") or {}
                        if (_li_conn.get("pageInfo") or {}).get("hasNextPage"):
                            print(f"  WARN: epic #{node.get('iid')} has more than "
                                  f"100 linked items — some links may be missing")
                        for li in _li_conn.get("nodes", []):
                            wi = li.get("workItem") or {}
                            if (li.get("linkType") != "is_blocked_by"
                                    or (wi.get("workItemType") or {}).get("name") != "Issue"):
                                continue
                            ns_path = (node.get("namespace") or {}).get("fullPath", "")
                            _row("Epic",
                                 {"id": legacy_epic_id.get((ns_path, node.get("iid"))),
                                  "iid": node.get("iid"),
                                  "title": node.get("title")},
                                 ns_path,
                                 "Issue",
                                 {"id": _gid_int(wi.get("id")), "iid": wi.get("iid"),
                                  "title": wi.get("title")},
                                 (wi.get("namespace") or {}).get("fullPath", ""))
                page = conn.get("pageInfo") or {}
                if not page.get("hasNextPage"):
                    break
                cursor = page.get("endCursor")
        except Exception as ex:
            print(f"  WARN: cross-type link pass failed — {ex}")
        n_cross = len(rows) - n_epic
        print(f"    {n_cross} epic←issue link(s)")

        # ── issue ← issue (bulk flag + REST links) ────────────────────────
        print("  Collecting issue blocking links...")
        pid_map = self._build_pid_path_map(group)
        flagged = []
        cursor = None
        try:
            while True:
                data = self.graphql_query(
                    self._LINK_ISSUE_FLAG_QUERY,
                    variables={"path": group.full_path, "cursor": cursor}, retries=1)
                conn = ((data or {}).get("group") or {}).get("issues") or {}
                for n in conn.get("nodes", []):
                    if n.get("blocked") or (n.get("blockedByCount") or 0) > 0:
                        flagged.append(n)
                page = conn.get("pageInfo") or {}
                if not page.get("hasNextPage"):
                    break
                cursor = page.get("endCursor")
        except Exception as ex:
            print(f"  WARN: issue flag pass failed — {ex}")
        for n in flagged:
            pid = _gid_int(n.get("projectId")) or n.get("projectId")
            url = f"{self.url}/api/v4/projects/{pid}/issues/{n.get('iid')}/links"
            try:
                resp = session.get(url)
                if not resp.ok:
                    continue
                for link in resp.json():
                    if link.get("link_type") != "is_blocked_by":
                        continue
                    _row("Issue",
                         {"id": None, "iid": n.get("iid"),
                          "title": n.get("title", "")},
                         pid_map.get(int(pid), "") if pid else "",
                         "Issue",
                         {"id": link.get("id"), "iid": link.get("iid"),
                          "title": link.get("title")},
                         pid_map.get(link.get("project_id"), ""))
            except Exception as ex:
                print(f"  WARN: issue links fetch failed for #{n.get('iid')} — {ex}")
        print(f"    {len(rows) - n_epic - n_cross} issue←issue link(s)")

        if not rows:
            print("  No blocking links found — nothing written.")
            return

        # Flag endpoints outside the exported tree up front (#202): the blocker
        # side of a link can live in another hierarchy (e.g. a stale link into a
        # deletion-scheduled group). Such rows have no counterpart on a target
        # system, so import-links will drop them — make that predictable at
        # export time instead of a surprise WARN mid-import.
        root_path = group.full_path

        def _external(container):
            return self._container_external(container, root_path)

        external = [r for r in rows
                    if _external(r["source_container"]) or _external(r["target_container"])]
        if external:
            print(f"  WARN: {len(external)} link(s) reference an endpoint outside "
                  f"'{root_path}' — a cross-system import will drop them "
                  f"(no counterpart exists on the target):")
            for r in external[:20]:
                ext = (r["target_container"] if _external(r["target_container"])
                       else r["source_container"]) or "unknown group"
                print(f"    {r['source_type']} '{r['source_title']}' ←blocked by← "
                      f"{r['target_type']} '{r['target_title']}'  (external: {ext})")
            if len(external) > 20:
                print(f"    … and {len(external) - 20} more")

        self._write_file(path, fmt, rows, LINK_EXPORT_FIELDS)
        print(f"  Exported {len(rows)} link(s) → {path}")
        url = self._export_url(path)
        if url:
            print(f"  Download: {url}")

    def import_links(self, input_path=None, group=None, epic_id_map=None,
                     source_root=None, dry_run=False):
        with self._group_override(group):
            return self._import_links(input_path, epic_id_map, source_root, dry_run)

    def _import_links(self, input_path=None, epic_id_map=None, source_root=None,
                      dry_run=False):
        """Recreate exported is_blocked_by links on the target (#198).

        Endpoints resolve like the issue→epic links (#197): epics via the
        paired-import id map, then exact title; issues via the reconciled
        project path + exact title. Raw source ids are never used to address
        target objects. Existing links are skipped (409/422), unresolvable
        endpoints WARN and drop the link — never mis-link.
        """
        if not input_path:
            print("ERROR: input_path is required.")
            return
        path = self._resolve_path(input_path)
        if not path.exists():
            print(f"ERROR: file not found: '{path}'")
            return

        print(f"\nImporting blocking links from '{path}'"
              + ("  [DRY RUN]" if dry_run else ""))
        rows = self._load_file(path)
        if rows is None:
            return
        if not rows:
            print("  File is empty — nothing to import.")
            return
        columns = set(rows[0].keys())
        if not {"source_type", "target_type"} <= columns:
            print("  INVALID: this does not look like a links export "
                  "(missing source_type/target_type columns).")
            return
        print(f"  {len(rows)} link record(s) in file")

        root_group = self.get_group_by_name(self.parent_group)
        if root_group is None:
            print(f"ERROR: target group '{self.parent_group}' not found.")
            return

        id_map = self._load_epic_id_map(epic_id_map)
        src_root, _trusted = self._infer_source_root(rows, "source_container", source_root)

        print("  Building target lookups...")
        epic_by_id, epic_titles = {}, {}
        for ep in root_group.epics.list(all=True):
            epic_by_id[ep.id] = ep
            epic_titles.setdefault(getattr(ep, "title", ""), []).append(ep)
        project_cache = self._build_project_cache(root_group)
        session = self._make_session()

        def _epic_end(ref_id, title, row_num):
            if ref_id is not None and str(ref_id) in id_map:
                ep = epic_by_id.get(id_map[str(ref_id)])
                if ep is not None:
                    return ep
            hits = epic_titles.get(title, [])
            if len(hits) > 1:
                print(f"  row {row_num}: WARN {len(hits)} target epics titled "
                      f"'{title}' — using the first")
            return hits[0] if hits else None

        _issue_title_cache = {}   # one issues listing per project (#201)

        def _issue_end(container, title, iid, row_num):
            ppath = container if container in project_cache else (
                self._reconcile_path(container, src_root, root_group.full_path,
                                     project_cache, allow_root=False))
            proj = project_cache.get(ppath) if ppath else None
            if proj is None:
                return None, None
            if title:
                return self._find_issue_by_title(proj, title,
                                                 cache=_issue_title_cache), proj
            # No title (a legacy titleless export) — iids on a re-imported
            # project are NOT stable (skips/failures/pre-existing issues all
            # shift them), so addressing by iid could silently link the wrong
            # issue. Drop instead; re-export with a current build to fix.
            return None, proj

        created = skipped = dropped = failed = 0
        for i, row in enumerate(rows, 1):
            s_type = str(row.get("source_type", "")).strip()
            t_type = str(row.get("target_type", "")).strip()
            s_id   = self._coerce_int(row.get("source_id"), "source_id", i, [])
            t_id   = self._coerce_int(row.get("target_id"), "target_id", i, [])
            s_iid  = self._coerce_int(row.get("source_iid"), "source_iid", i, [])
            t_iid  = self._coerce_int(row.get("target_iid"), "target_iid", i, [])
            s_title = str(row.get("source_title", "")).strip()
            t_title = str(row.get("target_title", "")).strip()
            s_cont  = str(row.get("source_container", "")).strip()
            t_cont  = str(row.get("target_container", "")).strip()

            label = f"{s_type} '{s_title or s_iid}' ←blocked by← {t_type} '{t_title or t_iid}'"

            if s_type == "Epic":
                src = _epic_end(s_id, s_title, i)
            else:
                src, _sp = _issue_end(s_cont, s_title, s_iid, i)
            if t_type == "Epic":
                tgt = _epic_end(t_id, t_title, i)
            else:
                tgt, _tp = _issue_end(t_cont, t_title, t_iid, i)

            if src is None or tgt is None:
                print(f"  row {i}: WARN link dropped — "
                      f"{'source' if src is None else 'target'} not found on "
                      f"target ({label})")
                dropped += 1
                continue

            if dry_run:
                print(f"  [dry] row {i}: would link {label}")
                created += 1
                continue

            try:
                if s_type == "Epic" and t_type == "Epic":
                    url = (f"{self.url}/api/v4/groups/{src.group_id}"
                           f"/epics/{src.iid}/related_epics")
                    resp = session.post(url, json={
                        "target_group_id": tgt.group_id,
                        "target_epic_iid": tgt.iid,
                        "link_type": "is_blocked_by",
                    })
                elif s_type == "Issue" and t_type == "Issue":
                    url = (f"{self.url}/api/v4/projects/{src.project_id}"
                           f"/issues/{src.iid}/links")
                    resp = session.post(url, json={
                        "target_project_id": tgt.project_id,
                        "target_issue_iid": tgt.iid,
                        "link_type": "is_blocked_by",
                    })
                else:
                    # Cross-type (epic ← Issue, #177): only expressible via the
                    # work-items GraphQL mutation.
                    src_wid = getattr(src, "work_item_id", None)
                    if not src_wid:
                        # A legacy epic id is NOT in the WorkItem id space —
                        # guessing would address a different work item.
                        print(f"  row {i}: FAILED {label} — epic has no "
                              f"work_item_id (cross-type links need it)")
                        failed += 1
                        continue
                    mutation = """
                    mutation($id: WorkItemID!, $items: [WorkItemID!]!) {
                      workItemAddLinkedItems(input: {
                        id: $id, workItemsIds: $items, linkType: BLOCKED_BY
                      }) { errors }
                    }"""
                    data = self.graphql_query(mutation, variables={
                        "id": f"gid://gitlab/WorkItem/{src_wid}",
                        "items": [f"gid://gitlab/WorkItem/{tgt.id}"],
                    })
                    errors = ((data or {}).get("workItemAddLinkedItems") or {}).get("errors") or []
                    if errors and any("already" in str(e).lower() for e in errors):
                        print(f"  row {i}: SKIP (exists) {label}")
                        skipped += 1
                    elif errors:
                        print(f"  row {i}: FAILED {label} — {errors}")
                        failed += 1
                    else:
                        print(f"  row {i}: linked {label}")
                        created += 1
                    continue

                if resp.status_code in (200, 201):
                    print(f"  row {i}: linked {label}")
                    created += 1
                elif resp.status_code in (409, 422):
                    print(f"  row {i}: SKIP (exists) {label}")
                    skipped += 1
                else:
                    print(f"  row {i}: FAILED [{resp.status_code}] {label} — "
                          f"{resp.text[:100]}")
                    failed += 1
            except Exception as ex:
                print(f"  row {i}: FAILED {label} — {ex}")
                failed += 1

        print(f"\n  Done — {created} linked  |  {skipped} already existed  |  "
              f"{dropped} dropped (unresolved)  |  {failed} failed"
              + ("  (dry run — no changes made)" if dry_run else ""))

    # ── Transfer bundle (#206) ─────────────────────────────────────────────────
    #
    # One artifact, one action in each direction: export-bundle zips the three
    # exports plus a merged group-names sidecar and a manifest; import-bundle
    # unpacks it on an isolated system and runs the proven sequence — epics
    # (id map captured in-memory) → issues → links — creating the group /
    # project containers along the way.

    BUNDLE_FORMAT  = "nce-bundle"
    BUNDLE_VERSION = 1

    @staticmethod
    def _container_external(container, root_path):
        """True when a link endpoint's container lies outside ``root_path``.

        Shared by the export-time WARN (#202) and the bundle manifest's
        external_links count so the two can never drift. Segment-aware:
        ``ns/source-old`` is not inside ``ns/source``.
        """
        return not (container == root_path
                    or str(container).startswith(root_path + "/"))

    def export_bundle(self, output_path=None, group=None):
        with self._group_override(group):
            return self._export_bundle(output_path)

    def _export_bundle(self, output_path=None):
        import shutil
        import tempfile
        import zipfile

        group = self.get_group_by_name(self.parent_group)
        if not group:
            print(f"ERROR: group '{self.parent_group}' not found.")
            return

        print(f"\nExporting transfer bundle from '{group.full_path}'...")
        tmp = Path(tempfile.mkdtemp(prefix="nce-bundle-"))
        try:
            epics_p  = tmp / "epics.csv"
            issues_p = tmp / "issues.csv"
            links_p  = tmp / "links.csv"

            self._export_epics(output_path=str(epics_p))
            self._export_issues(output_path=str(issues_p))
            self._export_links(output_path=str(links_p))

            if not epics_p.exists() and not issues_p.exists():
                print("ERROR: bundle aborted — neither the epics nor the issues "
                      "export produced a file (see messages above).")
                return

            # Merge the two sidecars (#200) into one names file both importers
            # can consume: the issues sidecar carries groups AND projects, the
            # epics one groups only — the union covers every container.
            names = {"groups": {}, "projects": {}}
            for export_p in (epics_p, issues_p):
                sidecar = export_p.with_name(export_p.stem + "-group-names.json")
                if sidecar.exists():
                    part = self._load_group_names(str(sidecar))
                    names["groups"].update(part["groups"])
                    names["projects"].update(part["projects"])
            names_p = None
            if names["groups"] or names["projects"]:
                names_p = tmp / "group-names.json"
                names_p.write_text(json.dumps(names, indent=2), encoding="utf-8")

            def _rows(p):
                if not p.exists():
                    return []
                with p.open(newline="", encoding="utf-8") as f:
                    return list(csv.DictReader(f))

            link_rows = _rows(links_p)
            root_path = group.full_path
            external_links = sum(
                1 for r in link_rows
                if self._container_external(r.get("source_container", ""), root_path)
                or self._container_external(r.get("target_container", ""), root_path))

            manifest = {
                "format":         self.BUNDLE_FORMAT,
                "format_version": self.BUNDLE_VERSION,
                "created_at":     datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source_root":    root_path,
                "files": {
                    **({"epics": epics_p.name} if epics_p.exists() else {}),
                    **({"issues": issues_p.name} if issues_p.exists() else {}),
                    **({"links": links_p.name} if links_p.exists() else {}),
                    **({"group_names": names_p.name} if names_p else {}),
                },
                "counts": {
                    "epics":          len(_rows(epics_p)),
                    "issues":         len(_rows(issues_p)),
                    "links":          len(link_rows),
                    "external_links": external_links,
                },
            }
            manifest_p = tmp / "manifest.json"
            manifest_p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            if output_path:
                zip_path = self._resolve_path(output_path)
            else:
                zip_path = self._default_export_name("bundle-export", "zip")
            members = [p for p in (epics_p, issues_p, links_p) if p.exists()]
            members.append(manifest_p)
            if names_p:
                members.append(names_p)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for m in members:
                    zf.write(m, arcname=m.name)

            c = manifest["counts"]
            print(f"\n  Bundle: {c['epics']} epic(s), {c['issues']} issue(s), "
                  f"{c['links']} link(s)"
                  + (f" ({c['external_links']} with external endpoints — "
                     f"dropped on a cross-system import)" if c["external_links"] else ""))
            print(f"  Exported bundle → {zip_path}")
            url = self._export_url(zip_path)
            if url:
                print(f"  Download: {url}")
            return zip_path
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def import_bundle(self, input_path=None, group=None, create_missing=True,
                      on_existing="skip", on_missing_bv_field="create",
                      dry_run=False):
        with self._group_override(group):
            return self._import_bundle(input_path, create_missing, on_existing,
                                       on_missing_bv_field, dry_run)

    def _import_bundle(self, input_path=None, create_missing=True,
                       on_existing="skip", on_missing_bv_field="create",
                       dry_run=False):
        """Import a transfer bundle: containers, epics, issues, links (#206).

        Runs the proven sequence with transfer-tuned defaults — containers are
        created along reconciled paths (still gated on the bundle's trusted
        source_root stamp) and the epic id map is threaded in-memory between
        the phases. on_existing=skip makes a partially-failed bundle
        recoverable by simply re-running it (all phases are idempotent).
        """
        import shutil
        import tempfile
        import zipfile

        if not input_path:
            print("ERROR: input_path is required.")
            return
        path = self._resolve_path(input_path)
        if not path.exists():
            print(f"ERROR: file not found: '{path}'")
            return
        if not zipfile.is_zipfile(path):
            print(f"INVALID: '{path.name}' is not a zip file — expected a "
                  f"bundle produced by export-bundle.")
            return

        tmp = Path(tempfile.mkdtemp(prefix="nce-bundle-"))
        try:
            with zipfile.ZipFile(path) as zf:
                for m in zf.namelist():
                    # Bundles are flat by construction; a nested or absolute
                    # member means this isn't ours (and guards zip-slip).
                    if m != Path(m).name:
                        print(f"INVALID: unexpected member path '{m}' — not a "
                              f"bundle produced by export-bundle.")
                        return
                zf.extractall(tmp)

            manifest_p = tmp / "manifest.json"
            if not manifest_p.exists():
                print("INVALID: bundle has no manifest.json — not a bundle "
                      "produced by export-bundle.")
                return
            try:
                manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
            except Exception as ex:
                print(f"INVALID: manifest.json could not be parsed ({ex}).")
                return
            if manifest.get("format") != self.BUNDLE_FORMAT:
                print(f"INVALID: manifest format is "
                      f"'{manifest.get('format')}', expected "
                      f"'{self.BUNDLE_FORMAT}'.")
                return
            try:
                version = int(manifest.get("format_version", 0))
            except (TypeError, ValueError):
                print(f"INVALID: bundle format_version "
                      f"{manifest.get('format_version')!r} is not a number.")
                return
            if version > self.BUNDLE_VERSION:
                print(f"INVALID: bundle format_version {version} is newer than "
                      f"this tool supports ({self.BUNDLE_VERSION}) — update the "
                      f"simulator.")
                return

            # Epics-only and issues-only hierarchies are legitimate bundles
            # (a subtree can have no projects, or no epics) — require at least
            # one of the two, and every file the manifest names must exist.
            files = manifest.get("files") or {}
            if not files.get("epics") and not files.get("issues"):
                print("INVALID: bundle contains neither an epics nor an "
                      "issues file.")
                return
            for role in ("epics", "issues", "links", "group_names"):
                fn = files.get(role)
                if fn and not (tmp / fn).exists():
                    print(f"INVALID: bundle is missing its {role} file "
                          f"('{fn}' named in the manifest but absent).")
                    return

            c = manifest.get("counts") or {}
            print(f"\nImporting bundle '{path.name}'"
                  + ("  [DRY RUN]" if dry_run else ""))
            print(f"  source: {manifest.get('source_root', '?')}  "
                  f"({c.get('epics', '?')} epics, {c.get('issues', '?')} issues, "
                  f"{c.get('links', '?')} links)")
            if c.get("external_links"):
                print(f"  note: {c['external_links']} link(s) have endpoints "
                      f"outside the source tree and will be dropped.")

            names_fn = files.get("group_names")
            names_path = str(tmp / names_fn) if names_fn and (tmp / names_fn).exists() else None

            if files.get("epics"):
                print(f"\n── Phase 1/3: epics ──")
                id_map = self._import_epics(
                    input_path=str(tmp / files["epics"]),
                    unresolved_parent="label", dry_run=dry_run,
                    create_missing=create_missing, on_existing=on_existing,
                    create_missing_groups=True, group_names=names_path,
                    on_missing_bv_field=on_missing_bv_field)
                if id_map is None:
                    if dry_run:
                        print("\n[dry run] preview stopped after the epics phase "
                              "— the reason is in the message above. One common "
                              "cause: a dry run cannot preview into a target "
                              "root that does not exist yet (the real import "
                              "would create it) — create the root group first "
                              "to preview the full sequence, or run without "
                              "dry run.")
                    else:
                        print("\nBundle import aborted — the epics phase did not "
                              "run (see messages above). Nothing further was "
                              "attempted.")
                    return
                if dry_run and not id_map:
                    print("  [dry run] no epic id map yet — the next phases "
                          "preview epic references by title instead.")
            else:
                id_map = {}
                print(f"\n── Phase 1/3: epics — none in bundle, skipped ──")

            if files.get("issues"):
                print(f"\n── Phase 2/3: issues ──")
                self._import_issues(
                    input_path=str(tmp / files["issues"]), dry_run=dry_run,
                    create_missing=not files.get("epics") and create_missing,
                    on_existing=on_existing,
                    epic_id_map=id_map, create_missing_projects=True,
                    group_names=names_path)
            else:
                print(f"\n── Phase 2/3: issues — none in bundle, skipped ──")

            links_fn = files.get("links")
            if links_fn and (tmp / links_fn).exists():
                print(f"\n── Phase 3/3: blocking links ──")
                self._import_links(input_path=str(tmp / links_fn),
                                   epic_id_map=id_map, dry_run=dry_run)
            else:
                print(f"\n── Phase 3/3: blocking links — none in bundle, skipped ──")

            print(f"\nBundle import complete"
                  + ("  (dry run — no changes made)" if dry_run else "")
                  + ".  Re-running the same bundle is safe: existing objects "
                    "are skipped.")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
