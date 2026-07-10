"""ECR as a first-class deploy target (issue #234).

The container-image repository is shared infrastructure: ECS pulls from it,
EKS pulls from it, and neither should own its lifecycle. It used to be a
resource inside ``NceStack``, which meant an in-app ECS destroy deleted the
repo — and its images — out from under a live EKS deployment (the pod fell
into ImagePullBackOff and the site 503'd). The repo now belongs to this
module: created/pushed by the ECR row of the Deployments dialog, referenced
by name from the ECS stack, and untouched by ECS/EKS deploy or destroy.

Operations, driven by ``NceGitLab.py --deploy-ecr publish|destroy|status``:

- **publish** — create the repository when absent (boto3, instant), then build
  and push the app image via the real ``make -C cdk ecr-push`` path as a
  streaming durable job. Requires Docker (decision A3: build only when Docker
  is present, never CodeBuild).
- **destroy** — delete the repository and every image in it. Explicit and
  loud: ECS and EKS cannot pull images until the repo is republished.
- **status** — repo presence + image count + last push time, surfaced as the
  ECR row's status cell so the ECS/EKS image dependency is visible at a
  glance.

This module is also the single home of the ECR read helpers the ECS/EKS
pre-flights use (``ecr_repo_exists`` / ``ecr_image_count``) — previously two
drifting copies, one of which treated a *missing* repository as "assume an
image exists" and let an EKS deploy sail into the ImagePullBackOff failure
this issue is about.
"""
import json
import shutil
import subprocess
from pathlib import Path

from server.deploy_proc import run_streaming

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CDK_DIR = _REPO_ROOT / "cdk"
_ECS_CTX = _CDK_DIR / "cdk-ecs.json"

# make target that owns the real image build+push (cdk/Makefile).
_PUSH_TARGET = "ecr-push"

# Tools the ecr-push make target needs on PATH. ``docker`` is checked
# separately (the daemon must be reachable, not just the CLI present).
_REQUIRED_TOOLS = ("make", "jq", "aws")


# ---------------------------------------------------------------------------
# config / shared read helpers
# ---------------------------------------------------------------------------

def _app_name(default="nce-safe-simulator") -> str:
    """The ECR repository / app name from cdk-ecs.json context."""
    try:
        return json.loads(_ECS_CTX.read_text())["context"]["app_name"]
    except Exception:
        return default


