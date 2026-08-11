"""Guards on the security-evidence refresh path (issue #317).

The generator (`scripts/security_evidence.py`, issue #304 §2) gained a `--check`
mode and a recipe that runs it. Both exist to answer one question — *is the
committed register still true?* — without ever writing to `docs/security` and
without ever failing a pipeline over the answer. The register's value rests on a
human having read and accepted the findings, so the two properties these tests
protect are: **it changes nothing**, and **it is green either way**.

The drift comparison also has to ignore provenance. Every regeneration re-stamps
the scan sha, timestamp, pipeline id and per-report SHA-256, so a naive textual
diff reports drift on every run and the signal becomes noise.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "security_evidence.py"
RECIPE = REPO_ROOT / "ci-recipes" / "security-evidence.yml"
RECIPES_README = REPO_ROOT / "ci-recipes" / "README.md"

_spec = importlib.util.spec_from_file_location("security_evidence", SCRIPT)
se = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(se)


# ── fixtures ─────────────────────────────────────────────────────────────────

def _finding(vid, **over):
    r = {"vuln_id": vid, "url": f"https://example/{vid}", "cve": f"CVE-2026-{vid}",
         "scanner": "Container Scanning", "component": "libc6", "severity": "HIGH",
         "state": "DISMISSED", "disposition": "Acceptable risk", "title": "t",
         "justification": "because", "report_type": "CONTAINER_SCANNING", "pkg_group": "glibc"}
    r.update(over)
    return r


def _write_register(d, findings, sha="aaaaaaaa", generated_at="2026-08-01T00:00:00Z",
                    pipeline=111, extra_md=""):
    """A minimal but structurally honest register, as the generator would emit."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "evidence.json").write_text(json.dumps({
        "project": "p", "scanned_sha": sha, "generated_at": generated_at,
        "scan_pipeline": {"id": pipeline, "url": f"https://example/-/pipelines/{pipeline}"},
        "totals": {"detected": 0, "dismissed": len(findings), "resolved": 0},
        "scanners": [{"job": "container_scanning", "scanner": "Trivy", "version": "0.1",
                      "report_sha256": sha * 8}],
        "findings": findings,
    }, indent=2))
    (d / "EVIDENCE.md").write_text(
        "# Register\n\n## Provenance\n"
        f"- **Scanned commit:** `develop @ {sha}`\n"
        f"- **Scan:** pipeline [#{pipeline}](https://example), {generated_at[:10]}\n"
        "- **Source:** GitLab Vulnerability Report.\n\n"
        f"## {len(findings)} findings\n{extra_md}"
    )
    (d / "dispositions.csv").write_text(
        "vuln_id,state\n" + "".join(f"{f['vuln_id']},{f['state']}\n" for f in findings))
    return d


# ── drift semantics ──────────────────────────────────────────────────────────

def test_findings_delta_spots_added_gone_and_changed():
    old = [_finding("1"), _finding("2"), _finding("3")]
    new = [_finding("1"),
           _finding("3", state="DETECTED", disposition="—"),
           _finding("4")]
    added, gone, changed = se.findings_delta(old, new)
    assert [r["vuln_id"] for r in added] == ["4"]
    assert [r["vuln_id"] for r in gone] == ["2"]
    assert [r["vuln_id"] for r, _ in changed] == ["3"]
    assert changed[0][1]["state"] == ("DISMISSED", "DETECTED")


def test_findings_delta_is_empty_for_an_unchanged_set():
    findings = [_finding("1"), _finding("2")]
    assert se.findings_delta(findings, list(reversed(findings))) == ([], [], [])


def test_a_changed_justification_counts_as_drift():
    """The justification IS the evidence — a silent edit must not slip through."""
    _, _, changed = se.findings_delta([_finding("1")],
                                      [_finding("1", justification="different now")])
    assert changed and "justification" in changed[0][1]


def test_normalize_evidence_drops_provenance_and_report_hashes():
    ev = {"scanned_sha": "a", "generated_at": "t", "scan_pipeline": {"id": 1},
          "totals": {"detected": 1}, "findings": [_finding("1")],
          "scanners": [{"job": "j", "scanner": "Trivy", "version": "0.1", "report_sha256": "x"}]}
    out = se.normalize_evidence(ev)
    assert not (set(se.PROVENANCE_KEYS) & set(out))
    assert out["scanners"] == [{"job": "j", "scanner": "Trivy", "version": "0.1"}]
    # a scanner VERSION change is real drift and must survive normalisation
    bumped = dict(ev, scanners=[dict(ev["scanners"][0], version="0.2")])
    assert se.normalize_evidence(bumped) != out


