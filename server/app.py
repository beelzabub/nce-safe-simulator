import asyncio
import json
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import markdown as _md

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from mixins.reports import REPORTS
from mixins.tools import TOOLS
from server.constraints import READONLY_TOOLS, _TOOL_GROUP, check_conflict
from server.runner import cancel_thread, install_writer, run_job

app = FastAPI(title="NCE Safe Simulator")

# Exclusive lock for the fetch-data phase — only one data snapshot at a time.
_report_data_lock = threading.Lock()

# Set of currently-running job keys (used for conflict checking).
_running_jobs: set = set()
# Separate timestamps dict for the /api/running status endpoint.
_running_started: dict = {}
_running_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def _tool_payload(tool: dict, gl=None) -> dict:
    key = tool["key"]
    params = []
    for p in tool.get("params", []):
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
            "section":  p.get("section"),
            "hint":     hint,
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


@app.get("/api/config")
def get_config(request: Request):
    gl = getattr(request.app.state, "gl", None)
    if gl is None:
        return {"target_group": "", "wiki_url": ""}
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
        "target_group": f"{ns}/{grp}" if ns else grp,
        "wiki_url":     getattr(request.app.state, "_wiki_url", ""),
    }


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
    now = time.time()
    with _running_lock:
        return [
            {"key": k, "elapsed_seconds": round(now - _running_started.get(k, now), 1)}
            for k in _running_jobs
        ]


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
# WebSocket job runner
# ---------------------------------------------------------------------------

@app.websocket("/ws/run")
async def ws_run(websocket: WebSocket):
    """Stream a tool or report job over WebSocket.

    Client sends:  {"tool": "<key>"}  or  {"report": "<key>"}
                   optional: {"params": {...}}  for tools
                   optional: {"formats": ["markdown"]}  for reports

    Server sends:
      {"type": "log",      "text": "..."}   — captured stdout line
      {"type": "done"}                       — job completed normally
      {"type": "error",    "message": "..."}  — job failed or invalid request
      {"type": "conflict", "blocking": [...]} — job conflicts with a running job
    """
    await websocket.accept()

    try:
        data = await websocket.receive_json()
    except Exception:
        await websocket.close(1003)
        return

    job_key: Optional[str] = (
        data.get("tool") or data.get("report")
        or ("reports" if data.get("reports") else None)
    )
    if not job_key:
        await websocket.send_json({"type": "error", "message": "Message must include 'tool', 'report', or 'reports'"})
        await websocket.close()
        return

    gl = getattr(websocket.app.state, "gl", None)
    if gl is None:
        await websocket.send_json({"type": "error", "message": "GitLab client not initialised"})
        await websocket.close()
        return

    # Conflict check and registration are atomic — happens before building the
    # callable so a conflict response is sent even if the method lookup would fail.
    with _running_lock:
        blocking = check_conflict(list(_running_jobs), job_key)
        if blocking:
            await websocket.send_json({"type": "conflict", "blocking": blocking})
            await websocket.close()
            return
        _running_jobs.add(job_key)
        _running_started[job_key] = time.time()

    gl.reload_config()

    try:
        fn = _build_job_fn(gl, data)
    except ValueError as exc:
        with _running_lock:
            _running_jobs.discard(job_key)
            _running_started.pop(job_key, None)
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return

    log_fh = None
    if "tool" in data:
        now = datetime.now()
        log_dir = Path("logs") / now.strftime("%Y%m%d")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{now.strftime('%H%M%S')}_{job_key}.log"
        log_fh = log_path.open("w", encoding="utf-8")
        await websocket.send_json({"type": "log_path", "path": str(log_path)})

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def on_output(text: str) -> None:
        # Detect the log-path announcement printed by _tee_to_log / _run_reports.
        if text.startswith("  log → "):
            lp = text[len("  log → "):].strip()
            loop.call_soon_threadsafe(q.put_nowait, ("log_path", lp))
        loop.call_soon_threadsafe(q.put_nowait, ("log", text))
        if log_fh is not None:
            log_fh.write(text + "\n")
            log_fh.flush()

    def on_done() -> None:
        loop.call_soon_threadsafe(q.put_nowait, ("done", None))

    def on_error(exc: Exception) -> None:
        loop.call_soon_threadsafe(q.put_nowait, ("error", str(exc)))

    install_writer()
    thread = run_job(fn, on_output, on_done=on_done, on_error=on_error)

    try:
        while True:
            kind, payload = await q.get()
            if kind == "log":
                await websocket.send_json({"type": "log", "text": payload})
            elif kind == "log_path":
                await websocket.send_json({"type": "log_path", "path": payload})
            elif kind == "done":
                await websocket.send_json({"type": "done"})
                break
            elif kind == "error":
                await websocket.send_json({"type": "error", "message": payload})
                break
    finally:
        cancel_thread(thread)
        if log_fh is not None:
            try:
                log_fh.close()
            except Exception:
                pass
        with _running_lock:
            _running_jobs.discard(job_key)
            _running_started.pop(job_key, None)
        await websocket.close()


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


def _build_job_fn(gl: object, data: dict):
    """Return a zero-argument callable for the tool or report described by *data*."""
    if "tool" in data:
        key  = data["tool"]
        tool = next((t for t in TOOLS if t["key"] == key), None)
        if tool is None:
            raise ValueError(f"Unknown tool: {key!r}")
        method = getattr(gl, tool["method"])
        params = data.get("params") or {}
        return lambda: method(**params)

    if "report" in data:
        key    = data["report"]
        report = next((r for r in REPORTS if r["key"] == key), None)
        if report is None:
            raise ValueError(f"Unknown report: {key!r}")
        formats    = set(data.get("formats") or ["markdown"])
        reuse_data = _resolve_reuse_data(data.get("reuse_data"))
        return lambda: gl._run_reports([report], formats=formats, reuse_data=reuse_data)

    if "reports" in data:
        keys    = data["reports"]
        reports = [next((r for r in REPORTS if r["key"] == k), None) for k in keys]
        missing = [k for k, r in zip(keys, reports) if r is None]
        if missing:
            raise ValueError(f"Unknown report key(s): {missing}")
        formats    = set(data.get("formats") or ["markdown"])
        reuse_data = _resolve_reuse_data(data.get("reuse_data"))
        return lambda: gl._run_reports([r for r in reports if r], formats=formats, reuse_data=reuse_data)

    raise ValueError("Message must include 'tool', 'report', or 'reports'")


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------
# Mounted last so all API routes above take precedence.

_reports_dir = Path("reports")
_reports_dir.mkdir(exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(_reports_dir)), name="reports")

_logs_dir = Path("logs")
_logs_dir.mkdir(exist_ok=True)   # ensure mount is always registered
app.mount("/logs", StaticFiles(directory=str(_logs_dir)), name="logs-files")

_public = Path("public")
if _public.is_dir():
    app.mount("/", StaticFiles(directory=str(_public), html=True), name="static")
