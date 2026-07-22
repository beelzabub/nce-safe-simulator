#Requires -Version 5.1
<#
.SYNOPSIS
  Export EVERYTHING needed to recreate this project on a GitLab instance in a
  separate network (issue #263) — PowerShell port of enclave-export.sh for
  Windows transfer boxes.

.DESCRIPTION
  Produces ONE artifact named <repo-name>-<YYYY-MM-DD>.txt (a gzipped tar; the
  .txt extension is the transfer-media naming convention) containing: a git
  bundle of every branch + tag, the project wiki (if any), every generic
  package in the package registry (enumerated live from the API), the
  runtime + dev container images, copies of both importers
  (enclave-import.sh / .ps1), and a SHA256SUMS manifest. The matching
  importers consume the .txt directly.

  Run it from any directory inside a clone of this git repo, on a box
  connected to the source GitLab.

  Requirements (preflight-checked): PowerShell 5.1+, git, tar
  (built into Windows 10+/Server 2019+); docker unless -NoImages.
  JSON parsing and sha256 hashing use PowerShell built-ins — no python or
  sha256sum needed (unlike the bash variant).

.PARAMETER OutDir
  Where to write the final .txt artifact (default: current directory).
  Staging happens in OutDir\<repo>-<date>-staging\.

.PARAMETER NoImages
  Skip container images (packages + repo only).

.PARAMETER WithBaseImages
  Also save the upstream base images the CI jobs and Docker builds pull
  (python:3.11, python:3.11-slim, node:20-slim, kaniko) for enclaves with no
  image proxy.

.NOTES
  Env: GITLAB_TOKEN — token with read_api, required to enumerate packages
  (file downloads themselves are anonymous; the listing API is not).
#>
[CmdletBinding()]
param(
    [string]$OutDir = ".",
    [switch]$NoImages,
    [switch]$WithBaseImages
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # WinPS 5.1: progress bars cripple download speed
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

function Log([string]$msg) { Write-Host "==> $msg" }
function Assert-Native([string]$what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}
function Invoke-GitTolerant {
    # git reports success chatter on stderr (e.g. a fetch's "From <url>" ref
    # summary). Under $ErrorActionPreference='Stop', WinPS 5.1 wraps redirected
    # native stderr in ErrorRecords and promotes them to terminating errors —
    # a SUCCESSFUL wiki fetch would kill the export. Relax the preference for
    # the one call whose stderr is deliberately discarded; callers branch on
    # $LASTEXITCODE as usual.
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & git @GitArgs 2>$null } finally { $ErrorActionPreference = $eap }
}

# ── Preflight: report ALL missing tools in one message ──────────────────────
$missing = @()
foreach ($tool in @('git', 'tar')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { $missing += $tool }
}
if (-not $NoImages -and -not (Get-Command docker -ErrorAction SilentlyContinue)) { $missing += 'docker' }
if ($missing.Count -gt 0) {
    Write-Error ("Missing required tools: {0}`nInstall them and rerun. (docker is only needed without -NoImages.)" -f ($missing -join ' '))
    exit 1
}
if (-not $env:GITLAB_TOKEN) {
    Write-Error "Set GITLAB_TOKEN (read_api scope) - needed to enumerate packages"
    exit 1
}
$Headers = @{ 'PRIVATE-TOKEN' = $env:GITLAB_TOKEN }

# ── Resolve repo root + API project URL from the clone's origin remote ──────
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$remote = (& git remote get-url origin).Trim()
Assert-Native 'git remote get-url origin'
if ($remote -match '^(?<scheme>https?)://(?<host>[^/]+)/(?<path>.+?)(\.git)?$') {
    $scheme = $Matches.scheme; $gitHost = $Matches.host; $path = $Matches.path
} elseif ($remote -match '^[^@]+@(?<host>[^:]+):(?<path>.+?)(\.git)?$') {
    $scheme = 'https'; $gitHost = $Matches.host; $path = $Matches.path
} else {
    throw "Unrecognized origin remote form: $remote"
}
$Api = "${scheme}://$gitHost/api/v4/projects/$([uri]::EscapeDataString($path))"

$RepoName = [IO.Path]::GetFileName($path)
$Stamp = Get-Date -Format 'yyyy-MM-dd'
$OutDir = (New-Item -ItemType Directory -Force -Path $OutDir).FullName
$Artifact = Join-Path $OutDir "$RepoName-$Stamp.txt"
$Stage = Join-Path $OutDir "$RepoName-$Stamp-staging"
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'repo'), (Join-Path $Stage 'packages') | Out-Null

# ── 1. Git repo: every branch + tag origin has, as one verified bundle ──────
Log "Fetching all refs from origin..."
& git fetch origin --prune --tags; Assert-Native 'git fetch'
Log "Writing repo bundle..."
$repoBundle = Join-Path $Stage 'repo/repo.bundle'
& git bundle create $repoBundle --remotes=origin --tags; Assert-Native 'git bundle create'
& git bundle verify $repoBundle | Out-Null; Assert-Native 'git bundle verify'
Log ("repo.bundle OK ({0:N0} MB)" -f ((Get-Item $repoBundle).Length / 1MB))

