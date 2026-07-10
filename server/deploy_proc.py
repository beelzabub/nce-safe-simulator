"""Live-streaming subprocess runner for the deploy jobs (issue #225).

The ECS/EKS deploys shell out to ``make`` → ``cdk`` → ``node``. When those
children's stdout is an ordinary pipe/file (as it is under the durable job
engine, whose stdout is a log file), they **block-buffer** — so a deploy would
show its output in one burst at the end instead of live. Attaching the child to
a **pseudo-tty** makes those line-oriented tools flush per line, so the job's log
window streams progress in real time.

``run_streaming`` reads the pty and writes to ``sys.stdout`` (which the CLI sets
line-buffered), so each chunk lands in the durable job log as it arrives.

The pty has a side effect (issue #233): cdk detects a terminal and renders its
interactive "bar" progress view — in-place rewrites via cursor-movement escapes
that flatten into garbage in the job pane and the on-disk log. So the child env
sets ``CI=true`` (cdk's ``--ci`` defaults from it, switching progress to
line-by-line CloudFormation *events*) and ``NO_COLOR=1`` (cdk/kubectl/helm).
Only app-driven jobs pass through here — a manual ``make -C cdk ...`` in a real
terminal keeps the interactive bar.
"""
import os
import subprocess
import sys


def _job_env() -> dict:
    """Child env for app-driven deploy subprocesses: non-interactive, no color."""
    return {**os.environ, "CI": "true", "NO_COLOR": "1"}


def run_streaming(argv, *, log=print) -> int:
    """Run *argv*, streaming combined stdout/stderr live, and return its exit code.

    The child runs under a pseudo-tty so line-oriented tools (make/cdk/node)
    flush per line instead of block-buffering to a pipe — with ``CI=true`` /
    ``NO_COLOR=1`` in its env so they still emit line-oriented, uncolored
    output (see module docstring). Falls back to inherited stdout where a pty
    isn't available (non-Unix).
    """
    log(f"$ {' '.join(argv)}")

    try:
        import pty
    except Exception:
        # No pty (e.g. non-Unix) — inherit stdout; output may be chunkier.
        return subprocess.run(argv, env=_job_env()).returncode

    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(
            argv, stdout=slave, stderr=slave, close_fds=True, env=_job_env()
        )
    except Exception:
        os.close(master)
        os.close(slave)
        raise
    os.close(slave)   # parent only reads from the master side

    try:
        while True:
            try:
                data = os.read(master, 4096)
            except OSError:
                break            # slave closed — child has exited
            if not data:
                break
            sys.stdout.write(data.decode("utf-8", "replace"))
            sys.stdout.flush()
    finally:
        os.close(master)

    return proc.wait()
