"""Validation of the enclave lift-and-shift scripts (issues #263 / #264).

The bash originals (enclave-export.sh / enclave-import.sh) and their
PowerShell ports (.ps1) must stay behavior-identical and cross-compatible:
either OS's export must be importable by either OS's importer. These tests
pin that contract statically — phases, flags, artifact layout, checksum
format, and the shipped-importer bootstrap — so drift between the pairs
fails CI rather than surfacing on a transfer box inside an enclave.

Syntax is validated with the real interpreters where available: `bash -n`
always (bash is in the CI image), a PowerShell AST parse only when `pwsh`
is on PATH (it is not in CI — the static contract tests carry the load
there).
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

EXPORT_SH = (SCRIPTS / "enclave-export.sh").read_text()
IMPORT_SH = (SCRIPTS / "enclave-import.sh").read_text()
EXPORT_PS = (SCRIPTS / "enclave-export.ps1").read_text()
IMPORT_PS = (SCRIPTS / "enclave-import.ps1").read_text()

ALL = {
    "enclave-export.sh": EXPORT_SH,
    "enclave-import.sh": IMPORT_SH,
    "enclave-export.ps1": EXPORT_PS,
    "enclave-import.ps1": IMPORT_PS,
}
PS = {k: v for k, v in ALL.items() if k.endswith(".ps1")}
SH = {k: v for k, v in ALL.items() if k.endswith(".sh")}


def _code_lines(text):
    """Lines with trailing comments stripped (naive but sufficient here)."""
    out = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0]
        if stripped.strip():
            out.append(stripped)
    return out


# ---------------------------------------------------------------------------
# Syntax — real interpreters
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(SH))
def test_bash_syntax(name):
    subprocess.run(["bash", "-n", str(SCRIPTS / name)], check=True)


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
@pytest.mark.parametrize("name", sorted(PS))
def test_powershell_ast_parses(name):
    check = (
        "$t=$null;$e=$null;"
        "[System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e)|Out-Null;"
        "if($e){$e|ForEach-Object{Write-Error $_.Message};exit 1}" % (SCRIPTS / name)
    )
    subprocess.run(["pwsh", "-NoProfile", "-Command", check], check=True)


# ---------------------------------------------------------------------------
# PowerShell portability — must run on Windows PowerShell 5.1
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(PS))
def test_ps_declares_51_floor(name):
    assert PS[name].splitlines()[0].strip() == "#Requires -Version 5.1"


@pytest.mark.parametrize("name", sorted(PS))
def test_ps_no_ps7_only_syntax(name):
    """`&&`/`||` chains and `??` don't exist in 5.1 — they'd die at parse
    time on the very box the ports were written for."""
    for line in _code_lines(PS[name]):
        assert " && " not in line and " || " not in line, line
        assert "??" not in line, line


@pytest.mark.parametrize("name", sorted(PS))
def test_ps_51_transfer_hygiene(name):
    text = PS[name]
    assert "$ErrorActionPreference = 'Stop'" in text
    # 5.1 defaults can exclude TLS 1.2, and its progress bars throttle
    # Invoke-WebRequest transfers badly.
    assert "Tls12" in text
    assert "$ProgressPreference = 'SilentlyContinue'" in text


# ---------------------------------------------------------------------------
# Preflight — every script checks its tools up front
# ---------------------------------------------------------------------------

def test_sh_preflight_tool_lists():
    for text in SH.values():
        assert re.search(r"for tool in git curl python3 tar sha256sum", text)
        assert 'BASH_VERSION' in text  # rejects plain sh with a clear message


def test_ps_preflight_tool_lists():
    for text in PS.values():
        assert re.search(r"@\('git',\s*'tar'\)", text)
        assert "Get-Command docker" in text  # contextual, image phases only


# ---------------------------------------------------------------------------
# Cross-pair contract — what makes .sh and .ps1 artifacts interchangeable
# ---------------------------------------------------------------------------

def test_artifact_naming_parity():
    assert '"$REPO_NAME-$STAMP.txt"' in EXPORT_SH or "$REPO_NAME-$STAMP.txt" in EXPORT_SH
    assert '"$RepoName-$Stamp.txt"' in EXPORT_PS
    assert "date +%Y-%m-%d" in EXPORT_SH
    assert "yyyy-MM-dd" in EXPORT_PS


def test_both_exporters_ship_both_importers():
    """The bootstrap contract: a receiving box has ONLY the .txt, so both
    importers must ride at the artifact top level regardless of which OS
    exported."""
    for text, copier in ((EXPORT_SH, "cp -p"), (EXPORT_PS, "Copy-Item")):
        for importer in ("enclave-import.sh", "enclave-import.ps1"):
            assert re.search(re.escape(copier) + r".*" + re.escape(importer), text), (
                f"exporter must ship {importer}"
            )


def test_checksum_format_cross_compatible():
    # bash writes/verifies with sha256sum; the PS side must emit the same
    # "<lowercase hash><2 spaces>./<path>" lines (unix newlines, no BOM)
    # and parse them back.
    assert "sha256sum > SHA256SUMS" in EXPORT_SH.replace("  ", " ") or "SHA256SUMS" in EXPORT_SH
    assert '"{0}  {1}"' in EXPORT_PS
    assert ".Hash.ToLower()" in EXPORT_PS
    assert "[IO.File]::WriteAllText" in EXPORT_PS  # no BOM, controlled newlines
    assert "sha256sum --quiet -c SHA256SUMS" in IMPORT_SH
    assert "[0-9a-f]{64}" in IMPORT_PS


def test_bundle_refspec_parity():
    """Bundles carry origin's refs; importers must map them back to heads."""
    for text in (EXPORT_SH, EXPORT_PS):
        assert "--remotes=origin" in text and "--tags" in text
        assert "refs/enclave-wiki/" in text
    for text in (IMPORT_SH, IMPORT_PS):
        assert "+refs/remotes/origin/*:refs/heads/*" in text
        assert "+refs/tags/*:refs/tags/*" in text
        assert "+refs/enclave-wiki/*:refs/heads/*" in text


