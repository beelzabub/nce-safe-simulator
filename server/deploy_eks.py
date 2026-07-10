"""App-driven EKS/Kubernetes deploy, status, and destroy (issue #218).

Mirror of the ECS module (#217): the Deploy Options section launches EKS
deploy/destroy as durable subprocess jobs through the ``--deploy-eks
publish|destroy|status`` subcommand on ``NceGitLab.py``, which shells into
:func:`run_cli` here. This is the exact same CDK/Helm path an operator drives by
hand (``make -C cdk eks-full-deploy`` / ``eks-destroy``); the app just runs it as
a refresh-survivable job, streaming output to the job log.

Deploy strategy (decision A3, locked):
- **Reuse the existing ECR image tag.** Unlike ``ecs-deploy``, ``eks-full-deploy``
  never builds an image — the Helm chart references the current ECR tag, which is
  pushed out of band with ``make -C cdk ecr-push``. So publish requires an image
  to already exist and fails fast with a clear message when the repository is
  empty (rather than deploying a chart that can't pull).
- **No CodeBuild.** The image is built/pushed by the operator; there is no
  server-side build service.

Status is read straight from CloudFormation (stack ``NceEksStack``), mirroring the
``GET /api/deploy/status`` reader in ``server/app.py`` so the CLI and the UI agree,
with the ``eks_cf_url`` value the CloudFront step writes to ``cdk-eks.json`` as a
fallback for the public URL.
"""
import json
import shutil
from pathlib import Path

from server.deploy_proc import run_streaming

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CDK_DIR = _REPO_ROOT / "cdk"
_EKS_CTX = _CDK_DIR / "cdk-eks.json"

# CloudFormation stack the EKS CDK app provisions (cdk/eks_app.py).
EKS_STACK = "NceEksStack"

# make targets that own the real CDK/Helm deploy/destroy (cdk/Makefile).
_DEPLOY_TARGET = "eks-full-deploy"
_DESTROY_TARGET = "eks-destroy"

# Stack statuses that mean "up and usable" — kept in sync with app._CFN_HEALTHY.
_CFN_HEALTHY = {
    "CREATE_COMPLETE", "UPDATE_COMPLETE",
    "UPDATE_ROLLBACK_COMPLETE", "IMPORT_COMPLETE",
}

# Tools the EKS deploy path needs on PATH. EKS additionally needs kubectl + helm
# (the LB controller install and the app chart), on top of the CDK toolchain;
# the make targets parse cdk context JSON with ``jq``. ``docker`` is
# intentionally excluded — the EKS path never builds an image.
_REQUIRED_TOOLS = ("make", "jq", "cdk", "node", "aws", "kubectl", "helm")


# ---------------------------------------------------------------------------
# config / preflight
# ---------------------------------------------------------------------------

def _cdk_context() -> dict:
    """Return the ``context`` dict from cdk-eks.json, or {} if unreadable."""
    try:
        return json.loads(_EKS_CTX.read_text()).get("context", {})
    except Exception:
        return {}


def _app_name(default="nce-safe-simulator") -> str:
    """The ECR repository / app name from cdk-eks.json context."""
    return _cdk_context().get("app_name") or default


def _missing_tools() -> list:
    """Required deploy tools that are not on PATH."""
    return [t for t in _REQUIRED_TOOLS if shutil.which(t) is None]


