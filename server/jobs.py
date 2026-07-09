"""Durable background job engine (issue #214).

Jobs run as ``subprocess.Popen`` children owned by the server process, not as
in-thread workers tied to a WebSocket. Each job's stdout+stderr is tee'd to a
log file and a JSON manifest records its lifecycle. Because the job is a real OS
process in its own session/process group, and its state lives on disk, a job
survives WebSocket disconnects, page refreshes, re-logins, second browser tabs,
and even a server restart (the OS process keeps running; the manifest is
reconciled on startup).

This is the foundation the Deploy Options epic (#134) sits on: deploy/destroy
jobs mutate real cloud resources and must never be killed by a browser refresh.
Report runs migrate onto this engine separately (#219).

Manifest schema (``logs/jobs/<id>.json``)::

    id         str    e.g. "20260708-213045-a1b2c3"
    kind       str    job category (e.g. "report", "tool", later "deploy:ecs")
    label      str    human label (usually the tool/report key)
    params     dict   the request params that produced this job
    argv       list   the exact command executed
    pid        int    leader process id
    pgid       int    process-group id (== pid; start_new_session=True)
    state      str    running | done | error | cancelled | unknown
    started    str    ISO-8601 UTC
    finished   str    ISO-8601 UTC, or null while running
    exit_code  int    process exit code, or null (running / unknowable)

State meanings:
    done       exited 0
    error      exited non-zero
    cancelled  a cancel was requested via cancel()
    unknown    a manifest left "running" by a since-restarted server whose
               process is no longer alive — the terminal outcome was never
               recorded because the reaper thread died with the old server.
"""
import json
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# Where manifests and logs live. Under logs/ so it rides the existing /logs
# static mount and the same EFS volume in the cloud.
JOBS_DIR = Path("logs") / "jobs"

# How long to wait after SIGTERM before escalating to SIGKILL on cancel.
_TERM_GRACE_SECONDS = 10.0

