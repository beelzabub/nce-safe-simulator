"""Guards on the CI configuration (issues #279, #283).

The .gitlab-ci.yml test job must run in the pipeline's own dev image with no
at-job package fetches, and the containerize-bootstrap recipe must stay an
ungated mirror of the baseline containerize job — it exists precisely to run
when the test gate cannot be satisfied (empty registry after a fresh import).
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_CI = REPO_ROOT / ".gitlab-ci.yml"
RECIPES = REPO_ROOT / "ci-recipes"


def _load(path):
    return yaml.safe_load(path.read_text())


def test_all_ci_yaml_parses():
    for path in [ROOT_CI, *sorted(RECIPES.glob("*.yml"))]:
        assert isinstance(_load(path), dict), f"{path.name} did not parse to a mapping"


def test_test_job_runs_in_the_dev_image():
    test_job = _load(ROOT_CI)["test"]
    assert test_job["image"] == "$CI_REGISTRY_IMAGE/dev:latest"


def test_test_job_makes_no_package_fetches():
    script = "\n".join(_load(ROOT_CI)["test"]["script"])
    for marker in ("weasyprint-apt-debs", "dpkg", "curl", "apt-get"):
        assert marker not in script, f"test job script still contains '{marker}'"
    # The delta-catcher stays: branch-added Python deps must install.
    assert "pip install -r requirements.txt" in script


def test_bootstrap_recipe_is_ungated():
    job = _load(RECIPES / "containerize-bootstrap.yml")["containerize-bootstrap"]
    assert "needs" not in job, "bootstrap recipe must not be gated on test"
    assert "rules" not in job, "selection by RECIPE is the only gate"


def test_bootstrap_recipe_mirrors_containerize():
    """The bootstrap recipe must build exactly what the baseline publishes —
    same targets, same destinations, same #269/#276 guards — or a bootstrapped
    registry would diverge from a normally built one."""
    baseline = _load(ROOT_CI)["containerize"]
    bootstrap = _load(RECIPES / "containerize-bootstrap.yml")["containerize-bootstrap"]

    assert bootstrap["script"] == baseline["script"]
    assert bootstrap["before_script"] == baseline["before_script"]
    assert bootstrap["image"] == baseline["image"]
    assert bootstrap["variables"]["FF_USE_INIT_WITH_DOCKER_EXECUTOR"] == \
        baseline["variables"]["FF_USE_INIT_WITH_DOCKER_EXECUTOR"]


def test_bootstrap_recipe_is_catalogued():
    readme = (RECIPES / "README.md").read_text()
    assert "containerize-bootstrap.yml" in readme
