"""Tests for the app-driven ECS deploy module (issue #217).

The module shells to the real ``make -C cdk ecs-deploy/ecs-destroy`` CDK path;
these tests mock the subprocess/tooling/boto3 boundaries so they never touch AWS
or actually run make/cdk.
"""
import json
import types

import pytest

import server.deploy_ecs as de


class _Completed:
    def __init__(self, returncode):
        self.returncode = returncode


# ---------------------------------------------------------------------------
# config / tool discovery
# ---------------------------------------------------------------------------

def test_app_name_from_context(monkeypatch, tmp_path):
    ctx = tmp_path / "cdk-ecs.json"
    ctx.write_text(json.dumps({"context": {"app_name": "my-app"}}))
    monkeypatch.setattr(de, "_ECS_CTX", ctx)
    assert de._app_name() == "my-app"


def test_app_name_falls_back_when_unreadable(monkeypatch, tmp_path):
    monkeypatch.setattr(de, "_ECS_CTX", tmp_path / "missing.json")
    assert de._app_name() == "nce-safe-simulator"


def test_missing_tools_reports_absent(monkeypatch):
    present = {"make", "cdk", "node"}  # aws "missing"
    monkeypatch.setattr(de.shutil, "which", lambda t: t if t in present else None)
    assert de._missing_tools() == ["aws"]


def test_missing_tools_empty_when_all_present(monkeypatch):
    monkeypatch.setattr(de.shutil, "which", lambda t: f"/usr/bin/{t}")
    assert de._missing_tools() == []


def test_docker_available_true(monkeypatch):
    monkeypatch.setattr(de.shutil, "which", lambda t: "/usr/bin/docker")
    monkeypatch.setattr(de.subprocess, "run", lambda *a, **k: _Completed(0))
    assert de._docker_available() is True


def test_docker_available_false_when_absent(monkeypatch):
    monkeypatch.setattr(de.shutil, "which", lambda t: None)
    assert de._docker_available() is False


def test_docker_available_false_when_daemon_down(monkeypatch):
    monkeypatch.setattr(de.shutil, "which", lambda t: "/usr/bin/docker")
    monkeypatch.setattr(de.subprocess, "run", lambda *a, **k: _Completed(1))
    assert de._docker_available() is False


# ---------------------------------------------------------------------------
# image-build decision
# ---------------------------------------------------------------------------

def test_needs_image_build_true_when_repo_empty(monkeypatch):
    monkeypatch.setattr(de, "_ecr_image_count", lambda name: 0)
    assert de._needs_image_build("app", log=lambda *_: None) is True


def test_needs_image_build_false_when_images_exist(monkeypatch):
    monkeypatch.setattr(de, "_ecr_image_count", lambda name: 3)
    assert de._needs_image_build("app", log=lambda *_: None) is False


def test_needs_image_build_false_when_count_unknown(monkeypatch):
    # Unknown (no creds / no boto3) must NOT block — the make target decides.
    monkeypatch.setattr(de, "_ecr_image_count", lambda name: None)
    assert de._needs_image_build("app", log=lambda *_: None) is False


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

def test_preflight_raises_on_missing_tools(monkeypatch):
    monkeypatch.setattr(de, "_missing_tools", lambda: ["cdk", "aws"])
    with pytest.raises(SystemExit) as exc:
        de._preflight(require_image_build_check=False, log=lambda *_: None)
    assert "cdk" in str(exc.value) and "aws" in str(exc.value)


def test_preflight_blocks_when_no_image_and_no_docker(monkeypatch):
    monkeypatch.setattr(de, "_missing_tools", lambda: [])
    monkeypatch.setattr(de, "_needs_image_build", lambda name, log=print: True)
    monkeypatch.setattr(de, "_docker_available", lambda: False)
    with pytest.raises(SystemExit) as exc:
        de._preflight(require_image_build_check=True, log=lambda *_: None)
    assert "no image" in str(exc.value).lower()


def test_preflight_passes_when_image_exists(monkeypatch):
    monkeypatch.setattr(de, "_missing_tools", lambda: [])
    monkeypatch.setattr(de, "_needs_image_build", lambda name, log=print: False)
    # Docker not consulted when an image already exists.
    monkeypatch.setattr(de, "_docker_available", lambda: pytest.fail("should not check docker"))
    de._preflight(require_image_build_check=True, log=lambda *_: None)


def test_preflight_skips_image_check_for_destroy(monkeypatch):
    monkeypatch.setattr(de, "_missing_tools", lambda: [])
    monkeypatch.setattr(de, "_needs_image_build",
                        lambda *a, **k: pytest.fail("destroy must not check images"))
    de._preflight(require_image_build_check=False, log=lambda *_: None)


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


def test_publish_runs_ecs_deploy_target(monkeypatch, _clean_preflight):
    captured = {}
    monkeypatch.setattr(de, "run_streaming", _capture_run(captured))
    de.publish(log=lambda *_: None)
    assert captured["argv"][:2] == ["make", "-C"]
    assert captured["argv"][-1] == "ecs-deploy"


def test_destroy_runs_ecs_destroy_target(monkeypatch, _clean_preflight):
    captured = {}
    monkeypatch.setattr(de, "run_streaming", _capture_run(captured))
    de.destroy(log=lambda *_: None)
    assert captured["argv"][-1] == "ecs-destroy"


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
    ("UPDATE_IN_PROGRESS", "deploying"),
    ("DELETE_IN_PROGRESS", "destroying"),
    ("ROLLBACK_FAILED", "error"),
])
def test_cfn_state_mapping(status, expected):
    assert de._cfn_state(status) == expected


def test_status_deployed_with_url(monkeypatch):
    monkeypatch.setattr(de, "_describe_stack",
                        lambda s: ("CREATE_COMPLETE", {"CloudFrontUrl": "https://ecs.example.com"}))
    result = de.ecs_deploy_status()
    assert result == {
        "state": "deployed",
        "url": "https://ecs.example.com",
        "stack_status": "CREATE_COMPLETE",
    }


def test_status_prefers_cloudfront_then_alb(monkeypatch):
    monkeypatch.setattr(de, "_describe_stack",
                        lambda s: ("UPDATE_COMPLETE", {"AlbDns": "alb-123.example.com"}))
    assert de.ecs_deploy_status()["url"] == "alb-123.example.com"


def test_status_not_deployed_when_stack_absent(monkeypatch):
    monkeypatch.setattr(de, "_describe_stack", lambda s: (None, {}))
    assert de.ecs_deploy_status() == {"state": "not_deployed", "url": None}


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
    monkeypatch.setattr(de, "ecs_deploy_status",
                        lambda: {"state": "deployed", "url": "https://x"})
    de.run_cli("status")
    assert json.loads(capsys.readouterr().out) == {"state": "deployed", "url": "https://x"}


def test_run_cli_unknown_action(monkeypatch):
    with pytest.raises(SystemExit):
        de.run_cli("frobnicate")
