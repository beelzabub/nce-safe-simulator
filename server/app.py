import json
import os
import re
import shlex
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import markdown as _md

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from mixins.reports import REPORTS
from mixins.tools import TOOLS
from server.auth_backgrounds import (
    list_backgrounds,
    load_auth_config,
    media_type_for,
    resolve_media_file,
)
from server.auth_gate import (
    SESSION_COOKIE,
    auth_method,
    create_session,
    destroy_session,
    gate_check,
    session_valid,
    verify_credentials,
)
from server.analysis import portfolio_payload
from server.constraints import READONLY_TOOLS, _TOOL_GROUP, check_conflict
from server.jobs import manager as job_manager
from server.version import app_version
from server.retention import prune_temp_files

app = FastAPI(title="NCE Safe Simulator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# Authentication gate (epic #135, issue #157). No-op while auth.method is
# "none"; with "basic" every HTTP request outside the login page's own
# surface must carry the session cookie or an Authorization: Basic header.
# Report/tool runs are durable jobs over plain HTTP (#219), so this one gate
# covers launching, tailing, and cancelling them.
@app.middleware("http")
async def auth_gate_middleware(request: Request, call_next):
    gl = getattr(request.app.state, "gl", None)
    if not gate_check(gl, request.method, request.url.path, request.cookies, request.headers):
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"},
            headers={"WWW-Authenticate": 'Basic realm="nce-safe-sim"'},
        )
    return await call_next(request)

@app.on_event("startup")
def _prune_temp_files_on_startup():
    """Sweep aged-out import/export temp files when the server boots (covers
    accumulation across restarts/redeploys)."""
    removed = prune_temp_files()
    if removed:
        print(f"[retention] pruned {len(removed)} stale import/export temp file(s)")


@app.on_event("startup")
def _reconcile_jobs_on_startup():
    """Reconcile durable jobs left mid-flight by a previous server process
    (issue #214). Dead-pid jobs become 'unknown'; still-running jobs are
    re-adopted so their terminal state is recorded when they exit."""
    changed = job_manager.reconcile()
    if changed:
        print(f"[jobs] reconciled {len(changed)} orphaned job(s) after restart")


# Exclusive lock for the fetch-data phase — only one data snapshot at a time.
_report_data_lock = threading.Lock()

# Browser-uploaded import files land here so the import tools can read them by
# server path. File extensions are restricted to the formats the importer reads.
_UPLOADS_DIR = Path("uploads")
_ALLOWED_UPLOAD_EXT = {".csv", ".json", ".zip"}


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def _tool_payload(tool: dict, gl=None) -> dict:
    key = tool["key"]
    params = []
    for p in tool.get("params", []):
        # cli_only params (e.g. server-side output_path) are hidden from the web
        # UI; the CLI still prompts for them from the raw tool def.
        if p.get("cli_only"):
            continue
        default = p.get("default")
        hint    = None

        if p.get("widget") == "group" and gl is not None:
            ns  = getattr(gl, "gitlab_namespace", None)
            grp = getattr(gl, "parent_group", "")
            default = f"{ns}/{grp}" if ns else grp

        elif p.get("gl_default") and gl is not None:
            raw = getattr(gl, p["gl_default"], None)
            if isinstance(raw, dict):
                desired = raw.get("desired")
                lo, hi  = raw.get("min"), raw.get("max")
                if desired is not None:
                    default = int(desired)
                    hint    = f"range {lo}–{hi} · leave blank to randomise"
                elif lo is not None:
                    default = None
                    hint    = f"random {lo}–{hi} · enter a value to pin it"
            elif raw is not None:
                if p["type"] is float:
                    default = raw
                    hint    = f"= {int(raw * 100)}% · enter as decimal (e.g. 0.85)"
                else:
                    default = int(raw)

        params.append({
            "name":     p["name"],
            "prompt":   p["prompt"],
            "type":     p["type"].__name__,
            "widget":   p.get("widget"),
            "options":  p.get("options"),
            "section":  p.get("section"),
            "help":     p.get("help"),
            "hint":     hint,
            "accept":   p.get("accept"),
            "default":  default,
            "optional": p.get("optional", False),
        })
    return {
        "key":               key,
        "description":       tool["description"],
        "confirm":           tool.get("confirm", False),
        "readonly":          key in READONLY_TOOLS,
        "parallelism_group": _TOOL_GROUP.get(key),
        "params":            params,
    }


def _report_payload(report: dict) -> dict:
    return {
        "key":               report["key"],
        "description":       report["description"],
        "readonly":          True,
        "parallelism_group": None,
    }


# ---------------------------------------------------------------------------
# REST routes
# ---------------------------------------------------------------------------

@app.get("/api/tools")
def list_tools(request: Request):
    gl = getattr(request.app.state, "gl", None)
    return [_tool_payload(t, gl) for t in TOOLS]


def _deployment_type() -> str:
    if os.environ.get("ECS_CONTAINER_METADATA_URI_V4") or os.environ.get("ECS_CONTAINER_METADATA_URI"):
        return "ecs"
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return "eks"
    return ""


@app.get("/api/config")
def get_config(request: Request):
    gl = getattr(request.app.state, "gl", None)
    dod_banner = bool(load_auth_config(gl).get("dod_banner_enabled", True))
    if gl is None:
        return {"target_group": "", "wiki_url": "", "grafana_url": "",
                "deployment_type": _deployment_type(), "dod_banner_enabled": dod_banner,
                "version": app_version()}
    ns  = getattr(gl, "gitlab_namespace", None)
    grp = getattr(gl, "parent_group", "")

    # Resolve the GitLab group web_url for the wiki link.
    # Cache keyed on parent_group so a config change triggers a fresh lookup.
    if getattr(request.app.state, "_wiki_url_group", None) != grp:
        wiki_url = ""
        try:
            group = gl.get_group_by_name(grp)
            if group:
                wiki_url = f"{group.web_url}/-/wikis"
        except Exception:
            pass
        request.app.state._wiki_url       = wiki_url
        request.app.state._wiki_url_group = grp

    return {
        "target_group":   f"{ns}/{grp}" if ns else grp,
        "wiki_url":       getattr(request.app.state, "_wiki_url", ""),
        "grafana_url":    os.environ.get("GRAFANA_URL", "") or getattr(gl, "grafana_url", ""),
        "deployment_type": _deployment_type(),
        "dod_banner_enabled": dod_banner,
        "version": app_version(),
    }


