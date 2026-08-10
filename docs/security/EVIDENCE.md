# Security posture & vulnerability disposition register — NCE Safe Simulator

## Provenance

- **Scanned commit:** `develop @ 2dbd11f0`
- **Scan:** pipeline [#2746483470](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/pipelines/2746483470), 2026-08-10
- **Scanners:** Trivy 0.72.0, Gitleaks 8.30.1, Semgrep 1.145.0
- **Disposition authority:** Reviewed and approved under issue #304 — container OS-package dispositions per the D4 review (note 3650491306), approved 2026-08-10.
- **Source:** GitLab Vulnerability Report; regenerate with `scripts/security_evidence.py`.
- **Full flat register:** [`dispositions.csv`](dispositions.csv) — one row per finding.

## 0 open · 237 accepted / N/A · 97 remediated

| Scanner | Open (Detected) | Accepted / N/A (Dismissed) | Remediated (Resolved) |
|---|---:|---:|---:|
| Container Scanning | 0 | 186 | 21 |
| Dependency Scanning | 0 | 1 | 11 |
| SAST / IaC | 0 | 47 | 58 |
| Secret Detection | 0 | 3 | 7 |
| **Total** | **0** | **237** | **97** |

## Accepted-risk & not-applicable register (dismissed)

Every accepted finding, its identifier and severity, and the justification for acceptance.

### Container · `util-linux` — 81 findings · **Not applicable**
*Justification:* single non-root Python process; mount/login/lastlog functionality is never invoked. No fixed version in Debian trixie. D4 review, issue #304 (note 3650491306).

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912315](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912315) | CVE-2026-53615 | liblastlog2-2 | HIGH |
| [345912300](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912300) | CVE-2026-53615 | libuuid1 | HIGH |
| [345912253](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912253) | CVE-2026-53615 | util-linux | HIGH |
| [345912225](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912225) | CVE-2026-53615 | libblkid1 | HIGH |
| [345912210](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912210) | CVE-2026-53615 | bsdutils | HIGH |
| [345912184](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912184) | CVE-2026-53615 | libmount1 | HIGH |
| [345912183](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912183) | CVE-2026-53615 | mount | HIGH |
| [345912149](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912149) | CVE-2026-53615 | login | HIGH |
| [345912142](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912142) | CVE-2026-53615 | libsmartcols1 | HIGH |
| [345912322](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912322) | CVE-2026-13595 | mount | MEDIUM |
| [345912318](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912318) | CVE-2026-13595 | bsdutils | MEDIUM |
| [345912310](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912310) | CVE-2026-27456 | libuuid1 | MEDIUM |
| [345912284](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912284) | CVE-2026-27456 | login | MEDIUM |
| [345912274](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912274) | CVE-2026-27456 | bsdutils | MEDIUM |
| [345912267](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912267) | CVE-2026-13595 | libblkid1 | MEDIUM |
| [345912261](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912261) | CVE-2026-3184 | liblastlog2-2 | MEDIUM |
| [345912254](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912254) | CVE-2026-13595 | util-linux | MEDIUM |
| [345912232](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912232) | CVE-2026-3184 | libmount1 | MEDIUM |
| [345912230](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912230) | CVE-2026-3184 | libuuid1 | MEDIUM |
| [345912226](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912226) | CVE-2026-13595 | liblastlog2-2 | MEDIUM |
| [345912224](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912224) | CVE-2026-13595 | libuuid1 | MEDIUM |
| [345912222](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912222) | CVE-2026-13595 | libmount1 | MEDIUM |
| [345912202](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912202) | CVE-2026-3184 | mount | MEDIUM |
| [345912182](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912182) | CVE-2026-3184 | login | MEDIUM |
| [345912180](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912180) | CVE-2026-27456 | libsmartcols1 | MEDIUM |
| [345912164](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912164) | CVE-2026-13595 | login | MEDIUM |
| [345912161](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912161) | CVE-2026-27456 | util-linux | MEDIUM |
| [345912158](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912158) | CVE-2026-3184 | libsmartcols1 | MEDIUM |
| [345912153](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912153) | CVE-2026-27456 | libblkid1 | MEDIUM |
| [345912150](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912150) | CVE-2026-3184 | libblkid1 | MEDIUM |
| [345912144](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912144) | CVE-2026-3184 | bsdutils | MEDIUM |
| [345912143](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912143) | CVE-2026-3184 | util-linux | MEDIUM |
| [345912136](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912136) | CVE-2026-27456 | liblastlog2-2 | MEDIUM |
| [345912135](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912135) | CVE-2026-27456 | mount | MEDIUM |
| [345912134](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912134) | CVE-2026-27456 | libmount1 | MEDIUM |
| [345912123](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912123) | CVE-2026-13595 | libsmartcols1 | MEDIUM |
| [345912282](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912282) | CVE-2025-14104 | login | LOW |
| [345912272](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912272) | CVE-2022-0563 | mount | LOW |
| [345912262](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912262) | CVE-2025-14104 | util-linux | LOW |
| [345912250](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912250) | CVE-2022-0563 | liblastlog2-2 | LOW |
| [345912236](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912236) | CVE-2022-0563 | util-linux | LOW |
| [345912218](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912218) | CVE-2025-14104 | libblkid1 | LOW |
| [345912205](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912205) | CVE-2025-14104 | libmount1 | LOW |
| [345912193](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912193) | CVE-2022-0563 | libuuid1 | LOW |
| [345912176](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912176) | CVE-2022-0563 | login | LOW |
| [345912173](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912173) | CVE-2022-0563 | bsdutils | LOW |
| [345912172](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912172) | CVE-2022-0563 | libmount1 | LOW |
| [345912167](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912167) | CVE-2025-14104 | libuuid1 | LOW |
| [345912162](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912162) | CVE-2025-14104 | libsmartcols1 | LOW |
| [345912160](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912160) | CVE-2025-14104 | mount | LOW |
| [345912145](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912145) | CVE-2025-14104 | bsdutils | LOW |
| [345912141](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912141) | CVE-2022-0563 | libsmartcols1 | LOW |
| [345912139](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912139) | CVE-2022-0563 | libblkid1 | LOW |
| [345912127](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912127) | CVE-2025-14104 | liblastlog2-2 | LOW |
| [345912324](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912324) | CVE-2026-53613 | liblastlog2-2 | UNKNOWN |
| [345912308](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912308) | CVE-2026-53614 | mount | UNKNOWN |
| [345912307](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912307) | CVE-2026-53612 | libuuid1 | UNKNOWN |
| [345912302](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912302) | CVE-2026-53612 | bsdutils | UNKNOWN |
| [345912298](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912298) | CVE-2026-53613 | util-linux | UNKNOWN |
| [345912291](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912291) | CVE-2026-53613 | bsdutils | UNKNOWN |
| [345912285](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912285) | CVE-2026-53612 | liblastlog2-2 | UNKNOWN |
| [345912278](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912278) | CVE-2026-53614 | login | UNKNOWN |
| [345912263](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912263) | CVE-2026-53613 | mount | UNKNOWN |
| [345912260](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912260) | CVE-2026-53614 | libsmartcols1 | UNKNOWN |
| [345912256](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912256) | CVE-2026-53612 | libsmartcols1 | UNKNOWN |
| [345912239](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912239) | CVE-2026-53612 | libmount1 | UNKNOWN |
| [345912231](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912231) | CVE-2026-53614 | util-linux | UNKNOWN |
| [345912223](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912223) | CVE-2026-53614 | libblkid1 | UNKNOWN |
| [345912217](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912217) | CVE-2026-53612 | libblkid1 | UNKNOWN |
| [345912212](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912212) | CVE-2026-53612 | mount | UNKNOWN |
| [345912201](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912201) | CVE-2026-53614 | liblastlog2-2 | UNKNOWN |
| [345912195](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912195) | CVE-2026-53614 | libuuid1 | UNKNOWN |
| [345912194](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912194) | CVE-2026-53613 | libsmartcols1 | UNKNOWN |
| [345912185](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912185) | CVE-2026-53614 | bsdutils | UNKNOWN |
| [345912165](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912165) | CVE-2026-53612 | login | UNKNOWN |
| [345912157](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912157) | CVE-2026-53613 | libblkid1 | UNKNOWN |
| [345912154](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912154) | CVE-2026-53613 | login | UNKNOWN |
| [345912131](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912131) | CVE-2026-53613 | libuuid1 | UNKNOWN |
| [345912125](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912125) | CVE-2026-53614 | libmount1 | UNKNOWN |
| [345912122](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912122) | CVE-2026-53612 | util-linux | UNKNOWN |
| [345912119](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912119) | CVE-2026-53613 | libmount1 | UNKNOWN |