def test_normalize_md_drops_the_provenance_bullets_only():
    md = ("# R\n- **Scanned commit:** `develop @ abc`\n"
          "- **Scan:** pipeline [#1](u), 2026-08-01\n- **Source:** kept\n")
    assert se.normalize_md(md) == ["# R", "- **Source:** kept"]


# ── check(): the verdict ─────────────────────────────────────────────────────

def test_check_reports_current_when_only_provenance_moved(tmp_path, capsys):
    """The acceptance criterion: an unchanged tree reports no drift."""
    findings = [_finding("1"), _finding("2")]
    committed = _write_register(tmp_path / "committed", findings,
                                sha="aaaaaaaa", generated_at="2026-08-01T00:00:00Z", pipeline=111)
    candidate = _write_register(tmp_path / "candidate", findings,
                                sha="bbbbbbbb", generated_at="2026-08-11T09:00:00Z", pipeline=222)
    assert se.check(str(candidate), str(committed)) == 0
    out = capsys.readouterr().out
    assert "CURRENT" in out and "STALE" not in out


def test_check_reports_stale_and_names_what_moved(tmp_path, capsys):
    committed = _write_register(tmp_path / "committed", [_finding("1"), _finding("2")])
    candidate = _write_register(tmp_path / "candidate",
                                [_finding("1"), _finding("3", severity="CRITICAL")],
                                sha="bbbbbbbb", generated_at="2026-08-11T09:00:00Z", pipeline=222)
    assert se.check(str(candidate), str(committed)) == 0
    out = capsys.readouterr().out
    assert "STALE" in out
    assert "3" in out and "CRITICAL" in out      # the new finding is named
    assert "2" in out                            # the one no longer reported


def test_check_flags_generator_drift_with_no_finding_movement(tmp_path, capsys):
    """A template edit that was never regenerated into the committed copy."""
    findings = [_finding("1")]
    committed = _write_register(tmp_path / "committed", findings)
    candidate = _write_register(tmp_path / "candidate", findings, sha="bbbbbbbb",
                                extra_md="\n## Refreshing this register\nnew section\n")
    assert se.check(str(candidate), str(committed)) == 0
    out = capsys.readouterr().out
    assert "STALE" in out and "EVIDENCE.md differs" in out


def test_check_is_green_even_with_no_committed_register(tmp_path, capsys):
    candidate = _write_register(tmp_path / "candidate", [_finding("1")])
    assert se.check(str(candidate), str(tmp_path / "nothing-here")) == 0
    assert "DRIFT" in capsys.readouterr().out


# ── main(): writes nothing it shouldn't ──────────────────────────────────────