@app.get("/api/groups")
def list_group_options(request: Request):
    """Return the groups available under the configured namespace / parent_group.

    Each entry has a full ``path`` (namespace-qualified, e.g. ``ns/team-a``) and
    a human ``name``. Discovery is scoped to the configured ``parent_group`` and
    its descendants via ``mixins/groups.py`` (get_all_subgroups). This is a
    read-only helper the web UI uses to populate the group picker; it never
    raises on failure. If the GitLab client is absent/unreachable or no groups
    are found, an empty list is returned (HTTP 200) so the UI falls back to
    free-text entry.
    """
    gl = getattr(request.app.state, "gl", None)
    if gl is None:
        return []
    grp = getattr(gl, "parent_group", "")
    if not grp:
        return []

    try:
        root = gl.get_group_by_name(grp)
        if root is None:
            return []
        # Single paginated descendant_groups call (root + all depths) instead of
        # the get_all_subgroups N+1 (one gl.groups.get per subgroup) — this is an
        # interactive path hit on every import-dialog open, so latency matters.
        discovered = [root] + gl.list_descendant_groups(root)

        groups = []
        seen = set()
        for g in discovered:
            path = getattr(g, "full_path", None) or (g if isinstance(g, str) else None)
            if not path or path in seen:
                continue
            seen.add(path)
            name = getattr(g, "name", None) or getattr(g, "full_name", None) or path
            groups.append({"path": path, "name": name})
        return groups
    except Exception:
        # GitLab unreachable, permissions, traversal error, etc. — degrade to [].
        return []


@app.get("/api/projects")
def list_project_options(request: Request):
    """Return the projects available under the configured namespace / parent_group.

    Mirrors ``GET /api/groups`` but for projects: each entry has a full ``path``
    (the namespace-qualified ``path_with_namespace``, e.g. ``ns/team-a/backlog``)
    and a human ``name``. Discovery is scoped to the configured ``parent_group``
    and its subgroups (``root_group.projects.list(include_subgroups=True)``, the
    same source as ``_build_project_cache``). This is a read-only helper the web
    UI uses to populate the import-issues project picker; it never raises on
    failure. If the GitLab client is absent/unreachable, no parent_group is
    configured, the root group isn't found, or GitLab errors, an empty list is
    returned (HTTP 200) so the UI falls back to free-text entry.
    """
    gl = getattr(request.app.state, "gl", None)
    if gl is None:
        return []
    grp = getattr(gl, "parent_group", "")
    if not grp:
        return []

    try:
        root = gl.get_group_by_name(grp)
        if root is None:
            return []
        discovered = root.projects.list(all=True, include_subgroups=True)

        projects = []
        seen = set()
        for p in discovered:
            path = getattr(p, "path_with_namespace", None) or (p if isinstance(p, str) else None)
            if not path or path in seen:
                continue
            seen.add(path)
            name = getattr(p, "name", None) or getattr(p, "name_with_namespace", None) or path
            projects.append({"path": path, "name": name})
        return projects
    except Exception:
        # GitLab unreachable, permissions, traversal error, etc. — degrade to [].
        return []


@app.get("/api/config/full")
def get_config_full():
    """Return the full config.json contents."""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="config.json not found")


