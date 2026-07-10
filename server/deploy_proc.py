"""Live-streaming subprocess runner for the deploy jobs (issue #225).

The ECS/EKS deploys shell out to ``make`` → ``cdk`` → ``node``. When those
children's stdout is an ordinary pipe/file (as it is under the durable job
engine, whose stdout is a log file), they **block-buffer** — so a deploy would
show its output in one burst at the end instead of live. Attaching the child to
a **pseudo-tty** makes those line-oriented tools flush per line, so the job's log
window streams progress in real time.

``run_streaming`` reads the pty and writes to ``sys.stdout`` (which the CLI sets
line-buffered), so each chunk lands in the durable job log as it arrives.
"""
import os
import subprocess
import sys


def run_streaming(argv, *, log=print) -> int:
    """Run *argv*, streaming combined stdout/stderr live, and return its exit code.

    The child runs under a pseudo-tty so line-oriented tools (make/cdk/node)
    flush per line instead of block-buffering to a pipe. Falls back to inherited
    stdout where a pty isn't available (non-Unix).
    """
    log(f"$ {' '.join(argv)}")

    try:
        import pty
    except Exception:
        # No pty (e.g. non-Unix) — inherit stdout; output may be chunkier.
        return subprocess.run(argv).returncode

    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(argv, stdout=slave, stderr=slave, close_fds=True)
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
