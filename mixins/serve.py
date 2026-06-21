import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from .utils import _clear, _fmt_duration, _pause, _tee_to_log


def _site_log_path(label: str) -> Path:
    now = datetime.now()
    return (
        Path("logs")
        / now.strftime("%Y-%m-%d")
        / f"{now.strftime('%H-%M-%S')}_site-{label}.log"
    )

_PID_FILE     = Path(".server.pid")
_DEFAULT_PORT = 4645


def _local_ip() -> str:
    """Best-guess LAN/external IP for display — falls back to localhost."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


class ServeMixin:
    # ------------------------------------------------------------------
    # Server
    # ------------------------------------------------------------------

    def _serve_port(self) -> int:
        return getattr(self, "serve_port", _DEFAULT_PORT)

    def _serve_status(self) -> Tuple[bool, Optional[int]]:
        """Return (is_running, pid). Cleans up stale PID file if process is gone."""
        if not _PID_FILE.exists():
            return False, None
        try:
            pid = int(_PID_FILE.read_text().strip())
            os.kill(pid, 0)   # signal 0 = existence check only
            return True, pid
        except (ValueError, ProcessLookupError, PermissionError):
            _PID_FILE.unlink(missing_ok=True)
            return False, None

    def _serve_start(self) -> int:
        """Start the uvicorn server in a detached background process. Returns PID."""
        port = self._serve_port()
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app",
             "--port", str(port), "--host", "0.0.0.0"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,   # detach: survives NceGitLab exit
        )
        _PID_FILE.write_text(str(proc.pid))
        return proc.pid

    def _serve_stop(self) -> bool:
        """Stop the server. Returns True if it was running."""
        running, pid = self._serve_status()
        if not running:
            return False
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        _PID_FILE.unlink(missing_ok=True)
        return True

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _serve_build_frontend(self) -> bool:
        """Run `npm run build` in frontend/. Returns True on success, False if skipped."""
        frontend = Path("frontend")
        if not frontend.exists():
            return False
        if Path("public/app/index.html").exists():
            return True  # already built (e.g. pre-built in Docker image)
        print("\nBuilding frontend (npm run build)...\n")
        proc = subprocess.Popen(
            ["npm", "run", "build"],
            cwd=str(frontend),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            print(f"  {line}", end="", flush=True)
        rc = proc.wait()
        ok = rc == 0
        print(f"\n  {'OK' if ok else f'FAILED (exit {rc})'}")
        return ok

    def _site_build_interactive(self) -> bool:
        """Export all Marimo WASM notebooks. Returns True on success."""
        print("\nBuilding interactive (Marimo WASM)...\n")
        proc = subprocess.Popen(
            [sys.executable, "build_interactive.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            print(f"  {line}", end="", flush=True)
        rc = proc.wait()
        ok = rc == 0
        print(f"\n  {'OK' if ok else f'FAILED (exit {rc})'}")
        return ok

    def _site_build_static(self) -> bool:
        """Render the Quarto static site. Returns True on success."""
        data_files = list(Path("quarto-data").glob("*.json")) if Path("quarto-data").exists() else []
        if not data_files:
            print("\n  Cannot build: quarto-data/*.json not found.")
            print("  Run reports first to generate the data layer:")
            print("    python NceGitLab.py --report all")
            return False

        print("\nBuilding static (quarto render)...\n")
        proc = subprocess.Popen(
            ["quarto", "render", "--no-clean"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            print(f"  {line}", end="", flush=True)
        rc = proc.wait()
        ok = rc == 0
        print(f"\n  {'OK' if ok else f'FAILED (exit {rc})'}")
        return ok

    def _restore_data_layer(self) -> int:
        """Copy quarto-data/*.json → public/data/ after Quarto has cleaned public/.
        Returns the number of files copied."""
        src = Path("quarto-data")
        dst = Path("public/data")
        if not src.exists():
            return 0
        dst.mkdir(parents=True, exist_ok=True)
        count = 0
        for f in src.glob("*.json"):
            shutil.copy2(f, dst / f.name)
            count += 1
        return count

    def _site_build_all(self) -> Tuple[bool, bool]:
        """Run static, restore data layer, then interactive. Returns (marimo_ok, quarto_ok).

        Quarto cleans all of public/ before rendering, which wipes both
        public/interactive/ and public/data/.  Sequence:
          1. quarto render  — cleans + builds public/
          2. copy data/*.json → public/data/  (Quarto wiped it)
          3. build_interactive.py  — writes public/interactive/
        """
        print("\nBuilding all (static → data → interactive)...\n")
        t0 = time.monotonic()

        quarto_ok = self._site_build_static()

        n = self._restore_data_layer()
        print(f"\n  Restored {n} JSON file(s) to public/data/")

        marimo_ok = self._site_build_interactive()

        elapsed = time.monotonic() - t0
        print(f"  total: {_fmt_duration(elapsed)}")
        return marimo_ok, quarto_ok

    # ------------------------------------------------------------------
    # Clean
    # ------------------------------------------------------------------

    def _site_clean_interactive(self) -> bool:
        """Delete public/interactive/. Returns True if it existed."""
        target = Path("public/interactive")
        if target.exists():
            shutil.rmtree(target)
            return True
        return False

    def _site_clean_static(self) -> int:
        """Delete quarto output from public/, preserving interactive/ and data/.
        Returns count of top-level items removed."""
        public = Path("public")
        if not public.exists():
            return 0
        keep  = {"interactive", "data"}
        count = 0
        for item in list(public.iterdir()):
            if item.name not in keep:
                shutil.rmtree(item) if item.is_dir() else item.unlink()
                count += 1
        return count

    def _site_clean_all(self) -> bool:
        """Delete public/ entirely. Returns True if it existed."""
        target = Path("public")
        if target.exists():
            shutil.rmtree(target)
            return True
        return False

    # ------------------------------------------------------------------
    # Interactive menu
    # ------------------------------------------------------------------

    def run_site_menu(self):
        """Site sub-menu: build, clean, and server controls in one place."""
        while True:
            _clear()
            running, pid = self._serve_status()
            port = self._serve_port()
            ip   = _local_ip()

            print("Site")
            print("=" * 50)
            if running:
                print(f"  Server : RUNNING  (pid {pid})")
                print(f"           http://localhost:{port}")
                print(f"           http://{ip}:{port}")
            else:
                print(f"  Server : stopped")
            print()
            print("  Build")
            print("  [1] interactive   Marimo WASM → public/interactive/")
            print("  [2] static        quarto render → public/  (requires data/ from a report run)")
            print("  [3] all           quarto → restore data → interactive  (requires data/)")
            print()
            print("  Clean")
            print("  [4] interactive   Delete public/interactive/")
            print("  [5] static        Delete quarto output  (keep interactive/ data/)")
            print("  [6] all           Delete public/ entirely")
            print()
            print("  Server")
            if running:
                print("  [7] Stop server")
                print("  [8] Restart server")
            else:
                print(f"  [7] Start server  (port {port})")
            print()
            print("  [b] back   [q] quit")
            print()

            raw = input("Select: ").strip().lower()

            if raw in ("q", "quit", "exit"):
                sys.exit(0)
            if raw in ("b", "back"):
                return

            if raw == "1":
                log = _site_log_path("build-interactive")
                with _tee_to_log(log):
                    print(f"  log → {log}\n")
                    self._site_build_interactive()
                _pause()
            elif raw == "2":
                log = _site_log_path("build-static")
                with _tee_to_log(log):
                    print(f"  log → {log}\n")
                    self._site_build_static()
                _pause()
            elif raw == "3":
                log = _site_log_path("build-all")
                with _tee_to_log(log):
                    print(f"  log → {log}\n")
                    self._site_build_all()
                _pause()
            elif raw == "4":
                removed = self._site_clean_interactive()
                print("  Deleted public/interactive/" if removed else "  public/interactive/ not found.")
                _pause()
            elif raw == "5":
                n = self._site_clean_static()
                print(f"  Removed {n} item(s) from public/  (kept interactive/ data/).")
                _pause()
            elif raw == "6":
                removed = self._site_clean_all()
                print("  Deleted public/." if removed else "  public/ not found.")
                _pause()
            elif raw == "7":
                if running:
                    self._serve_stop()
                    print("  Server stopped.")
                else:
                    try:
                        new_pid = self._serve_start()
                        print(f"  Server started  (pid {new_pid})")
                        print(f"  http://localhost:{port}")
                        print(f"  http://{ip}:{port}")
                    except FileNotFoundError as exc:
                        print(f"  {exc}")
                _pause()
            elif raw == "8" and running:
                self._serve_stop()
                try:
                    new_pid = self._serve_start()
                    print(f"  Server restarted  (pid {new_pid})")
                    print(f"  http://localhost:{port}")
                    print(f"  http://{ip}:{port}")
                except FileNotFoundError as exc:
                    print(f"  {exc}")
                _pause()
            # all actions loop → menu refreshes with current state

    def run_serve_menu(self):
        """Backwards-compatible alias for run_site_menu."""
        self.run_site_menu()
