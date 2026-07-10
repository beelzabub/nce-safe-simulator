"""Tests for the shared ECR deploy target (issue #234)."""
from datetime import datetime, timedelta, timezone

import pytest

import server.deploy_ecr as de

boto3 = pytest.importorskip("boto3")
from botocore.exceptions import ClientError  # noqa: E402


def _client_error(code, op="Op"):
    return ClientError({"Error": {"Code": code}}, op)


class FakeEcr:
    """Minimal ECR stub: absent repo raises; present repo reports images."""

    def __init__(self, exists=True, images=None, uri="123.dkr.ecr.us-east-1.amazonaws.com/app"):
        self.exists = exists
        self.images = images if images is not None else []
        self.uri = uri
        self.created = []
        self.deleted = []

    def describe_repositories(self, repositoryNames):
        if not self.exists:
            raise _client_error("RepositoryNotFoundException", "DescribeRepositories")
        return {"repositories": [{"repositoryName": repositoryNames[0],
                                  "repositoryUri": self.uri}]}

    def describe_images(self, repositoryName):
        if not self.exists:
            raise _client_error("RepositoryNotFoundException", "DescribeImages")
        return {"imageDetails": self.images}

    def list_images(self, repositoryName):
        if not self.exists:
            raise _client_error("RepositoryNotFoundException", "ListImages")
        return {"imageIds": [{"imageDigest": f"sha{i}"} for i in range(len(self.images))]}

    def create_repository(self, repositoryName):
        self.created.append(repositoryName)
        self.exists = True
        return {"repository": {"repositoryName": repositoryName, "repositoryUri": self.uri}}

    def delete_repository(self, repositoryName, force=False):
        if not self.exists:
            raise _client_error("RepositoryNotFoundException", "DeleteRepository")
        self.deleted.append((repositoryName, force))
        self.exists = False
        return {}


def _use(monkeypatch, fake):
    monkeypatch.setattr(boto3, "client", lambda service: fake)
    return fake


# ---------------------------------------------------------------------------
# shared read helpers (used by the ECS/EKS pre-flights)
# ---------------------------------------------------------------------------

def test_image_count_zero_when_repo_absent(monkeypatch):
    # A missing repository is a definite zero, not an unknown — this is the
    # exact gap that let an EKS deploy end as an ImagePullBackOff 503.
    _use(monkeypatch, FakeEcr(exists=False))
    assert de.ecr_image_count("app") == 0


def test_image_count_none_on_other_client_error(monkeypatch):
    class _Denied:
        def list_images(self, repositoryName):
            raise _client_error("AccessDeniedException", "ListImages")
    _use(monkeypatch, _Denied())
    assert de.ecr_image_count("app") is None


def test_image_count_counts_images(monkeypatch):
    _use(monkeypatch, FakeEcr(images=[{"imageDigest": "a"}, {"imageDigest": "b"}]))
    assert de.ecr_image_count("app") == 2


def test_repo_exists_true_false_and_unknown(monkeypatch):
    _use(monkeypatch, FakeEcr(exists=True))
    assert de.ecr_repo_exists("app") is True
    _use(monkeypatch, FakeEcr(exists=False))
    assert de.ecr_repo_exists("app") is False

    class _Denied:
        def describe_repositories(self, repositoryNames):
            raise _client_error("AccessDeniedException", "DescribeRepositories")
    _use(monkeypatch, _Denied())
    assert de.ecr_repo_exists("app") is None


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def test_status_not_deployed_when_repo_absent(monkeypatch):
    _use(monkeypatch, FakeEcr(exists=False))
    assert de.ecr_deploy_status() == {"state": "not_deployed", "url": None}


def test_status_no_image_when_repo_empty(monkeypatch):
    _use(monkeypatch, FakeEcr(images=[]))
    result = de.ecr_deploy_status()
    assert result["state"] == "no_image"
    assert result["url"] is None
    assert "no image" in result["detail"]


def test_status_deployed_with_count_and_last_push(monkeypatch):
    # boto3 returns tz-aware local-offset datetimes; the detail must convert to
    # UTC before labelling it UTC (-07:00 22:54 → 05:54 UTC next day).
    pushed = datetime(2026, 7, 9, 22, 54, tzinfo=timezone(timedelta(hours=-7)))
    _use(monkeypatch, FakeEcr(images=[
        {"imageDigest": "a", "imagePushedAt": pushed},
        {"imageDigest": "b"},
    ]))
    result = de.ecr_deploy_status()
    assert result["state"] == "deployed"
    assert result["image_count"] == 2
    assert "2 image(s)" in result["detail"]
    assert "2026-07-10 05:54 UTC" in result["detail"]