### Container · `glibc` — 22 findings · **Acceptable risk**
*Justification:* linked by every process, but the CVEs target rarely-used functions; app input is HTTP via Caddy/ALB. No fixed glibc in trixie; clears on base refresh. D4 review, issue #304 (note 3650491306).

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912276](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912276) | CVE-2026-5435 | libc-bin | MEDIUM |
| [345912243](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912243) | CVE-2026-6238 | libc6 | MEDIUM |
| [345912238](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912238) | CVE-2026-5928 | libc-bin | MEDIUM |
| [345912147](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912147) | CVE-2026-5928 | libc6 | MEDIUM |
| [345912138](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912138) | CVE-2026-5435 | libc6 | MEDIUM |
| [345912137](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912137) | CVE-2026-5450 | libc6 | MEDIUM |
| [345912129](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912129) | CVE-2026-5450 | libc-bin | MEDIUM |
| [345912124](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912124) | CVE-2026-6238 | libc-bin | MEDIUM |
| [345912312](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912312) | CVE-2019-1010023 | libc-bin | LOW |
| [345912311](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912311) | CVE-2019-1010023 | libc6 | LOW |
| [345912290](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912290) | CVE-2019-1010025 | libc6 | LOW |
| [345912288](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912288) | CVE-2019-9192 | libc-bin | LOW |
| [345912266](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912266) | CVE-2010-4756 | libc6 | LOW |
| [345912228](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912228) | CVE-2019-1010024 | libc6 | LOW |
| [345912215](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912215) | CVE-2018-20796 | libc6 | LOW |
| [345912207](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912207) | CVE-2019-1010022 | libc-bin | LOW |
| [345912197](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912197) | CVE-2019-1010025 | libc-bin | LOW |
| [345912163](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912163) | CVE-2018-20796 | libc-bin | LOW |
| [345912148](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912148) | CVE-2019-1010022 | libc6 | LOW |
| [345912133](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912133) | CVE-2019-9192 | libc6 | LOW |
| [345912128](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912128) | CVE-2010-4756 | libc-bin | LOW |
| [345912126](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912126) | CVE-2019-1010024 | libc-bin | LOW |