@pytest.fixture
def offline(monkeypatch):
    """No API calls, no git, no network — main()'s plumbing only."""
    for var in se.TOKEN_VARS + ("CI_COMMIT_SHORT_SHA", "CI_API_V4_URL", "CI_DEFAULT_BRANCH"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(se, "resolve_scan_pipeline", lambda ref=None, scan=20: ("999", "cccccccc"))
    monkeypatch.setattr(se, "gql", lambda q: pytest.fail("main() must not call the API here"))
    monkeypatch.setattr(se, "api", lambda p: pytest.fail("main() must not call the API here"))
    return monkeypatch


def test_check_never_writes_the_committed_register(offline, tmp_path):
    seen = {}

    def fake_generate(out, pipeline, sha, generated_at, project_id):
        seen.update(out=out, pipeline=pipeline, sha=sha)
        Path(out).mkdir(parents=True, exist_ok=True)
        return 0

    offline.setattr(se, "generate", fake_generate)
    offline.setattr(se, "check", lambda cand, committed, **kw: seen.update(checked=(cand, committed)) or 0)
    offline.setattr(sys, "argv", ["security_evidence.py", "--check"])

    assert se.main() == 0
    assert os.path.abspath(seen["out"]) != os.path.abspath(se.DOCS_SECURITY)
    assert seen["checked"][1] == se.DOCS_SECURITY          # compared against it
    assert not os.path.exists(seen["out"])                  # temp dir cleaned up


def test_check_refuses_to_write_into_the_committed_dir(offline, capsys):
    offline.setattr(se, "generate", lambda *a, **k: pytest.fail("must not regenerate"))
    offline.setattr(sys, "argv", ["security_evidence.py", "--check", "--out", se.DOCS_SECURITY])
    assert se.main() == 1
    assert "overwrite the committed register" in capsys.readouterr().err


def test_plain_run_still_writes_docs_security(offline, tmp_path):
    """The by-hand refresh path is unchanged: no --check, no --out → in place."""
    seen = {}
    offline.setattr(se, "generate", lambda out, *a, **k: seen.update(out=out))
    offline.setattr(sys, "argv", ["security_evidence.py"])
    assert se.main() == 0
    assert seen["out"] == se.DOCS_SECURITY


def test_sha_comes_from_the_cited_scan_not_this_checkout(offline):
    """The recipe runs on a branch but cites a default-branch scan (#315)."""
    seen = {}
    offline.setattr(se, "generate", lambda out, pipeline, sha, *a: seen.update(sha=sha, pipeline=pipeline))
    offline.setattr(se, "default_sha", lambda: pytest.fail("must not fall back to HEAD"))
    offline.setattr(sys, "argv", ["security_evidence.py"])
    assert se.main() == 0
    assert seen == {"sha": "cccccccc", "pipeline": "999"}


def test_missing_scan_pipeline_fails_actionably(offline, capsys):
    offline.setattr(se, "resolve_scan_pipeline", lambda ref=None, scan=20: (None, None))
    offline.setattr(se, "generate", lambda *a, **k: pytest.fail("nothing to cite"))
    offline.setattr(sys, "argv", ["security_evidence.py", "--check"])
    assert se.main() == 1
    assert "security-all" in capsys.readouterr().err


# ── API access: CI has no glab ───────────────────────────────────────────────

def test_http_is_used_when_a_token_is_present(monkeypatch):
    for var in se.TOKEN_VARS:
        monkeypatch.delenv(var, raising=False)
    assert se.http() is None                                  # → glab fallback
    monkeypatch.setenv("GITLAB_TOKEN", "t-last")
    monkeypatch.setenv("SECURITY_EVIDENCE_TOKEN", "t-first")
    assert se.http() == "t-first"                             # precedence order


def test_api_root_follows_the_ci_environment(monkeypatch):
    monkeypatch.delenv("CI_API_V4_URL", raising=False)
    assert se.api_v4() == "https://gitlab.com/api/v4"
    monkeypatch.setenv("CI_API_V4_URL", "https://gitlab.example.mil/api/v4/")
    assert se.api_v4() == "https://gitlab.example.mil/api/v4"
    # the GraphQL endpoint is a sibling of v4, not a child
    assert se.api_v4().rsplit("/", 1)[0] + "/graphql" == "https://gitlab.example.mil/api/graphql"


def test_the_script_never_shells_out_to_glab_when_a_token_exists(monkeypatch):
    """CI has requests baked in and no glab; a download would break air-gap."""
    monkeypatch.setenv("SECURITY_EVIDENCE_TOKEN", "tok")
    monkeypatch.setattr(se.subprocess, "run", lambda *a, **k: pytest.fail("shelled out to glab"))

    class _R:
        status_code = 200
        text = '{"sha": "deadbeefcafe"}'

        @staticmethod
        def json():
            return {"data": {}}

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setattr(se.requests, "get", lambda *a, **k: _R())
    monkeypatch.setattr(se.requests, "post", lambda *a, **k: _R())
    assert se.api("projects/1/pipelines/2") == _R.text
    assert se.gql("query {}") == {"data": {}}
    assert se.pipeline_sha("1", "2") == "deadbeef"            # short, as the register uses


# ── the recipe ───────────────────────────────────────────────────────────────

def test_recipe_checks_and_never_targets_docs_security():
    job = yaml.safe_load(RECIPE.read_text())["security-evidence"]
    script = " ".join(job["script"])
    assert "--check" in script
    assert "docs/security" not in script
    assert "build/security-evidence" in script


def test_recipe_publishes_the_candidate_as_artifacts():
    job = yaml.safe_load(RECIPE.read_text())["security-evidence"]
    assert "build/security-evidence/" in job["artifacts"]["paths"]
    assert job["artifacts"]["when"] == "always"


def test_recipe_is_green_either_way():
    """No gate on drift: nothing may turn a stale register into a red pipeline."""
    job = yaml.safe_load(RECIPE.read_text())["security-evidence"]
    assert "rules" not in job          # selection by RECIPE= is the only gate
    assert "retry" not in job
    assert job.get("allow_failure") is None


def test_recipe_runs_in_the_projects_own_image():
    job = yaml.safe_load(RECIPE.read_text())["security-evidence"]
    assert job["image"]["name"] == "$CI_REGISTRY_IMAGE:latest"
    assert job["image"]["entrypoint"] == [""]


def test_recipe_header_states_the_token_requirement():
    header = RECIPE.read_text()
    assert "CI_JOB_TOKEN" in header and "read_api" in header


def test_recipe_is_catalogued():
    readme = RECIPES_README.read_text()
    assert "security-evidence.yml" in readme


def test_refresh_procedure_lives_in_the_generator_not_the_generated_file():
    """EVIDENCE.md is generated output — hand-written prose there is erased."""
    source = SCRIPT.read_text()
    assert "## Refreshing this register" in source
    assert "the commit IS the review step" in source or "deliberate review step" in source
