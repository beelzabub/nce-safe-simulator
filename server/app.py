import asyncio
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.staticfiles import StaticFiles

from mixins.reports import REPORTS
from mixins.tools import TOOLS
from server.constraints import READONLY_TOOLS, _TOOL_GROUP, check_conflict
from server.runner import install_writer, run_job

app = FastAPI(title="NCE Safe Simulator")

# Exclusive lock for the fetch-data phase — only one data snapshot at a time.
_report_data_lock = threading.Lock()

# Registry of currently-running job keys and its guard lock.
_running_jobs: set = set()
_running_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def _tool_payload(tool: dict) -> dict:
    key = tool["key"]
    return {
        "key":               key,
        "description":       tool["description"],
        "readonly":          key in READONLY_TOOLS,
        "parallelism_group": _TOOL_GROUP.get(key),
        "params": [
            {
                "name":     p["name"],
                "prompt":   p["prompt"],
                "type":     p["type"].__name__,
                "default":  p.get("default"),
                "optional": p.get("optional", False),
            }
            for p in tool.get("params", [])
        ],
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
def list_tools():
    return [_tool_payload(t) for t in TOOLS]


@app.get("/api/reports")
def list_reports():
    return [_report_payload(r) for r in REPORTS]


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

    job_key: Optional[str] = data.get("tool") or data.get("report")
    if not job_key:
        await websocket.send_json({"type": "error", "message": "Message must include 'tool' or 'report'"})
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

    try:
        fn = _build_job_fn(gl, data)
    except ValueError as exc:
        with _running_lock:
            _running_jobs.discard(job_key)
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def on_output(text: str) -> None:
        loop.call_soon_threadsafe(q.put_nowait, ("log", text))

    def on_done() -> None:
        loop.call_soon_threadsafe(q.put_nowait, ("done", None))

    def on_error(exc: Exception) -> None:
        loop.call_soon_threadsafe(q.put_nowait, ("error", str(exc)))

    install_writer()
    run_job(fn, on_output, on_done=on_done, on_error=on_error)

    try:
        while True:
            kind, payload = await q.get()
            if kind == "log":
                await websocket.send_json({"type": "log", "text": payload})
            elif kind == "done":
                await websocket.send_json({"type": "done"})
                break
            elif kind == "error":
                await websocket.send_json({"type": "error", "message": payload})
                break
    finally:
        with _running_lock:
            _running_jobs.discard(job_key)
        await websocket.close()


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
        formats = set(data.get("formats") or ["markdown"])
        return lambda: gl._run_reports([report], formats=formats)

    raise ValueError("Message must include 'tool' or 'report'")


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------
# Mounted last so all API routes above take precedence.
# Skipped gracefully if public/ hasn't been built yet.

_public = Path("public")
if _public.is_dir():
    app.mount("/", StaticFiles(directory=str(_public), html=True), name="static")