def ecr_repo_exists(app_name) -> "bool | None":
    """Whether the app's ECR repository exists; ``None`` when it can't be
    determined (no boto3, no credentials, access denied)."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except Exception:
        return None
    try:
        ecr = boto3.client("ecr")
        ecr.describe_repositories(repositoryNames=[app_name])
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code") if hasattr(e, "response") else None
        if code == "RepositoryNotFoundException":
            return False
        return None
    except (BotoCoreError, NoCredentialsError):
        return None
    except Exception:
        return None


def ecr_image_count(app_name) -> "int | None":
    """Number of images in the app's ECR repository, or ``None`` when it can't
    be determined (no boto3, no credentials). A **missing repository** is a
    definite answer, not an unknown: the repo is managed by this module, so
    absent-repo means zero images and an initial publish is certainly
    required. Shared by the ECS and EKS pre-flights (issue #234 — previously
    two drifting copies)."""
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


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

def _missing_tools() -> list:
    """Required publish tools that are not on PATH."""
    return [t for t in _REQUIRED_TOOLS if shutil.which(t) is None]


def _docker_available() -> bool:
    """True when a Docker daemon is reachable (publish always builds+pushes)."""
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except Exception:
        return False


def _preflight(*, log=print) -> None:
    """Verify the publish toolchain before mutating anything, so the job log
    explains a bad environment instead of dying mid-make."""
    missing = _missing_tools()
    if missing:
        raise SystemExit(
            "ECR publish requires these tools on PATH but they are missing: "
            f"{', '.join(missing)}. Install them where the server runs (the ops "
            "image variant carries them; the slim image does not)."
        )
    if not _docker_available():
        raise SystemExit(
            "ECR publish builds and pushes the container image, which requires a "
            "reachable Docker daemon (decision A3: build only when Docker is "
            "present, never CodeBuild). Start Docker — for the ops container, "
            "run it with /var/run/docker.sock mounted (make redeploy-ops does) — "
            "then retry."
        )


# ---------------------------------------------------------------------------
# public operations
# ---------------------------------------------------------------------------

def publish(*, log=print) -> int:
    """Create the repository when absent, then build+push the app image via the
    real ``make -C cdk ecr-push`` path. Returns the exit code; raises
    SystemExit on a preflight failure or non-zero push."""
    app_name = _app_name()
    log(f"ECR publish — repository '{app_name}' (issue #234)")
    _preflight(log=log)

    exists = ecr_repo_exists(app_name)
    if exists is False:
        log(f"  repository '{app_name}' absent — creating it")
        import boto3
        try:
            boto3.client("ecr").create_repository(repositoryName=app_name)
        except Exception as e:
            # A concurrent creation is fine; anything else is fatal and clear.
            if "RepositoryAlreadyExistsException" not in str(type(e)) + str(e):
                raise SystemExit(f"Could not create ECR repository '{app_name}': {e}")
    elif exists is True:
        log(f"  repository '{app_name}' exists — building and pushing the image")
    else:
        log("  (could not read repository state — ecr-push will surface any problem)")

    rc = run_streaming(["make", "-C", str(_CDK_DIR), _PUSH_TARGET], log=log)
    if rc != 0:
        raise SystemExit(f"ecr-push failed (exit {rc})")
    log("ECR publish complete.")
    return rc


def destroy(*, log=print) -> int:
    """Delete the repository and every image in it.

    Loud on purpose: until the repo is republished, ECS and EKS deploys are
    blocked at pre-flight and any already-running pods keep serving their
    pulled image but cannot restart onto it."""
    app_name = _app_name()
    log(f"ECR destroy — repository '{app_name}' (issue #234)")
    log("  NOTE: ECS and EKS pull from this repository; they cannot deploy "
        "again until ECR is republished.")
    try:
        import boto3
        from botocore.exceptions import ClientError
    except Exception:
        raise SystemExit("boto3 is required to destroy the ECR repository.")
    try:
        boto3.client("ecr").delete_repository(repositoryName=app_name, force=True)
        log(f"  repository '{app_name}' deleted (images included).")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code") if hasattr(e, "response") else None
        if code == "RepositoryNotFoundException":
            log(f"  repository '{app_name}' already absent — nothing to do.")
        else:
            raise SystemExit(f"ECR destroy failed: {e}")
    log("ECR destroy complete.")
    return 0


def ecr_deploy_status() -> dict:
    """Point-in-time status of the shared image repository for the Deployments
    dialog's ECR row.

    States: ``not_deployed`` (repo definitively absent), ``no_image`` (repo
    exists but holds nothing — ECS/EKS cannot pull), ``deployed`` (repo exists
    with images; ``detail`` carries count + last push), ``unreadable`` (state
    could not be read — no boto3/credentials or AccessDenied; never rendered
    as a false not-deployed, issue #235), ``error`` (an unexpected AWS
    failure worth surfacing). ``url`` is always None — a registry has no
    public front door."""
    app_name = _app_name()
    _unreadable = {
        "state": "unreadable", "url": None,
        "detail": ("status unreadable — the server's AWS identity lacks read "
                   "permissions (or has no credentials)"),
    }
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except Exception:
        return dict(_unreadable)
    try:
        ecr = boto3.client("ecr")
        try:
            repos = ecr.describe_repositories(repositoryNames=[app_name]).get("repositories", [])
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code") if hasattr(e, "response") else None
            if code == "RepositoryNotFoundException":
                return {"state": "not_deployed", "url": None}
            raise
        uri = repos[0].get("repositoryUri") if repos else None
        images = ecr.describe_images(repositoryName=app_name).get("imageDetails", [])
        if not images:
            return {
                "state": "no_image",
                "url": None,
                "repository_uri": uri,
                "detail": "repository created — no image pushed yet",
            }
        last = max((i.get("imagePushedAt") for i in images if i.get("imagePushedAt")),
                   default=None)
        detail = f"{len(images)} image(s)"
        if last is not None:
            # boto3 returns tz-aware local-offset datetimes — normalise so the
            # label is honest.
            from datetime import timezone
            detail += f", last push {last.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC"
        return {
            "state": "deployed",
            "url": None,
            "repository_uri": uri,
            "image_count": len(images),
            "detail": detail,
        }
    except (BotoCoreError, NoCredentialsError):
        return dict(_unreadable)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code") if hasattr(e, "response") else None
        if code in ("AccessDeniedException", "AccessDenied", "UnauthorizedOperation"):
            return dict(_unreadable)
        return {"state": "error", "url": None, "detail": str(e)}
    except Exception:
        return dict(_unreadable)


def run_cli(action, *, log=print):
    """Entry point for ``NceGitLab.py --deploy-ecr ACTION``.

    ``publish`` and ``destroy`` run as durable subprocess jobs; ``status``
    prints the status JSON (handy for operators / smoke tests)."""
    if action == "publish":
        publish(log=log)
    elif action == "destroy":
        destroy(log=log)
    elif action == "status":
        print(json.dumps(ecr_deploy_status(), indent=2, default=str))
    else:
        raise SystemExit(f"Unknown deploy-ecr action: {action!r}")
