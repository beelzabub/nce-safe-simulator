"""Tests for the Deploy Options status + launch endpoints (issue #215).

The status endpoint aggregates per-target state; S3 is a stub (owned by #216),
ECS/EKS read CloudFormation. These tests mock boto3 so they never touch AWS.
"""
import sys

import boto3
import pytest
from fastapi.testclient import TestClient

import server.app as appmod
from server.jobs import JobManager


# ---------------------------------------------------------------------------
# Fake CloudFormation
# ---------------------------------------------------------------------------

class _FakeCF:
    """A boto3 cloudformation client stand-in driven by a name→(status, outputs)
    map. Unknown stacks raise ClientError, exactly like the real API."""

    def __init__(self, mapping):
        self._m = mapping

    def describe_stacks(self, StackName):
        entry = self._m.get(StackName)
        if entry is None:
            from botocore.exceptions import ClientError
            raise ClientError(
                {"Error": {"Code": "ValidationError",
                           "Message": f"Stack with id {StackName} does not exist"}},
                "DescribeStacks",
            )
        status, outputs = entry
        return {"Stacks": [{
            "StackStatus": status,
            "Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in outputs.items()],
        }]}


def _install_cf(monkeypatch, mapping):
    """Patch boto3.client so cloudformation returns our fake; other services 404."""
    def _client(service, *a, **k):
        if service == "cloudformation":
            return _FakeCF(mapping)
        raise AssertionError(f"unexpected boto3 client: {service}")
    monkeypatch.setattr(boto3, "client", _client)


@pytest.fixture(autouse=True)
def _reset_cache():
    """The endpoint caches across calls; reset it around every test."""
    appmod._deploy_status_cache["value"] = None
    appmod._deploy_status_cache["at"] = 0.0
    yield
    appmod._deploy_status_cache["value"] = None
    appmod._deploy_status_cache["at"] = 0.0


@pytest.fixture()
def client():
    appmod.app.state.gl = None
    return TestClient(appmod.app)


# ---------------------------------------------------------------------------
# _cfn_state mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,expected", [
    (None,                       "not_deployed"),
    ("CREATE_COMPLETE",          "deployed"),
    ("UPDATE_COMPLETE",          "deployed"),
    ("UPDATE_ROLLBACK_COMPLETE", "deployed"),
    ("CREATE_IN_PROGRESS",       "deploying"),
    ("UPDATE_IN_PROGRESS",       "deploying"),
    ("DELETE_IN_PROGRESS",       "destroying"),
    ("CREATE_FAILED",            "error"),
    ("ROLLBACK_COMPLETE",        "error"),
    ("DELETE_FAILED",            "error"),
])
def test_cfn_state_mapping(status, expected):
    assert appmod._cfn_state(status) == expected


# ---------------------------------------------------------------------------
# GET /api/deploy/status
# ---------------------------------------------------------------------------

def test_status_shape_all_targets(client, monkeypatch):
    _install_cf(monkeypatch, {})  # nothing deployed
    body = client.get("/api/deploy/status").json()
    assert set(body) == {"s3", "ecr", "ecs", "eks"}
    for target in body.values():
        assert "state" in target and "url" in target


def test_ecr_status_from_deploy_module(client, monkeypatch):
    # #234 added the shared image repository as a target: the endpoint surfaces
    # whatever server.deploy_ecr.ecr_deploy_status reports (repo/image presence).
    import server.deploy_ecr as deploy_ecr
    _install_cf(monkeypatch, {})
    monkeypatch.setattr(
        deploy_ecr, "ecr_deploy_status",
        lambda: {"state": "deployed", "url": None, "image_count": 3,
                 "detail": "3 image(s), last push 2026-07-10 05:30 UTC"},
    )
    body = client.get("/api/deploy/status").json()
    assert body["ecr"]["state"] == "deployed"
    assert body["ecr"]["image_count"] == 3


def test_ecr_status_resilient_when_module_raises(client, monkeypatch):
    # An unexpected module failure reads as `unreadable` (#235) — the dialog
    # still renders, and nothing false is claimed about the repo.
    import server.deploy_ecr as deploy_ecr
    _install_cf(monkeypatch, {})

    def _boom():
        raise RuntimeError("no credentials")

    monkeypatch.setattr(deploy_ecr, "ecr_deploy_status", _boom)
    body = client.get("/api/deploy/status").json()
    assert body["ecr"] == {"state": "unreadable", "url": None}


