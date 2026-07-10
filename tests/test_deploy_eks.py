"""Tests for the app-driven EKS deploy module (issue #218).

The module shells to the real ``make -C cdk eks-full-deploy/eks-destroy``
CDK/Helm path; these tests mock the subprocess/tooling/boto3 boundaries so they
never touch AWS or actually run make/cdk/helm.
"""
import json

import pytest

import server.deploy_eks as de


# ---------------------------------------------------------------------------
# config / tool discovery
# ---------------------------------------------------------------------------

def test_app_name_from_context(monkeypatch, tmp_path):
    ctx = tmp_path / "cdk-eks.json"
    ctx.write_text(json.dumps({"context": {"app_name": "my-app"}}))
    monkeypatch.setattr(de, "_EKS_CTX", ctx)
    assert de._app_name() == "my-app"


def test_app_name_falls_back_when_unreadable(monkeypatch, tmp_path):
    monkeypatch.setattr(de, "_EKS_CTX", tmp_path / "missing.json")
    assert de._app_name() == "nce-safe-simulator"


def test_missing_tools_reports_absent(monkeypatch):
    present = {"make", "cdk", "node", "aws", "kubectl"}  # helm "missing"
    monkeypatch.setattr(de.shutil, "which", lambda t: t if t in present else None)
    assert de._missing_tools() == ["helm"]


def test_missing_tools_empty_when_all_present(monkeypatch):
    monkeypatch.setattr(de.shutil, "which", lambda t: f"/usr/bin/{t}")
    assert de._missing_tools() == []


def test_required_tools_include_kubectl_and_helm():
    assert "kubectl" in de._REQUIRED_TOOLS
    assert "helm" in de._REQUIRED_TOOLS
    # EKS never builds an image, so docker is not required.
    assert "docker" not in de._REQUIRED_TOOLS


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

def test_preflight_raises_on_missing_tools(monkeypatch):
    monkeypatch.setattr(de, "_missing_tools", lambda: ["helm", "kubectl"])
    with pytest.raises(SystemExit) as exc:
        de._preflight(require_image=False, log=lambda *_: None)
    assert "helm" in str(exc.value) and "kubectl" in str(exc.value)


def test_preflight_blocks_when_repo_empty(monkeypatch):
    monkeypatch.setattr(de, "_missing_tools", lambda: [])
    monkeypatch.setattr(de, "_ecr_image_count", lambda name: 0)
    with pytest.raises(SystemExit) as exc:
        de._preflight(require_image=True, log=lambda *_: None)
    assert "ecr-push" in str(exc.value).lower()


def test_preflight_passes_when_image_exists(monkeypatch):
    monkeypatch.setattr(de, "_missing_tools", lambda: [])
    monkeypatch.setattr(de, "_ecr_image_count", lambda name: 2)
    de._preflight(require_image=True, log=lambda *_: None)


def test_preflight_proceeds_when_image_count_unknown(monkeypatch):
    # Unknown (no creds / no boto3) must NOT block — the make target decides.
    monkeypatch.setattr(de, "_missing_tools", lambda: [])
    monkeypatch.setattr(de, "_ecr_image_count", lambda name: None)
    de._preflight(require_image=True, log=lambda *_: None)


def test_preflight_skips_image_check_for_destroy(monkeypatch):
    monkeypatch.setattr(de, "_missing_tools", lambda: [])
    monkeypatch.setattr(de, "_ecr_image_count",
                        lambda *a, **k: pytest.fail("destroy must not check images"))
    de._preflight(require_image=False, log=lambda *_: None)


# ---------------------------------------------------------------------------
# publish / destroy → make targets
# ---------------------------------------------------------------------------

@pytest.fixture()
def _clean_preflight(monkeypatch):
    monkeypatch.setattr(de, "_preflight", lambda **k: None)


def _capture_run(captured, returncode=0):
    def _run(argv, *a, **k):
        captured["argv"] = argv
        return returncode
    return _run


def test_publish_runs_eks_full_deploy_target(monkeypatch, _clean_preflight):
    captured = {}
    monkeypatch.setattr(de, "run_streaming", _capture_run(captured))
    de.publish(log=lambda *_: None)
    assert captured["argv"][:2] == ["make", "-C"]
    assert captured["argv"][-1] == "eks-full-deploy"


def test_destroy_runs_eks_destroy_target(monkeypatch, _clean_preflight):
    captured = {}
    monkeypatch.setattr(de, "run_streaming", _capture_run(captured))
    de.destroy(log=lambda *_: None)
    assert captured["argv"][-1] == "eks-destroy"


def test_publish_raises_on_nonzero_exit(monkeypatch, _clean_preflight):
    monkeypatch.setattr(de, "run_streaming", lambda *a, **k: 2)
    with pytest.raises(SystemExit) as exc:
        de.publish(log=lambda *_: None)
    assert "exit 2" in str(exc.value)


def test_destroy_raises_on_nonzero_exit(monkeypatch, _clean_preflight):
    monkeypatch.setattr(de, "run_streaming", lambda *a, **k: 1)
    with pytest.raises(SystemExit):
        de.destroy(log=lambda *_: None)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,expected", [
    (None, "not_deployed"),
    ("CREATE_COMPLETE", "deployed"),
    ("UPDATE_COMPLETE", "deployed"),
    ("CREATE_IN_PROGRESS", "deploying"),
    ("DELETE_IN_PROGRESS", "destroying"),
    ("ROLLBACK_FAILED", "error"),
])
def test_cfn_state_mapping(status, expected):
    assert de._cfn_state(status) == expected


def test_status_deployed_with_url(monkeypatch):
    monkeypatch.setattr(de, "_describe_stack",
                        lambda s: ("CREATE_COMPLETE", {"CloudFrontUrl": "https://eks.example.com"}))
    result = de.eks_deploy_status()
    assert result == {
        "state": "deployed",
        "url": "https://eks.example.com",
        "stack_status": "CREATE_COMPLETE",
    }


def test_status_url_falls_back_to_cdk_context(monkeypatch):
    # Stack live but no URL output yet → fall back to eks_cf_url from cdk-eks.json.
    monkeypatch.setattr(de, "_describe_stack", lambda s: ("UPDATE_COMPLETE", {}))
    monkeypatch.setattr(de, "_cdk_context", lambda: {"eks_cf_url": "https://cf.example.com"})
    assert de.eks_deploy_status()["url"] == "https://cf.example.com"


def test_status_not_deployed_when_stack_absent(monkeypatch):
    monkeypatch.setattr(de, "_describe_stack", lambda s: (None, {}))
    monkeypatch.setattr(de, "_cdk_context", lambda: {})
    assert de.eks_deploy_status() == {"state": "not_deployed", "url": None}


# ---------------------------------------------------------------------------
# run_cli dispatch
# ---------------------------------------------------------------------------

def test_run_cli_publish(monkeypatch):
    calls = []
    monkeypatch.setattr(de, "publish", lambda **k: calls.append("publish"))
    de.run_cli("publish")
    assert calls == ["publish"]


def test_run_cli_destroy(monkeypatch):
    calls = []
    monkeypatch.setattr(de, "destroy", lambda **k: calls.append("destroy"))
    de.run_cli("destroy")
    assert calls == ["destroy"]


def test_run_cli_status_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(de, "eks_deploy_status",
                        lambda: {"state": "deployed", "url": "https://x"})
    de.run_cli("status")
    assert json.loads(capsys.readouterr().out) == {"state": "deployed", "url": "https://x"}


def test_run_cli_unknown_action():
    with pytest.raises(SystemExit):
        de.run_cli("frobnicate")