def _ecr_image_count(app_name) -> "int | None":
    """Number of images in the app's ECR repository, or ``None`` when it can't be
    determined (no boto3, no credentials, repo absent). ``None`` means "don't
    block" — the make target will surface any real problem."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except Exception:
        return None
    try:
        ecr = boto3.client("ecr")
        ids = ecr.list_images(repositoryName=app_name).get("imageIds", [])
        return len(ids)
    except (ClientError, BotoCoreError, NoCredentialsError):
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# make / cdk runner
# ---------------------------------------------------------------------------

def _run_make(target, *, log=print) -> int:
    """Run ``make -C cdk <target>`` and return its exit code.

    Runs under a pseudo-tty (issue #225) so cdk/node/helm stream line-by-line
    into the durable job log instead of block-buffering to a burst at the end.
    """
    return run_streaming(["make", "-C", str(_CDK_DIR), target], log=log)


def _preflight(*, require_image, log=print) -> None:
    """Verify the deploy toolchain before invoking the CDK/Helm path.

    Raises SystemExit with a clear, operator-facing message when the environment
    can't run the deploy — so the job log explains the failure instead of dying
    with a cryptic error deep inside make/cdk/helm.
    """
    missing = _missing_tools()
    if missing:
        raise SystemExit(
            "EKS deploy requires these tools on PATH but they are missing: "
            f"{', '.join(missing)}. Install them on the box running the server "
            "(this is the operator environment, not the deployed container)."
        )
    if require_image:
        app_name = _app_name()
        count = _ecr_image_count(app_name)
        if count == 0:
            raise SystemExit(
                f"ECR repository '{app_name}' has no image. EKS deploy never builds "
                "one (the Helm chart pulls the current tag), so push an image first "
                "with 'make -C cdk ecr-push' (decision A3: reuse the existing tag, "
                "never CodeBuild), then retry."
            )
        if count is None:
            log("  (could not read ECR image count — assuming an image exists)")
        else:
            log(f"  ECR repository '{app_name}' holds {count} image(s)")


# ---------------------------------------------------------------------------
# public operations
# ---------------------------------------------------------------------------

def publish(*, log=print) -> int:
    """Deploy (or update) the EKS stack + app via the real CDK/Helm path.

    Reuses the existing ECR image tag (the deploy never builds one); fails fast in
    preflight when the repository is empty. Returns the exit code; raises
    SystemExit on a preflight failure or non-zero deploy.
    """
    log("EKS deploy — CDK stack 'NceEksStack' + Helm release (issue #218)")
    _preflight(require_image=True, log=log)
    rc = _run_make(_DEPLOY_TARGET, log=log)
    if rc != 0:
        raise SystemExit(f"eks-full-deploy failed (exit {rc})")
    log("EKS deploy complete.")
    return rc


def destroy(*, log=print) -> int:
    """Tear down the EKS stack (the Helm release is uninstalled first by the make
    target). Returns the exit code; raises SystemExit on a preflight failure or
    non-zero destroy."""
    log("EKS destroy — CDK stack 'NceEksStack' (issue #218)")
    _preflight(require_image=False, log=log)
    rc = _run_make(_DESTROY_TARGET, log=log)
    if rc != 0:
        raise SystemExit(f"eks-destroy failed (exit {rc})")
    log("EKS destroy complete.")
    return rc


def eks_deploy_status() -> dict:
    """Point-in-time status of the EKS deployment, read from CloudFormation.

    Standalone by design (so ``--deploy-eks status`` works without importing the
    server app): mirrors ``server/app.py``'s stack-backed reader — a coarse
    ``state``, the public ``url`` when known (falling back to the ``eks_cf_url``
    the CloudFront step writes to cdk-eks.json), and the raw ``stack_status``.
    Resilient: any failure reads as ``not_deployed``.
    """
    status, outputs = _describe_stack(EKS_STACK)
    url = None
    for key in ("CloudFrontUrl", "AppUrl"):
        if outputs.get(key):
            url = outputs[key]
            break
    if url is None:
        url = _cdk_context().get("eks_cf_url") or None
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
    """Entry point for ``NceGitLab.py --deploy-eks ACTION``.

    ``publish`` and ``destroy`` run as durable subprocess jobs; ``status`` prints
    the status JSON (handy for operators / smoke tests).
    """
    if action == "publish":
        publish(log=log)
    elif action == "destroy":
        destroy(log=log)
    elif action == "status":
        print(json.dumps(eks_deploy_status(), indent=2))
    else:
        raise SystemExit(f"Unknown deploy-eks action: {action!r}")