def test_s3_status_from_deploy_module(client, monkeypatch):
    # #216 replaced the S3 stub with real status: the endpoint surfaces whatever
    # server.deploy_s3.s3_deploy_status reports (bucket/distribution presence).
    import server.deploy_s3 as deploy_s3
    _install_cf(monkeypatch, {})
    monkeypatch.setattr(
        deploy_s3, "s3_deploy_status",
        lambda *a, **k: {"state": "deployed", "url": "https://cdn.example.com",
                         "object_count": 42, "last_sync": "2026-07-09T00:00:00Z"},
    )
    body = client.get("/api/deploy/status").json()
    assert body["s3"]["state"] == "deployed"
    assert body["s3"]["url"] == "https://cdn.example.com"
    assert body["s3"]["object_count"] == 42


def test_s3_status_resilient_when_module_raises(client, monkeypatch):
    # Any failure (no config/credentials, boto3 absent) must read as not_deployed
    # so the Deploy Options section still renders.
    import server.deploy_s3 as deploy_s3
    _install_cf(monkeypatch, {})

    def _boom(*a, **k):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(deploy_s3, "s3_deploy_status", _boom)
    body = client.get("/api/deploy/status").json()
    assert body["s3"] == {"state": "not_deployed", "url": None}


def test_nothing_deployed(client, monkeypatch):
    _install_cf(monkeypatch, {})
    body = client.get("/api/deploy/status").json()
    assert body["ecs"]["state"] == "not_deployed"
    assert body["eks"]["state"] == "not_deployed"
    assert body["ecs"]["url"] is None


def test_ecs_deployed_with_url(client, monkeypatch):
    _install_cf(monkeypatch, {
        "NceStack": ("CREATE_COMPLETE",
                     {"CloudFrontUrl": "https://ecs.example.com"}),
    })
    body = client.get("/api/deploy/status").json()
    assert body["ecs"]["state"] == "deployed"
    assert body["ecs"]["url"] == "https://ecs.example.com"
    assert body["ecs"]["stack_status"] == "CREATE_COMPLETE"
    # EKS still absent
    assert body["eks"]["state"] == "not_deployed"


def test_eks_deploying(client, monkeypatch):
    _install_cf(monkeypatch, {
        "NceEksStack": ("CREATE_IN_PROGRESS", {}),
    })
    body = client.get("/api/deploy/status").json()
    assert body["eks"]["state"] == "deploying"


def test_ecs_error_state(client, monkeypatch):
    _install_cf(monkeypatch, {
        "NceStack": ("ROLLBACK_COMPLETE", {}),
    })
    body = client.get("/api/deploy/status").json()
    assert body["ecs"]["state"] == "error"


def test_status_is_cached(client, monkeypatch):
    calls = {"n": 0}
    real = _FakeCF({})

    class _Counting(_FakeCF):
        def describe_stacks(self, StackName):
            calls["n"] += 1
            return real.describe_stacks(StackName)

    monkeypatch.setattr(boto3, "client",
                        lambda service, *a, **k: _Counting({}))
    client.get("/api/deploy/status")
    first = calls["n"]
    assert first > 0
    client.get("/api/deploy/status")     # served from cache — no new AWS calls
    assert calls["n"] == first
    client.get("/api/deploy/status?refresh=1")   # forced recompute
    assert calls["n"] > first


def test_status_survives_boto_error(client, monkeypatch):
    # A read failure is "unreadable", never a false "not deployed" (#235).
    def _boom(service, *a, **k):
        raise RuntimeError("no credentials")
    monkeypatch.setattr(boto3, "client", _boom)
    body = client.get("/api/deploy/status").json()
    assert body["ecs"]["state"] == "unreadable"
    assert body["eks"]["state"] == "unreadable"


def test_status_unreadable_on_access_denied(client, monkeypatch):
    # The EKS pod's own-cluster case (#235): DescribeStacks AccessDenied must
    # render as `unreadable` (with an explanatory detail and no URL), not as
    # the false "not deployed" the pod used to report about itself.
    from botocore.exceptions import ClientError

    class _Denied:
        def describe_stacks(self, StackName):
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "not authorized"}},
                "DescribeStacks",
            )

    monkeypatch.setattr(boto3, "client", lambda service, *a, **k: _Denied())
    body = client.get("/api/deploy/status").json()
    for target in ("ecs", "eks"):
        assert body[target]["state"] == "unreadable"
        assert body[target]["url"] is None
        assert "unreadable" in body[target]["detail"]


def test_status_absent_stack_is_still_not_deployed(client, monkeypatch):
    # The definitive "does not exist" ValidationError keeps mapping to
    # not_deployed — only *unreadable* states moved (#235).
    _install_cf(monkeypatch, {})
    body = client.get("/api/deploy/status").json()
    assert body["ecs"]["state"] == "not_deployed"
    assert body["eks"]["state"] == "not_deployed"


