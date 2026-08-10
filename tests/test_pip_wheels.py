"""Tests for the self-hosted pip wheel closure (issue #271).

The enclave contract: every CI-built Dockerfile stage that installs Python
packages (runtime, diagram-builder) does so from the project's generic package
registry — package ``pip-wheels``, a full wheel closure captured by
scripts/capture-pip-wheels.sh from requirements.lock — with
``pip install --no-index``, never from pypi.org / files.pythonhosted.org. Only
the ops stage (never built in CI, AWS-deploy tooling) may still reach PyPI.

OFFLINE=0 is the connected-dev escape hatch: a pip install without --no-index
is legal only as the fallback branch of the ``OFFLINE`` conditional, must
still pin via requirements.lock, and CI must never pass the flag — the
OFFLINE=1 default keeps every CI build on the wheelhouse.
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


def _run_blocks(body):
    """Each RUN command (backslash continuations joined) as one string."""
    blocks, cur = [], None
    for line in body.splitlines():
        if cur is None:
            if line.lstrip().startswith("RUN"):
                cur = [line]
        else:
            cur.append(line)
        if cur is not None and not line.rstrip().endswith("\\"):
            blocks.append("\n".join(cur))
            cur = None
    if cur:
        blocks.append("\n".join(cur))
    return blocks


OFFLINE_GUARD = 'if [ "$OFFLINE" = "1" ]'


def _lock_pins():
    pins = {}
    for line in LOCK.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s]+)$", line)
        if m:
            pins[m.group(1).lower().replace("_", "-")] = m.group(2)
    return pins


def test_online_pip_install_only_behind_the_offline_flag():
    """In CI-built stages, a `pip install` without --no-index (which would
    reach PyPI at build time — the egress #271 removes) is legal only as the
    OFFLINE=0 fallback: inside a RUN guarded by the OFFLINE conditional whose
    offline branch installs --no-index from the wheelhouse."""
    for name, body in _stages().items():
        if name == "ops":  # AWS tooling, out of enclave scope
            continue
        for block in _run_blocks(body):
            bare = [
                l.strip() for l in block.splitlines()
                if re.search(r"\bpip install\b", l) and "--no-index" not in l
            ]
            if not bare:
                continue
            assert OFFLINE_GUARD in block and re.search(
                r"pip install[^\n]*--no-index", block
            ), (
                f"stage {name} has a pip install without --no-index outside "
                f"the OFFLINE guard: {bare!r} — the default build must install "
                f"from the pip-wheels registry package (issue #271)"
            )


def test_online_pip_fallback_is_lock_pinned():
    """The OFFLINE=0 branch may reach PyPI but must install exactly what the
    wheelhouse would have — pinned via requirements.lock (-r or -c)."""
    for name, body in _stages().items():
        if name == "ops":
            continue
        for line in body.splitlines():
            if re.search(r"\bpip install\b", line) and "--no-index" not in line:
                assert re.search(r"-[rc] (/tmp/)?requirements\.lock", line), (
                    f"stage {name}: online pip fallback must pin via "
                    f"requirements.lock: {line.strip()!r}"
                )


def test_offline_is_the_default():
    """OFFLINE must default to 1 (the enclave contract); stage-level
    redeclarations must inherit it bare — an `ARG OFFLINE=0` anywhere would
    silently flip a default build online."""
    defaults = re.findall(r"(?m)^ARG OFFLINE(?:=(\S+))?\s*$", DOCKERFILE)
    assert defaults, "Dockerfile must declare ARG OFFLINE"
    assert all(d in ("", "1") for d in defaults), f"non-offline OFFLINE default: {defaults}"
    assert "1" in defaults, "top-level ARG OFFLINE=1 default is missing"


def test_ci_never_sets_offline():
    """CI must ride the offline default: no pipeline yaml may pass an OFFLINE
    build-arg — OFFLINE=0 in CI would rebuild the very egress #271 removed."""
    ci_files = [REPO / ".gitlab-ci.yml", *sorted((REPO / "ci-recipes").glob("*.yml"))]
    assert len(ci_files) > 1
    for f in ci_files:
        assert "OFFLINE" not in f.read_text(), f"{f.name} references OFFLINE"


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


def _req_txt_names():
    """Normalised distribution names declared in requirements.txt.

    Comments and extras are stripped, so prose in a `#` line can never be
    mistaken for a requirement.
    """
    names = set()
    for raw in REQ_TXT.splitlines():
        name = raw.split("#", 1)[0].strip()
        if not name:
            continue
        names.add(re.split(r"[<>=!\[;]", name, 1)[0].strip().lower().replace("_", "-"))
    return names


def test_lock_covers_every_requirements_txt_name():
    """Every direct requirement must appear pinned in the lock, or the
    wheelhouse would be missing a top-level package."""
    pins = _lock_pins()
    for base in sorted(_req_txt_names()):
        assert base in pins, f"requirements.txt name {base!r} is not pinned in requirements.lock"


def test_jupyter_is_not_in_the_closure():
    """The jupyter metapackage was dropped (#271); it must not reappear via a
    lock recompile. Transitive pieces are fine and deliberately allowed —
    nbformat pulls jupyter-core, and quarto's engine needs nbclient/ipykernel
    (which pull jupyter-client). Only the bare `jupyter` metapackage is barred.

    Matched against parsed requirement names, not raw words: requirements.txt
    carries comments explaining why each pin is there, and one of them names
    the jupyter engine in prose.
    """
    assert "jupyter" not in [n for n in _lock_pins() if n == "jupyter"]
    assert "jupyter" not in _req_txt_names()


def test_pip_wheels_version_is_content_derived():
    """No version variable exists to bump (issue #296): every install site
    derives the registry version from the lock file it is about to install —
    first 12 hex of sha256(requirements.lock) — and the capture script
    publishes under the identical derivation. A lock change without its
    capture therefore 404s the next image build instead of silently building
    against the stale closure."""
    assert "ARG PIP_WHEELS_VERSION" not in DOCKERFILE, \
        "the pip-wheels version must be derived from the lock, not pinned"
    assert "sha256sum requirements.lock | cut -c1-12" in DOCKERFILE      # runtime
    assert "sha256sum /tmp/requirements.lock | cut -c1-12" in DOCKERFILE  # diagram-builder
    assert 'VERSION="$(sha256sum "$REPO_DIR/requirements.lock" | cut -c1-12)"' in CAPTURE, \
        "capture script must publish under the same derivation the Dockerfile fetches"


def test_dockerfile_fetch_matches_capture_package_path():
    """The Dockerfile must fetch the exact artifact the capture script uploads:
    pip-wheels/<version>/pip-wheels-<arch>.tar.gz."""
    assert "packages/generic/pip-wheels/" in DOCKERFILE
    assert "pip-wheels-${ARCH}.tar.gz" in DOCKERFILE
    assert "pip-wheels-$ARCH.tar.gz" in CAPTURE or 'pip-wheels-$ARCH.tar.gz' in CAPTURE


def test_capture_script_parses():
    subprocess.run(["bash", "-n", str(REPO / "scripts" / "capture-pip-wheels.sh")], check=True)