### Container · `perl` — 15 findings · **Not applicable**
*Justification:* Not applicable — no perl execution path. The container runs a single python/uvicorn process; nothing in the app, scripts, or runtime tooling invokes perl (verified across the repo, #304). perl-base is present only because it is a dpkg Essential package (cannot be removed without breaking dpkg/apt). Worst-case impact of the perl-base CVE set is a crash of a perl process that never runs. No fixed perl-base exists in Debian trixie: verified 2026-08-06 against freshly pulled python:3.11-slim and python:3.13-slim — both Debian 13.6 with the same perl-base 5.40.1-6. The Dockerfile's unpinned base tag means a routine rebuild picks up Debian's fix automatically once released, after which this finding stops appearing in scans. Refs #304.

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912316](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912316) | CVE-2026-57433 | perl-base | CRITICAL |
| [345912305](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912305) | CVE-2026-42496 | perl-base | CRITICAL |
| [345912264](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912264) | CVE-2026-8376 | perl-base | CRITICAL |
| [345912170](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912170) | CVE-2026-13221 | perl-base | CRITICAL |
| [345912234](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912234) | CVE-2026-9538 | perl-base | HIGH |
| [345912209](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912209) | CVE-2026-57432 | perl-base | HIGH |
| [345912199](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912199) | CVE-2026-42497 | perl-base | HIGH |
| [345912198](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912198) | CVE-2026-48962 | perl-base | HIGH |
| [345912246](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912246) | CVE-2026-48961 | perl-base | MEDIUM |
| [345912240](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912240) | CVE-2026-7010 | perl-base | MEDIUM |
| [345912237](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912237) | CVE-2025-15649 | perl-base | MEDIUM |
| [345912196](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912196) | CVE-2026-48959 | perl-base | MEDIUM |
| [345912188](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912188) | CVE-2026-12087 | perl-base | MEDIUM |
| [345912211](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912211) | CVE-2011-4116 | perl-base | LOW |
| [345912303](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912303) | CVE-2026-7017 | perl-base | UNKNOWN |

### Container · `shell-utils` — 14 findings · **Not applicable**
*Justification:* base shell utilities never invoked by the serving process on untrusted input. No fix in trixie. D4 review, issue #304 (note 3650491306).

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912321](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912321) | CVE-2026-41992 | gzip | HIGH |
| [348083371](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/348083371) | CVE-2026-18508 | tar | MEDIUM |
| [347969841](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/347969841) | CVE-2026-18477 | tar | MEDIUM |
| [345912244](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912244) | CVE-2026-41991 | gzip | MEDIUM |
| [345912156](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912156) | CVE-2026-5704 | tar | MEDIUM |
| [345912313](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912313) | TEMP-0841856-B18BAF | bash | LOW |
| [345912259](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912259) | TEMP-0290435-0B57B5 | tar | LOW |
| [345912258](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912258) | CVE-2026-56392 | coreutils | LOW |
| [345912247](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912247) | CVE-2026-56391 | coreutils | LOW |
| [345912216](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912216) | CVE-2026-53910 | diffutils | LOW |
| [345912191](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912191) | CVE-2025-5278 | coreutils | LOW |
| [345912181](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912181) | CVE-2005-2541 | tar | LOW |
| [345912177](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912177) | CVE-2017-18018 | coreutils | LOW |
| [345912118](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912118) | TEMP-0517018-A83CE6 | sysvinit-utils | LOW |

