"""App-driven ECS/Fargate deploy, status, and destroy (issue #217).

The Deploy Options section of Run Reports launches ECS deploy/destroy as durable
subprocess jobs (issue #214/#215) through the ``--deploy-ecs publish|destroy|status``
subcommand on ``NceGitLab.py``, which shells into :func:`run_cli` here. This is
the exact same CDK path an operator drives by hand (``make -C cdk ecs-deploy`` /
``ecs-destroy`` → ``cdk deploy/destroy NceStack``); the app just runs it as a
refresh-survivable job, streaming CDK output to the job log.

Deploy strategy (decision A3, locked):
- **Reuse the existing ECR image tag.** The ``ecs-deploy`` make target only builds
  and pushes a new image when the repository is empty; when an image already
  exists it deploys the current tag straight through.
- **Build+push only when a Docker daemon is present.** A fresh (empty) repository
  needs an initial image, which requires Docker. If no image exists *and* Docker
  is unavailable, we fail fast here with a clear message rather than letting the
  make target die mid-build.
- **No CodeBuild.** The image is built locally (operator box) or reused; there is
  no server-side build service.

Status is read straight from CloudFormation (stack ``NceStack``), mirroring the
``GET /api/deploy/status`` reader in ``server/app.py`` so the CLI and the UI agree.
"""
import json
import shutil
import subprocess
from pathlib import Path

from server.deploy_proc import run_streaming

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CDK_DIR = _REPO_ROOT / "cdk"
_ECS_CTX = _CDK_DIR / "cdk-ecs.json"

# CloudFormation stack the ECS CDK app provisions (cdk/ecs_app.py).
ECS_STACK = "NceStack"

# make targets that own the real CDK deploy/destroy (cdk/Makefile).
_DEPLOY_TARGET = "ecs-deploy"
_DESTROY_TARGET = "ecs-destroy"

# Stack statuses that mean "up and usable" — kept in sync with app._CFN_HEALTHY.
_CFN_HEALTHY = {
    "CREATE_COMPLETE", "UPDATE_COMPLETE",
    "UPDATE_ROLLBACK_COMPLETE", "IMPORT_COMPLETE",
}

# Tools the CDK deploy path needs on PATH. The make targets parse cdk context
# JSON with ``jq``. ``docker`` is intentionally excluded — it is only required
# for the initial image build (see _needs_image_build).
_REQUIRED_TOOLS = ("make", "jq", "cdk", "node", "aws")


# ---------------------------------------------------------------------------
# config / preflight
# ---------------------------------------------------------------------------

def _app_name(default="nce-safe-simulator") -> str:
    """The ECR repository / ECS app name from cdk-ecs.json context."""
    try:
        return json.loads(_ECS_CTX.read_text())["context"]["app_name"]
    except Exception:
        return default


def _missing_tools() -> list:
    """Required deploy tools that are not on PATH."""
    return [t for t in _REQUIRED_TOOLS if shutil.which(t) is None]


def _docker_available() -> bool:
    """True when a Docker daemon is reachable (needed only for the first image)."""
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except Exception:
        return False


