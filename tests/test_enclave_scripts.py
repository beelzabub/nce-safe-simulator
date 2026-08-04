"""Validation of the enclave lift-and-shift scripts (issues #263 / #264).

The bash originals (enclave-export.sh / enclave-import.sh) and their
PowerShell ports (.ps1) must stay behavior-identical and cross-compatible:
either OS's export must be importable by either OS's importer. These tests
pin that contract statically — phases, flags, artifact layout, checksum
format, and the shipped-importer bootstrap — so drift between the pairs
fails CI rather than surfacing on a transfer box inside an enclave.

Syntax is validated with the real interpreters where available: `bash -n`
always (bash is in the CI image), and a PowerShell AST parse when a
PowerShell is on PATH — `pwsh` (7+) or Windows PowerShell 5.1's
`powershell`, whichever exists. Neither is in the CI image, so the parse
tests skip there and the static contract tests carry the load; run them
locally before review. Linux install for the parse tests (portable
tarball, no package manager — pick linux-x64 or linux-arm64):

    mkdir -p ~/.local/pwsh && curl -fsSL \
      https://github.com/PowerShell/PowerShell/releases/download/v7.4.6/powershell-7.4.6-linux-x64.tar.gz \
      | tar -xz -C ~/.local/pwsh && chmod +x ~/.local/pwsh/pwsh
    PATH=~/.local/pwsh:$PATH python -m pytest tests/test_enclave_scripts.py

On Windows, no install needed — the built-in `powershell` (5.1) is picked
up automatically, and validating against 5.1 is exactly the floor these
scripts declare.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


# pwsh (PowerShell 7+) or Windows PowerShell 5.1 — whichever this box has.
# 5.1 is the declared floor, so parsing with it is the strongest check.
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@pytest.mark.skipif(
    POWERSHELL is None,
    reason="no PowerShell on PATH — see this module's docstring for the Linux install",
)
@pytest.mark.parametrize("name", sorted(PS))
def test_powershell_ast_parses(name):
    check = (
        "$t=$null;$e=$null;"
        "[System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e)|Out-Null;"
        "if($e){$e|ForEach-Object{Write-Error $_.Message};exit 1}" % (SCRIPTS / name)
    )
    subprocess.run([POWERSHELL, "-NoProfile", "-Command", check], check=True)


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
def test_ps_stderr_redirects_only_in_tolerant_helper(name):
    """WinPS 5.1 + $ErrorActionPreference='Stop' promotes redirected native
    stderr (2>$null / 2>&1) into a terminating NativeCommandError — git's
    success chatter (a wiki fetch's "From <url>" ref summary) killed real
    exports on the exact box the ports target. Stderr may only be discarded
    inside Invoke-GitTolerant, which relaxes the preference around the call
    (callers still branch on $LASTEXITCODE)."""
    for line in _code_lines(PS[name]):
        if re.search(r"2>\s*(\$null|&1)", line):
            assert "@GitArgs" in line, f"bare native stderr redirect: {line.strip()}"


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
        # Real curl streams the large package transfers WinPS 5.1's web
        # cmdlets drop; probed as curl.exe first because bare 'curl' is an
        # Invoke-WebRequest alias there, plain curl on pwsh/Linux.
        assert "Get-Command curl.exe, curl -CommandType Application" in text


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
        assert "--tags" in text
        # origin/HEAD must never enter the bundle: gits up to at least 2.46
        # write the symref dereferenced (a duplicate entry under its target
        # name), and cloning such a bundle fails with "multiple updates for
        # ref ... not allowed". Neither --remotes=origin nor --exclude is
        # safe there — the refs must be enumerated explicitly with the
        # symref filtered out.
        assert "--remotes=origin" not in text
        assert re.search(r"for-each-ref --format='?%\(refname\)'? refs/remotes/origin", text)
        assert "refs/remotes/origin/HEAD" in text
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


def test_import_rewrite_committer_parity():
    """Targets enforcing GitLab's 'committer restriction' push rule (committer
    email must be a verified email of the pushing account) reject a
    transferred history wholesale. Both importers expose an opt-in authorship
    rewrite — applied to the repo AND wiki mirrors before push — built on
    filter-branch, which ships inside git (nothing to install on an enclave
    box)."""
    assert "--rewrite-committer" in IMPORT_SH
    assert "$RewriteCommitter" in IMPORT_PS
    # --sign-commits / -SignCommits: same history pass also satisfies the
    # "reject unsigned commits" push rule, signing with the key matching the
    # (possibly rewritten) committer identity.
    assert "--sign-commits" in IMPORT_SH
    assert "$SignCommits" in IMPORT_PS
    for text, rewriter in ((IMPORT_SH, "history_filter"), (IMPORT_PS, "Invoke-HistoryFilter")):
        assert "FILTER_BRANCH_SQUELCH_WARNING" in text
        assert "--tag-name-filter" in text
        assert """git commit-tree -S "$@\"""" in text
        # definition + repo call + wiki call
        assert len(re.findall(re.escape(rewriter), text)) >= 3, rewriter