def test_status_unreadable_on_access_denied(monkeypatch):
    # Can't-read must never render as a false not-deployed (#235).
    class _Denied:
        def describe_repositories(self, repositoryNames):
            raise _client_error("AccessDeniedException", "DescribeRepositories")
    _use(monkeypatch, _Denied())
    result = de.ecr_deploy_status()
    assert result["state"] == "unreadable"
    assert "unreadable" in result["detail"]


def test_status_unreadable_on_missing_credentials(monkeypatch):
    from botocore.exceptions import NoCredentialsError

    class _NoCreds:
        def describe_repositories(self, repositoryNames):
            raise NoCredentialsError()
    _use(monkeypatch, _NoCreds())
    assert de.ecr_deploy_status()["state"] == "unreadable"


def test_status_error_on_unexpected_client_error(monkeypatch):
    class _Throttled:
        def describe_repositories(self, repositoryNames):
            raise _client_error("ThrottlingException", "DescribeRepositories")
    _use(monkeypatch, _Throttled())
    result = de.ecr_deploy_status()
    assert result["state"] == "error"
    assert "Throttling" in result["detail"]


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

def test_preflight_raises_on_missing_tools(monkeypatch):
    monkeypatch.setattr(de, "_missing_tools", lambda: ["jq", "aws"])
    with pytest.raises(SystemExit) as exc:
        de._preflight(log=lambda *_: None)
    assert "jq" in str(exc.value) and "aws" in str(exc.value)


def test_preflight_requires_docker(monkeypatch):
    monkeypatch.setattr(de, "_missing_tools", lambda: [])
    monkeypatch.setattr(de, "_docker_available", lambda: False)
    with pytest.raises(SystemExit) as exc:
        de._preflight(log=lambda *_: None)
    assert "Docker" in str(exc.value)


# ---------------------------------------------------------------------------
# publish / destroy
# ---------------------------------------------------------------------------

def _capture_run(captured, returncode=0):
    def _run(argv, *a, **k):
        captured["argv"] = argv
        return returncode
    return _run


def test_publish_creates_absent_repo_then_pushes(monkeypatch):
    fake = _use(monkeypatch, FakeEcr(exists=False))
    monkeypatch.setattr(de, "_preflight", lambda **k: None)
    monkeypatch.setattr(de, "ecr_repo_exists", lambda name: False)
    captured = {}
    monkeypatch.setattr(de, "run_streaming", _capture_run(captured))
    de.publish(log=lambda *_: None)
    assert fake.created == [de._app_name()]
    assert captured["argv"][:2] == ["make", "-C"]
    assert captured["argv"][-1] == "ecr-push"


def test_publish_skips_create_when_repo_exists(monkeypatch):
    fake = _use(monkeypatch, FakeEcr(exists=True))
    monkeypatch.setattr(de, "_preflight", lambda **k: None)
    monkeypatch.setattr(de, "ecr_repo_exists", lambda name: True)
    captured = {}
    monkeypatch.setattr(de, "run_streaming", _capture_run(captured))
    de.publish(log=lambda *_: None)
    assert fake.created == []
    assert captured["argv"][-1] == "ecr-push"


def test_publish_raises_on_nonzero_push(monkeypatch):
    _use(monkeypatch, FakeEcr(exists=True))
    monkeypatch.setattr(de, "_preflight", lambda **k: None)
    monkeypatch.setattr(de, "ecr_repo_exists", lambda name: True)
    monkeypatch.setattr(de, "run_streaming", lambda *a, **k: 2)
    with pytest.raises(SystemExit) as exc:
        de.publish(log=lambda *_: None)
    assert "exit 2" in str(exc.value)


def test_destroy_deletes_repo_with_force(monkeypatch):
    fake = _use(monkeypatch, FakeEcr(exists=True))
    rc = de.destroy(log=lambda *_: None)
    assert rc == 0
    assert fake.deleted == [(de._app_name(), True)]


def test_destroy_tolerates_absent_repo(monkeypatch):
    _use(monkeypatch, FakeEcr(exists=False))
    assert de.destroy(log=lambda *_: None) == 0


# ---------------------------------------------------------------------------
# run_cli
# ---------------------------------------------------------------------------

def test_run_cli_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(de, "publish", lambda log: calls.append("publish"))
    monkeypatch.setattr(de, "destroy", lambda log: calls.append("destroy"))
    de.run_cli("publish", log=lambda *_: None)
    de.run_cli("destroy", log=lambda *_: None)
    assert calls == ["publish", "destroy"]
    with pytest.raises(SystemExit):
        de.run_cli("bogus", log=lambda *_: None)


def test_run_cli_status_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(de, "ecr_deploy_status", lambda: {"state": "no_image", "url": None})
    de.run_cli("status", log=lambda *_: None)
    assert '"no_image"' in capsys.readouterr().out