### Container · `glib` — 10 findings · **Acceptable risk**
*Justification:* reachable via the WeasyPrint/Pango PDF stack, but rendered content is our own templates + GitLab data, not arbitrary uploads. No fix; clears on refresh. D4 review, issue #304 (note 3650491306).

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912200](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912200) | CVE-2026-58016 | libglib2.0-0t64 | CRITICAL |
| [345912277](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912277) | CVE-2026-58015 | libglib2.0-0t64 | HIGH |
| [345912268](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912268) | CVE-2026-58013 | libglib2.0-0t64 | HIGH |
| [345912265](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912265) | CVE-2026-58014 | libglib2.0-0t64 | HIGH |
| [345912166](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912166) | CVE-2026-58011 | libglib2.0-0t64 | HIGH |
| [345912159](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912159) | CVE-2026-58012 | libglib2.0-0t64 | HIGH |
| [345912132](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912132) | CVE-2026-58010 | libglib2.0-0t64 | HIGH |
| [345912294](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912294) | CVE-2026-16118 | libglib2.0-0t64 | MEDIUM |
| [345912273](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912273) | CVE-2026-15588 | libglib2.0-0t64 | MEDIUM |
| [345912286](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912286) | CVE-2012-0039 | libglib2.0-0t64 | LOW |

### Container · `systemd` — 10 findings · **Not applicable**
*Justification:* no init system or device management runs in the container; the CVE code paths never execute. No fix in trixie. D4 review, issue #304 (note 3650491306).

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912317](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912317) | CVE-2023-31437 | libsystemd0 | LOW |
| [345912309](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912309) | CVE-2023-31439 | libudev1 | LOW |
| [345912281](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912281) | CVE-2013-4392 | libudev1 | LOW |
| [345912251](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912251) | CVE-2023-31438 | libsystemd0 | LOW |
| [345912245](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912245) | CVE-2026-40228 | libsystemd0 | LOW |
| [345912233](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912233) | CVE-2013-4392 | libsystemd0 | LOW |
| [345912227](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912227) | CVE-2026-40228 | libudev1 | LOW |
| [345912186](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912186) | CVE-2023-31438 | libudev1 | LOW |
| [345912178](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912178) | CVE-2023-31439 | libsystemd0 | LOW |
| [345912175](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912175) | CVE-2023-31437 | libudev1 | LOW |

### Container · `ncurses` — 8 findings · **Not applicable**
*Justification:* no interactive terminal in the serving container. No fix in trixie. D4 review, issue #304 (note 3650491306).

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912249](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912249) | CVE-2025-69720 | libtinfo6 | HIGH |
| [345912219](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912219) | CVE-2025-69720 | libncursesw6 | HIGH |
| [345912203](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912203) | CVE-2025-69720 | ncurses-base | HIGH |
| [345912187](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912187) | CVE-2025-69720 | ncurses-bin | HIGH |
| [345912314](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912314) | CVE-2025-6141 | ncurses-base | LOW |
| [345912293](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912293) | CVE-2025-6141 | libncursesw6 | LOW |
| [345912241](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912241) | CVE-2025-6141 | ncurses-bin | LOW |
| [345912213](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912213) | CVE-2025-6141 | libtinfo6 | LOW |

### Container · `misc-base` — 7 findings · **Not applicable**
*Justification:* apt never runs at container runtime; these CVEs sit in code paths the app does not drive with untrusted input. No fix in trixie. D4 review, issue #304 (note 3650491306).

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912190](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912190) | CVE-2026-54369 | libacl1 | HIGH |
| [345912275](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912275) | CVE-2026-42250 | libbz2-1.0 | MEDIUM |
| [345912270](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912270) | CVE-2026-54370 | libacl1 | MEDIUM |
| [345912171](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912171) | CVE-2026-54371 | libattr1 | MEDIUM |
| [345912130](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912130) | CVE-2026-27171 | zlib1g | MEDIUM |
| [345912301](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912301) | CVE-2011-3374 | libapt-pkg7.0 | LOW |
| [345912214](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912214) | CVE-2011-3374 | apt | LOW |

### Container · `sqlite` — 6 findings · **Acceptable risk**
*Justification:* Python links sqlite3, but persistence is JSON/files — no sqlite DB is parsed from untrusted input. No fix in trixie. D4 review, issue #304 (note 3650491306).

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912306](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912306) | CVE-2026-50813 | libsqlite3-0 | MEDIUM |
| [345912292](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912292) | CVE-2026-50812 | libsqlite3-0 | MEDIUM |
| [345912257](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912257) | CVE-2026-11822 | libsqlite3-0 | MEDIUM |
| [345912206](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912206) | CVE-2026-11824 | libsqlite3-0 | MEDIUM |
| [345912304](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912304) | CVE-2021-45346 | libsqlite3-0 | LOW |
| [345912299](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912299) | CVE-2025-70873 | libsqlite3-0 | LOW |