@app.put("/api/config/full", status_code=200)
async def put_config_full(request: Request):
    """Overwrite config.json with the supplied JSON body and reload the running client."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Config must be a JSON object")

    try:
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config.json: {exc}")

    gl = getattr(request.app.state, "gl", None)
    if gl is not None:
        try:
            gl.reload_config()
        except Exception:
            pass

    return {"status": "ok"}


@app.post("/api/upload", status_code=200)
async def upload_import_file(file: UploadFile = File(...)):
    """Store a browser-uploaded import file server-side and return its path.

    The web UI's import tools (import-epics / import-issues) need a file that
    already exists on the server, but a browser user has no way to place one
    there. The file-picker widget posts the chosen file here first, then passes
    the returned server path as the tool's input_path. CLI import is unaffected.
    """
    raw_name = file.filename or ""
    # Guard against path traversal — keep only the basename component.
    safe_name = Path(raw_name).name
    if not safe_name:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(safe_name).suffix.lower()
    if ext not in _ALLOWED_UPLOAD_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or '(none)'}'. Allowed: .csv, .json",
        )

    _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    prune_temp_files()  # keep uploads/ and exports/ from growing unbounded
    # Timestamp-prefix to avoid collisions between successive uploads.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = _UPLOADS_DIR / f"{stamp}_{safe_name}"

    try:
        contents = await file.read()
        dest.write_bytes(contents)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {exc}")
    finally:
        await file.close()

    return {
        "path":     str(dest.resolve()),
        "filename": safe_name,
        "size":     dest.stat().st_size,
    }


@app.get("/api/reports")
def list_reports():
    return [_report_payload(r) for r in REPORTS]


@app.get("/api/history")
def list_history():
    """Return completed report runs from disk as session-history entries, newest first.

    Each entry matches the _sessionHistory shape in useJobs.js so the frontend
    can pre-populate history on startup without having to replay WebSocket jobs.
    """
    runs = []
    reports_root = Path("reports")
    if not reports_root.is_dir():
        return runs

    for date_dir in sorted(reports_root.iterdir(), reverse=True):
        if not date_dir.is_dir() or not re.match(r"^\d{8}$", date_dir.name):
            continue
        for time_dir in sorted(date_dir.iterdir(), reverse=True):
            if not time_dir.is_dir() or not re.match(r"^\d{6}$", time_dir.name):
                continue

            log_files = sorted(time_dir.glob("*.log"))
            if not log_files:
                continue
            log_file = log_files[0]

            stem = log_file.stem
            if stem == "reports-all":
                key = "reports (all)"
            elif re.match(r"^reports-\d+-selected$", stem):
                key = f"reports ({stem.split('-')[1]})"
            elif stem.startswith("reports-"):
                key = stem[len("reports-"):]
            else:
                key = stem

            d, t = date_dir.name, time_dir.name
            try:
                run_dt = datetime(int(d[:4]), int(d[4:6]), int(d[6:]),
                                  int(t[:2]), int(t[2:4]), int(t[4:]))
            except ValueError:
                continue

            started_ms = int(run_dt.timestamp() * 1000)
            ended_ms   = int(log_file.stat().st_mtime * 1000)

            try:
                content = log_file.read_text(encoding="utf-8", errors="replace")
                lines = [ln.rstrip() for ln in content.splitlines()]
            except OSError:
                lines = ["(log unreadable)"]

            runs.append({
                "id":        f"disk-{d}-{t}",
                "key":       key,
                "status":    "done",
                "startedAt": started_ms,
                "endedAt":   ended_ms,
                "logPath":   str(log_file),
                "lines":     lines,
            })

    return runs


@app.get("/api/analysis/portfolio")
def analysis_portfolio():
    """Portfolio-level analysis view (epic #165).

    Every portfolio epic (epic::epic tier) with attention flags — blocked
    descendants (with chains and weight/BV rollups) and behind-schedule.
    Reads the newest complete report snapshot from disk — no GitLab calls.
    404s with a hint when no snapshot exists yet.
    """
    data_dir = _resolve_reuse_data("last")
    if data_dir is None:
        raise HTTPException(
            status_code=404,
            detail="No complete report snapshot found — run reports first.",
        )
    return portfolio_payload(data_dir)


@app.get("/api/runs")
def list_runs():
    """List report run directories, newest first.

    Each entry has: date, time, path, has_log, has_data.
    Used by the Session Jobs tab to link log and data files.
    """
    reports_dir = Path("reports")
    if not reports_dir.is_dir():
        return []
    runs = []
    for date_dir in sorted(reports_dir.iterdir(), reverse=True):
        if not date_dir.is_dir() or not date_dir.name.isdigit():
            continue
        for time_dir in sorted(date_dir.iterdir(), reverse=True):
            if not time_dir.is_dir() or not time_dir.name.isdigit():
                continue
            log_files = sorted(time_dir.glob("*.log"))
            runs.append({
                "date":     date_dir.name,
                "time":     time_dir.name,
                "path":     f"reports/{date_dir.name}/{time_dir.name}",
                "has_log":  bool(log_files),
                "log_name": log_files[0].name if log_files else None,
                "has_data": (time_dir / "data").is_dir(),
                "has_wiki": (time_dir / "wiki").is_dir(),
            })
    return runs


@app.get("/api/runs/{date}/{time}/data", response_class=HTMLResponse)
def browse_run_data(date: str, time: str):
    """Simple file browser for a run's data snapshot directory."""
    data_dir = Path("reports") / date / time / "data"
    if not data_dir.is_dir():
        raise HTTPException(status_code=404, detail="Data directory not found")
    files = sorted(f for f in data_dir.iterdir() if f.is_file())
    t = f"{time[:2]}:{time[2:4]}:{time[4:6]}"
    d = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    items = "\n".join(
        f'<li><a href="/reports/{date}/{time}/data/{f.name}" target="_blank">'
        f'{f.name}</a> <span class="sz">{f.stat().st_size // 1024} KB</span></li>'
        for f in files
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Data — {d} {t}</title>
  <style>
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      background: #0d1117; color: #e6edf3;
      padding: 2rem; margin: 0;
    }}
    h1 {{ font-size: 1rem; color: #8b949e; margin: 0 0 1.2rem; font-weight: 500; }}
    ul {{ list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.35rem; }}
    li {{ display: flex; align-items: baseline; gap: 0.75rem; }}
    a {{
      color: #60a5fa; text-decoration: none;
      font-family: ui-monospace, monospace; font-size: 0.88rem;
    }}
    a:hover {{ text-decoration: underline; }}
    .sz {{ color: #6e7681; font-size: 0.78rem; }}
  </style>
</head>
<body>
  <h1>Data snapshot &mdash; {d} &nbsp; {t}</h1>
  <ul>{items}</ul>
</body>
</html>"""


_WIKI_CSS = """
body{font-family:system-ui,-apple-system,sans-serif;background:#0d1117;color:#e6edf3;
  margin:0;padding:0}
.page{max-width:960px;margin:0 auto;padding:1.5rem 2rem 4rem}
nav{font-size:0.8rem;color:#8b949e;margin-bottom:1.5rem}
nav a{color:#60a5fa;text-decoration:none}
nav a:hover{text-decoration:underline}
h1{font-size:1.6rem;border-bottom:1px solid #30363d;padding-bottom:.5rem;margin-top:0}
h2{font-size:1.2rem;border-bottom:1px solid #21262d;padding-bottom:.3rem;margin-top:2rem}
h3{font-size:1rem;margin-top:1.5rem}
h4,h5,h6{font-size:.95rem;margin-top:1.2rem}
a{color:#60a5fa;text-decoration:none}
a:hover{text-decoration:underline}
p{line-height:1.6;margin:.5rem 0}
table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.88rem}
th,td{border:1px solid #30363d;padding:.4rem .75rem;text-align:left}
th{background:#161b22;font-weight:600;color:#c9d1d9}
tr:nth-child(even) td{background:#0d1117}
tr:nth-child(odd) td{background:#111820}
code{background:#161b22;border:1px solid #30363d;border-radius:3px;
  padding:.1em .35em;font-family:ui-monospace,monospace;font-size:.85em}
pre{background:#161b22;border:1px solid #30363d;border-radius:6px;
  padding:1rem;overflow-x:auto}
pre code{background:none;border:none;padding:0}
blockquote{border-left:3px solid #30363d;margin:0;padding:.3rem 1rem;color:#8b949e}
details{border:1px solid #30363d;border-radius:6px;padding:.5rem 1rem;margin:.75rem 0}
summary{cursor:pointer;font-weight:600;color:#c9d1d9}
summary:hover{color:#e6edf3}
hr{border:none;border-top:1px solid #30363d;margin:1.5rem 0}
ul,ol{padding-left:1.5rem;line-height:1.7}
strong{color:#e6edf3}
"""

_WIKI_INDEX_CSS = """
body{font-family:system-ui,-apple-system,sans-serif;background:#0d1117;color:#e6edf3;
  padding:2rem;margin:0}
h1{font-size:1rem;color:#8b949e;margin:0 0 1.2rem;font-weight:500}
ul{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:.35rem}
li{display:flex;align-items:baseline;gap:.75rem}
a{color:#60a5fa;text-decoration:none;font-size:.9rem}
a:hover{text-decoration:underline}
.stem{color:#6e7681;font-family:ui-monospace,monospace;font-size:.75rem}
"""


def _wiki_page_title(path: Path) -> str:
    """Extract the first H1 heading from a markdown file, fall back to stem."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
    except Exception:
        pass
    return path.stem


def _latest_wiki_run() -> Optional[tuple]:
    """Return (date, time) of the most recent run that has a wiki directory."""
    reports_root = Path("reports")
    if not reports_root.is_dir():
        return None
    for date_dir in sorted(reports_root.iterdir(), reverse=True):
        if not date_dir.is_dir() or not date_dir.name.isdigit():
            continue
        for time_dir in sorted(date_dir.iterdir(), reverse=True):
            if (time_dir / "wiki").is_dir():
                return date_dir.name, time_dir.name
    return None


@app.get("/api/wiki", response_class=HTMLResponse)
def wiki_latest():
    """Redirect to the most recent run's wiki index."""
    run = _latest_wiki_run()
    if not run:
        raise HTTPException(status_code=404, detail="No wiki output found")
    return RedirectResponse(url=f"/api/runs/{run[0]}/{run[1]}/wiki")


@app.get("/api/runs/{date}/{time}/wiki", response_class=HTMLResponse)
def browse_run_wiki(date: str, time: str):
    """HTML index of wiki pages for a run."""
    wiki_dir = Path("reports") / date / time / "wiki"
    if not wiki_dir.is_dir():
        raise HTTPException(status_code=404, detail="Wiki directory not found")
    pages = sorted(
        ((f.stem, _wiki_page_title(f)) for f in wiki_dir.glob("*.md")),
        key=lambda x: x[1].lower(),
    )
    d = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    t = f"{time[:2]}:{time[2:4]}:{time[4:6]}"
    items = "\n".join(
        f'<li><a href="/api/runs/{date}/{time}/wiki/{stem}">{title}</a>'
        f' <span class="stem">{stem}</span></li>'
        for stem, title in pages
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Wiki — {d} {t}</title>
<style>{_WIKI_INDEX_CSS}</style></head>
<body>
  <h1>Wiki pages &mdash; {d} &nbsp; {t} &nbsp; ({len(pages)} pages)</h1>
  <ul>{items}</ul>
</body></html>"""


_TIER_NAMES = {
    "00": "Executive Pulse",
    "01": "Program Management",
    "02": "Operational Detail",
    "03": "Data Quality",
}


def _wiki_page_tier(slug_or_path: str) -> "str | None":
    """Tier number ("00".."03") from a wiki page path or slug, or None.

    Works on real page paths ("… Portfolio Home/01 Program Management/…")
    and on slugs, where dash collapsing has erased the '/' separators
    (…portfolio-home-01-program-management-…).
    """
    m = re.search(r"(?:^|[/-])(0[0-3])[ -]", slug_or_path)
    return m.group(1) if m else None


@app.get("/api/runs/{date}/{time}/wiki/index.json")
def wiki_index_json(date: str, time: str):
    """Wiki pages of a run as JSON for the in-app Reports tab (epic #165).

    Each entry carries the page's real GitLab wiki path (from the run's
    pages.json manifest) split into segments, so the Reports tab can mirror
    the wiki hierarchy exactly. Runs from before the manifest fall back to
    the leaf H1 title with no nesting.
    """
    wiki_dir = Path("reports") / date / time / "wiki"
    if not wiki_dir.is_dir():
        raise HTTPException(status_code=404, detail="Wiki directory not found")

    manifest = {}
    manifest_path = wiki_dir / "pages.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError:
            manifest = {}

    pages = []
    for f in sorted(wiki_dir.glob("*.md")):
        path = manifest.get(f.stem)
        if path:
            segments = path.split("/")
            title = segments[-1]
            tier = _wiki_page_tier(path)
        else:
            segments = None
            title = _wiki_page_title(f)
            tier = _wiki_page_tier(f.stem)
        pages.append({
            "slug": f.stem,
            "title": title,
            "path": path,
            "segments": segments,
            "tier": tier,
            "tier_name": _TIER_NAMES.get(tier),
        })
    # Wiki order: by full path where known (home page naturally precedes the
    # numbered tier folders), legacy entries by tier then title.
    pages.sort(key=lambda p: (
        (p["path"] or "").lower() or (p["tier"] or "") + p["title"].lower(),
    ))
    return pages


@app.get("/api/runs/{date}/{time}/wiki/{slug}.json")
def wiki_page_json(date: str, time: str, slug: str):
    """A wiki page rendered to an HTML fragment for the in-app viewer.

    Same renderer as the standalone HTML route; the SPA styles the fragment
    with its own theme variables.
    """
    md_path = Path("reports") / date / time / "wiki" / f"{slug}.md"
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail="Wiki page not found")
    content = md_path.read_text(encoding="utf-8")
    return {
        "slug": slug,
        "title": _wiki_page_title(md_path),
        "html": _md.markdown(content, extensions=["extra", "toc"]),
    }


@app.get("/api/runs/{date}/{time}/wiki/{slug}", response_class=HTMLResponse)
def view_wiki_page(date: str, time: str, slug: str):
    """Render a markdown wiki page as HTML."""
    wiki_dir = Path("reports") / date / time / "wiki"
    md_path  = wiki_dir / f"{slug}.md"
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail="Wiki page not found")
    content   = md_path.read_text(encoding="utf-8")
    html_body = _md.markdown(content, extensions=["extra", "toc"])
    d = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    t = f"{time[:2]}:{time[2:4]}:{time[4:6]}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{_wiki_page_title(md_path)}</title>
<style>{_WIKI_CSS}</style></head>
<body>
  <div class="page">
    <nav><a href="/api/runs/{date}/{time}/wiki">← Wiki index</a>
    &nbsp;·&nbsp; {d} {t}</nav>
    {html_body}
  </div>
</body></html>"""


@app.delete("/api/runs")
def clear_runs():
    """Delete all timestamped report run directories from disk."""
    reports_dir = Path("reports")
    if not reports_dir.is_dir():
        return {"deleted": 0}
    deleted = 0
    for date_dir in list(reports_dir.iterdir()):
        if not date_dir.is_dir() or not date_dir.name.isdigit():
            continue
        for time_dir in list(date_dir.iterdir()):
            if not time_dir.is_dir() or not time_dir.name.isdigit():
                continue
            shutil.rmtree(time_dir)
            deleted += 1
        try:
            date_dir.rmdir()   # succeeds only if now empty
        except OSError:
            pass
    return {"deleted": deleted}


@app.get("/api/running")
def list_running():
    """Currently-running work, derived from the durable job engine (#219).

    Report/tool runs are subprocess jobs whose live state lives on disk, so the
    Server-status tab reads the running manifests directly instead of an
    in-memory set that a disconnect could desync. ``key`` is the job label (the
    tool/report key); elapsed is measured from the manifest's start time.
    """
    now = datetime.now(timezone.utc)
    running = []
    for m in job_manager.list_jobs():
        if m.get("state") != "running":
            continue
        started = m.get("started")
        elapsed = 0.0
        if started:
            try:
                elapsed = (now - datetime.fromisoformat(started)).total_seconds()
            except ValueError:
                elapsed = 0.0
        running.append({"key": m.get("label") or m.get("kind"),
                        "elapsed_seconds": round(max(0.0, elapsed), 1)})
    return running


# ---------------------------------------------------------------------------
# Durable background jobs (issue #214)
# ---------------------------------------------------------------------------
# Unlike the /ws/run path (in-process threads that die when the socket closes),
# these jobs run as subprocess.Popen children owned by the server. Their state
# and logs live on disk, so a job survives refreshes, re-logins, extra tabs,
# and server restarts. Cancellation is an explicit call here — never a side
# effect of a disconnect. This is the foundation for the Deploy Options epic;
# report runs migrate onto it under #219.

@app.post("/api/jobs", status_code=201)
async def launch_durable_job(request: Request):
    """Launch a durable background job. Body is the report/tool run shape
    ({"tool": key, "params": {...}}, {"report": key, ...}, or {"reports":
    [...], ...}); the server maps it to a whitelisted argv. Returns the job
    manifest (with its id).

    A write-tool request that conflicts with an already-running job is rejected
    with 409 and the blocking job list (the same guard the retired /ws/run path
    enforced) — reports are read-only and never conflict. The equivalent CLI
    command is echoed as the first log line(s) so the run record reproduces
    itself (issue #140)."""
    gl = getattr(request.app.state, "gl", None)
    if gl is None:
        raise HTTPException(status_code=503, detail="GitLab client not initialised")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Expected JSON body")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    try:
        kind, label, argv = _job_argv(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Parallelism guard: a running write tool that shares a group with this one
    # blocks the launch. Running keys are the labels of live durable jobs.
    running_keys = [m.get("label") for m in job_manager.list_jobs()
                    if m.get("state") == "running"]
    blocking = check_conflict(running_keys, label)
    if blocking:
        raise HTTPException(status_code=409, detail={"blocking": blocking})

    header = [f"$ {line}" for line in build_cli_command(data).splitlines()]
    return job_manager.launch(
        argv, kind=kind, label=label, params=data.get("params") or {},
        log_header=header or None,
    )


@app.get("/api/jobs")
def list_durable_jobs():
    """All durable jobs (live + recent), newest first."""
    return job_manager.list_jobs()


@app.get("/api/jobs/{job_id}")
def get_durable_job(job_id: str, offset: int = 0):
    """Job manifest plus the log tail from *offset* bytes. Pass the returned
    ``offset`` on the next poll to resume streaming where you left off."""
    job = job_manager.get_job(job_id, offset=offset)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_durable_job(job_id: str):
    """Explicitly cancel a running job (SIGTERM to its process group, escalating
    to SIGKILL). No-op on an already-finished job."""
    job = job_manager.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ---------------------------------------------------------------------------
# Deploy Options status (epic #134, issue #215)
# ---------------------------------------------------------------------------
# The Run Reports dialog's Deploy Options section surfaces the live state of each
# target (S3 / ECS / EKS) so an operator can see what's already running and
# launch / destroy from the same place. Status is aggregated from small
# per-target helpers so the sibling deploy-execution issues can slot their real
# logic in without colliding here: #216 fills in the S3/CloudFront status (stub
# for now), #217/#218 supply the actual ECS/EKS deploy execution. ECS/EKS status
# is real today, read from CloudFormation.

_ECS_STACK = "NceStack"       # cdk/ecs_app.py — NceEcsStack(app, "NceStack")
_EKS_STACK = "NceEksStack"    # cdk/eks_app.py — NceEksStack(app, "NceEksStack")

_CDK_DIR = Path(__file__).resolve().parent.parent / "cdk"

# CloudFormation stack statuses that mean "stack is up and usable".
_CFN_HEALTHY = {
    "CREATE_COMPLETE", "UPDATE_COMPLETE",
    "UPDATE_ROLLBACK_COMPLETE", "IMPORT_COMPLETE",
}

# Cache the (potentially slow) AWS round-trips briefly so the dialog's 3s poll
# doesn't hammer CloudFormation while it's open.
_DEPLOY_STATUS_TTL = 10.0
_deploy_status_lock = threading.Lock()
_deploy_status_cache = {"at": 0.0, "value": None}


def _cfn_state(status: "str | None") -> str:
    """Map a raw CloudFormation stack status to the coarse state the Deploy
    Options UI renders."""
    if status is None:
        return "not_deployed"
    if status.endswith("_IN_PROGRESS"):
        return "destroying" if status.startswith("DELETE") else "deploying"
    if status in _CFN_HEALTHY:
        return "deployed"
    return "error"


def _cdk_context(filename: str) -> dict:
    """Return the ``context`` dict from a cdk JSON file, or {} if unreadable."""
    try:
        return json.loads((_CDK_DIR / filename).read_text()).get("context", {})
    except Exception:
        return {}


def _describe_stack(stack_name: str) -> "tuple[str | None, dict]":
    """Return ``(stack_status, outputs)`` for a CloudFormation stack, or
    ``(None, {})`` when the stack is absent, boto3 is unavailable, or no AWS
    credentials are configured. Never raises."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except Exception:
        return None, {}
    try:
        cf = boto3.client("cloudformation")
        stacks = cf.describe_stacks(StackName=stack_name).get("Stacks", [])
    except (ClientError, BotoCoreError, NoCredentialsError):
        return None, {}
    except Exception:
        return None, {}
    if not stacks:
        return None, {}
    stack = stacks[0]
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
    return stack.get("StackStatus"), outputs


def _stack_deploy_status(stack_name: str, url_output_keys, url_fallback=None) -> dict:
    """Shared CloudFormation-backed status for a stack-based target (ECS/EKS).
    Resolves the public URL from the first matching stack output, falling back to
    ``url_fallback`` (e.g. a value the deploy wrote to cdk JSON) when present."""
    status, outputs = _describe_stack(stack_name)
    url = None
    for key in url_output_keys:
        if outputs.get(key):
            url = outputs[key]
            break
    if url is None and url_fallback:
        url = url_fallback
    result = {"state": _cfn_state(status), "url": url}
    if status:
        result["stack_status"] = status
    return result


def _s3_deploy_status() -> dict:
    # TODO(#216): real S3/CloudFront status (bucket existence + website/CDN URL).
    # Wired in by the orchestrator after #216 merges; stubbed here so the Deploy
    # Options section renders the S3 row today without a hard dependency on #216.
    return {"state": "not_deployed", "url": None}


def _ecs_deploy_status() -> dict:
    return _stack_deploy_status(
        _ECS_STACK,
        ("CloudFrontUrl", "AppUrl", "AlbUrl", "AlbDns"),
    )


def _eks_deploy_status() -> dict:
    return _stack_deploy_status(
        _EKS_STACK,
        ("CloudFrontUrl", "AppUrl"),
        url_fallback=_cdk_context("cdk-eks.json").get("eks_cf_url") or None,
    )


def _compute_deploy_status() -> dict:
    return {
        "s3":  _s3_deploy_status(),
        "ecs": _ecs_deploy_status(),
        "eks": _eks_deploy_status(),
    }


@app.get("/api/deploy/status")
def deploy_status(refresh: bool = False):
    """Live deploy status per target for the Run Reports Deploy Options section
    (issue #215). Each target reports a coarse ``state`` (``not_deployed`` /
    ``deploying`` / ``deployed`` / ``destroying`` / ``error``), a public ``url``
    when known, and — for ECS/EKS — the raw ``stack_status``. Results are cached
    for a few seconds so the dialog's 3s poll doesn't hammer AWS; pass
    ``?refresh=1`` to force a fresh read."""
    now = time.time()
    with _deploy_status_lock:
        cached = _deploy_status_cache["value"]
        if not refresh and cached is not None and now - _deploy_status_cache["at"] < _DEPLOY_STATUS_TTL:
            return cached
    value = _compute_deploy_status()
    with _deploy_status_lock:
        _deploy_status_cache["at"] = time.time()
        _deploy_status_cache["value"] = value
    return value


_DEPLOY_TARGETS = {"s3", "ecs", "eks"}
_DEPLOY_ACTIONS = {"deploy", "destroy"}


@app.post("/api/deploy/{target}/{action}", status_code=201)
def launch_deploy_job(target: str, action: str):
    """Launch a durable deploy/destroy job for a target (issue #215).

    The actual cloud execution (S3 publish, ECS/EKS apply/destroy) lands in the
    sibling issues #216/#217/#218. Until then this launches a clearly-marked
    placeholder durable job through the same engine, so the UI's
    pre-flight → launch → live-log → reattach flow is real end to end: the job
    shows up in ``GET /api/jobs`` and is re-adopted by ``useDurableJobs`` after a
    refresh exactly like a real deploy will be."""
    if target not in _DEPLOY_TARGETS:
        raise HTTPException(status_code=404, detail=f"Unknown deploy target: {target}")
    if action not in _DEPLOY_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown deploy action: {action}")

    label = f"{action} {target.upper()}"
    # TODO(#216/#217/#218): replace this placeholder argv with the real deploy /
    # destroy command for the target.
    script = (
        "import sys, time\n"
        f"print('[placeholder] {action} {target} — cloud execution arrives in "
        "#216/#217/#218'); sys.stdout.flush()\n"
        "for i in range(3):\n"
        f"    print('  {action} {target}: step %d/3' % (i + 1)); sys.stdout.flush(); time.sleep(1)\n"
        f"print('[placeholder] {action} {target} complete')\n"
    )
    argv = [sys.executable, "-c", script]
    return job_manager.launch(
        argv, kind="deploy", label=label,
        params={"target": target, "action": action},
    )


@app.post("/api/reports/fetch-data", status_code=200)
def fetch_report_data(request: Request):
    """Fetch live data from GitLab and load it into memory.

    Returns 409 if a fetch is already in progress, 503 if the GitLab client
    has not been initialised (server started without --serve wiring).
    """
    gl = getattr(request.app.state, "gl", None)
    if gl is None:
        raise HTTPException(status_code=503, detail="GitLab client not initialised")

    if not _report_data_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Data fetch already in progress")

    try:
        now      = datetime.now()
        data_dir = Path("reports") / now.strftime("%Y%m%d") / now.strftime("%H%M%S") / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        for attr in ("_metrics_cache", "_issues_cache", "_all_epics_cache"):
            if hasattr(gl, attr):
                delattr(gl, attr)

        group = gl.get_group_by_name(gl.parent_group)
        gl._rd_root_obj = group
        gl._write_report_data(data_dir)
        gl._load_report_data(data_dir)
    finally:
        _report_data_lock.release()

    return {"status": "ok", "data_dir": str(data_dir)}


# ---------------------------------------------------------------------------
# Report/tool run helpers
# ---------------------------------------------------------------------------
# Report and tool runs launched from the UI are durable jobs (issue #219): they
# go through POST /api/jobs, run as subprocess.Popen children owned by the
# server, and are tailed/reattached/cancelled over the /api/jobs endpoints. The
# old /ws/run WebSocket — in-process threads whose output streamed over a socket
# and which were cancelled when that socket closed — has been retired, along
# with its disconnect-kills-job path.


def _resolve_reuse_data(value) -> "Path | None":
    """Resolve the reuse_data WebSocket field to a concrete data/ Path or None.

    Accepts:
      "last"  — find the most recent reports/YYYYMMDD/HHMMSS/data/ directory
      None    — fetch fresh data (default)
    """
    if not value:
        return None
    if value == "last":
        reports_dir = Path("reports")
        candidates = sorted(
            (
                d / "data"
                for d in reports_dir.glob("*/*/")
                if (d / "data" / "snapshot.complete").is_file()
            ),
            reverse=True,
        )
        if candidates:
            return candidates[0]
        print("No complete snapshot found — fetching fresh data.")
        return None
    return Path(value)


CLI_ENTRY = "python3 NceGitLab.py"


def _quote(value) -> str:
    """POSIX-shell-quote a value; empty string becomes ''."""
    s = str(value)
    return "''" if s == "" else shlex.quote(s)


def _tool_arg_tokens(tool: dict, params: dict) -> list:
    """Flags for a tool's params, mirroring the frontend builder (useCliCommand.js):
    booleans expressed relative to their default; dash-leading values use the
    attached --name=value form so the CLI parser can't mistake them for a flag."""
    tokens: list = []
    for p in tool["params"]:
        if p.get("cli_only"):
            continue
        name = p["name"]
        if name not in params:
            continue
        v = params[name]
        if p["type"] is bool:
            if v is None:
                continue
            on = v is True
            if p.get("default") is True:
                tokens.append(f"--{name}" if on else f"--{name}=false")
            elif on:
                tokens.append(f"--{name}")
            continue
        if v is None or v == "":
            continue
        s = str(v)
        q = _quote(s)
        if s.startswith("-"):
            tokens.append(f"--{name}={q}")
        else:
            tokens.extend([f"--{name}", q])
    return tokens


def _tool_argv_tokens(tool: dict, params: dict) -> list:
    """Like ``_tool_arg_tokens`` but produces raw argv elements (no shell
    quoting): each element is passed literally to ``subprocess.Popen``. Dash-
    leading values use the attached --name=value form so argparse can't mistake
    them for a flag."""
    tokens: list = []
    for p in tool["params"]:
        if p.get("cli_only"):
            continue
        name = p["name"]
        if name not in params:
            continue
        v = params[name]
        if p["type"] is bool:
            if v is None:
                continue
            on = v is True
            if p.get("default") is True:
                tokens.append(f"--{name}" if on else f"--{name}=false")
            elif on:
                tokens.append(f"--{name}")
            continue
        if v is None or v == "":
            continue
        s = str(v)
        if s.startswith("-"):
            tokens.append(f"--{name}={s}")
        else:
            tokens.extend([f"--{name}", s])
    return tokens


def _job_argv(data: dict) -> tuple:
    """Map a durable-job request to ``(kind, label, argv)``.

    Only whitelisted kinds are accepted — the request never supplies a raw
    command line, so this endpoint can't be used to run arbitrary programs. The
    kinds are single tool, single report, and multi-report runs, all invoking
    the same ``NceGitLab.py`` entrypoint the CLI uses (issue #219); deploy kinds
    are added by the ECS/EKS/S3 children of #134.
    """
    entry = [sys.executable, "NceGitLab.py"]

    if "tool" in data:
        key = data["tool"]
        tool = next((t for t in TOOLS if t["key"] == key), None)
        if tool is None:
            raise ValueError(f"Unknown tool: {key!r}")
        argv = entry + ["-ut", key] + _tool_argv_tokens(tool, data.get("params") or {})
        return "tool", key, argv

    # Single report and multi-report selections both map to the CLI's `-r`
    # report path — the multi case as a comma-separated key list run in one pass
    # (mixins/reports.run_reports_menu splits it), so the whole selection is one
    # refresh-survivable subprocess sharing a single data snapshot.
    keys = None
    label = None
    if "report" in data:
        keys = [data["report"]]
        label = data["report"]
    elif "reports" in data:
        keys = list(data["reports"] or [])
        label = keys[0] if len(keys) == 1 else f"reports ({len(keys)})"

    if keys is not None:
        if not keys:
            raise ValueError("No reports selected")
        unknown = [k for k in keys if not any(r["key"] == k for r in REPORTS)]
        if unknown:
            raise ValueError(f"Unknown report: {unknown[0]!r}")
        argv = entry + ["-r", ",".join(keys)]
        formats = data.get("formats")
        if formats:
            argv += ["--formats", *[str(f) for f in formats]]
        if data.get("reuse_data") == "last":
            argv.append("--last")
        return "report", label, argv

    raise ValueError("Message must include 'tool', 'report', or 'reports'")


def build_cli_command(data: dict) -> str:
    """The equivalent `NceGitLab.py` command line for a report/tool job request.

    This is the authoritative, server-side rendering of the command the UI is
    about to run — echoed into the run's output so every job (tools, reports,
    and no-param utilities like diagnose alike) carries the exact command that
    reproduces it (issue #140). Reports yield one `-r` line per selected report.
    """
    if "tool" in data:
        key  = data["tool"]
        tool = next((t for t in TOOLS if t["key"] == key), None)
        if tool is None:
            return ""
        toks = _tool_arg_tokens(tool, data.get("params") or {})
        return " ".join([CLI_ENTRY, "-ut", key, *toks])

    keys = data.get("reports") or ([data["report"]] if data.get("report") else [])
    if not keys:
        return ""
    tail: list = []
    formats = data.get("formats")
    if formats:
        tail.extend(["--formats", *[_quote(f) for f in formats]])
    if data.get("reuse_data") == "last":
        tail.append("--last")
    suffix = (" " + " ".join(tail)) if tail else ""
    return "\n".join(f"{CLI_ENTRY} -r {_quote(k)}{suffix}" for k in keys)


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------
# Latest-run data endpoint — serves JSON files from the most recent complete
# snapshot so Grafana's Infinity datasource can reach them via the ALB.

@app.get("/data/{filename}")
def latest_data(filename: str):
    reports_dir = Path("reports")
    candidates = sorted(
        (d / "data" for d in reports_dir.glob("*/*/") if (d / "data" / "snapshot.complete").is_file()),
        reverse=True,
    )
    if not candidates:
        raise HTTPException(status_code=404, detail="No complete snapshot available")
    f = candidates[0] / filename
    if not f.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found in latest snapshot")
    return FileResponse(str(f), media_type="application/json")


# ---------------------------------------------------------------------------
# Export download endpoint — serves files written to public/exports by the
# export-epics / export-issues tools as proper browser downloads (attachment),
# so the web UI works on any host instead of a hardcoded localhost link.

@app.get("/api/download/{filename}")
def download_export(filename: str):
    prune_temp_files()  # opportunistic cleanup of aged-out exports/uploads
    # Basename only — reject anything with path separators or traversal.
    safe_name = Path(filename).name
    if not safe_name or safe_name != filename:
        raise HTTPException(status_code=404, detail="Not found")
    exports_dir = Path("public/exports").resolve()
    target = (exports_dir / safe_name).resolve()
    if target.parent != exports_dir or not target.is_file():
        raise HTTPException(status_code=404, detail=f"{safe_name} not found")
    media_type = "application/json" if target.suffix.lower() == ".json" else "text/csv"
    return FileResponse(str(target), media_type=media_type, filename=safe_name)


# ---------------------------------------------------------------------------
# Login-page backgrounds (epic #135) — rotating imagery for /login. Images are
# committed under media/login-backgrounds/; S3 is a curation staging preview
# only. Both endpoints degrade instead of raising: the login page is the
# front door and must always render.

# ── Auth endpoints (issue #157) ─────────────────────────────────────────────
# Method dispatch and dev "basic" sessions; real AAA methods (#152-#156) plug
# their own validation into this surface later.

@app.post("/api/auth/login")
async def auth_login(request: Request):
    gl = getattr(request.app.state, "gl", None)
    method = auth_method(gl)
    if method == "none":
        # Nothing to validate — the UI's cosmetic front door handles "none".
        return {"authenticated": True, "method": "none"}
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Expected JSON body")
    if not verify_credentials(data.get("username"), data.get("password")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_session()
    resp = JSONResponse({"authenticated": True, "method": method})
    resp.set_cookie(
        SESSION_COOKIE, token,
        httponly=True, samesite="lax", path="/",
    )
    return resp


@app.get("/api/auth/session")
def auth_session(request: Request):
    gl = getattr(request.app.state, "gl", None)
    method = auth_method(gl)
    if method == "none":
        return {"authenticated": True, "method": "none"}
    return {
        "authenticated": session_valid(request.cookies.get(SESSION_COOKIE)),
        "method": method,
    }


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    destroy_session(request.cookies.get(SESSION_COOKIE))
    resp = JSONResponse({"authenticated": False})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/api/auth/backgrounds")
def auth_backgrounds(request: Request, limit: Optional[int] = None):
    """Server-shuffled background list: images[0] is the random initial
    image, the rest are the client's lazy-loaded rotation pool."""
    gl = getattr(request.app.state, "gl", None)
    return list_backgrounds(gl, limit=limit)


@app.get("/api/auth/backgrounds/{filename}")
def auth_background_file(filename: str):
    target = resolve_media_file(filename)
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(
        str(target),
        media_type=media_type_for(target),
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ---------------------------------------------------------------------------
# SPA history fallback (epic #135): the Vue app uses history-mode routing, so
# a hard load of a client-side route like /app/login must serve the app shell.
# Real built files under public/app still win; unknown paths get index.html.

@app.get("/app/{path:path}")
def spa_fallback(path: str):
    app_dir = (Path("public") / "app").resolve()
    if app_dir.is_dir():
        candidate = (app_dir / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(app_dir):
            return FileResponse(str(candidate))
        index = app_dir / "index.html"
        if index.is_file():
            return FileResponse(str(index))
    raise HTTPException(status_code=404, detail="Not found")


# ---------------------------------------------------------------------------
# Mounted last so all API routes above take precedence.

_reports_dir = Path("reports")
_reports_dir.mkdir(exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(_reports_dir)), name="reports")

_logs_dir = Path("logs")
_logs_dir.mkdir(exist_ok=True)   # ensure mount is always registered
app.mount("/logs", StaticFiles(directory=str(_logs_dir)), name="logs-files")

_quarto_site = Path("quarto-site")
_quarto_site.mkdir(exist_ok=True)   # ensure mount is always registered
app.mount("/quarto", StaticFiles(directory=str(_quarto_site), html=True), name="quarto-static")

@app.get("/")
def root():
    return RedirectResponse(url="/app/")

_public = Path("public")
if _public.is_dir():
    app.mount("/", StaticFiles(directory=str(_public), html=True), name="static")