# Terminal states — a job in any of these will never change again.
TERMINAL_STATES = frozenset({"done", "error", "cancelled", "unknown"})


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    """Owns the lifecycle of durable subprocess jobs.

    Thread-safe. A single module-level instance (``manager``) is shared by the
    FastAPI endpoints; tests construct their own against a tmp directory.
    """

    def __init__(self, jobs_dir=JOBS_DIR):
        self._dir = Path(jobs_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # id -> Popen, only for jobs THIS server process started. Absent for
        # jobs adopted after a restart (we can signal them but not wait() them).
        self._procs: dict = {}
        # ids for which a cancel was requested, so the reaper records "cancelled"
        # rather than "error" when the process exits non-zero from the signal.
        self._cancelling: set = set()

    # -- paths --------------------------------------------------------------

    def _manifest_path(self, job_id: str) -> Path:
        return self._dir / f"{job_id}.json"

    def _log_path(self, job_id: str) -> Path:
        return self._dir / f"{job_id}.log"

    # -- manifest io --------------------------------------------------------

    def _write_manifest(self, manifest: dict) -> None:
        path = self._manifest_path(manifest["id"])
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # atomic — a concurrent reader never sees a half-write

    def _read_manifest(self, job_id: str) -> "dict | None":
        path = self._manifest_path(job_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    # -- id -----------------------------------------------------------------

    @staticmethod
    def _new_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{os.urandom(3).hex()}"

    # -- process helpers ----------------------------------------------------

    @staticmethod
    def _pid_alive(pid) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but owned by another user
        return True

    @staticmethod
    def _signal_group(pgid, sig) -> None:
        if not pgid:
            return
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    # -- launch -------------------------------------------------------------

    def launch(self, argv, *, kind: str, label: str = None,
               params: dict = None, cwd=None, env=None, log_header=None) -> dict:
        """Start *argv* as a durable job and return its manifest.

        The process runs in its own session (``start_new_session=True``) so the
        whole tree can be signalled as a group on cancel. stdout and stderr are
        merged into ``logs/jobs/<id>.log``. A daemon reaper thread waits on the
        process and records the terminal state.

        *log_header* is an optional list of lines written to the log before the
        subprocess starts — used by the report/tool runner to echo the
        equivalent CLI command as the first output lines (issue #140), so the
        run record carries the exact command that reproduces it.
        """
        job_id = self._new_id()
        argv = [str(a) for a in argv]
        log_fh = self._log_path(job_id).open("w", encoding="utf-8", buffering=1)
        if log_header:
            for line in log_header:
                log_fh.write(f"{line}\n")
            log_fh.flush()

        manifest = {
            "id": job_id,
            "kind": kind,
            "label": label or kind,
            "params": params or {},
            "argv": argv,
            "pid": None,
            "pgid": None,
            "state": "running",
            "started": _utcnow_iso(),
            "finished": None,
            "exit_code": None,
        }

        try:
            proc = subprocess.Popen(
                argv,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                env=env,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            log_fh.write(f"failed to start job: {exc}\n")
            log_fh.close()
            manifest.update(state="error", finished=_utcnow_iso(), exit_code=None)
            self._write_manifest(manifest)
            return manifest

        manifest["pid"] = proc.pid
        manifest["pgid"] = os.getpgid(proc.pid)
        self._write_manifest(manifest)

        with self._lock:
            self._procs[job_id] = proc

        threading.Thread(
            target=self._reap, args=(job_id, proc, log_fh), daemon=True
        ).start()
        return manifest

    def _reap(self, job_id: str, proc: subprocess.Popen, log_fh) -> None:
        exit_code = proc.wait()
        try:
            log_fh.flush()
            log_fh.close()
        except Exception:
            pass
        with self._lock:
            cancelled = job_id in self._cancelling
            self._cancelling.discard(job_id)
            self._procs.pop(job_id, None)

        manifest = self._read_manifest(job_id) or {"id": job_id}
        if cancelled:
            state = "cancelled"
        elif exit_code == 0:
            state = "done"
        else:
            state = "error"
        manifest.update(state=state, finished=_utcnow_iso(), exit_code=exit_code)
        self._write_manifest(manifest)

    # -- cancel -------------------------------------------------------------

    def cancel(self, job_id: str) -> "dict | None":
        """Request cancellation of a running job. Returns the current manifest,
        or None if the job is unknown. No-op on an already-terminal job.

        SIGTERM is sent to the whole process group immediately; a background
        watcher escalates to SIGKILL after a grace period. Cancellation is an
        explicit action here — never a side effect of a socket disconnect.
        """
        manifest = self._read_manifest(job_id)
        if manifest is None:
            return None
        if manifest.get("state") in TERMINAL_STATES:
            return manifest

        with self._lock:
            self._cancelling.add(job_id)

        pgid = manifest.get("pgid") or manifest.get("pid")
        self._signal_group(pgid, signal.SIGTERM)
        threading.Thread(
            target=self._escalate, args=(job_id, pgid), daemon=True
        ).start()
        return self._read_manifest(job_id)

    def _escalate(self, job_id: str, pgid) -> None:
        deadline = time.time() + _TERM_GRACE_SECONDS
        while time.time() < deadline:
            if not self._pid_alive(pgid):
                break
            time.sleep(0.2)
        if self._pid_alive(pgid):
            self._signal_group(pgid, signal.SIGKILL)

        # If we own the process, the reaper records the terminal state. For an
        # adopted (post-restart) job there is no reaper, so record it here once
        # the process is gone.
        with self._lock:
            owned = job_id in self._procs
        if owned:
            return
        for _ in range(50):
            if not self._pid_alive(pgid):
                break
            time.sleep(0.2)
        manifest = self._read_manifest(job_id) or {"id": job_id}
        if manifest.get("state") not in TERMINAL_STATES:
            manifest.update(state="cancelled", finished=_utcnow_iso(), exit_code=None)
            self._write_manifest(manifest)

    # -- read ---------------------------------------------------------------

    def list_jobs(self) -> list:
        """All known jobs (live + recent), newest first."""
        jobs = []
        for mp in self._dir.glob("*.json"):
            m = self._read_manifest(mp.stem)
            if m:
                jobs.append(m)
        jobs.sort(key=lambda m: m.get("started") or "", reverse=True)
        return jobs

    def get_job(self, job_id: str, offset: int = 0) -> "dict | None":
        """Manifest plus the log tail from *offset* bytes.

        The returned ``offset`` is the new byte position to pass on the next
        poll, so a viewer (fresh page load, second tab, reattach after refresh)
        can resume streaming exactly where it left off.
        """
        manifest = self._read_manifest(job_id)
        if manifest is None:
            return None

        log_path = self._log_path(job_id)
        chunk = ""
        new_offset = max(0, offset)
        if log_path.is_file():
            size = log_path.stat().st_size
            if 0 <= offset < size:
                with log_path.open("rb") as f:
                    f.seek(offset)
                    data = f.read()
                chunk = data.decode("utf-8", errors="replace")
                new_offset = offset + len(data)
            else:
                new_offset = size

        return {
            **manifest,
            "log": chunk,
            "offset": new_offset,
            "running": manifest.get("state") == "running",
        }

    # -- startup reconciliation --------------------------------------------

    def reconcile(self) -> list:
        """Reconcile manifests left ``running`` by a previous server process.

        A job whose leader pid is dead is marked ``unknown`` (its outcome was
        never recorded). A job whose pid is still alive kept running across the
        restart — it is re-adopted by a watcher that records a terminal state
        when it eventually exits. Returns the ids whose state changed now.
        """
        changed = []
        for m in self.list_jobs():
            if m.get("state") != "running":
                continue
            job_id, pid = m["id"], m.get("pid")
            with self._lock:
                if job_id in self._procs:
                    continue  # a job this same process started; reaper owns it
            if self._pid_alive(pid):
                threading.Thread(
                    target=self._readopt, args=(job_id, pid), daemon=True
                ).start()
                continue
            m.update(state="unknown", finished=_utcnow_iso())
            self._write_manifest(m)
            changed.append(job_id)
        return changed

    def _readopt(self, job_id: str, pid) -> None:
        while self._pid_alive(pid):
            time.sleep(1.0)
        with self._lock:
            cancelling = job_id in self._cancelling
        if cancelling:
            return  # an explicit cancel is in flight; _escalate records 'cancelled'
        manifest = self._read_manifest(job_id) or {"id": job_id}
        if manifest.get("state") not in TERMINAL_STATES:
            # Exit code is unknowable for a process we didn't spawn.
            manifest.update(state="unknown", finished=_utcnow_iso())
            self._write_manifest(manifest)

    # -- retention ----------------------------------------------------------

    def prune(self, max_age_seconds: float) -> list:
        """Delete terminal jobs (manifest + log) older than *max_age_seconds*.

        Running jobs are never pruned. Returns the ids removed. A value <= 0
        disables pruning.
        """
        if max_age_seconds <= 0:
            return []
        cutoff = time.time() - max_age_seconds
        removed = []
        for m in self.list_jobs():
            if m.get("state") not in TERMINAL_STATES:
                continue
            mp = self._manifest_path(m["id"])
            try:
                if mp.stat().st_mtime >= cutoff:
                    continue
                self._log_path(m["id"]).unlink(missing_ok=True)
                mp.unlink(missing_ok=True)
                removed.append(m["id"])
            except OSError:
                continue
        return removed


# Module-level singleton shared by the FastAPI endpoints.
manager = JobManager()
