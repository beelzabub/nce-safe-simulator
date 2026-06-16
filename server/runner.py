import ctypes
import io
import re
import sys
import threading
from typing import Callable, Optional

_thread_local = threading.local()

# Matches ANSI/VT100 escape sequences (CSI sequences and lone ESC codes).
# These are meaningful in a terminal but meaningless — and visually broken —
# in a browser <pre> block, so we strip them before buffering.
_ANSI_ESC = re.compile(r'\x1b(?:\[[0-9;]*[A-Za-z]|[^\[])')


class ThreadLocalWriter(io.TextIOBase):
    """sys.stdout replacement that routes writes to a per-thread callback.

    The main thread falls back to the original stdout so normal CLI output
    is unaffected. Worker threads set _thread_local.write_callback before
    calling print(); each line lands in their own output stream.
    """

    def __init__(self, original: object = None):
        self._original = original or sys.__stdout__

    def write(self, text: str) -> int:
        cb = getattr(_thread_local, "write_callback", None)
        if cb is not None:
            # Strip terminal control codes; treat bare \r as line separator
            # so carriage-return-overwrite patterns don't corrupt the next line.
            text = _ANSI_ESC.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
            buf = getattr(_thread_local, "write_buffer", "") + text
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                cb(line)
            _thread_local.write_buffer = buf
        else:
            self._original.write(text)
        return len(text)

    def flush(self) -> None:
        cb = getattr(_thread_local, "write_callback", None)
        if cb is not None:
            buf = getattr(_thread_local, "write_buffer", "")
            if buf:
                cb(buf)
                _thread_local.write_buffer = ""
        else:
            self._original.flush()

    @property
    def encoding(self):
        return self._original.encoding


_writer: Optional[ThreadLocalWriter] = None


def cancel_thread(thread: threading.Thread) -> None:
    """Raise KeyboardInterrupt inside a running thread (best-effort).

    Works at Python bytecode boundaries; won't interrupt a blocking C-level
    call (e.g. mid-flight requests.get), but the exception fires as soon as
    control returns to Python — typically within the next API call's response
    handling.  Safe to call on an already-finished thread (no-op).
    """
    if thread.is_alive():
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(thread.ident),
            ctypes.py_object(KeyboardInterrupt),
        )


def install_writer() -> None:
    """Install the thread-local writer as sys.stdout (idempotent)."""
    global _writer
    if not isinstance(sys.stdout, ThreadLocalWriter):
        _writer = ThreadLocalWriter(sys.stdout)
        sys.stdout = _writer


def run_job(
    fn: Callable[[], None],
    on_output: Callable[[str], None],
    on_done: Optional[Callable[[], None]] = None,
    on_error: Optional[Callable[[Exception], None]] = None,
) -> threading.Thread:
    """Run *fn* in a daemon thread, routing all print() output to *on_output*.

    on_done  — called (in the worker thread) when fn() returns normally.
    on_error — called (in the worker thread) when fn() raises; if omitted,
               on_done is called instead so the caller always gets a terminal
               signal.
    """
    def _target():
        _thread_local.write_callback = on_output
        _thread_local.write_buffer   = ""
        try:
            fn()
            sys.stdout.flush()
            if on_done is not None:
                on_done()
        except Exception as exc:
            sys.stdout.flush()
            if on_error is not None:
                on_error(exc)
            elif on_done is not None:
                on_done()
        finally:
            _thread_local.write_callback = None
            _thread_local.write_buffer   = ""

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    return t
