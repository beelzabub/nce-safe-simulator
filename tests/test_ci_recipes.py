"""ci-recipes/ consistency checks.

The baseline recipe (ci-recipes/baseline-gitlab-ci.yml) promises to be a
verbatim copy of the shipped .gitlab-ci.yml below its header marker, so a
user can `cp` it over their experiments to get back to ground zero
(issue #276 follow-on to #275). This test is what keeps that promise:
any edit to .gitlab-ci.yml must be mirrored into the recipe.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKER = "verbatim baseline below"


def test_baseline_recipe_matches_gitlab_ci():
    ci = (REPO_ROOT / ".gitlab-ci.yml").read_text()
    recipe_lines = (
        (REPO_ROOT / "ci-recipes" / "baseline-gitlab-ci.yml")
        .read_text()
        .splitlines(keepends=True)
    )
    marker_idx = next(
        i for i, line in enumerate(recipe_lines) if MARKER in line
    )
    body = "".join(recipe_lines[marker_idx + 1 :])
    assert body == ci, (
        "ci-recipes/baseline-gitlab-ci.yml has drifted from .gitlab-ci.yml — "
        "re-copy the file below the marker (edit .gitlab-ci.yml first, "
        "then mirror it into the recipe)"
    )
