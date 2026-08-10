# Security posture — NCE Safe Simulator

> **Generated 2026-08-10T08:20:22Z** from `develop @ 2dbd11f0`, scan pipeline [#2746483470](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/pipelines/2746483470). Regenerate with `scripts/security_evidence.py` after a scan.

## 0 Detected · 237 Dismissed · 97 Resolved

Every finding is either fixed (Resolved) or dispositioned with a written reason (Dismissed). This file is the source of truth so you don't have to page through *Secure → Vulnerability report*.

| Scanner | Detected | Dismissed | Resolved |
|---|---:|---:|---:|
| Container Scanning | 0 | 186 | 21 |
| Dependency Scanning | 0 | 1 | 11 |
| SAST | 0 | 47 | 58 |
| Secret Detection | 0 | 3 | 7 |
| **Total** | **0** | **237** | **97** |

## Dismissed — Container Scanning (no fix available in Debian trixie)

| Package group | Findings | Reason |
|---|---:|---|
| `util-linux` (bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux) | 81 | Not applicable |
| `glibc` (libc6, libc-bin) | 22 | Acceptable risk |
| `perl` (perl-base) | 15 | Not applicable |
| `shell-utils` (tar, gzip, coreutils, bash, diffutils, sysvinit-utils) | 14 | Not applicable |
| `glib` (libglib2.0-0t64) | 10 | Acceptable risk |
| `systemd` (libsystemd0, libudev1) | 10 | Not applicable |
| `ncurses` (libncursesw6, libtinfo6, ncurses-base, ncurses-bin) | 8 | Not applicable |
| `misc-base` (libattr1, libacl1, libbz2-1.0, zlib1g, apt, libapt-pkg7.0) | 7 | Not applicable |
| `sqlite` (libsqlite3-0) | 6 | Acceptable risk |
| `shadow` (passwd, login.defs) | 6 | Not applicable |
| `pam` (libpam-modules, libpam-modules-bin, libpam-runtime, libpam0g) | 4 | Not applicable |
| `libpng` (libpng16-16t64) | 2 | Acceptable risk |
| `expat` (libexpat1) | 1 | Acceptable risk |

_Full per-finding rationale is on each vulnerability (Secure → Vulnerability report → the finding), citing the D4 review (#304, note 3650491306)._

## Dismissed — Dependency Scanning

| Finding | Reason |
|---|---|
| PyMdown Extensions: Path traversal in the b64 extension lets <img src> read files outside base_path | Not applicable |

## Dismissed — SAST

| Finding | Reason |
|---|---|
| Missing User Instruction | Acceptable risk |
| Server-side request forgery (SSRF) | False positive |
| Server-side request forgery (SSRF) | False positive |
| Apt Get Install Pin Version Not Defined | Acceptable risk |
| NPM Install Command Without Pinned Version | Acceptable risk |
| Improper authorization in handler for custom URL scheme | False positive |
| NPM Install Command Without Pinned Version | Acceptable risk |
| Unpinned Package Version in Pip Install | Mitigating control |
| Apt Get Install Pin Version Not Defined | Acceptable risk |
| Regular expression with non-literal value | Used in tests |
| Container Running With Low UID | Acceptable risk |
| Container Running As Root | Acceptable risk |
| Improper restriction of XML external entity reference | False positive |
| Improper authorization in handler for custom URL scheme | False positive |
| Improper authorization in handler for custom URL scheme | False positive |
| Improper restriction of XML external entity reference | False positive |
| NPM Install Command Without Pinned Version | Acceptable risk |
| Apt Get Install Pin Version Not Defined | Acceptable risk |
| Container Running As Root | Acceptable risk |
| Container Running With Low UID | Acceptable risk |
| Pod or Container Without LimitRange | Not applicable |
| Pod or Container Without ResourceQuota | Not applicable |
| Healthcheck Instruction Missing | Mitigating control |
| Pod or Container Without ResourceQuota | Not applicable |
| Pod or Container Without LimitRange | Not applicable |
| Pod or Container Without LimitRange | Not applicable |
| Service Does Not Target Pod | Not applicable |
| Pod or Container Without LimitRange | Not applicable |
| Pod or Container Without ResourceQuota | Not applicable |
| Pod or Container Without ResourceQuota | Not applicable |
| Image Without Digest | Not applicable |
| Root Container Not Mounted Read-only | Not applicable |
| Pod or Container Without LimitRange | Not applicable |
| Pod or Container Without ResourceQuota | Not applicable |
| Pod or Container Without ResourceQuota | Not applicable |
| Pod or Container Without LimitRange | Not applicable |
| Image Without Digest | Acceptable risk |
| Pod or Container Without LimitRange | Not applicable |
| Healthcheck Instruction Missing | Mitigating control |
| Pod or Container Without ResourceQuota | Not applicable |
| Pod or Container Without ResourceQuota | Not applicable |
| Root Container Not Mounted Read-only | Acceptable risk |
| Ensure Administrative Boundaries Between Resources | Not applicable |
| Pod or Container Without LimitRange | Not applicable |
| Missing AppArmor Profile | Not applicable |
| Pod or Container Without ResourceQuota | Not applicable |
| Pod or Container Without LimitRange | Not applicable |

## Dismissed — Secret Detection

| Finding | Reason |
|---|---|
| GitLab personal access token | False positive |
| GitLab personal access token | Used in tests |
| GitLab personal access token | Used in tests |

## Scanners (this evidence)

| Job | Scanner | Version | Report SHA-256 |
|---|---|---|---|
| container_scanning | Trivy | 0.72.0 | `d8c8cdfd23fe454f…` |
| secret_detection | Gitleaks | 8.30.1 | `466973565b017cff…` |
| semgrep-sast | Semgrep | 1.145.0 | `ffcd8e26b1f03806…` |

