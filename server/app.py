import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from mixins.reports import REPORTS
from mixins.tools import TOOLS
from server.constraints import READONLY_TOOLS, _TOOL_GROUP

app = FastAPI(title="NCE Safe Simulator")

# Exclusive lock for the fetch-data phase — only one data snapshot at a time.
_report_data_lock = threading.Lock()


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
# Static file serving
# ---------------------------------------------------------------------------
# Mounted last so all API routes above take precedence.
# Skipped gracefully if public/ hasn't been built yet.

_public = Path("public")
if _public.is_dir():
    app.mount("/", StaticFiles(directory=str(_public), html=True), name="static")