@pytest.mark.skipif(
    POWERSHELL is None,
    reason="no PowerShell on PATH — see this module's docstring for the Linux install",
)
def test_ps_history_filter_rewrites_author_and_committer(tmp_path):
    """Run the real Invoke-HistoryFilter on a scratch mirror and check the
    result. The env-filter must reach filter-branch as ONE argument: inside
    @(...) the comma binds tighter than '+', so a concatenation split across
    elements becomes a stray third element that filter-branch fatals on as a
    bad revision — and the committer half never gets exported, so the
    committer-restriction push rule keeps rejecting (first real enclave run,
    issue #270)."""
    m = re.search(r"function Invoke-HistoryFilter.*?\n\}", IMPORT_PS, re.S)
    assert m, "Invoke-HistoryFilter not found in enclave-import.ps1"
    src = tmp_path / "src"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Source Author",
        "GIT_AUTHOR_EMAIL": "author@source.example",
        "GIT_COMMITTER_NAME": "Source Committer",
        "GIT_COMMITTER_EMAIL": "committer@source.example",
    }
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    (src / "f.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(src), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(src), "commit", "-q", "-m", "one"], check=True, env=env)
    mirror = tmp_path / "mirror.git"
    subprocess.run(["git", "clone", "-q", "--mirror", str(src), str(mirror)], check=True)
    harness = tmp_path / "harness.ps1"
    harness.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "function Log([string]$msg) {}\n"
        "function Assert-Native([string]$what) {\n"
        "    if ($LASTEXITCODE -ne 0) { throw \"$what failed (exit $LASTEXITCODE)\" }\n"
        "}\n"
        "$RewriteCommitter = 'New Name <new@target.example>'\n"
        "$SignCommits = $false\n"
        "$RwName = 'New Name'; $RwEmail = 'new@target.example'\n"
        f"{m.group(0)}\n"
        f"Invoke-HistoryFilter '{mirror}'\n"
    )
    subprocess.run([POWERSHELL, "-NoProfile", "-File", str(harness)], check=True)
    out = subprocess.run(
        ["git", "-C", str(mirror), "log", "--format=%an|%ae|%cn|%ce", "main"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert out == "New Name|new@target.example|New Name|new@target.example"


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


def test_export_package_listing_paginates_parity():
    """GitLab caps per_page at 100 and a single request silently truncates
    larger sets — the 225-file apt-debs package lost every manifest-*.txt
    and imported registries 404'd the image build (#273). Both exporters
    must route every listing through their pager (definition + packages
    call + package_files call) and never issue a bare one-shot listing."""
    assert len(re.findall(r"\blist_paged\b", EXPORT_SH)) >= 3
    assert len(re.findall(r"\bGet-AllPages\b", EXPORT_PS)) >= 3
    for name, text in (("enclave-export.sh", EXPORT_SH), ("enclave-export.ps1", EXPORT_PS)):
        for line in _code_lines(text):
            if "package_files" in line or "package_type=generic" in line:
                assert "per_page" not in line, f"{name}: unpaginated listing: {line.strip()}"


class _PagedRegistryHandler(BaseHTTPRequestHandler):
    """Pages of {"file_name": ...} items — the real 225-file apt-debs shape."""
    TOTAL = 225

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        per = int(q.get("per_page", ["20"])[0])
        page = int(q.get("page", ["1"])[0])
        lo = (page - 1) * per
        items = [{"file_name": f"f-{i:03d}"} for i in range(lo, min(lo + per, self.TOTAL))]
        body = json.dumps(items).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def paged_registry():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _PagedRegistryHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/files"
    finally:
        srv.shutdown()


def test_sh_pager_fetches_all_pages(paged_registry):
    """Run the real list_paged against a 225-item endpoint: all three pages
    must come back, in order, as one line per item."""
    m = re.search(r"list_paged\(\) \{.*?\n\}", EXPORT_SH, re.S)
    assert m, "list_paged not found in enclave-export.sh"
    script = (
        "auth=()\n"
        f"{m.group(0)}\n"
        f"list_paged '{paged_registry}' "
        "'import json,sys; [print(f[\"file_name\"]) for f in json.load(sys.stdin)]'\n"
    )
    out = subprocess.run(
        ["bash", "-c", script], check=True, capture_output=True, text=True
    ).stdout.split()
    assert len(out) == 225
    assert out[0] == "f-000" and out[-1] == "f-224"


@pytest.mark.skipif(
    POWERSHELL is None,
    reason="no PowerShell on PATH — see this module's docstring for the Linux install",
)
def test_ps_pager_fetches_all_pages(paged_registry, tmp_path):
    """Same 225-item endpoint through the real Get-AllPages."""
    m = re.search(r"function Get-AllPages.*?\n\}", EXPORT_PS, re.S)
    assert m, "Get-AllPages not found in enclave-export.ps1"
    harness = tmp_path / "pager.ps1"
    harness.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "$Headers = @{}\n"
        f"{m.group(0)}\n"
        f"(Get-AllPages '{paged_registry}') | ForEach-Object {{ $_.file_name }}\n"
    )
    out = subprocess.run(
        [POWERSHELL, "-NoProfile", "-File", str(harness)],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    assert len(out) == 225
    assert out[0] == "f-000" and out[-1] == "f-224"


def test_package_transfer_retry_parity():
    """One transient TLS reset mid-file (seen on gitlab.com: WinPS 5.1
    IOException 'decryption operation failed', repeatably on the ~120 MB
    quarto .deb) must not abort a whole transfer: all four scripts retry
    each package download/upload with backoff. Exporters must also discard
    partial downloads — SHA256SUMS is computed FROM staged files, so a
    partial left behind would checksum as 'valid'."""
    assert "fetch_with_retry" in EXPORT_SH
    assert "rm -f" in EXPORT_SH
    assert "Invoke-DownloadWithRetry" in EXPORT_PS
    assert "Remove-Item -Force" in EXPORT_PS
    assert "upload_with_retry" in IMPORT_SH
    assert "Invoke-UploadWithRetry" in IMPORT_PS


def test_ps_large_transfers_use_real_curl():
    """WinPS 5.1's SChannel-backed web cmdlets reproducibly drop long TLS
    streams, so neither package phase may move file bodies with them —
    both stream through the preflighted $CurlBin instead. (API JSON calls
    are small and stay on Invoke-RestMethod.)"""
    for name, text in PS.items():
        assert "$CurlBin" in text, name
        assert not re.search(r"Invoke-WebRequest .*-OutFile", text), name
        assert not re.search(r"Invoke-RestMethod .*-InFile", text), name


def test_importers_accept_txt_or_directory():
    assert 'tar -xf "$ARCHIVE"' in IMPORT_SH.replace("'", '"') or "tar -xf" in IMPORT_SH
    assert "tar -xf" in IMPORT_PS
    assert "-extracted" in IMPORT_SH and "-extracted" in IMPORT_PS


# ---------------------------------------------------------------------------
# Package sync (issue #295) — sha256 convergence, prune-by-default, and the
# protected-branch force-push preflight
# ---------------------------------------------------------------------------

def test_import_prune_is_default_with_opt_out_parity():
    """The archive is a complete snapshot of the source registry, so pruning
    destination extras is the DEFAULT; both importers expose the same
    opt-out flag."""
    assert "--no-prune" in IMPORT_SH
    assert re.search(r"(?m)^DO_REPO=1 DO_PACKAGES=1 DO_IMAGES=1 PRUNE=1$", IMPORT_SH)
    assert re.search(r"--no-prune\)\s*PRUNE=0", IMPORT_SH)
    assert "$NoPrune" in IMPORT_PS
    assert "[switch]$NoPrune" in IMPORT_PS


def test_import_sync_compares_content_not_names():
    """Skip decisions must be sha256 comparisons (a name-only skip-if-exists
    would silently keep stale bytes when content changes under an unchanged
    version — same-day re-capture). Both sides read the destination's
    file_sha256 and the archive's own SHA256SUMS."""
    for text in (IMPORT_SH, IMPORT_PS):
        assert "file_sha256" in text
        assert "SHA256SUMS" in text
        assert "package_files" in text


def test_import_package_listing_paginates_parity():
    """Same #273 rule as the exporters, now on the import side: every
    package listing goes through the pager, never a bare one-shot request."""
    assert len(re.findall(r"\blist_paged\b", IMPORT_SH)) >= 3
    assert len(re.findall(r"\bGet-AllPages\b", IMPORT_PS)) >= 3
    for name, text in (("enclave-import.sh", IMPORT_SH), ("enclave-import.ps1", IMPORT_PS)):
        for line in _code_lines(text):
            if "package_files" in line or "package_type=generic" in line:
                assert "per_page" not in line, f"{name}: unpaginated listing: {line.strip()}"


def test_import_uploads_before_deletes_parity():
    """A replaced file's new bytes must be live before its superseded
    entries are deleted — no window where the file is unserved."""
    assert IMPORT_SH.index('upload_with_retry "$DIR/packages/') \
        < IMPORT_SH.index('api_delete_with_retry "$API/projects/$ENC/packages/')
    assert IMPORT_PS.index("Invoke-UploadWithRetry (Join-Path $pkgRoot") \
        < IMPORT_PS.index("Invoke-DeleteWithRetry $d.Uri")


def test_import_force_push_preflight_parity():
    """A pre-created target (classic: UI 'Initialize repository with a
    README') holds a protected branch whose tip the bundle does not build
    on; the forced update is rejected and one rejected ref fails the ENTIRE
    push. Both importers must detect the collision up front — by ancestry
    (merge-base), not object existence — and name the fix."""
    for text in (IMPORT_SH, IMPORT_PS):
        assert "protected_branches" in text
        assert "allow_force_push" in text
        assert "merge-base" in text and "--is-ancestor" in text
        assert "Initialize repository with a README" in text


def test_import_sync_summary_parity():
    """Operators must see at a glance whether an import changed anything."""
    for text in (IMPORT_SH, IMPORT_PS):
        assert "Package sync:" in text
        for token in ("uploaded", "replaced", "skipped identical",
                      "stale entries removed", "pruned"):
            assert token in text, token


# The bash importer's plan logic is an embedded python heredoc; run the real
# thing against fixture archive/destination states and check the emitted plan.

def _plan_py():
    m = re.search(r"<<'PLAN_PY'\n(.*?)\nPLAN_PY", IMPORT_SH, re.S)
    assert m, "PLAN_PY heredoc not found in enclave-import.sh"
    return m.group(1)


def _run_plan(tmp_path, files, dest_rows, pkg_rows, prune=True):
    """files: {name/ver/file: bytes}; dest_rows: 7-tuples mirroring dest.tsv
    (pkg_id, name, version, file_name, file_id, sha256, created_at);
    pkg_rows: 3-tuples mirroring pkgs.tsv (pkg_id, name, version)."""
    root = tmp_path / "xfer"
    (root / "packages").mkdir(parents=True)
    sums = []
    for key, data in files.items():
        p = root / "packages" / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        sums.append(f"{hashlib.sha256(data).hexdigest()}  ./packages/{key}")
    (root / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    dest_tsv = tmp_path / "dest.tsv"
    dest_tsv.write_text("".join("\t".join(map(str, r)) + "\n" for r in dest_rows))
    pkgs_tsv = tmp_path / "pkgs.tsv"
    pkgs_tsv.write_text("".join("\t".join(map(str, r)) + "\n" for r in pkg_rows))
    out = subprocess.run(
        [sys.executable, "-", str(root), str(dest_tsv), str(pkgs_tsv),
         "1" if prune else "0"],
        input=_plan_py(), capture_output=True, text=True, check=True,
    )
    return [tuple(line.split("\t")) for line in out.stdout.splitlines()]


def test_plan_absent_file_uploads_as_new(tmp_path):
    plan = _run_plan(tmp_path, {"a/1.0/f.txt": b"x"}, [], [])
    assert plan == [("UPLOAD", "a/1.0/f.txt", "new")]


def test_plan_identical_skips_and_sweeps_duplicates(tmp_path):
    h = hashlib.sha256(b"x").hexdigest()
    dest = [
        (7, "a", "1.0", "f.txt", 11, h, "2026-08-01T00:00:00Z"),
        (7, "a", "1.0", "f.txt", 12, h, "2026-08-02T00:00:00Z"),  # newest
    ]
    plan = _run_plan(tmp_path, {"a/1.0/f.txt": b"x"}, dest, [(7, "a", "1.0")])
    assert ("SKIP", "a/1.0/f.txt", "identical") in plan
    assert ("DELETE_FILE", "7", "11", "a/1.0/f.txt", "duplicate") in plan
    assert not any(p[0] == "UPLOAD" for p in plan)
    assert not any(p[0] == "DELETE_FILE" and p[2] == "12" for p in plan), \
        "the newest identical entry must survive the sweep"


def test_plan_changed_bytes_replace_and_delete_superseded(tmp_path):
    dest = [(7, "a", "1.0", "f.txt", 11,
             hashlib.sha256(b"old").hexdigest(), "2026-08-01T00:00:00Z")]
    plan = _run_plan(tmp_path, {"a/1.0/f.txt": b"new"}, dest, [(7, "a", "1.0")])
    assert plan[0] == ("UPLOAD", "a/1.0/f.txt", "changed")
    assert ("DELETE_FILE", "7", "11", "a/1.0/f.txt", "superseded") in plan


def test_plan_prunes_stale_file_and_whole_package(tmp_path):
    h = hashlib.sha256(b"x").hexdigest()
    dest = [
        (7, "a", "1.0", "f.txt", 11, h, "t"),
        (7, "a", "1.0", "gone.txt", 12, "b" * 64, "t"),   # stale file, kept pkg
        (9, "old", "0.1", "z.bin", 21, "d" * 64, "t"),     # whole pkg stale
    ]
    plan = _run_plan(tmp_path, {"a/1.0/f.txt": b"x"}, dest,
                     [(7, "a", "1.0"), (9, "old", "0.1")])
    assert ("DELETE_FILE", "7", "12", "a/1.0/gone.txt", "pruned") in plan
    assert ("DELETE_PKG", "9", "old/0.1") in plan
    assert not any(p[0] == "DELETE_PKG" and p[1] == "7" for p in plan), \
        "a package with surviving files is pruned file-wise, not wholesale"


def test_plan_zero_file_stale_package_pruned(tmp_path):
    plan = _run_plan(tmp_path, {"a/1.0/f.txt": b"x"}, [], [(9, "ghost", "0.0")])
    assert ("DELETE_PKG", "9", "ghost/0.0") in plan


def test_plan_no_prune_keeps_destination_extras(tmp_path):
    dest = [(9, "old", "0.1", "z.bin", 21, "d" * 64, "t")]
    plan = _run_plan(tmp_path, {"a/1.0/f.txt": b"x"}, dest,
                     [(9, "old", "0.1")], prune=False)
    assert all(p[0] == "UPLOAD" for p in plan)


def test_plan_rerun_of_unchanged_archive_is_all_skips(tmp_path):
    files = {"a/1.0/f.txt": b"x", "b/2.0/g.bin": b"y"}
    dest = [
        (1, "a", "1.0", "f.txt", 11, hashlib.sha256(b"x").hexdigest(), "t"),
        (2, "b", "2.0", "g.bin", 21, hashlib.sha256(b"y").hexdigest(), "t"),
    ]
    plan = _run_plan(tmp_path, files, dest, [(1, "a", "1.0"), (2, "b", "2.0")])
    assert all(p[0] == "SKIP" for p in plan)


# ---------------------------------------------------------------------------
# Live end-to-end round-trip (opt-in): export the simulator, recreate it in
# GitLab as <group>/nce-safe-simulator-<username>
# ---------------------------------------------------------------------------
#
# Gated behind NCE_ENCLAVE_E2E=1 + GITLAB_TOKEN (api scope — it CREATES a
# project) so the normal suite stays offline. Each runner gets their own
# evidence project named after their GitLab username; reruns are idempotent
# (the importer is). The project is left in place for review — delete it in
# the UI when done. Images are excluded (--no-images) so no docker or
# gigabyte transfers are involved; repo, wiki, and packages are the point.
#
# Staging + artifact need ~0.6 GB; pytest's tmp dir is used by default, but
# if your system temp is small (tmpfs), point NCE_E2E_WORKDIR at a roomier
# directory — its contents are left behind for inspection.
#
# Uses the PowerShell scripts when a PowerShell is on PATH (that is what's
# under review), the bash pair otherwise.

E2E_ENABLED = os.environ.get("NCE_ENCLAVE_E2E") == "1" and bool(os.environ.get("GITLAB_TOKEN"))


def _api(url, token, method="GET"):
    req = urllib.request.Request(url, method=method, headers={"PRIVATE-TOKEN": token})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _origin_parts():
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=SCRIPTS.parent, capture_output=True, text=True, check=True,
    ).stdout.strip()
    m = re.match(r"^(?P<scheme>https?)://(?P<host>[^/]+)/(?P<path>.+?)(\.git)?$", remote)
    if not m:
        m = re.match(r"^[^@]+@(?P<host>[^:]+):(?P<path>.+?)(\.git)?$", remote)
        return "https", m.group("host"), m.group("path")
    return m.group("scheme"), m.group("host"), m.group("path")


@pytest.mark.skipif(
    not E2E_ENABLED,
    reason="set NCE_ENCLAVE_E2E=1 and GITLAB_TOKEN (api scope) for the live round-trip",
)
def test_live_export_import_roundtrip(tmp_path):
    token = os.environ["GITLAB_TOKEN"]
    scheme, host, path = _origin_parts()
    api = f"{scheme}://{host}/api/v4"
    group, repo_name = path.rsplit("/", 1)

    username = _api(f"{api}/user", token)["username"]

    # Land evidence projects in the enclave-imports sandbox subgroup when it
    # exists (or wherever NCE_E2E_GROUP points): its creator holds Owner
    # there, so runners can DELETE their projects after review — Maintainer
    # on the parent group can create projects but not remove them.
    group_override = os.environ.get("NCE_E2E_GROUP")
    if group_override:
        group = group_override
    else:
        sandbox = f"{group}/enclave-imports"
        try:
            _api(f"{api}/groups/{urllib.parse.quote(sandbox, safe='')}", token)
            group = sandbox
        except Exception:
            pass
    target = f"{group}/{repo_name}-{username}"

    workdir = os.environ.get("NCE_E2E_WORKDIR")
    if workdir:
        tmp_path = Path(workdir)
        tmp_path.mkdir(parents=True, exist_ok=True)

    # Export → single .txt artifact (PowerShell scripts when available)
    if POWERSHELL:
        export = [POWERSHELL, "-NoProfile", "-File", str(SCRIPTS / "enclave-export.ps1"),
                  "-OutDir", str(tmp_path), "-NoImages"]
    else:
        export = ["bash", str(SCRIPTS / "enclave-export.sh"), "-o", str(tmp_path), "--no-images"]
    subprocess.run(export, check=True, timeout=900)
    artifact = next(tmp_path.glob("*.txt"))

    # Import → recreates the project as <group>/<repo>-<username>
    if POWERSHELL:
        imp = [POWERSHELL, "-NoProfile", "-File", str(SCRIPTS / "enclave-import.ps1"),
               "-TransferPath", str(artifact), "-GitLabUrl", f"{scheme}://{host}",
               "-Project", target]
    else:
        imp = ["bash", str(SCRIPTS / "enclave-import.sh"), "-d", str(artifact),
               "-u", f"{scheme}://{host}", "-p", target]
    subprocess.run(imp, check=True, timeout=900)

    # The recreated project must hold the goods
    enc = urllib.parse.quote(target, safe="")
    project = _api(f"{api}/projects/{enc}", token)
    assert project["default_branch"] == "main"
    assert project["package_registry_access_level"] == "public"
    branches = _api(f"{api}/projects/{enc}/repository/branches?per_page=100", token)
    assert any(b["name"] == "develop" for b in branches)
    packages = {p["name"] for p in _api(f"{api}/projects/{enc}/packages?per_page=100", token)}
    assert {"quarto", "weasyprint-apt-debs"} <= packages
