"""Tests for the self-hosted pip wheel closure (issue #271).

The enclave contract: every CI-built Dockerfile stage that installs Python
packages (runtime, diagram-builder) does so from the project's generic package
registry — package ``pip-wheels``, a full wheel closure captured by
scripts/capture-pip-wheels.sh from requirements.lock — with
``pip install --no-index``, never from pypi.org / files.pythonhosted.org. Only
the ops stage (never built in CI, AWS-deploy tooling) may still reach PyPI.
"""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = (REPO / "Dockerfile").read_text()
CAPTURE = (REPO / "scripts" / "capture-pip-wheels.sh").read_text()
REQ_TXT = (REPO / "requirements.txt").read_text()
LOCK = REPO / "requirements.lock"


def _stages():
    """{stage_name: body} with comment lines removed (mirrors test_apt_debs)."""
    no_comments = "\n".join(
        l for l in DOCKERFILE.splitlines() if not l.lstrip().startswith("#")
    )
    parts = re.split(r"(?m)^FROM\s+\S+(?:\s+AS\s+(\S+))?\s*$", no_comments)
    return {name or "_final": body for name, body in zip(parts[1::2], parts[2::2])}


def _lock_pins():
    pins = {}
    for line in LOCK.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s]+)$", line)
        if m:
            pins[m.group(1).lower().replace("_", "-")] = m.group(2)
    return pins


def test_ci_built_stages_pip_install_is_no_index_only():
    """CI-built stages may only `pip install` from the vendored wheelhouse
    (--no-index). A bare `pip install pkg` or `-r requirements.txt` would reach
    PyPI at build time — exactly the egress #271 removes."""
    for name, body in _stages().items():
        if name == "ops":  # AWS tooling, out of enclave scope
            continue
        for line in body.splitlines():
            if re.search(r"\bpip install\b", line):
                assert "--no-index" in line, (
                    f"stage {name} has a pip install without --no-index: "
                    f"{line.strip()!r} — CI-built stages must install from the "
                    f"pip-wheels registry package (issue #271)"
                )


def test_ci_built_stages_have_no_pypi_hosts():
    for name, body in _stages().items():
        if name == "ops":
            continue
        for host in ("pypi.org", "files.pythonhosted.org", "pythonhosted"):
            assert host not in body, f"stage {name} references {host}"


def test_runtime_installs_from_lock_not_txt():
    """The wheelhouse is captured from requirements.lock, so the runtime must
    install from the lock (pinned) — installing the unpinned requirements.txt
    would drift from what was captured."""
    runtime = _stages()["runtime"]
    assert re.search(r"pip install[^\n]*--no-index[^\n]*-r requirements\.lock", runtime), \
        "runtime stage must `pip install --no-index ... -r requirements.lock`"


def test_requirements_lock_exists_and_is_fully_pinned():
    assert LOCK.exists(), "requirements.lock missing — compile it (see capture-pip-wheels.sh)"
    for line in LOCK.read_text().splitlines():
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        assert "==" in s, f"requirements.lock has an unpinned line: {line!r}"


def test_lock_covers_every_requirements_txt_name():
    """Every direct requirement must appear pinned in the lock, or the
    wheelhouse would be missing a top-level package."""
    pins = _lock_pins()
    for raw in REQ_TXT.splitlines():
        name = raw.split("#", 1)[0].strip()
        if not name:
            continue
        base = re.split(r"[<>=!\[;]", name, 1)[0].strip().lower().replace("_", "-")
        assert base in pins, f"requirements.txt name {base!r} is not pinned in requirements.lock"


def test_jupyter_is_not_in_the_closure():
    """The jupyter metapackage was dropped (#271); it must not reappear via a
    lock recompile (nbformat's transitive jupyter-core is fine — different)."""
    assert "jupyter" not in [n for n in _lock_pins() if n == "jupyter"]
    assert "jupyter" not in REQ_TXT.split()


def test_pip_wheels_version_is_pinned():
    assert re.search(r"(?m)^ARG PIP_WHEELS_VERSION=\d{4}\.\d{2}\.\d{2}$", DOCKERFILE), \
        "PIP_WHEELS_VERSION must be pinned to a dated version at the top of the Dockerfile"


def test_dockerfile_fetch_matches_capture_package_path():
    """The Dockerfile must fetch the exact artifact the capture script uploads:
    pip-wheels/<version>/pip-wheels-<arch>.tar.gz."""
    assert "packages/generic/pip-wheels/" in DOCKERFILE
    assert "pip-wheels-${ARCH}.tar.gz" in DOCKERFILE
    assert "pip-wheels-$ARCH.tar.gz" in CAPTURE or 'pip-wheels-$ARCH.tar.gz' in CAPTURE


def test_capture_script_parses():
    subprocess.run(["bash", "-n", str(REPO / "scripts" / "capture-pip-wheels.sh")], check=True)