# ---------------------------------------------------------------------------
# POST /api/deploy/{target}/{action}
# ---------------------------------------------------------------------------

@pytest.fixture()
def deploy_client(monkeypatch, tmp_path):
    """TestClient whose job_manager writes to a temp dir, and whose _job_argv is
    swapped for a harmless echo (preserving the real kind/label) — so a deploy
    launch exercises the durable-job plumbing without shelling to a real
    ``--deploy-*`` CLI (which would run make/cdk against AWS)."""
    real_job_argv = appmod._job_argv

    def harmless_argv(data):
        kind, label, _argv = real_job_argv(data)
        return kind, label, [sys.executable, "-c", "print('ok')"]

    monkeypatch.setattr(appmod, "_job_argv", harmless_argv)
    test_mgr = JobManager(jobs_dir=tmp_path / "jobs")
    monkeypatch.setattr(appmod, "job_manager", test_mgr)
    appmod.app.state.gl = None
    return TestClient(appmod.app), test_mgr


def test_launch_deploy_returns_durable_job(deploy_client):
    # Every target now delegates to a real CLI; the fixture's harmless _job_argv
    # keeps the real kind/label but runs a no-op subprocess.
    client, mgr = deploy_client
    r = client.post("/api/deploy/eks/deploy")
    assert r.status_code == 201
    manifest = r.json()
    assert manifest["kind"] == "deploy:eks"
    assert manifest["params"] == {"target": "eks", "action": "deploy"}
    # It's a real durable job: listed and tailable.
    assert any(j["id"] == manifest["id"] for j in client.get("/api/jobs").json())


def test_launch_destroy_action(deploy_client):
    client, _ = deploy_client
    r = client.post("/api/deploy/eks/destroy")
    assert r.status_code == 201
    assert r.json()["params"]["action"] == "destroy"


def test_launch_unknown_target_404(deploy_client):
    client, _ = deploy_client
    assert client.post("/api/deploy/gcp/deploy").status_code == 404


def test_launch_unknown_action_400(deploy_client):
    client, _ = deploy_client
    assert client.post("/api/deploy/ecs/frobnicate").status_code == 400


def test_launch_s3_delegates_to_real_cli(monkeypatch):
    # S3 execution is real (#216): the generic deploy route must delegate to the
    # whitelisted --deploy-s3 CLI, mapping the UI's "deploy" action to "publish"
    # (and "destroy" straight through). Capture the argv instead of spawning.
    captured = {}

    def fake_launch(argv, **kw):
        captured["argv"] = argv
        captured.update(kw)
        return {"id": "s3", "state": "running", **kw}

    monkeypatch.setattr(appmod.job_manager, "launch", fake_launch)
    appmod.app.state.gl = None
    client = TestClient(appmod.app)

    r = client.post("/api/deploy/s3/deploy")
    assert r.status_code == 201
    assert captured["kind"] == "deploy:s3"
    assert captured["argv"][-2:] == ["--deploy-s3", "publish"]
    assert captured["params"] == {"target": "s3", "action": "deploy"}

    r = client.post("/api/deploy/s3/destroy")
    assert r.status_code == 201
    assert captured["argv"][-2:] == ["--deploy-s3", "destroy"]


def test_launch_ecs_delegates_to_real_cli(monkeypatch):
    # ECS execution is real (#217): the generic deploy route delegates to the
    # whitelisted --deploy-ecs CLI, mapping "deploy" -> "publish" and passing
    # "destroy" straight through. Capture the argv instead of spawning.
    captured = {}

    def fake_launch(argv, **kw):
        captured["argv"] = argv
        captured.update(kw)
        return {"id": "ecs", "state": "running", **kw}

    monkeypatch.setattr(appmod.job_manager, "launch", fake_launch)
    appmod.app.state.gl = None
    client = TestClient(appmod.app)

    r = client.post("/api/deploy/ecs/deploy")
    assert r.status_code == 201
    assert captured["kind"] == "deploy:ecs"
    assert captured["argv"][-2:] == ["--deploy-ecs", "publish"]
    assert captured["params"] == {"target": "ecs", "action": "deploy"}

    r = client.post("/api/deploy/ecs/destroy")
    assert r.status_code == 201
    assert captured["argv"][-2:] == ["--deploy-ecs", "destroy"]