def _ecr_image_count(app_name) -> "int | None":
    """Number of images in the app's ECR repository, or ``None`` when it can't be
    determined (no boto3, no credentials). ``None`` means "don't block" — the
    make target will surface any real problem. A **missing repository** is a
    definite answer, not an unknown: the stack creates the repo itself on the
    first deploy, so absent-repo means zero images and an initial build+push
    is certainly required."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except Exception:
        return None
    try:
        ecr = boto3.client("ecr")
        ids = ecr.list_images(repositoryName=app_name).get("imageIds", [])
        return len(ids)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code") if hasattr(e, "response") else None
        if code == "RepositoryNotFoundException":
            return 0
        return None
    except (BotoCoreError, NoCredentialsError):
        return None
    except Exception:
        return None


def _needs_image_build(app_name, *, log=print) -> bool:
    """Decide whether this deploy would have to build+push an initial image.

    Returns True only when we can positively determine the ECR repo is empty.
    When the count is unknown (no creds / no boto3) we assume an image exists and
    let the make target proceed — it does its own authoritative check.
    """
    count = _ecr_image_count(app_name)
    if count is None:
        log("  (could not read ECR image count — assuming an image exists)")
        return False
    log(f"  ECR repository '{app_name}' holds {count} image(s)")
    return count == 0


# ---------------------------------------------------------------------------
# make / cdk runner
# ---------------------------------------------------------------------------

def _run_make(target, *, log=print) -> int:
    """Run ``make -C cdk <target>`` and return its exit code.

    Runs under a pseudo-tty (issue #225) so cdk/node stream line-by-line into
    the durable job log instead of block-buffering to a burst at the end.
    """
    return run_streaming(["make", "-C", str(_CDK_DIR), target], log=log)


def _preflight(*, require_image_build_check, log=print) -> None:
    """Verify the deploy toolchain before invoking the CDK path.

    Raises SystemExit with a clear, operator-facing message when the environment
    can't run the deploy — so the job log explains the failure instead of dying
    with a cryptic error deep inside make/cdk.
    """
    missing = _missing_tools()
    if missing:
        raise SystemExit(
            "ECS deploy requires these tools on PATH but they are missing: "
            f"{', '.join(missing)}. Install them on the box running the server "
            "(this is the operator environment, not the deployed container)."
        )
    if require_image_build_check:
        app_name = _app_name()
        if _needs_image_build(app_name, log=log) and not _docker_available():
            raise SystemExit(
                f"ECR repository '{app_name}' has no image and no Docker daemon "
                "is available to build the first one (decision A3: build only when "
                "Docker is present, never CodeBuild). Start Docker, or push an "
                "initial image with 'make -C cdk ecr-push', then retry."
            )


# ---------------------------------------------------------------------------
# public operations
# ---------------------------------------------------------------------------

def publish(*, log=print) -> int:
    """Deploy (or update) the ECS/Fargate stack via the real CDK path.

    Reuses the existing ECR image tag; only the make target's own check builds a
    new image, and only when Docker is present (decision A3). Returns the exit
    code; raises SystemExit on a preflight failure or non-zero deploy.
    """
    log("ECS deploy — CDK stack 'NceStack' (issue #217)")
    _preflight(require_image_build_check=True, log=log)
    rc = _run_make(_DEPLOY_TARGET, log=log)
    if rc != 0:
        raise SystemExit(f"ecs-deploy failed (exit {rc})")
    log("ECS deploy complete.")
    return rc


def destroy(*, log=print) -> int:
    """Tear down the ECS/Fargate stack (EFS and CloudWatch logs are retained by
    the CDK stack's removal policies). Returns the exit code; raises SystemExit
    on a preflight failure or non-zero destroy."""
    log("ECS destroy — CDK stack 'NceStack' (issue #217)")
    _preflight(require_image_build_check=False, log=log)
    rc = _run_make(_DESTROY_TARGET, log=log)
    if rc != 0:
        raise SystemExit(f"ecs-destroy failed (exit {rc})")
    log("ECS destroy complete.")
    return rc


def ecs_deploy_status() -> dict:
    """Point-in-time status of the ECS deployment, read from CloudFormation.

    Standalone by design (so ``--deploy-ecs status`` works without importing the
    server app): mirrors ``server/app.py``'s stack-backed reader — a coarse
    ``state``, the public ``url`` when known, and the raw ``stack_status``.
    Resilient: any failure reads as ``not_deployed``.
    """
    status, outputs = _describe_stack(ECS_STACK)
    url = None
    for key in ("CloudFrontUrl", "AppUrl", "AlbUrl", "AlbDns"):
        if outputs.get(key):
            url = outputs[key]
            break
    result = {"state": _cfn_state(status), "url": url}
    if status:
        result["stack_status"] = status
    return result


def _cfn_state(status: "str | None") -> str:
    if status is None:
        return "not_deployed"
    if status.endswith("_IN_PROGRESS"):
        return "destroying" if status.startswith("DELETE") else "deploying"
    if status in _CFN_HEALTHY:
        return "deployed"
    return "error"


def _describe_stack(stack_name: str) -> "tuple[str | None, dict]":
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except Exception:
        return None, {}
    try:
        cf = boto3.client("cloudformation")
        stacks = cf.describe_stacks(StackName=stack_name).get("Stacks", [])
    except (ClientError, BotoCoreError, NoCredentialsError):
        return None, {}
    except Exception:
        return None, {}
    if not stacks:
        return None, {}
    stack = stacks[0]
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
    return stack.get("StackStatus"), outputs


def run_cli(action, *, log=print):
    """Entry point for ``NceGitLab.py --deploy-ecs ACTION``.

    ``publish`` and ``destroy`` run as durable subprocess jobs; ``status`` prints
    the status JSON (handy for operators / smoke tests).
    """
    if action == "publish":
        publish(log=log)
    elif action == "destroy":
        destroy(log=log)
    elif action == "status":
        print(json.dumps(ecs_deploy_status(), indent=2))
    else:
        raise SystemExit(f"Unknown deploy-ecs action: {action!r}")
