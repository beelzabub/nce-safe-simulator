"""Tests for the self-hosted apt-debs system packages (issue #269).

The enclave contract: every CI-built Dockerfile stage (frontend-builder,
diagram-builder, runtime, dev) installs system packages from the project's
generic package registry — package ``apt-debs``, captured by
scripts/capture-apt-debs.sh and fetched by scripts/fetch-apt-debs.py — never
from deb.debian.org or deb.nodesource.com. Only the ops stage (never built in
CI, AWS-deploy tooling) may still reach the public internet.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = (REPO / "Dockerfile").read_text()
CAPTURE = (REPO / "scripts" / "capture-apt-debs.sh").read_text()
FETCH = REPO / "scripts" / "fetch-apt-debs.py"


def _stages():
    """Split the Dockerfile into {stage_name: instruction body} with comment
    lines removed (the trailing unnamed ``FROM runtime`` re-select stage is
    empty and keyed '_final'). Comments may legitimately name the hosts the
    build no longer contacts; only instructions matter here."""
    no_comments = "\n".join(
        l for l in DOCKERFILE.splitlines() if not l.lstrip().startswith("#")
    )
    parts = re.split(r"(?m)^FROM\s+\S+(?:\s+AS\s+(\S+))?\s*$", no_comments)
    # re.split yields [preamble, name1, body1, name2, body2, ...]
    stages = {}
    for name, body in zip(parts[1::2], parts[2::2]):
        stages[name or "_final"] = body
    return stages


def test_stage_split_sees_expected_stages():
    assert set(_stages()) == {
        "frontend-builder", "diagram-builder", "runtime", "ops", "dev", "_final",
    }


def test_ci_built_stages_apt_get_is_offline_only():
    """CI-built stages may use apt-get ONLY to install the already-fetched
    /tmp/debs files (apt orders Pre-Depends that a flat dpkg -i cannot). No
    `apt-get update` — the slim images ship without package indexes, so an
    incomplete closure fails loudly instead of reaching for a mirror."""
    allowed = re.compile(r"apt-get install -y --no-install-recommends /tmp/debs/\*\.deb")
    for name, body in _stages().items():
        if name == "ops":
            continue
        assert "apt-get update" not in body, f"stage {name} runs apt-get update"
        for line in body.splitlines():
            if "apt-get" in line:
                assert allowed.search(line), (
                    f"stage {name} has a non-offline apt-get use: {line.strip()!r} "
                    f"— CI-built stages must install debs from the apt-debs "
                    f"registry package (issue #269)"
                )


def test_ci_built_stages_have_no_external_package_hosts():
    for name, body in _stages().items():
        if name == "ops":
            continue
        for host in ("deb.debian.org", "deb.nodesource.com", "github.com"):
            assert host not in body, f"stage {name} references {host}"


def test_dockerfile_layers_exist_in_capture_script():
    """Every layer the Dockerfile fetches must be one the capture script
    publishes (grab <layer> ...), or image builds 404 on the manifest."""
    fetched = set(re.findall(r'fetch-apt-debs\.py\s+"\$PKG_PROJECT"\s+"\$APT_DEBS_VERSION"\s+\\?\s*(\w+)', DOCKERFILE))
    captured = set(re.findall(r"(?m)^grab (\w+) ", CAPTURE))
    assert fetched, "no fetch-apt-debs.py layers found in Dockerfile"
    assert fetched <= captured, f"Dockerfile fetches {fetched - captured} but capture-apt-debs.sh never captures it"


def test_apt_debs_version_is_pinned():
    assert re.search(r"(?m)^ARG APT_DEBS_VERSION=\d{4}\.\d{2}\.\d{2}$", DOCKERFILE), (
        "APT_DEBS_VERSION must be pinned to a dated version at the top of the Dockerfile"
    )


def test_capture_script_parses():
    subprocess.run(["bash", "-n", str(REPO / "scripts" / "capture-apt-debs.sh")], check=True)


def test_fetch_apt_debs_downloads_manifest_files(tmp_path):
    """fetch-apt-debs.py must download exactly the debs the manifest lists —
    exercised over file:// so no network is involved."""
    pkg = tmp_path / "registry" / "packages" / "generic" / "apt-debs" / "2099.01.01"
    pkg.mkdir(parents=True)
    (pkg / "manifest-graphviz-amd64.txt").write_text("a_1.0_amd64.deb\nb_2.0_all.deb\n")
    (pkg / "a_1.0_amd64.deb").write_bytes(b"deb-a")
    (pkg / "b_2.0_all.deb").write_bytes(b"deb-b")
    dest = tmp_path / "out"
    subprocess.run(
        [sys.executable, str(FETCH), (tmp_path / "registry").as_uri(),
         "2099.01.01", "graphviz", "amd64", str(dest)],
        check=True,
    )
    assert sorted(p.name for p in dest.iterdir()) == ["a_1.0_amd64.deb", "b_2.0_all.deb"]
    assert (dest / "a_1.0_amd64.deb").read_bytes() == b"deb-a"


def test_fetch_apt_debs_fails_on_missing_manifest(tmp_path):
    r = subprocess.run(
        [sys.executable, str(FETCH), (tmp_path).as_uri(), "2099.01.01",
         "graphviz", "amd64", str(tmp_path / "out")],
        capture_output=True,
    )
    assert r.returncode != 0


def test_capture_script_matches_dockerfile_stamp():
    """apt-debs cannot content-address its version (issue #296): its closure
    is defined by the layer package lists inside the capture script, not a
    single committed lock file, so a stale capture cannot 404 on its own.
    The Dockerfile therefore carries a capture-input stamp — the first 12
    hex of sha256 over scripts/capture-apt-debs.sh. Editing the script
    without re-capturing fails HERE: run `make capture-apt`, bump
    APT_DEBS_VERSION, and set the printed stamp."""
    import hashlib
    actual = hashlib.sha256(
        (REPO / "scripts" / "capture-apt-debs.sh").read_bytes()
    ).hexdigest()[:12]
    m = re.search(r"apt-debs capture-input: ([0-9a-f]{12})", DOCKERFILE)
    assert m, "capture-input stamp missing next to APT_DEBS_VERSION"
    assert m.group(1) == actual, (
        "scripts/capture-apt-debs.sh changed but the Dockerfile stamp did not "
        f"— run `make capture-apt`, bump APT_DEBS_VERSION, and set the stamp "
        f"to {actual}"
    )