def test_base_image_lists_identical():
    pat = re.compile(r"(python:3\.11-slim|python:3\.11|node:20-slim|gcr\.io/kaniko-project/executor:debug)")
    sh_set = set(pat.findall(EXPORT_SH))
    ps_set = set(pat.findall(EXPORT_PS))
    assert sh_set == ps_set and len(sh_set) == 4


def test_image_tar_mapping_parity():
    for text in (IMPORT_SH, IMPORT_PS):
        assert "runtime.tar" in text
        assert "dev.tar" in text
        assert "base-" in text          # base images load-only, never pushed
        assert "image-refs.txt" in text
        assert "container_registry_image_prefix" in text
        assert "--password-stdin" in text


def test_import_phases_and_flags_parity():
    # bash long options ↔ PowerShell switch params, same defaults
    assert '--skip-repo' in IMPORT_SH and '--skip-packages' in IMPORT_SH and '--skip-images' in IMPORT_SH
    for switch in ("$SkipRepo", "$SkipPackages", "$SkipImages"):
        assert switch in IMPORT_PS
    assert 'DEFAULT_BRANCH="main"' in IMPORT_SH
    assert "$DefaultBranch = 'main'" in IMPORT_PS
    for text in (IMPORT_SH, IMPORT_PS):
        assert "packages/generic/" in text
        assert "package_registry_access_level" in text  # anonymous-pull enable
        assert "default_branch" in text
        assert "namespace_id" in text                   # create-if-absent path


def test_export_api_enumeration_parity():
    """Packages must be enumerated live (nothing hardcoded) by both."""
    for text in (EXPORT_SH, EXPORT_PS):
        assert "package_type=generic" in text
        assert "package_files" in text


def test_importers_accept_txt_or_directory():
    assert 'tar -xf "$ARCHIVE"' in IMPORT_SH.replace("'", '"') or "tar -xf" in IMPORT_SH
    assert "tar -xf" in IMPORT_PS
    assert "-extracted" in IMPORT_SH and "-extracted" in IMPORT_PS