# ── 2. Project wiki (skipped if absent/empty). Fetched through this clone so
#      the repo's own git credentials apply. ────────────────────────────────
$wikiUrl = ($remote -replace '\.git$', '') + '.wiki.git'
Invoke-GitTolerant fetch $wikiUrl '+refs/heads/*:refs/enclave-wiki/*'
if ($LASTEXITCODE -eq 0 -and (& git for-each-ref 'refs/enclave-wiki/')) {
    Log "Writing wiki bundle..."
    $wikiBundle = Join-Path $Stage 'repo/wiki.bundle'
    & git bundle create $wikiBundle '--glob=refs/enclave-wiki/*'; Assert-Native 'git bundle create (wiki)'
    & git bundle verify $wikiBundle | Out-Null; Assert-Native 'git bundle verify (wiki)'
    foreach ($ref in (& git for-each-ref --format='%(refname)' 'refs/enclave-wiki/')) {
        & git update-ref -d $ref
    }
    Log "wiki.bundle OK"
} else {
    Log "No project wiki content - skipping wiki bundle"
}

# ── 3. Generic packages: enumerate via API so new packages/versions are
#      picked up automatically; download every file. ────────────────────────
Log "Enumerating generic packages..."
$packages = Invoke-RestMethod -Headers $Headers -Uri "$Api/packages?package_type=generic&per_page=100"
foreach ($pkg in $packages) {
    $files = Invoke-RestMethod -Headers $Headers -Uri "$Api/packages/$($pkg.id)/package_files?per_page=100"
    foreach ($f in $files) {
        $dest = Join-Path $Stage "packages/$($pkg.name)/$($pkg.version)/$($f.file_name)"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
        Log "  package $($pkg.name)/$($pkg.version)/$($f.file_name)"
        Invoke-WebRequest -Headers $Headers -Uri "$Api/packages/generic/$($pkg.name)/$($pkg.version)/$($f.file_name)" -OutFile $dest
    }
}

# ── 4. Container images ─────────────────────────────────────────────────────
if (-not $NoImages) {
    $imgDir = New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'images')
    $prefix = (Invoke-RestMethod -Headers $Headers -Uri $Api).container_registry_image_prefix
    Log "Container registry: $prefix (docker login may be required for private registries)"
    $refs = @(@('runtime', "${prefix}:latest"), @('dev', "$prefix/dev:latest"))
    foreach ($pair in $refs) {
        $short = $pair[0]; $ref = $pair[1]
        Log "  pulling $ref"
        & docker pull --platform linux/amd64 $ref | Out-Null; Assert-Native "docker pull $ref"
        & docker save $ref -o (Join-Path $imgDir "$short.tar"); Assert-Native "docker save $ref"
        Add-Content -Path (Join-Path $imgDir 'image-refs.txt') -Value "$short.tar $ref"
    }
    if ($WithBaseImages) {
        foreach ($base in @('python:3.11', 'python:3.11-slim', 'node:20-slim', 'gcr.io/kaniko-project/executor:debug')) {
            $fname = 'base-' + ($base -replace '[/:]', '_') + '.tar'
            Log "  pulling base $base"
            & docker pull --platform linux/amd64 $base | Out-Null; Assert-Native "docker pull $base"
            & docker save $base -o (Join-Path $imgDir $fname); Assert-Native "docker save $base"
            Add-Content -Path (Join-Path $imgDir 'image-refs.txt') -Value "$fname $base"
        }
    }
}

# ── 5. Ship both importers inside the artifact: the enclave box has ONLY the
#      .txt file, and the scripts' canonical home (this repo) is locked
#      inside repo.bundle. ──────────────────────────────────────────────────
Copy-Item (Join-Path $PSScriptRoot 'enclave-import.sh') (Join-Path $Stage 'enclave-import.sh')
Copy-Item (Join-Path $PSScriptRoot 'enclave-import.ps1') (Join-Path $Stage 'enclave-import.ps1')

# ── 6. Manifest + checksums (sha256sum -c compatible: "<hash>  ./<path>") ───
$head = Invoke-GitTolerant rev-parse origin/HEAD
if ($LASTEXITCODE -ne 0) { $head = & git rev-parse origin/develop }
$stageFiles = Get-ChildItem -Path $Stage -Recurse -File
$manifest = @(
    "source: $remote"
    "exported: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm')) UTC"
    "head: $head"
    "contents:"
) + ($stageFiles | ForEach-Object { '  ./' + $_.FullName.Substring($Stage.Length + 1).Replace('\', '/') } | Sort-Object)
Set-Content -Path (Join-Path $Stage 'MANIFEST.txt') -Value $manifest -Encoding utf8

$sums = Get-ChildItem -Path $Stage -Recurse -File | Where-Object Name -ne 'SHA256SUMS' | ForEach-Object {
    $rel = './' + $_.FullName.Substring($Stage.Length + 1).Replace('\', '/')
    "{0}  {1}" -f (Get-FileHash -Algorithm SHA256 -Path $_.FullName).Hash.ToLower(), $rel
} | Sort-Object
# Unix newlines + no BOM so `sha256sum -c` on a Linux importer accepts it
[IO.File]::WriteAllText((Join-Path $Stage 'SHA256SUMS'), (($sums -join "`n") + "`n"))

# ── 7. Single-file artifact ─────────────────────────────────────────────────
Log "Packing $Artifact ..."
& tar -czf $Artifact -C $Stage .; Assert-Native 'tar -czf'
Remove-Item -Recurse -Force $Stage

Log ("Export complete: $Artifact ({0:N1} GB)" -f ((Get-Item $Artifact).Length / 1GB))
Log "Outer sha256 (note it down for the far side): $((Get-FileHash -Algorithm SHA256 -Path $Artifact).Hash.ToLower())"
Log "On the enclave box (importers ship inside the artifact):"
Log "  tar -xf $RepoName-$Stamp.txt ./enclave-import.ps1        (or ./enclave-import.sh)"
Log "  `$env:GITLAB_TOKEN='<token>'; ./enclave-import.ps1 -TransferPath $RepoName-$Stamp.txt -GitLabUrl https://<enclave-gitlab> -Project <group/project>"
