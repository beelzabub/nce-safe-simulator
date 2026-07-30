# CI recipes

Runnable GitLab CI/CD child pipelines, selected at run time by a pipeline
variable. The repo's top-level `.gitlab-ci.yml` is a **router** (issue #283):
with no variable it runs the baseline pipeline (`test` + `containerize`,
issue #275's ground zero) exactly as always; with `RECIPE=<name>` the baseline
sits out and `ci-recipes/<name>.yml` runs as a child pipeline instead. Nothing
gets copied into `.gitlab-ci.yml` and nothing needs restoring afterwards.

## How to run one

- **UI:** CI/CD → Pipelines → **Run pipeline** → pick the branch → add variable
  `RECIPE` = the recipe name (filename without `.yml`).
- **CLI:** `glab ci run -b <branch> --variables RECIPE:smoke`
- **Scheduled:** Build → Pipeline schedules → new schedule that defines
  `RECIPE=<name>` — e.g. a weekly `all-reports` run.

> **If GitLab answers "Insufficient permissions to set pipeline variables":**
> the project restricts run-time pipeline variables to a role you don't have
> (`ci_pipeline_variables_minimum_override_role`, Owner by default on newer
> projects — an Owner can lower it under Settings → CI/CD → Variables). Until
> then, use a temporary **project** variable, which that setting doesn't gate:
>
> ```bash
> glab variable set RECIPE smoke
> glab api "projects/:id/pipeline?ref=<branch>" -X POST
> # wait for the pipeline AND its child to finish, then:
> glab variable delete RECIPE
> ```
>
> Two cautions: the variable applies to every pipeline started while it's set
> (don't leave it lying around), and it must survive until the child pipeline
> has been created — the recipe filename is resolved when the `recipe` trigger
> job executes, so deleting the variable too early fails the child with
> "Included file `ci-recipes/.yml` does not have YAML extension".

Extra variables on the same run are forwarded into the child pipeline
(`trigger:forward:pipeline_variables`), so recipes can take parameters
(e.g. a future `RECIPE=tool` + `TOOL=export-epics`).

In the UI the parent pipeline shows a single `recipe` trigger job; the child
pipeline hangs off it as a downstream pipeline, and its result is the parent's
result (`strategy: depend`).

## Before you run one

Open the recipe and read its header — it lists how to run it and the
prerequisites (committed files, CI/CD variables, access tokens). Secrets go in
masked CI/CD variables, never in the file.

## Recipes

| File | What it does |
|------|--------------|
| [`smoke.yml`](smoke.yml) | **Start here.** Proves the router plumbing: runs one echo job in a child pipeline and shows which variables were forwarded. Also the skeleton to copy when authoring a new recipe. |
| [`epic-cards-deck.yml`](epic-cards-deck.yml) | Renders the epic-cards "Capability Card" PDF and publishes it as a downloadable pipeline artifact. Runs in the project's own runtime image — Pango/fonts/deps baked in, no external downloads (a standalone python:3.11 variant is included for spaces without the image). |
| [`all-reports.yml`](all-reports.yml) | Runs the full report suite (`--report all`) inside the project's own runtime image — Quarto/Pango/deps baked in, no external downloads — and publishes the rendered `public/` site as an artifact. A full run rewrites the wiki report pages, so it runs only when selected (or on a schedule you create). |
| [`kaniko-runner-diag.yml`](kaniko-runner-diag.yml) | **Diagnostic.** Discriminates every known cause of the `containerize` "unlinkat //sbin/docker-init: device or resource busy" failure (issue #276): stale-yaml retries, runner init injection / pinned feature flag, umount privileges, stale kaniko image. Run it, save the log. |
| [`security-sast.yml`](security-sast.yml) | Static application security testing (Semgrep) over the Python + JS source. Findings: pipeline Security tab, Vulnerability report, `gl-sast-report.json`. |
| [`security-secret-detection.yml`](security-secret-detection.yml) | Leaked tokens/keys/credentials (Gitleaks). `SECRET_DETECTION_HISTORIC_SCAN=true` sweeps the full git history. |
| [`security-dependency-scanning.yml`](security-dependency-scanning.yml) | Known-vulnerable dependency versions from requirements.txt + frontend lockfiles, plus the Dependency list SBOM view. |
| [`security-container-scanning.yml`](security-container-scanning.yml) | CVE scan (Trivy) of the project's own runtime image from the Container Registry (`CS_IMAGE` to scan another). |
| [`security-iac.yml`](security-iac.yml) | Infrastructure-as-code misconfiguration scan (KICS) over cdk/, helm/, Dockerfile. |
| [`security-all.yml`](security-all.yml) | All five scanners in one child pipeline — the one-shot audit / the recipe to schedule. |

## Writing a new recipe

A recipe is a **self-contained child pipeline**, not a job snippet — it
inherits nothing from the root yaml:

1. Copy `smoke.yml` to `ci-recipes/<name>.yml`.
2. Declare your own `stages:` and per-job `image:` (the project's runtime
   image `$CI_REGISTRY_IMAGE:latest` with `entrypoint: [""]` is the usual
   choice — all deps baked in, air-gap safe).
3. No selection `rules:` needed — being selected by `RECIPE=<name>` *is* the
   gate. Only add rules for gates beyond selection (e.g. a `CONFIRM=yes`
   variable on a mutating recipe).
4. Document prerequisites in the header, run it with `RECIPE=<name>`, and add
   a row to the table above.

## Why these work unattended

The CLI is non-interactive-safe: when stdin isn't a TTY (every CI runner), tools
never prompt — each option you don't pass on the command line takes its default,
and a genuinely required-but-missing value fails the job loudly instead of
hanging. So a recipe only has to pass the handful of options it actually wants to
pin (e.g. `--output_path`); everything else resolves from `config.json` and the
tool's own config files (for epic-cards, `epic-cards-spec.json`).