### Container · `shadow` — 6 findings · **Not applicable**
*Justification:* no account operations at runtime. No fix in trixie. D4 review, issue #304 (note 3650491306).

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912297](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912297) | TEMP-0628843-DBAD28 | login.defs | LOW |
| [345912248](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912248) | CVE-2024-56433 | passwd | LOW |
| [345912192](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912192) | CVE-2007-5686 | login.defs | LOW |
| [345912179](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912179) | TEMP-0628843-DBAD28 | passwd | LOW |
| [345912152](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912152) | CVE-2024-56433 | login.defs | LOW |
| [345912151](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912151) | CVE-2007-5686 | passwd | LOW |

### Container · `pam` — 4 findings · **Not applicable**
*Justification:* no login/su/ssh in the container; PAM modules never load. No fix in trixie. D4 review, issue #304 (note 3650491306).

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912319](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912319) | CVE-2026-54411 | libpam-modules | MEDIUM |
| [345912295](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912295) | CVE-2026-54411 | libpam0g | MEDIUM |
| [345912271](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912271) | CVE-2026-54411 | libpam-modules-bin | MEDIUM |
| [345912269](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912269) | CVE-2026-54411 | libpam-runtime | MEDIUM |

### Container · `libpng` — 2 findings · **Acceptable risk**
*Justification:* decodes images our own report pipeline produces; not exposed to arbitrary uploads. No fix in trixie. D4 review, issue #304 (note 3650491306).

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912279](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912279) | CVE-2026-3713 | libpng16-16t64 | LOW |
| [345912208](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912208) | CVE-2021-4214 | libpng16-16t64 | LOW |

### Container · `expat` — 1 findings · **Acceptable risk**
*Justification:* fontconfig parses only the baked-in system font config (trusted). No fix for this CVE. D4 review, issue #304 (note 3650491306).

| Vuln | CVE | Package | Severity |
|---|---|---|---|
| [345912121](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912121) | CVE-2025-66382 | libexpat1 | MEDIUM |

### SAST / IaC — 47 findings