def test_launch_ecr_delegates_to_real_cli(monkeypatch):
    # ECR execution is real (#234): the generic deploy route delegates to the
    # whitelisted --deploy-ecr CLI, mapping "deploy" -> "publish" and passing
    # "destroy" straight through. Capture the argv instead of spawning.
    captured = {}

    def fake_launch(argv, **kw):
        captured["argv"] = argv
        captured.update(kw)
        return {"id": "ecr", "state": "running", **kw}

    monkeypatch.setattr(appmod.job_manager, "launch", fake_launch)
    appmod.app.state.gl = None
    client = TestClient(appmod.app)

    r = client.post("/api/deploy/ecr/deploy")
    assert r.status_code == 201
    assert captured["kind"] == "deploy:ecr"
    assert captured["argv"][-2:] == ["--deploy-ecr", "publish"]
    assert captured["params"] == {"target": "ecr", "action": "deploy"}

    r = client.post("/api/deploy/ecr/destroy")
    assert r.status_code == 201
    assert captured["argv"][-2:] == ["--deploy-ecr", "destroy"]


def test_launch_eks_delegates_to_real_cli(monkeypatch):
    # EKS execution is real (#218): the generic deploy route delegates to the
    # whitelisted --deploy-eks CLI, mapping "deploy" -> "publish" and passing
    # "destroy" straight through. Capture the argv instead of spawning.
    captured = {}

    def fake_launch(argv, **kw):
        captured["argv"] = argv
        captured.update(kw)
        return {"id": "eks", "state": "running", **kw}

    monkeypatch.setattr(appmod.job_manager, "launch", fake_launch)
    appmod.app.state.gl = None
    client = TestClient(appmod.app)

    r = client.post("/api/deploy/eks/deploy")
    assert r.status_code == 201
    assert captured["kind"] == "deploy:eks"
    assert captured["argv"][-2:] == ["--deploy-eks", "publish"]
    assert captured["params"] == {"target": "eks", "action": "deploy"}

    r = client.post("/api/deploy/eks/destroy")
    assert r.status_code == 201
    assert captured["argv"][-2:] == ["--deploy-eks", "destroy"]


# ---------------------------------------------------------------------------
# S3 bucket selector (issue #225)
# ---------------------------------------------------------------------------

def test_s3_buckets_endpoint(monkeypatch):
    from types import SimpleNamespace
    from server import deploy_s3

    monkeypatch.setattr(deploy_s3, "list_buckets", lambda: [{"name": "a", "region": "us-east-1"}])
    monkeypatch.setattr(deploy_s3, "account_id", lambda: "123456789012")
    monkeypatch.setattr(appmod, "_s3_deploy_status", lambda: {"state": "deployed", "bucket": "live-bucket"})
    monkeypatch.setattr(deploy_s3, "s3_settings", lambda *a, **k: SimpleNamespace(bucket="cfgbase"))
    appmod.app.state.gl = None
    client = TestClient(appmod.app)

    body = client.get("/api/deploy/s3/buckets").json()
    assert body["buckets"] == [{"name": "a", "region": "us-east-1"}]
    assert body["account_id"] == "123456789012"
    assert body["default"] == "live-bucket"
    assert body["suggested_base"] == "cfgbase"


def test_launch_s3_with_bucket_appends_flag(monkeypatch):
    captured = {}

    def fake_launch(argv, **kw):
        captured["argv"] = argv
        captured.update(kw)
        return {"id": "s3", "state": "running", **kw}

    monkeypatch.setattr(appmod.job_manager, "launch", fake_launch)
    appmod.app.state.gl = None
    client = TestClient(appmod.app)

    r = client.post("/api/deploy/s3/deploy", json={"bucket": "nce-safe-sim-site-123456789012"})
    assert r.status_code == 201
    assert captured["argv"][-4:] == [
        "--deploy-s3", "publish", "--deploy-s3-bucket", "nce-safe-sim-site-123456789012",
    ]


def test_launch_s3_invalid_bucket_is_400(monkeypatch):
    appmod.app.state.gl = None
    client = TestClient(appmod.app)
    r = client.post("/api/deploy/s3/deploy", json={"bucket": "BAD_NAME"})
    assert r.status_code == 400


def test_launch_s3_bucket_ignored_for_destroy(monkeypatch):
    captured = {}

    def fake_launch(argv, **kw):
        captured["argv"] = argv
        return {"id": "s3", "state": "running", **kw}

    monkeypatch.setattr(appmod.job_manager, "launch", fake_launch)
    appmod.app.state.gl = None
    client = TestClient(appmod.app)

    r = client.post("/api/deploy/s3/destroy", json={"bucket": "whatever-123"})
    assert r.status_code == 201
    assert captured["argv"][-2:] == ["--deploy-s3", "destroy"]   # no bucket flag
