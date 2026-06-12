import io
import sys
import threading
from typing import Callable, Optional

_thread_local = threading.local()


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
