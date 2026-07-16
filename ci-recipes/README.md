# CI recipes

Drop-in GitLab CI/CD job snippets. Each `*.yml` here is a **self-contained job**
you copy into your project's top-level `.gitlab-ci.yml` — they are *examples to
grab from*, not files GitLab includes automatically.

## How to use one

1. Open the recipe and read its header — it lists the prerequisites (committed
   files, CI/CD variables, access tokens).
2. Copy the job block into your `.gitlab-ci.yml`.
3. Adjust the marked spots: the `stage:` (must exist in your pipeline), the
   `image:`, and the `rules:` / triggers.
4. Set any CI/CD variables the recipe calls for (mask secrets).

You can also pull one in with GitLab's native
[`include`](https://docs.gitlab.com/ee/ci/yaml/#include) if you'd rather
reference it than paste it — but the intent here is copy-and-own.

## Recipes

| File | What it does |
|------|--------------|
| [`epic-cards-deck.yml`](epic-cards-deck.yml) | Renders the epic-cards "Capability Card" PDF and publishes it as a downloadable pipeline artifact. |

## Why these work unattended

The CLI is non-interactive-safe: when stdin isn't a TTY (every CI runner), tools
never prompt — each option you don't pass on the command line takes its default,
and a genuinely required-but-missing value fails the job loudly instead of
hanging. So a recipe only has to pass the handful of options it actually wants to
pin (e.g. `--output_path`); everything else resolves from `config.json` and the
tool's own config files (for epic-cards, `epic-cards-spec.json`).