| Vuln | Finding | Component | Severity | Disposition | Justification |
|---|---|---|---|---|---|
| [345912101](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912101) | Missing User Instruction | Dockerfile:48 | CRITICAL | Acceptable risk | #287 accepted root pending an app-wide port move. Superseded 2026-08-06 by the actual fix on feature/304 (USER app uid 1000 + port 8080, commit a268b73); current-generation duplicate 349121555 tracks the fix through merge. This 2026-07-30 fingerprint will not re-detect. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912331](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912331) | Server-side request forgery (SSRF) | frontend/src/api.js:245 | HIGH | False positive | False positive — wrong-runtime rule. nodejs_scan's node_ssrf targets Node.js server code; frontend/src/api.js is browser code (Vite/Vue bundle), so there is no server-side request to forge — the fetch runs from the user's own browser and network position. Independently: both URLs are same-origin relative paths (/api/...), so no host component is attacker-controllable (SSRF requires steering the request host); and every interpolated value is wrapped in encodeURIComponent, so a hostile value cannot escape its path segment. Caller provenance: getJob ids come from job manifests returned by our own backend (useJobs.js polling); launchDeploy target/action come from fixed buttons in DeploymentsDialog.vue (s3|ecs|eks x deploy|destroy). Checked for a mislabeled real issue (unencoded interpolation / user-controlled full URL): none present. Backfills the reasonless 2026-07-31 (#287) dismissal. Refs #304. |
| [345912330](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912330) | Server-side request forgery (SSRF) | frontend/src/api.js:205 | HIGH | False positive | False positive — wrong-runtime rule. nodejs_scan's node_ssrf targets Node.js server code; frontend/src/api.js is browser code (Vite/Vue bundle), so there is no server-side request to forge — the fetch runs from the user's own browser and network position. Independently: both URLs are same-origin relative paths (/api/...), so no host component is attacker-controllable (SSRF requires steering the request host); and every interpolated value is wrapped in encodeURIComponent, so a hostile value cannot escape its path segment. Caller provenance: getJob ids come from job manifests returned by our own backend (useJobs.js polling); launchDeploy target/action come from fixed buttons in DeploymentsDialog.vue (s3|ecs|eks x deploy|destroy). Checked for a mislabeled real issue (unencoded interpolation / user-controlled full URL): none present. Backfills the reasonless 2026-07-31 (#287) dismissal. Refs #304. |
| [351178280](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/351178280) | Apt Get Install Pin Version Not Defined | Dockerfile:281 | MEDIUM | Acceptable risk | Unpinned apt/npm in the operator-only ops stage, which is never deployed to the serving image; mirrors the #287 disposition of the same finding class. #304. |
| [351178279](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/351178279) | NPM Install Command Without Pinned Version | Dockerfile:281 | MEDIUM | Acceptable risk | Unpinned apt/npm in the operator-only ops stage, which is never deployed to the serving image; mirrors the #287 disposition of the same finding class. #304. |
| [351178278](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/351178278) | Improper authorization in handler for custom URL scheme | deck/deck_checks.py:47 | MEDIUM | False positive | The URL is app_url from shots.yaml (committed, trusted config), not user input; no scheme/host injection is possible. #304. |
| [349121552](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121552) | NPM Install Command Without Pinned Version | Dockerfile:246 | MEDIUM | Acceptable risk | npm install -g aws-cdk sits in the same operator-only ops stage; tracking the current cdk CLI there is deliberate. Mirrors the #287 disposition of its old-generation twin (345912099). Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [349121547](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121547) | Unpinned Package Version in Pip Install | Dockerfile:84 | MEDIUM | Mitigating control | The flagged pip install is fully version-pinned: packages come from requirements.lock (-r/-c) resolved against the content-addressed vendored wheelhouse (#271; PIP_WHEELS_VERSION is derived from the lock's own sha256, #296). KICS only pattern-matches for ==pins on the RUN line and cannot see lockfile pinning. Control: requirements.lock + content-addressed capture. Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [349121546](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121546) | Apt Get Install Pin Version Not Defined | Dockerfile:246 | MEDIUM | Acceptable risk | apt-get install sits in the ops stage — an operator-run toolchain image, built only explicitly (docker build --target ops), never pushed to ECR or deployed, documented in the Dockerfile as deliberately outside the enclave/pinning scope. Mirrors the #287 disposition of its old-generation twin (345912096). Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [349121489](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121489) | Regular expression with non-literal value | frontend/e2e/search.spec.js:334 | MEDIUM | Used in tests | Playwright e2e spec (frontend/e2e/search.spec.js): the dynamic RegExp is constructed from the suite's own fixture data inside test code that never ships to production. The rule targets user-input-driven RegExp DoS in application code. Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [346978061](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/346978061) | Container Running With Low UID | helm/nce-safe-simulator/templates/deployment.yaml:34 | MEDIUM | Acceptable risk | Same root cause as 'Container Running As Root' — accepted risk per #287 for the privileged port-80 bind. Re-flagged only because the securityContext edit changed the fingerprint. |
| [346978060](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/346978060) | Container Running As Root | helm/nce-safe-simulator/templates/deployment.yaml:25 | MEDIUM | Acceptable risk | Accepted risk per #287: the container binds privileged port 80, so it runs as root. Going non-root requires an app-wide port migration across EKS/ECS/single-box; 'fully functional' is the hard constraint. Compensating controls in place: allowPrivilegeEscalation=false, all capabilities dropped except NET_BIND_SERVICE, seccompProfile RuntimeDefault, automountServiceAccountToken=false. Re-flagged only because the securityContext edit changed the fingerprint. |
| [345912378](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912378) | Improper restriction of XML external entity reference | slides/243-slide-brief-as-is-to-be/build_brief.py:66 | MEDIUM | False positive | Same as deck/build_deck.py:83 — parses the theme part of the repo's own .pptx template; no untrusted XML reaches the call and stdlib ElementTree does not resolve external entities by default. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912348](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912348) | Improper authorization in handler for custom URL scheme | scripts/fetch-apt-debs.py:42 | MEDIUM | False positive | Same as line 36 — registry base and package names are trusted build inputs; no user-controlled URL/scheme. Build-time script, not a runtime service. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912340](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912340) | Improper authorization in handler for custom URL scheme | scripts/fetch-apt-debs.py:36 | MEDIUM | False positive | urlretrieve URL is built from trusted CLI args (project package-registry base + version, passed by Makefile/CI) and manifest-listed package names; no user-controlled scheme or URL reaches the call. Build-time script, not a runtime service. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912333](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912333) | Improper restriction of XML external entity reference | deck/build_deck.py:83 | MEDIUM | False positive | etree.fromstring parses theme1.xml obtained from the local .pptx template package via python-pptx part_related_by — repo-controlled input, not attacker-supplied XML; stdlib ElementTree does not resolve external entities by default. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912099](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912099) | NPM Install Command Without Pinned Version | Dockerfile:166 | MEDIUM | Acceptable risk | npm install -g aws-cdk sits in the ops stage — built explicitly by an operator, never pushed to ECR or deployed; tracking the current cdk CLI there is deliberate. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912096](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912096) | Apt Get Install Pin Version Not Defined | Dockerfile:166 | MEDIUM | Acceptable risk | apt-get install in the same operator-only ops stage, which pulls tooling from the internet by design and never ships. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912095](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912095) | Container Running As Root | helm/nce-safe-simulator/templates/deployment.yaml:19 | MEDIUM | Acceptable risk | #287 accepted root pending the port move. Superseded by feature/304: deployment.yaml now sets runAsNonRoot: true / runAsUser 1000 (commit a268b73). Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912089](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912089) | Container Running With Low UID | helm/nce-safe-simulator/templates/deployment.yaml:19 | MEDIUM | Acceptable risk | #287 kept root. feature/304 sets runAsUser 1000 — non-root but below this rule's >=10000 bar, chosen to match the single-box bind-mount owner (ec2-user uid 1000). If the rule refires post-merge, the disposition remains acceptable risk on the same grounds. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [349121554](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121554) | Pod or Container Without LimitRange | helm/nce-safe-simulator/templates/pvc.yaml:34 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, bounding the workload. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Same rationale as the dispositioned old-generation twins (#287 backfill). Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [349121553](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121553) | Pod or Container Without ResourceQuota | helm/nce-safe-simulator/templates/pvc.yaml:20 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, bounding the workload. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Same rationale as the dispositioned old-generation twins (#287 backfill). Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [349121551](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121551) | Healthcheck Instruction Missing | Dockerfile:109 | INFO | Mitigating control | No Docker HEALTHCHECK, but the container is orchestrated: the helm deployment defines readiness/liveness probes (now against :8080) and the single-box path health-checks via Caddy; kubelet ignores Docker HEALTHCHECK. Same rationale as the dispositioned old-generation twin (345912104). Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [349121550](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121550) | Pod or Container Without ResourceQuota | helm/nce-safe-simulator/templates/pvc.yaml:34 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, bounding the workload. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Same rationale as the dispositioned old-generation twins (#287 backfill). Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [349121549](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121549) | Pod or Container Without LimitRange | helm/nce-safe-simulator/templates/pvc.yaml:20 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, bounding the workload. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Same rationale as the dispositioned old-generation twins (#287 backfill). Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [349121548](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121548) | Pod or Container Without LimitRange | helm/nce-safe-simulator/templates/pvc.yaml:6 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, bounding the workload. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Same rationale as the dispositioned old-generation twins (#287 backfill). Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [349121543](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121543) | Service Does Not Target Pod | helm/nce-safe-simulator/templates/service.yaml:3 | INFO | Not applicable | KICS template noise: the Service selector (app: {{ .Release.Name }}) exactly matches the Deployment's pod template labels in the same chart — verified. The rule cannot resolve Helm template expressions. Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [349121542](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121542) | Pod or Container Without LimitRange | helm/nce-safe-simulator/templates/pvc.yaml:48 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, bounding the workload. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Same rationale as the dispositioned old-generation twins (#287 backfill). Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [349121541](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121541) | Pod or Container Without ResourceQuota | helm/nce-safe-simulator/templates/pvc.yaml:6 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, bounding the workload. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Same rationale as the dispositioned old-generation twins (#287 backfill). Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [349121540](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/349121540) | Pod or Container Without ResourceQuota | helm/nce-safe-simulator/templates/pvc.yaml:48 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, bounding the workload. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Same rationale as the dispositioned old-generation twins (#287 backfill). Refs #304 (D3 sweep of the remediation plan posted 2026-08-06). |
| [346978063](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/346978063) | Image Without Digest | helm/nce-safe-simulator/templates/deployment.yaml:27 | INFO | Not applicable | The chart deploys an image rebuilt on every release, so a pinned sha256 digest in values.yaml would be stale on the next build and require a chart edit per deploy. The mutable-tag exposure this finding really targets is tracked separately as a deploy-pipeline fix (immutable tag at push + deploy time). |
| [346978062](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/346978062) | Root Container Not Mounted Read-only | helm/nce-safe-simulator/templates/deployment.yaml:25 | INFO | Not applicable | Verified 2026-08-03: readOnlyRootFilesystem would break the container. scripts/entrypoint-eks.sh runs 'ln -sf /mnt/config/config.json /app/config.json', writing into the image root filesystem on every boot. Persistent data already lives on EFS-backed PVCs; making the root FS read-only would require emptyDir mounts and an entrypoint rewrite for no additional protection. |
| [345912113](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912113) | Pod or Container Without LimitRange | helm/nce-safe-simulator/templates/pvc.yaml:47 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, so the workload is bounded. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912110](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912110) | Pod or Container Without ResourceQuota | helm/nce-safe-simulator/templates/pvc.yaml:19 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, so the workload is bounded. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912109](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912109) | Pod or Container Without ResourceQuota | helm/nce-safe-simulator/templates/deployment.yaml:4 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, so the workload is bounded. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912108](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912108) | Pod or Container Without LimitRange | helm/nce-safe-simulator/templates/deployment.yaml:4 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, so the workload is bounded. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912107](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912107) | Image Without Digest | helm/nce-safe-simulator/templates/deployment.yaml:21 | INFO | Acceptable risk | Helm image is referenced by tag; tags are immutable CI artifacts from a team-controlled registry (#290 requires the exact ecr-push tag), so digest pinning adds churn without a meaningful integrity gain. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912105](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912105) | Pod or Container Without LimitRange | helm/nce-safe-simulator/templates/pvc.yaml:19 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, so the workload is bounded. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912104](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912104) | Healthcheck Instruction Missing | Dockerfile:48 | INFO | Mitigating control | No Docker HEALTHCHECK, but the container is orchestrated: k8s readiness/liveness probes (deployment.yaml) and the single-box Caddy upstream perform the same function; kubelet ignores Docker HEALTHCHECK anyway. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912103](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912103) | Pod or Container Without ResourceQuota | helm/nce-safe-simulator/templates/pvc.yaml:47 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, so the workload is bounded. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912100](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912100) | Pod or Container Without ResourceQuota | helm/nce-safe-simulator/templates/pvc.yaml:5 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, so the workload is bounded. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912097](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912097) | Root Container Not Mounted Read-only | helm/nce-safe-simulator/templates/deployment.yaml:19 | INFO | Acceptable risk | Real hardening candidate, deferred: readOnlyRootFilesystem requires emptyDir mounts for /tmp and the Quarto/WeasyPrint/matplotlib cache paths. Accepted until that work is scheduled. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912094](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912094) | Ensure Administrative Boundaries Between Resources | helm/nce-safe-simulator/templates/service.yaml:5 | INFO | Not applicable | Service and all chart objects set namespace: {{ .Release.Namespace }} — segregation is parameterized per release; the finding fires on the template placeholder. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912092](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912092) | Pod or Container Without LimitRange | helm/nce-safe-simulator/templates/pvc.yaml:33 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, so the workload is bounded. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912091](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912091) | Missing AppArmor Profile | helm/nce-safe-simulator/templates/deployment.yaml:14 | INFO | Not applicable | Chart targets EKS; default EKS node AMIs (AL2/AL2023, Bottlerocket) do not load AppArmor, so the annotation would be inert. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912088](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912088) | Pod or Container Without ResourceQuota | helm/nce-safe-simulator/templates/pvc.yaml:33 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, so the workload is bounded. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |
| [345912086](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912086) | Pod or Container Without LimitRange | helm/nce-safe-simulator/templates/pvc.yaml:5 | INFO | Not applicable | Namespace-admin policy, not an app-chart concern: the deployment declares explicit per-container resources.requests and resources.limits, so the workload is bounded. ResourceQuota/LimitRange are cluster-namespace objects owned by the cluster admin. Backfilled from the #287 triage record (security-fix-via-graph-eng.md); original dismissal 2026-07-31 carried no reason. Refs #304. |

### Dependency Scanning — 1 findings

| Vuln | Finding | Component | Severity | Disposition | Justification |
|---|---|---|---|---|---|
| [345912116](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912116) | CVE-2026-61632 | pymdown-extensions | MEDIUM | Not applicable | Not applicable — the vulnerable functionality is never enabled. pymdown-extensions is not imported anywhere in this codebase; it arrives only as a transitive dependency of marimo (interactive report pages), and marimo's markdown renderer explicitly disables the b64 extension this CVE lives in — its source comments it out with the note 'Base64 is not enabled, since app users could potentially use it to grab files they shouldn't have access to' (marimo/_output/md.py, verified in marimo 0.23.16). No code path, user-facing or otherwise, loads pymdownx.b64. Footnote: requirements.lock has since moved to pymdown-extensions 11.0.1 (finding was against 10.21.3), so the finding may also age out on a future scan; the dismissal rests on unreachability, not the version. Refs #304. |

### Secret Detection — 3 findings

| Vuln | Finding | Component | Severity | Disposition | Justification |
|---|---|---|---|---|---|
| [346976723](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/346976723) | GitLab personal access token | — | CRITICAL | False positive | Documentation placeholder (glpat-XXXX... spelling), not a credential. Defanged at HEAD by #292 (angle-bracket form); retained history immutably keeps the old spelling, so historic scans will keep matching it. Same disposition as the two 2026-07-30 placeholder findings. |
| [345912115](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912115) | GitLab personal access token | — | CRITICAL | Used in tests | Documentation placeholder, not a credential: the glpat- example token in the sample config / README env-var instructions. The PAT rule matches the pattern regardless of content. |
| [345912114](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/security/vulnerabilities/345912114) | GitLab personal access token | — | CRITICAL | Used in tests | Documentation placeholder, not a credential: the glpat- example token in the sample config / README env-var instructions. The PAT rule matches the pattern regardless of content. |

## Remediated (resolved) register

97 findings fixed in code and verified gone in the scan. Full list in [`dispositions.csv`](dispositions.csv). By scanner:

| Scanner | Remediated |
|---|---:|
| Container Scanning | 21 |
| Dependency Scanning | 11 |
| SAST / IaC | 58 |
| Secret Detection | 7 |

