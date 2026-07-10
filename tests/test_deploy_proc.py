"""Tests for the live-streaming deploy subprocess runner (issue #225)."""
import sys

from server.deploy_proc import run_streaming


def test_run_streaming_captures_output_and_exit_zero(capsys):
    rc = run_streaming([sys.executable, "-c", "print('hello-stream')"], log=lambda *_: None)
    assert rc == 0
    assert "hello-stream" in capsys.readouterr().out


def test_run_streaming_returns_child_exit_code():
    rc = run_streaming([sys.executable, "-c", "import sys; sys.exit(3)"], log=lambda *_: None)
    assert rc == 3


def test_run_streaming_falls_back_without_pty(monkeypatch, capsys):
    # Simulate a platform with no pty module: run_streaming must still run the
    # command and return its exit code via the subprocess fallback.
    import builtins
    real_import = builtins.__import__

    def _no_pty(name, *a, **k):
        if name == "pty":
            raise ImportError("no pty here")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_pty)
    rc = run_streaming([sys.executable, "-c", "print('fallback')"], log=lambda *_: None)
    assert rc == 0
