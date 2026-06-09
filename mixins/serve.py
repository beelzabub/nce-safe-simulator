import os
import signal
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from .utils import _clear, _pause

_PID_FILE    = Path(".server.pid")
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
    # Internal helpers
    # ------------------------------------------------------------------

    def _serve_port(self) -> int:
        return getattr(self, "serve_port", _DEFAULT_PORT)

    def _serve_status(self) -> Tuple[bool, Optional[int]]:
        """Return (is_running, pid). Removes stale PID file if process is dead."""
        if not _PID_FILE.exists():
            return False, None
        try:
            pid = int(_PID_FILE.read_text().strip())
            os.kill(pid, 0)   # signal 0 = check existence only
            return True, pid
        except (ValueError, ProcessLookupError, PermissionError):
            _PID_FILE.unlink(missing_ok=True)
            return False, None

    def _serve_start(self) -> int:
        """Start HTTP server in a detached background process. Returns PID."""
        port   = self._serve_port()
        public = Path("public")
        if not public.exists():
            raise FileNotFoundError(
                "public/ not found — run reports (which builds the site) first."
            )
        proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--directory", str(public)],
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
    # Interactive menu
    # ------------------------------------------------------------------

    def run_serve_menu(self):
        """Interactive start / stop / restart menu for the site preview server."""
        while True:
            _clear()
            running, pid = self._serve_status()
            port = self._serve_port()
            ip   = _local_ip()

            print("Site Server")
            print("=" * 50)
            if running:
                print(f"  Status : RUNNING  (pid {pid})")
                print(f"  URL    : http://localhost:{port}")
                print(f"           http://{ip}:{port}")
                print()
                print("  [1] Stop server")
                print("  [2] Restart server")
            else:
                print(f"  Status : stopped")
                print()
                print(f"  [1] Start server  (port {port}, public/)")
            print()
            print("  [b] back   [q] quit")
            print()

            raw = input("Select: ").strip().lower()

            if raw in ("q", "quit", "exit"):
                sys.exit(0)
            if raw in ("b", "back"):
                return

            if running:
                if raw == "1":
                    self._serve_stop()
                    print("  Server stopped.")
                    _pause()
                elif raw == "2":
                    self._serve_stop()
                    try:
                        new_pid = self._serve_start()
                        print(f"  Server restarted  (pid {new_pid})")
                        print(f"  http://localhost:{port}")
                        print(f"  http://{ip}:{port}")
                    except FileNotFoundError as exc:
                        print(f"  {exc}")
                    _pause()
                # loop → refresh status display
            else:
                if raw == "1":
                    try:
                        new_pid = self._serve_start()
                        print(f"  Server started  (pid {new_pid})")
                        print(f"  http://localhost:{port}")
                        print(f"  http://{ip}:{port}")
                    except FileNotFoundError as exc:
                        print(f"  {exc}")
                    _pause()
                # loop → refresh status display
