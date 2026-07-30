"""Tests for mixins/image_convert.py — the OVA → AMI → EC2 tool family
(issue #285). All AWS access is mocked; nothing here touches real AWS."""
import json

import pytest
from botocore.exceptions import ClientError

from mixins import image_convert
from mixins.image_convert import (
    ImageConvertMixin,
    SSH_SG_NAME,
    VMIMPORT_ROLE,
    receipt_key,
    vmimport_role_policy,
    vmimport_trust_policy,
)
from mixins.tools import _TOOL_BY_KEY


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _client_error(code, op="Op", msg="nope"):
    return ClientError({"Error": {"Code": code, "Message": msg}}, op)


class FakeS3:
    def __init__(self, exists=True, objects=None):
        self.exists = exists
        self.objects = dict(objects or {})   # key -> bytes
        self.created = False
        self.public_block = None
        self.lifecycle = None
        self.deleted = []

    def head_bucket(self, Bucket):
        if not self.exists:
            raise _client_error("404", "HeadBucket")

    def create_bucket(self, **kw):
        self.exists = True
        self.created = True
        self.create_kwargs = kw

    def put_public_access_block(self, Bucket, PublicAccessBlockConfiguration):
        self.public_block = PublicAccessBlockConfiguration

    def put_bucket_lifecycle_configuration(self, Bucket, LifecycleConfiguration):
        self.lifecycle = LifecycleConfiguration

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _client_error("404", "HeadObject")
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _client_error("NoSuchKey", "GetObject")

        class _Body:
            def __init__(self, b): self._b = b
            def read(self): return self._b

        return {"Body": _Body(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)
        self.objects.pop(Key, None)

    def upload_file(self, path, bucket, key):
        self.objects[key] = open(path, "rb").read()


class FakeIAM:
    def __init__(self, role_exists=False):
        self.role_exists = role_exists
        self.created_role = None
        self.put_policies = []

    def get_role(self, RoleName):
        if not self.role_exists:
            raise _client_error("NoSuchEntity", "GetRole")
        return {"Role": {"RoleName": RoleName}}

    def create_role(self, **kw):
        self.role_exists = True
        self.created_role = kw

    def put_role_policy(self, **kw):
        self.put_policies.append(kw)


class FakeEC2:
    """Covers the import/export/launch/cleanup calls the mixin makes. Import
    and export tasks walk a scripted list of status dicts, one per describe."""

    def __init__(self, import_states=None, export_states=None,
                 default_vpc=True, sg_exists=False):
        self.import_states = list(import_states or [])
        self.export_states = list(export_states or [])
        self.default_vpc = default_vpc
        self.sg_exists = sg_exists
        self.tags = []
        self.run_kwargs = None
        self.instance_states = ["running"]
        self.terminated = []
        self.deregistered = []
        self.deleted_snapshots = []
        self.images = {}          # ami id -> image dict
        self.export_image_kwargs = None
        self.instance_export_kwargs = None

    # -- import ----------------------------------------------------------- #
    def import_image(self, **kw):
        self.import_kwargs = kw
        return {"ImportTaskId": "import-ami-0123"}

    def describe_import_image_tasks(self, ImportTaskIds):
        state = self.import_states.pop(0) if len(self.import_states) > 1 \
            else self.import_states[0]
        return {"ImportImageTasks": [state]}

    def create_tags(self, Resources, Tags):
        self.tags.append((Resources, Tags))

    # -- launch ----------------------------------------------------------- #
    def describe_security_groups(self, Filters):
        if self.sg_exists:
            return {"SecurityGroups": [{"GroupId": "sg-existing"}]}
        return {"SecurityGroups": []}

    def describe_vpcs(self, Filters):
        return {"Vpcs": [{"VpcId": "vpc-default"}] if self.default_vpc else []}

    def create_security_group(self, **kw):
        self.sg_kwargs = kw
        return {"GroupId": "sg-new"}

    def authorize_security_group_ingress(self, **kw):
        self.ingress_kwargs = kw

    def run_instances(self, **kw):
        self.run_kwargs = kw
        return {"Instances": [{"InstanceId": "i-0abc"}]}

    def describe_instances(self, InstanceIds):
        state = self.instance_states.pop(0) if len(self.instance_states) > 1 \
            else self.instance_states[0]
        return {"Reservations": [{"Instances": [{
            "InstanceId": InstanceIds[0],
            "State": {"Name": state},
            "PublicIpAddress": "203.0.113.7" if state == "running" else None,
        }]}]}

    # -- export ----------------------------------------------------------- #
    def export_image(self, **kw):
        self.export_image_kwargs = kw
        return {"ExportImageTaskId": "export-ami-0456"}

    def describe_export_image_tasks(self, ExportImageTaskIds):
        state = self.export_states.pop(0) if len(self.export_states) > 1 \
            else self.export_states[0]
        return {"ExportImageTasks": [state]}

    def create_instance_export_task(self, **kw):
        self.instance_export_kwargs = kw
        return {"ExportTask": {"ExportTaskId": "export-i-0789"}}

    def describe_export_tasks(self, ExportTaskIds):
        state = self.export_states.pop(0) if len(self.export_states) > 1 \
            else self.export_states[0]
        return {"ExportTasks": [state]}

    # -- cleanup ---------------------------------------------------------- #
    def terminate_instances(self, InstanceIds):
        self.terminated.extend(InstanceIds)
        self.instance_states = ["terminated"]

    def describe_images(self, ImageIds):
        img = self.images.get(ImageIds[0])
        return {"Images": [img] if img else []}

    def deregister_image(self, ImageId):
        self.deregistered.append(ImageId)

    def delete_snapshot(self, SnapshotId):
        self.deleted_snapshots.append(SnapshotId)


class Harness(ImageConvertMixin):
    """ImageConvertMixin on a bare object with canned clients and config."""

    def __init__(self, s3=None, ec2=None, iam=None, account="881490118830",
                 config=None):
        self.image_conversion = config if config is not None else {}
        self._clients = {"s3": s3 or FakeS3(), "ec2": ec2 or FakeEC2(),
                         "iam": iam or FakeIAM()}
        self._account = account

    def _ic_client(self, service, region=None):
        return self._clients[service]

    def _ic_account_id(self):
        return self._account


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(image_convert.time, "sleep", lambda s: None)


# ---------------------------------------------------------------------------
# settings / helpers
# ---------------------------------------------------------------------------

def test_bucket_composed_from_base_and_account():
    s = Harness()._ic_settings()
    assert s.bucket == "nce-safe-sim-ova-881490118830"


def test_explicit_bucket_used_verbatim():
    s = Harness()._ic_settings(bucket="my-bucket")
    assert s.bucket == "my-bucket"


def test_bucket_base_unchanged_without_account():
    s = Harness(account=None, config={"bucket": "fixed-name"})._ic_settings()
    assert s.bucket == "fixed-name"


def test_config_overrides_defaults():
    s = Harness(config={"instance_type": "t3.small",
                        "lifecycle_expire_days": 3})._ic_settings()
    assert s.instance_type == "t3.small"
    assert s.lifecycle_days == 3
    assert s.staging_prefix == "staging/"


def test_receipt_key():
    assert receipt_key("staging/x.ova") == "staging/x.ova.import.json"


def test_role_policy_scoped_to_bucket():
    pol = vmimport_role_policy("b-1")
    s3_stmt = pol["Statement"][0]
    assert s3_stmt["Resource"] == ["arn:aws:s3:::b-1", "arn:aws:s3:::b-1/*"]
    assert vmimport_trust_policy()["Statement"][0]["Principal"]["Service"] == \
        "vmie.amazonaws.com"


# ---------------------------------------------------------------------------
# ova-import-setup
# ---------------------------------------------------------------------------

def test_setup_creates_missing_bucket_and_role():
    s3, iam = FakeS3(exists=False), FakeIAM(role_exists=False)
    h = Harness(s3=s3, iam=iam)
    h._tool_ova_import_setup()
    assert s3.created and s3.public_block["BlockPublicAcls"] is True
    rule = s3.lifecycle["Rules"][0]
    assert rule["Filter"]["Prefix"] == "staging/" and rule["Expiration"]["Days"] == 14
    assert iam.created_role["RoleName"] == VMIMPORT_ROLE
    trust = json.loads(iam.created_role["AssumeRolePolicyDocument"])
    assert trust["Statement"][0]["Condition"]["StringEquals"]["sts:Externalid"] == \
        VMIMPORT_ROLE
    assert iam.put_policies[0]["RoleName"] == VMIMPORT_ROLE


def test_setup_is_idempotent_and_converges_policy():
    s3, iam = FakeS3(exists=True), FakeIAM(role_exists=True)
    h = Harness(s3=s3, iam=iam)
    h._tool_ova_import_setup(lifecycle_days=30)
    assert not s3.created and iam.created_role is None
    assert s3.lifecycle["Rules"][0]["Expiration"]["Days"] == 30
    assert len(iam.put_policies) == 1          # policy still converged


def test_setup_dry_run_changes_nothing():
    s3, iam = FakeS3(exists=False), FakeIAM(role_exists=False)
    h = Harness(s3=s3, iam=iam)
    h._tool_ova_import_setup(dry_run=True)
    assert not s3.created and iam.created_role is None and not iam.put_policies


# ---------------------------------------------------------------------------
# ova-to-ami
# ---------------------------------------------------------------------------

def _import_walk():
    return [
        {"Status": "pending"},
        {"Status": "converting", "Progress": "42", "StatusMessage": "converting"},
        {"Status": "completed", "ImageId": "ami-0dead",
         "SnapshotDetails": [{"SnapshotId": "snap-01"}]},
    ]


def test_ova_to_ami_full_flow_writes_receipt():
    s3 = FakeS3(objects={"staging/x.ova": b"ova-bytes"})
    ec2 = FakeEC2(import_states=_import_walk(), sg_exists=True)
    h = Harness(s3=s3, ec2=ec2)
    h._tool_ova_to_ami(key="staging/x.ova", name="x-ami")

    assert ec2.import_kwargs["DiskContainers"][0]["UserBucket"] == \
        {"S3Bucket": "nce-safe-sim-ova-881490118830", "S3Key": "staging/x.ova"}
    assert ec2.tags[0] == (["ami-0dead"], [{"Key": "Name", "Value": "x-ami"}])
    assert ec2.run_kwargs["ImageId"] == "ami-0dead"
    assert ec2.run_kwargs["SecurityGroupIds"] == ["sg-existing"]

    receipt = json.loads(s3.objects["staging/x.ova.import.json"])
    assert receipt["ami_id"] == "ami-0dead"
    assert receipt["snapshot_ids"] == ["snap-01"]
    assert receipt["instance_id"] == "i-0abc"
    assert receipt["public_ip"] == "203.0.113.7"


def test_ova_to_ami_import_only_skips_launch():
    s3 = FakeS3(objects={"staging/x.ova": b"ova"})
    ec2 = FakeEC2(import_states=_import_walk())
    Harness(s3=s3, ec2=ec2)._tool_ova_to_ami(key="staging/x.ova", launch=False)
    assert ec2.run_kwargs is None
    assert json.loads(s3.objects["staging/x.ova.import.json"])["instance_id"] is None


def test_ova_to_ami_missing_object_points_at_ova_fetch():
    h = Harness(s3=FakeS3(objects={}), ec2=FakeEC2())
    with pytest.raises(SystemExit, match="ova-fetch"):
        h._tool_ova_to_ami(key="staging/nope.ova")


def test_ova_to_ami_failed_task_raises():
    s3 = FakeS3(objects={"staging/x.ova": b"ova"})
    ec2 = FakeEC2(import_states=[
        {"Status": "deleting", "StatusMessage": "ClientError: unsupported OS"}])
    with pytest.raises(SystemExit, match="unsupported OS"):
        Harness(s3=s3, ec2=ec2)._tool_ova_to_ami(key="staging/x.ova")


def test_ova_to_ami_dry_run_calls_nothing():
    ec2 = FakeEC2()
    Harness(s3=FakeS3(objects={}), ec2=ec2)._tool_ova_to_ami(
        key="staging/x.ova", dry_run=True)
    assert not hasattr(ec2, "import_kwargs")


def test_launch_creates_ssh_sg_when_missing():
    s3 = FakeS3(objects={"staging/x.ova": b"ova"})
    ec2 = FakeEC2(import_states=_import_walk(), sg_exists=False)
    Harness(s3=s3, ec2=ec2)._tool_ova_to_ami(key="staging/x.ova")
    assert ec2.sg_kwargs["GroupName"] == SSH_SG_NAME
    perm = ec2.ingress_kwargs["IpPermissions"][0]
    assert (perm["FromPort"], perm["ToPort"]) == (22, 22)
    assert ec2.run_kwargs["SecurityGroupIds"] == ["sg-new"]


def test_launch_without_default_vpc_raises():
    s3 = FakeS3(objects={"staging/x.ova": b"ova"})
    ec2 = FakeEC2(import_states=_import_walk(), default_vpc=False)
    with pytest.raises(SystemExit, match="default VPC"):
        Harness(s3=s3, ec2=ec2)._tool_ova_to_ami(key="staging/x.ova")


# ---------------------------------------------------------------------------
# ami-to-ova
# ---------------------------------------------------------------------------

def test_ami_source_uses_export_image():
    ec2 = FakeEC2(export_states=[{"Status": "active", "Progress": "10"},
                                 {"Status": "completed"}])
    s3 = FakeS3(objects={"exports/export-ami-0456.vmdk": b"x" * 10})
    Harness(s3=s3, ec2=ec2)._tool_ami_to_ova(source="ami-0dead")
    kw = ec2.export_image_kwargs
    assert kw["ImageId"] == "ami-0dead"
    assert kw["DiskImageFormat"] == "VMDK"
    assert kw["RoleName"] == VMIMPORT_ROLE
    assert kw["S3ExportLocation"]["S3Prefix"] == "exports/"
    assert ec2.instance_export_kwargs is None


def test_instance_source_exports_true_ova():
    ec2 = FakeEC2(export_states=[{"State": "active"}, {"State": "completed"}])
    s3 = FakeS3(objects={"exports/export-i-0789.ova": b"x" * 10})
    Harness(s3=s3, ec2=ec2)._tool_ami_to_ova(source="i-0abc")
    kw = ec2.instance_export_kwargs
    assert kw["InstanceId"] == "i-0abc"
    assert kw["ExportToS3Task"]["ContainerFormat"] == "ova"
    assert ec2.export_image_kwargs is None


def test_ami_to_ova_rejects_garbage_source():
    with pytest.raises(SystemExit, match="neither an instance id"):
        Harness()._tool_ami_to_ova(source="vol-123")


def test_ami_to_ova_failed_export_raises():
    ec2 = FakeEC2(export_states=[
        {"Status": "cancelled", "StatusMessage": "insufficient permissions"}])
    with pytest.raises(SystemExit, match="insufficient permissions"):
        Harness(ec2=ec2)._tool_ami_to_ova(source="ami-0dead")


# ---------------------------------------------------------------------------
# ova-import-cleanup
# ---------------------------------------------------------------------------

def _receipt_s3():
    receipt = {"ami_id": "ami-0dead", "instance_id": "i-0abc",
               "snapshot_ids": ["snap-01"]}
    return FakeS3(objects={
        "staging/x.ova": b"ova",
        "staging/x.ova.import.json": json.dumps(receipt).encode(),
    })


def test_cleanup_from_receipt_tears_everything_down():
    s3, ec2 = _receipt_s3(), FakeEC2()
    ec2.images["ami-0dead"] = {
        "BlockDeviceMappings": [{"Ebs": {"SnapshotId": "snap-01"}},
                                {"Ebs": {"SnapshotId": "snap-02"}}]}
    Harness(s3=s3, ec2=ec2)._tool_ova_import_cleanup(key="staging/x.ova")
    assert ec2.terminated == ["i-0abc"]
    assert ec2.deregistered == ["ami-0dead"]
    # receipt snapshot + the extra one discovered on the image, no duplicates
    assert sorted(ec2.deleted_snapshots) == ["snap-01", "snap-02"]
    assert s3.deleted == []                     # staged OVA kept by default


def test_cleanup_delete_staged_removes_ova_and_receipt():
    s3, ec2 = _receipt_s3(), FakeEC2()
    Harness(s3=s3, ec2=ec2)._tool_ova_import_cleanup(
        key="staging/x.ova", delete_staged=True)
    assert set(s3.deleted) == {"staging/x.ova", "staging/x.ova.import.json"}


def test_cleanup_explicit_ids_without_receipt():
    ec2 = FakeEC2()
    Harness(s3=FakeS3(objects={}), ec2=ec2)._tool_ova_import_cleanup(
        ami_id="ami-0dead", instance_id="i-0abc")
    assert ec2.terminated == ["i-0abc"]
    # AMI unknown to describe_images → reported gone, nothing deregistered
    assert ec2.deregistered == []


def test_cleanup_dry_run_changes_nothing():
    s3, ec2 = _receipt_s3(), FakeEC2()
    Harness(s3=s3, ec2=ec2)._tool_ova_import_cleanup(
        key="staging/x.ova", delete_staged=True, dry_run=True)
    assert not ec2.terminated and not ec2.deregistered
    assert not ec2.deleted_snapshots and not s3.deleted


def test_cleanup_with_no_targets_raises():
    with pytest.raises(SystemExit, match="nothing to clean"):
        Harness()._tool_ova_import_cleanup()


# ---------------------------------------------------------------------------
# ova-fetch
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def raise_for_status(self): pass

    def iter_content(self, chunk_size):
        yield self._payload

    def __enter__(self): return self

    def __exit__(self, *a): return False


def test_ova_fetch_verifies_sha_and_uploads(monkeypatch):
    import hashlib

    import requests
    payload = b"fake-ova-bytes"
    monkeypatch.setattr(requests, "get",
                        lambda url, stream, timeout: _FakeResponse(payload))
    s3 = FakeS3()
    Harness(s3=s3)._tool_ova_fetch(
        url="https://example.com/dl/image.ova",
        sha256=hashlib.sha256(payload).hexdigest())
    assert s3.objects["staging/image.ova"] == payload


def test_ova_fetch_sha_mismatch_aborts_before_upload(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda url, stream, timeout: _FakeResponse(b"tampered"))
    s3 = FakeS3()
    with pytest.raises(SystemExit, match="SHA-256 mismatch"):
        Harness(s3=s3)._tool_ova_fetch(url="https://example.com/image.ova",
                                       sha256="0" * 64)
    assert "staging/image.ova" not in s3.objects


def test_ova_fetch_dry_run_downloads_nothing(monkeypatch):
    import requests

    def _boom(*a, **kw):
        raise AssertionError("network touched during dry run")

    monkeypatch.setattr(requests, "get", _boom)
    Harness()._tool_ova_fetch(url="https://example.com/image.ova", dry_run=True)


# ---------------------------------------------------------------------------
# error surface
# ---------------------------------------------------------------------------

def test_access_denied_maps_to_clean_systemexit():
    class DeniedEC2(FakeEC2):
        def import_image(self, **kw):
            raise _client_error("UnauthorizedOperation", "ImportImage", "denied")

    s3 = FakeS3(objects={"staging/x.ova": b"ova"})
    with pytest.raises(SystemExit, match="access denied"):
        Harness(s3=s3, ec2=DeniedEC2())._tool_ova_to_ami(key="staging/x.ova")


def test_missing_vmimport_role_points_at_setup_tool():
    class NoRoleEC2(FakeEC2):
        def import_image(self, **kw):
            raise _client_error("InvalidParameter", "ImportImage",
                                "The service role vmimport does not exist")

    s3 = FakeS3(objects={"staging/x.ova": b"ova"})
    with pytest.raises(SystemExit, match="ova-import-setup"):
        Harness(s3=s3, ec2=NoRoleEC2())._tool_ova_to_ami(key="staging/x.ova")


# ---------------------------------------------------------------------------
# registry contract + CLI confirm gate
# ---------------------------------------------------------------------------

IMAGE_TOOLS = ["ova-import-setup", "ova-fetch", "ova-to-ami",
               "ami-to-ova", "ova-import-cleanup"]


def test_registry_has_all_image_tools_with_preflight_profile():
    for key in IMAGE_TOOLS:
        tool = _TOOL_BY_KEY[key]
        assert tool["requires"] == ["image-convert"]
        assert hasattr(ImageConvertMixin, tool["method"])


def test_billable_and_destructive_tools_require_confirm():
    for key in ("ova-to-ami", "ami-to-ova", "ova-import-cleanup", "ova-import-setup"):
        tool = _TOOL_BY_KEY[key]
        assert tool["confirm"] is True and tool.get("confirm_text")
    assert not _TOOL_BY_KEY["ova-fetch"].get("confirm")


def test_confirm_gate_blocks_noninteractive_without_yes(monkeypatch, capsys):
    from mixins.tools import ToolsMixin

    class T(ToolsMixin):
        pass

    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())
    tool = _TOOL_BY_KEY["ova-to-ami"]
    with pytest.raises(SystemExit, match="--yes"):
        T()._tool_confirm_gate(tool)
    T()._tool_confirm_gate(tool, assume_yes=True)      # --yes passes
    T()._tool_confirm_gate(_TOOL_BY_KEY["ova-fetch"])  # non-confirm tool passes


def test_confirm_gate_interactive_decline_backs_out(monkeypatch):
    from mixins.tools import ToolsMixin, _BackSignal

    class T(ToolsMixin):
        pass

    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: True})())
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    with pytest.raises(_BackSignal):
        T()._tool_confirm_gate(_TOOL_BY_KEY["ova-import-cleanup"])
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    T()._tool_confirm_gate(_TOOL_BY_KEY["ova-import-cleanup"])


def test_server_appends_yes_for_confirm_tools():
    from server.app import _job_argv
    _, _, argv = _job_argv({"tool": "ova-to-ami", "params": {"key": "staging/x.ova"}})
    assert argv[-1] == "--yes"
    _, _, argv = _job_argv({"tool": "ova-fetch",
                            "params": {"url": "https://example.com/x.ova"}})
    assert "--yes" not in argv
