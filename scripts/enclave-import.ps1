#Requires -Version 5.1
<#
.SYNOPSIS
  Import a transfer artifact produced by enclave-export.sh / .ps1 into a
  GitLab instance on this network (issue #263) — PowerShell port of
  enclave-import.sh for Windows transfer boxes.

.DESCRIPTION
  Verifies checksums, creates the project if it does not exist, pushes every
  branch + tag (and the wiki), syncs all generic packages (sha256-driven —
  see the packages phase, issue #295), enables anonymous package-registry
  pull (what lets Docker builds fetch Quarto with no token), and loads +
  pushes the container images. Each phase is idempotent — safe to rerun
  after a partial failure, and a rerun with an unchanged artifact uploads
  nothing.

  Bootstrap: the artifact carries a copy of this script at its top level —
  on a box that has ONLY the .txt file (the repo is still inside the bundle):
    tar -xf <repo>-<date>.txt ./enclave-import.ps1
    $env:GITLAB_TOKEN='<token>'; ./enclave-import.ps1 -TransferPath <repo>-<date>.txt -GitLabUrl https://... -Project group/project

  Requirements (preflight-checked): PowerShell 5.1+, git, curl and tar
  (curl.exe and tar are built into Windows 10+/Server 2019+); docker only
  for the images phase. JSON parsing and sha256 hashing use PowerShell
  built-ins.

.PARAMETER TransferPath
  The <repo>-<date>.txt archive the exporter produced (a gzipped tar;
  extracted next to itself), or an already-extracted directory.

.PARAMETER GitLabUrl
  Base URL of the target GitLab instance, e.g. https://gitlab.enclave.mil

.PARAMETER Project
  Full path of the target project, e.g. tools/nce-safe-simulator.
  Created (in an existing group) if absent.

.PARAMETER DefaultBranch
  Default branch to set after the push (default: main).

.PARAMETER RewriteCommitter
  'Full Name <email@domain>' — rewrite author AND committer on every commit
  of the repo and wiki before pushing. For targets enforcing the "committer
  restriction" push rule (only commits whose committer email is a verified
  email of the pushing account are accepted), which rejects any transferred
  history wholesale. Changes every commit hash (deterministically — reruns
  yield identical hashes, so imports stay idempotent).

.PARAMETER SignCommits
  GPG-sign every commit of the repo and wiki during the history pass — for
  targets enforcing the "reject unsigned commits" push rule. Requires gpg
  set up for git on THIS box (gpg.program/user.signingkey in the global git
  config, or a secret key matching the committer email); expect one
  pinentry passphrase prompt, then gpg-agent caches it. Composes with
  -RewriteCommitter: the rewritten identity chooses the signing key.
  Signing is NOT deterministic — every run yields new hashes, and a rerun
  force-pushes the fresh history over the previous one.

.PARAMETER NoPrune
  Keep destination generic packages/files that the archive does not carry.
  By default the packages phase prunes them: the archive is a complete
  snapshot of the source registry, so anything extra at the destination is
  stale. Pass -NoPrune for a destination that deliberately hosts additional
  generic packages outside this pipeline.

.NOTES
  Env: GITLAB_TOKEN — token with api scope on the TARGET instance, required.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TransferPath,
    [Parameter(Mandatory = $true)][string]$GitLabUrl,
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$DefaultBranch = 'main',
    [string]$RewriteCommitter,
    [switch]$SignCommits,
    [switch]$SkipRepo,
    [switch]$SkipPackages,
    [switch]$SkipImages,
    [switch]$NoPrune
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # WinPS 5.1: progress bars cripple upload speed
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

function Log([string]$msg) { Write-Host "==> $msg" }
function Assert-Native([string]$what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}
function Invoke-UploadWithRetry([string]$InFile, [string]$Uri) {
    # Mirror of the exporter's Invoke-DownloadWithRetry: WinPS 5.1's
    # SChannel-backed web cmdlets reproducibly drop long TLS streams, and a
    # ~120 MB package PUT is exactly that. Stream with the real curl
    # ($CurlBin, preflighted); the backoff loop covers mid-stream resets
    # that plain --retry does not. Uploads are idempotent, so a half-sent
    # file is safe to resend. Explicit content type: without it GitLab
    # parses the body as JSON and rejects the upload ("Invalid JSON
    # format").
    $max = 4
    for ($try = 1; $try -le $max; $try++) {
        & $CurlBin -fsS -H "PRIVATE-TOKEN: $env:GITLAB_TOKEN" -H 'Content-Type: application/octet-stream' `
            --upload-file $InFile $Uri | Out-Null
        if ($LASTEXITCODE -eq 0) { return }
        if ($try -eq $max) { throw "upload failed after $max attempts (curl exit $LASTEXITCODE): $Uri" }
        Log "  transient upload failure - retry $try/$($max - 1) in $(2 * $try)s (curl exit $LASTEXITCODE)"
        Start-Sleep -Seconds (2 * $try)
    }
}
function Invoke-DeleteWithRetry([string]$Uri) {
    # Registry deletes are small JSON API calls (no long TLS stream), so
    # Invoke-RestMethod is fine here — the $CurlBin rule covers file bodies.
    $max = 4
    for ($try = 1; $try -le $max; $try++) {
        try {
            Invoke-RestMethod -Headers $Headers -Method Delete -Uri $Uri | Out-Null
            return
        } catch {
            if ($try -eq $max) { throw "delete failed after $max attempts: $Uri" }
            Log "  transient delete failure - retry $try/$($max - 1) in $(2 * $try)s"
            Start-Sleep -Seconds (2 * $try)
        }
    }
}
function Get-AllPages([string]$Uri) {
    # Same pager as the exporter's: GitLab caps per_page at 100 and a
    # one-shot request silently truncates larger sets (the 225-file apt-debs
    # package, #273).
    $sep = if ($Uri.Contains('?')) { '&' } else { '?' }
    $all = @(); $page = 1
    while ($true) {
        # ForEach-Object forces enumeration: Invoke-RestMethod can emit a JSON
        # array as ONE object, and @() around that is a 1-element array — the
        # count check would end the walk on page 1 regardless of page size.
        $batch = @(Invoke-RestMethod -Headers $Headers -Uri "$Uri${sep}per_page=100&page=$page" |
            ForEach-Object { $_ })
        $all += $batch
        if ($batch.Count -lt 100) { break }
        $page++
    }
    return $all
}
function Invoke-HistoryFilter([string]$RepoPath) {
    # Rewrite author+committer and/or GPG-sign every commit of a scratch
    # mirror before it is pushed (see -RewriteCommitter / -SignCommits).
    # filter-branch rather than git-filter-repo because it ships inside
    # git — nothing to install on an enclave box. Its refs/original/*
    # backups never match the push refspecs, so only rewritten history
    # leaves the mirror.
    $what = @()
    if ($RewriteCommitter) { $what += "authorship -> $RwName <$RwEmail>" }
    if ($SignCommits) { $what += 'gpg signing' }
    Log "  rewriting history ($($what -join ' + ')) - large histories take a while..."
    $env:FILTER_BRANCH_SQUELCH_WARNING = '1'
    $fbArgs = @('filter-branch', '-f')
    if ($RewriteCommitter) {
        # One variable, then the array: inside @(...) the comma binds tighter
        # than '+', so concatenating across elements would emit the second
        # string as a THIRD element — a stray arg filter-branch rejects as
        # "bad revision", and only the author half would ever be exported.
        $envFilter = "export GIT_AUTHOR_NAME='$RwName' GIT_AUTHOR_EMAIL='$RwEmail'" +
            " GIT_COMMITTER_NAME='$RwName' GIT_COMMITTER_EMAIL='$RwEmail'"
        $fbArgs += @('--env-filter', $envFilter)
    }
    if ($SignCommits) {
        # --commit-filter replaces the stock commit-tree call; -S signs with
        # the key matching the (possibly rewritten) committer identity, per
        # the box's global git/gpg config.
        $fbArgs += @('--commit-filter', 'git commit-tree -S "$@"')
    }
    $fbArgs += @('--tag-name-filter', 'cat', '--', '--all')
    & git -C $RepoPath @fbArgs
    Assert-Native 'git filter-branch'
}

# ── Preflight: report ALL missing tools in one message ──────────────────────
$missing = @()
foreach ($tool in @('git', 'tar')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { $missing += $tool }
}
# curl streams the large package transfers that WinPS 5.1's SChannel-backed
# web cmdlets reproducibly drop mid-file. Probe curl.exe first: bare 'curl'
# is an Invoke-WebRequest ALIAS in WinPS 5.1. curl.exe ships with Windows
# 10+/Server 2019+ (same floor as tar); plain curl covers pwsh on Linux.
$CurlBin = Get-Command curl.exe, curl -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $CurlBin) { $missing += 'curl' }
if (-not $SkipImages -and -not (Get-Command docker -ErrorAction SilentlyContinue)) { $missing += 'docker' }
if ($missing.Count -gt 0) {
    Write-Error ("Missing required tools: {0}`nInstall them and rerun. (docker is only needed without -SkipImages.)" -f ($missing -join ' '))
    exit 1
}
if (-not $env:GITLAB_TOKEN) {
    Write-Error "Set GITLAB_TOKEN (api scope on the target instance)"
    exit 1
}
$RwName = $null; $RwEmail = $null
if ($RewriteCommitter) {
    if ($RewriteCommitter -notmatch '^(?<n>[^<>]+?)\s*<(?<e>[^<>@\s]+@[^<>\s]+)>$') {
        Write-Error "RewriteCommitter must look like 'Full Name <email@domain>'"
        exit 1
    }
    $RwName = $Matches.n; $RwEmail = $Matches.e
}
$Token = $env:GITLAB_TOKEN
$Headers = @{ 'PRIVATE-TOKEN' = $Token }
$GitLabUrl = $GitLabUrl.TrimEnd('/')
$Api = "$GitLabUrl/api/v4"
$Enc = [uri]::EscapeDataString($Project)

# ── Accept the single-file .txt artifact (a gzipped tar) or a directory ─────
if (Test-Path $TransferPath -PathType Leaf) {
    $archive = (Resolve-Path $TransferPath).Path
    $extract = $archive -replace '\.txt$', '-extracted'
    Log "Extracting $(Split-Path -Leaf $archive) to $extract ..."
    New-Item -ItemType Directory -Force -Path $extract | Out-Null
    & tar -xf $archive -C $extract; Assert-Native 'tar -xf'
    $TransferPath = $extract
}
$Dir = (Resolve-Path $TransferPath).Path

# ── 0. Integrity: verify every entry in SHA256SUMS ("<hash>  ./<path>") ─────
Log "Verifying checksums..."
foreach ($line in Get-Content (Join-Path $Dir 'SHA256SUMS')) {
    if ($line -notmatch '^(?<hash>[0-9a-f]{64})\s+\*?(?<path>.+)$') { continue }
    $file = Join-Path $Dir ($Matches.path -replace '^\./', '')
    $actual = (Get-FileHash -Algorithm SHA256 -Path $file).Hash.ToLower()
    if ($actual -ne $Matches.hash) { throw "Checksum mismatch: $($Matches.path)" }
}
Log "Checksums OK"

# ── 1. Project (create if absent) ───────────────────────────────────────────
$projectExists = $true
try { Invoke-RestMethod -Headers $Headers -Uri "$Api/projects/$Enc" | Out-Null }
catch { $projectExists = $false }
if ($projectExists) {
    Log "Project $Project exists"
} else {
    $group = $Project.Substring(0, $Project.LastIndexOf('/'))
    $name = $Project.Substring($Project.LastIndexOf('/') + 1)
    Log "Creating project $name in group $group..."
    $ns = Invoke-RestMethod -Headers $Headers -Uri "$Api/groups/$([uri]::EscapeDataString($group))"
    Invoke-RestMethod -Headers $Headers -Method Post -Uri "$Api/projects" -Body @{
        name = $name; path = $name; namespace_id = $ns.id; visibility = 'private'
    } | Out-Null
    Log "Created"
}

# ── 2. Repo: push every branch + tag from the bundle ────────────────────────
# The bundle carries origin's refs as refs/remotes/origin/*; the push refspec
# maps them back to refs/heads/* on the target.
$scheme = ($GitLabUrl -split '://')[0]
$hostPart = ($GitLabUrl -split '://')[1]
$pushUrl = "${scheme}://oauth2:$Token@$hostPart/$Project.git"
if (-not $SkipRepo) {
    # Scratch clone lives beside the transfer contents, NOT in the system
    # temp — /tmp is often a small tmpfs while the transfer dir is on a
    # disk already proven big enough to hold the artifact.
    $tmp = Join-Path $Dir (".import-" + [IO.Path]::GetRandomFileName())
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        Log "Pushing repo (all branches + tags)..."
        & git clone --quiet --mirror (Join-Path $Dir 'repo/repo.bundle') (Join-Path $tmp 'repo.git'); Assert-Native 'git clone (bundle)'
        if ($RewriteCommitter -or $SignCommits) { Invoke-HistoryFilter (Join-Path $tmp 'repo.git') }
        # A pre-existing target can hold a protected branch whose tip is not
        # in the bundle's history — classic cause: the project was
        # pre-created in the UI with "Initialize repository with a README",
        # so its main has a stray root commit. The push below force-updates
        # every branch, protection rejects forced updates unless
        # allow_force_push is set, and a pre-receive rejection fails the
        # ENTIRE push — a wall of rejected refs with no hint. Detect the
        # collision up front (after the history filter, so the check sees
        # the refs that will actually be pushed) and say how to fix it.
        if ($projectExists) {
            $mirror = Join-Path $tmp 'repo.git'
            foreach ($b in (Get-AllPages "$Api/projects/$Enc/protected_branches")) {
                if ($b.allow_force_push) { continue }
                $sha = $null
                try {
                    $bEnc = [uri]::EscapeDataString($b.name)
                    $sha = (Invoke-RestMethod -Headers $Headers -Uri "$Api/projects/$Enc/repository/branches/$bEnc").commit.id
                } catch {}   # wildcard rule or branch absent — push creates, no force needed
                if (-not $sha) { continue }
                & git -C $mirror show-ref --verify --quiet "refs/remotes/origin/$($b.name)"
                if ($LASTEXITCODE -ne 0) { continue }
                $diverged = $true
                & git -C $mirror rev-parse --quiet --verify "$sha^{commit}" | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    & git -C $mirror merge-base --is-ancestor $sha "refs/remotes/origin/$($b.name)"
                    if ($LASTEXITCODE -eq 0) { $diverged = $false }
                }
                if ($diverged) {
                    throw ("protected branch '$($b.name)' on $Project has history the bundle does not build on, " +
                        "and its protection disallows force push - GitLab would reject the forced update, and one " +
                        "rejected ref fails the ENTIRE push. Common cause: the project was pre-created in the UI " +
                        "with 'Initialize repository with a README'. Fix ONE of these, then rerun: allow force " +
                        "push on the branch (PATCH $Api/projects/$Enc/protected_branches/$($b.name)?allow_force_push=true), " +
                        "or delete the pre-created project and let this importer create it.")
                }
            }
        }
        & git -C (Join-Path $tmp 'repo.git') push --quiet $pushUrl '+refs/remotes/origin/*:refs/heads/*' '+refs/tags/*:refs/tags/*'; Assert-Native 'git push'
        # PUT bodies must be explicit JSON: PowerShell form-encodes hashtable
        # bodies only for GET/POST — on PUT it stringifies the hashtable and
        # GitLab rejects it with "Invalid JSON format".
        Invoke-RestMethod -Headers $Headers -Method Put -Uri "$Api/projects/$Enc" `
            -ContentType 'application/json' -Body (@{ default_branch = $DefaultBranch } | ConvertTo-Json) | Out-Null
        Log "Repo pushed; default branch = $DefaultBranch"
        if (Test-Path (Join-Path $Dir 'repo/wiki.bundle')) {
            Log "Pushing wiki..."
            & git clone --quiet --mirror (Join-Path $Dir 'repo/wiki.bundle') (Join-Path $tmp 'wiki.git'); Assert-Native 'git clone (wiki bundle)'
            if ($RewriteCommitter -or $SignCommits) { Invoke-HistoryFilter (Join-Path $tmp 'wiki.git') }
            $wikiPush = $pushUrl -replace '\.git$', '.wiki.git'
            & git -C (Join-Path $tmp 'wiki.git') push --quiet $wikiPush '+refs/enclave-wiki/*:refs/heads/*'; Assert-Native 'git push (wiki)'
            Log "Wiki pushed"
        }
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
}

# ── 3. Generic packages (layout: packages/<name>/<version>/<file>) ──────────
# Sync, not blind upload (issue #295). GitLab's generic registry APPENDS on
# re-publish of an existing name/version/file — downloads resolve to the
# newest entry, every older copy is kept — so unconditional re-uploads stack
# a full duplicate set per rerun, and files removed at the source lived on
# at the destination forever. The archive is a complete snapshot of the
# source registry, so the destination converges to it BY CONTENT: per file,
# the sha256 from the archive's own SHA256SUMS (phase 0 verified it against
# disk) is compared to the newest destination entry — identical skips,
# different or absent uploads and then deletes the superseded entries
# (upload FIRST, so there is no window where the file is unserved); older
# duplicates are swept; anything the archive does not carry is pruned unless
# -NoPrune. A name-only skip-if-exists would be wrong: bytes can change
# under an unchanged version (same-day re-capture), and the destination
# would silently serve stale content forever.
if (-not $SkipPackages) {
    $pkgRoot = Join-Path $Dir 'packages'
    # Archive content hashes come from SHA256SUMS (phase 0 verified them
    # against disk); anything unlisted is hashed directly.
    $sums = @{}
    foreach ($line in Get-Content (Join-Path $Dir 'SHA256SUMS')) {
        if ($line -match '^(?<hash>[0-9a-f]{64})\s+\*?(?<path>.+)$') {
            $sums[($Matches.path -replace '^\./', '')] = $Matches.hash
        }
    }
    $archive = @{}                 # name/version/file -> sha256
    foreach ($f in Get-ChildItem -Path $pkgRoot -Recurse -File) {
        $key = $f.FullName.Substring($pkgRoot.Length + 1).Replace('\', '/')
        $rel = $f.FullName.Substring($Dir.Length + 1).Replace('\', '/')
        $sha = $sums[$rel]
        if (-not $sha) { $sha = (Get-FileHash -Algorithm SHA256 -Path $f.FullName).Hash.ToLower() }
        $archive[$key] = $sha
    }
    Log "Enumerating destination packages..."
    $destEntries = @{}             # key -> array of @{Created; Id; Sha; PkgId}, unsorted
    $pkgKeys = @{}                 # pkgId -> array of keys (zero-file packages included)
    $pkgLabel = @{}
    foreach ($p in (Get-AllPages "$Api/projects/$Enc/packages?package_type=generic")) {
        $pkgId = [long]$p.id
        if (-not $pkgKeys.ContainsKey($pkgId)) { $pkgKeys[$pkgId] = @() }
        $pkgLabel[$pkgId] = "$($p.name)/$($p.version)"
        foreach ($pf in (Get-AllPages "$Api/projects/$Enc/packages/$pkgId/package_files")) {
            $key = "$($p.name)/$($p.version)/$($pf.file_name)"
            $sha = ''
            if ($pf.file_sha256) { $sha = [string]$pf.file_sha256 }
            if (-not $destEntries.ContainsKey($key)) { $destEntries[$key] = @() }
            $destEntries[$key] += [pscustomobject]@{
                Created = [string]$pf.created_at; Id = [long]$pf.id; Sha = $sha; PkgId = $pkgId
            }
            $pkgKeys[$pkgId] += $key
        }
    }
    # Uploads first — a replaced file's new bytes must be live before its old
    # entries are deleted — then every delete (dupes, superseded, prune).
    $upNew = 0; $upChanged = 0; $skipped = 0; $stale = 0; $prunedFiles = 0; $prunedPkgs = 0
    $deletes = @()
    foreach ($key in ($archive.Keys | Sort-Object)) {
        $entries = @()
        if ($destEntries.ContainsKey($key)) {
            $entries = @($destEntries[$key] | Sort-Object -Property Created, Id -Descending)
        }
        if ($entries.Count -eq 0) {
            Log "  upload (new): $key"
            Invoke-UploadWithRetry (Join-Path $pkgRoot $key) "$Api/projects/$Enc/packages/generic/$key"
            $upNew++
        } elseif ($entries[0].Sha -eq $archive[$key]) {
            $skipped++
            foreach ($e in ($entries | Select-Object -Skip 1)) {
                $deletes += @{ Uri = "$Api/projects/$Enc/packages/$($e.PkgId)/package_files/$($e.Id)"; Kind = 'stale'; Label = $key }
            }
        } else {
            Log "  upload (changed): $key"
            Invoke-UploadWithRetry (Join-Path $pkgRoot $key) "$Api/projects/$Enc/packages/generic/$key"
            $upChanged++
            foreach ($e in $entries) {
                $deletes += @{ Uri = "$Api/projects/$Enc/packages/$($e.PkgId)/package_files/$($e.Id)"; Kind = 'stale'; Label = $key }
            }
        }
    }
    if (-not $NoPrune) {
        foreach ($pkgId in $pkgKeys.Keys) {
            $keys = @($pkgKeys[$pkgId] | Sort-Object -Unique)
            $staleKeys = @($keys | Where-Object { -not $archive.ContainsKey($_) })
            if ($keys.Count -gt 0 -and $staleKeys.Count -eq 0) { continue }
            if ($staleKeys.Count -eq $keys.Count) {            # covers zero-file packages
                $deletes += @{ Uri = "$Api/projects/$Enc/packages/$pkgId"; Kind = 'prune-pkg'; Label = $pkgLabel[$pkgId] }
            } else {
                foreach ($k in $staleKeys) {
                    foreach ($e in $destEntries[$k]) {
                        $deletes += @{ Uri = "$Api/projects/$Enc/packages/$($e.PkgId)/package_files/$($e.Id)"; Kind = 'prune-file'; Label = $k }
                    }
                }
            }
        }
    }
    foreach ($d in $deletes) {
        Log "  delete ($($d.Kind)): $($d.Label)"
        Invoke-DeleteWithRetry $d.Uri
        switch ($d.Kind) {
            'stale'      { $stale++ }
            'prune-file' { $prunedFiles++ }
            'prune-pkg'  { $prunedPkgs++ }
        }
    }
    # Anonymous pull from the package registry (project stays private) — this
    # is what lets Docker builds fetch Quarto with no token in build args.
    # (JSON body: see the default_branch PUT note.)
    Invoke-RestMethod -Headers $Headers -Method Put -Uri "$Api/projects/$Enc" `
        -ContentType 'application/json' -Body (@{ package_registry_access_level = 'public' } | ConvertTo-Json) | Out-Null
    $pruneNote = "$prunedFiles files + $prunedPkgs packages pruned"
    if ($NoPrune) { $pruneNote = 'prune skipped (-NoPrune)' }
    Log ("Package sync: {0} uploaded ({1} new, {2} replaced), {3} skipped identical, {4} stale entries removed, {5}; anonymous package-registry pull enabled" -f `
        ($upNew + $upChanged), $upNew, $upChanged, $skipped, $stale, $pruneNote)
}

# ── 4. Container images ─────────────────────────────────────────────────────
if (-not $SkipImages -and (Test-Path (Join-Path $Dir 'images'))) {
    $prefix = (Invoke-RestMethod -Headers $Headers -Uri "$Api/projects/$Enc").container_registry_image_prefix
    $regHost = ($prefix -split '/')[0]
    Log "Logging in to $regHost..."
    $Token | & docker login $regHost --username oauth2 --password-stdin | Out-Null; Assert-Native 'docker login'
    foreach ($line in Get-Content (Join-Path $Dir 'images/image-refs.txt')) {
        $tarName, $origRef = $line -split ' ', 2
        $tarPath = Join-Path $Dir "images/$tarName"
        switch -Wildcard ($tarName) {
            'runtime.tar' { $newRef = "${prefix}:latest" }
            'dev.tar'     { $newRef = "$prefix/dev:latest" }
            'base-*'      {
                Log "  loading base image $origRef (not pushed - hand to your registry/proxy admin)"
                & docker load -i $tarPath | Out-Null; Assert-Native 'docker load'
                continue
            }
            default       { Write-Warning "unknown image entry: $tarName - skipping"; continue }
        }
        Log "  $tarName -> $newRef"
        & docker load -i $tarPath | Out-Null; Assert-Native 'docker load'
        & docker tag $origRef $newRef; Assert-Native 'docker tag'
        & docker push $newRef | Out-Null; Assert-Native 'docker push'
    }
    Log "Images pushed"
}

Log "Import complete. Post-import checklist:"
@'
  1. Runners: ensure the instance has runners that can pull the imported
     images (and the CI base images python:3.11 / kaniko, via proxy or
     registry import).
  2. CI/CD variables: create GITLAB_API_TOKEN (masked) if the report/deck
     recipes will run here.
  3. config.json: copy config.example.json and fill url/token/parent_group
     for THIS instance.
  4. Protect the default branch (Settings -> Repository) to match your flow.
  5. First green pipeline proves the lift: test fetches Pango debs and a
     default-branch merge rebuilds images - both from THIS instance's
     registries (README -> Enclave Transfer, Verify section).
'@ | Write-Host
